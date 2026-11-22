"""E-mail ao solicitante quando a TI escreve observações no Planner.

Roda junto da sincronização de cada chamado (a cada ~2 min). Observações que chegam em
sequência viram UM e-mail: ele sai quando passam ESPERA minutos sem observação nova.
O texto das observações não vai no e-mail; o solicitante lê no portal.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

ESPERA = timedelta(minutes=15)


def verificar(ticket, *, agora=None):
    """Atualiza o controle de observações do chamado e enfileira o aviso quando chega a hora.

    Devolve o número de avisos enfileirados (0 ou 1).
    """
    from apps.planner_integration.observations import read_observations
    from apps.tickets.models import Ticket

    if ticket.is_sensitive or not ticket.planner_task_id:
        return 0
    leitura = read_observations(ticket, refresh=True)
    if not (leitura.get("complete") and leitura.get("available")):
        return 0  # sem leitura completa não se decide nada (nem marca como visto)
    datas = [d for d in (parse_datetime(m.get("created_at") or "") for m in leitura.get("messages") or []) if d]
    agora = agora or timezone.now()
    with transaction.atomic():
        atual = Ticket.objects.select_for_update().filter(pk=ticket.pk).first()
        if atual is None or atual.is_sensitive:
            return 0
        if atual.observations_seen_until is None:
            # Primeira leitura: o histórico que já existia não gera e-mail.
            atual.observations_seen_until = max(datas, default=atual.created_at)
        novas = [d for d in datas if d > atual.observations_seen_until]
        if novas:
            atual.observations_pending = min(atual.observations_pending + len(novas), 999)
            atual.observation_last_at = atual.observations_seen_until = max(novas)
        enfileirados = 0
        if atual.observations_pending and atual.observation_last_at and agora - atual.observation_last_at >= ESPERA:
            enfileirados = len(_enfileirar(atual))
            atual.observations_pending = 0
        atual.save(update_fields=["observations_seen_until", "observations_pending", "observation_last_at"])
    return enfileirados


def _enfileirar(ticket):
    from apps.tickets.models import Ticket

    from .email_layout import montar
    from .services import _enqueue_for_requester

    etapa = Ticket.portal_status_for(ticket.status) or "ABERTO"
    assunto, texto, html = montar(ticket, etapa, ticket.observation_last_at, observacoes=ticket.observations_pending)
    chave = f"observacoes:{ticket.pk}:{ticket.observation_last_at.isoformat()}:{{recipient}}:email:ticket-observation-v1"
    linhas = _enqueue_for_requester(ticket, chave, assunto, texto, html, template_key="ticket-observation-v1")
    logger.info("Aviso de observações enfileirado: chamado=%s observacoes=%s", ticket.number, ticket.observations_pending)
    return linhas
