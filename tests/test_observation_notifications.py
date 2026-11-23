from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from apps.notifications import observations
from apps.notifications.email_layout import montar
from apps.notifications.models import NotificationOutbox
from apps.tickets.models import Category, Ticket

pytestmark = pytest.mark.django_db
T0 = timezone.now().replace(microsecond=0) - timedelta(hours=2)


@pytest.fixture
def ticket(django_user_model, settings):
    settings.PORTAL_BASE_URL = "https://chamados.example.test"
    user = django_user_model.objects.create_user("solicitante", email="solicitante@example.test")
    return Ticket.objects.create(number="C+2026-000050", requester=user, title="Assunto do chamado",
                                 description="Descrição privada", category=Category.objects.create(name="Admissão"),
                                 planner_task_id="task-1", status=Ticket.Status.EM_ATENDIMENTO)


def leitura(*minutos, completa=True):
    mensagens = [{"id": str(m), "created_at": (T0 + timedelta(minutes=m)).isoformat(), "author": "TI",
                  "content": "texto privado da observação"} for m in minutos]
    return {"messages": mensagens, "complete": completa, "available": completa}


def rodar(ticket, resposta, minuto):
    with mock.patch("apps.planner_integration.observations.read_observations", return_value=resposta):
        return observations.verificar(Ticket.objects.get(pk=ticket.pk), agora=T0 + timedelta(minutes=minuto))


def test_historico_existente_nao_gera_email(ticket):
    assert rodar(ticket, leitura(0, 1), 60) == 0
    ticket.refresh_from_db()
    assert ticket.observations_seen_until == T0 + timedelta(minutes=1)
    assert NotificationOutbox.objects.count() == 0


def test_junta_observacoes_e_envia_15_min_depois_da_ultima(ticket):
    rodar(ticket, leitura(0), 1)                      # histórico: só marca como visto
    assert rodar(ticket, leitura(0, 10), 11) == 0     # nova às 10
    assert rodar(ticket, leitura(0, 10, 18), 19) == 0  # outra às 18: o prazo recomeça
    assert rodar(ticket, leitura(0, 10, 18), 32) == 0  # 14 min depois da última
    assert rodar(ticket, leitura(0, 10, 18), 33) == 1  # 15 min sem nova: um e-mail só
    aviso = NotificationOutbox.objects.get()
    assert aviso.recipient == "solicitante@example.test" and aviso.template_key == "ticket-observation-v1"
    assert aviso.subject == "[Não responder] C+ Service Desk — C+2026-000050 — Novas observações"
    assert "Há 2 novas observações" in aviso.body_html
    assert "texto privado" not in aviso.body_text + aviso.body_html
    assert "Descrição privada" not in aviso.body_text + aviso.body_html
    assert rodar(ticket, leitura(0, 10, 18), 60) == 0  # não repete
    ticket.refresh_from_db()
    assert ticket.observations_pending == 0


def test_leitura_incompleta_ou_chamado_sensivel_nao_decide(ticket):
    rodar(ticket, leitura(0), 1)
    assert rodar(ticket, leitura(0, 5, completa=False), 30) == 0
    ticket.refresh_from_db()
    assert ticket.observations_pending == 0
    Ticket.objects.filter(pk=ticket.pk).update(is_sensitive=True)
    assert rodar(ticket, leitura(0, 5), 30) == 0
    assert NotificationOutbox.objects.count() == 0


def test_layout_por_etapa(ticket):
    assunto, texto, html = montar(ticket, "RESOLVIDO", timezone.now())
    assert assunto.endswith("— Finalizado") and "Seu chamado foi finalizado" in html
    assert "Assunto do chamado" in html and "Admissão" in html and "Descrição privada" not in html + texto
    assert "https://chamados.example.test/chamados/" in html


def test_envio_pela_microsoft_leva_a_logo_embutida(ticket, settings):
    import json

    from apps.notifications import services

    settings.EMAIL_ENABLED, settings.MICROSOFT_GRAPH_APPROVED, settings.GRAPH_MAILBOX_ID = True, True, "chamados@example.test"
    assunto, texto, html = montar(ticket, "ABERTO", timezone.now())
    assert 'src="cid:logo-cmais"' in html
    enviado = {}

    class Resposta:
        status = 202
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class Abridor:
        def open(self, pedido, timeout):
            enviado["dados"] = json.loads(pedido.data)
            return Resposta()

    aviso = NotificationOutbox(ticket=ticket, recipient="solicitante@example.test", subject=assunto,
                               body_text=texto, body_html=html, idempotency_key="k-logo")
    with mock.patch.object(services, "configured_token_provider", return_value=lambda: "token"):
        services.deliver_graph(aviso, opener=Abridor())
    anexo, = enviado["dados"]["message"]["attachments"]
    assert anexo["isInline"] is True and anexo["contentId"] == "logo-cmais" and anexo["contentType"] == "image/png"
    assert len(anexo["contentBytes"]) > 1000
