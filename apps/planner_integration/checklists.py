"""Internal templates and additive, journaled publication to native Planner checklists."""

import logging
import uuid

from django.core.exceptions import ValidationError
from django.utils import timezone

from .client import PlannerError
from .models import PlannerTaskProvisioning
from .ticket_locks import serialized_ticket

logger = logging.getLogger(__name__)
MAX_ITEMS = 20
MAX_TITLE = 100


def validate_titles(items):
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise ValidationError('O Planner permite até 20 itens por checklist.')
    result = []
    for title in items:
        if (not isinstance(title, str) or not title.strip()
                or len(title.strip().encode('utf-16-le')) // 2 > MAX_TITLE
                or any(ord(char) < 32 for char in title)):
            raise ValidationError('Cada item deve ter entre 1 e 100 caracteres, em uma única linha.')
        result.append(title.strip())
    if len({title.casefold() for title in result}) != len(result):
        raise ValidationError('Remova os itens duplicados do checklist.')
    return result


def snapshot_items(ticket_id, titles):
    return [{'id': str(uuid.uuid5(ticket_id, f'planner-checklist:{index}')), 'title': title}
            for index, title in enumerate(validate_titles(titles))]


def provision_checklist(provisioning, client):
    """Never update an existing remote item or recreate an acknowledged deletion.

    Persist the PATCH intent before HTTP. An unchanged details ETag proves an
    ambiguous request did not modify remote state. If it changed and IDs vanished,
    require reconciliation rather than potentially undoing a manual deletion.
    """
    row = PlannerTaskProvisioning.objects.get(pk=provisioning.pk)
    if not row.checklist_snapshot or row.checklist_completed_at:
        return

    ticket = provisioning.ticket
    for attempt in range(3):
        details = client.get_task_details(ticket.planner_task_id)
        if not isinstance(details, dict) or not isinstance(details.get('checklist'), dict):
            raise PlannerError('INVALID_PAYLOAD', 'Checklist remoto inválido.')
        remote, etag = details['checklist'], details.get('@odata.etag')
        if not isinstance(etag, str) or not etag:
            raise PlannerError('INVALID_PAYLOAD', 'ETag de detalhes ausente.')
        acknowledged = set(row.checklist_acknowledged_ids)
        acknowledged.update(item['id'] for item in row.checklist_snapshot if item['id'] in remote)
        row.checklist_acknowledged_ids = sorted(acknowledged)
        row.save(update_fields=['checklist_acknowledged_ids'])
        missing = [item for item in row.checklist_snapshot if item['id'] not in acknowledged]
        if not missing:
            row.checklist_completed_at = timezone.now()
            row.graph_write_inflight = False
            row.save(update_fields=['checklist_completed_at', 'graph_write_inflight'])
            return
        uncertain_missing = set(row.checklist_inflight_ids) & {item['id'] for item in missing}
        if uncertain_missing and etag != row.checklist_inflight_etag:
            raise PlannerError('CHECKLIST_RECONCILIATION',
                               'Checklist requer conferência após alteração remota.', status=409)
        if len(remote) + len(missing) > MAX_ITEMS:
            raise PlannerError('CHECKLIST_LIMIT', 'O checklist remoto excederia 20 itens.', status=400)
        # Append new items in template order without moving existing manual items.
        hint = max((value.get('orderHint', '') for value in remote.values()
                    if isinstance(value, dict) and isinstance(value.get('orderHint', ''), str)), default='')
        patch = {}
        for item in missing:
            hint += ' !'
            patch[item['id']] = {'@odata.type': 'microsoft.graph.plannerChecklistItem',
                                 'title': item['title'], 'isChecked': False, 'orderHint': hint}
        row.checklist_inflight_ids = list(patch)
        row.checklist_inflight_etag = etag
        row.save(update_fields=['checklist_inflight_ids', 'checklist_inflight_etag'])
        try:
            client.patch_task_checklist(ticket.planner_task_id, checklist=patch, etag=etag)
        except PlannerError as exc:
            # These responses definitely rejected the write; a timeout/5xx may not have.
            if not row.graph_write_inflight and exc.status in {400, 401, 403, 404, 409, 412, 429}:
                row.checklist_inflight_ids = []
                row.checklist_inflight_etag = ''
                row.save(update_fields=['checklist_inflight_ids', 'checklist_inflight_etag'])
            logger.warning('Planner checklist failed provisioning=%s code=%s', row.pk, exc.code)
            if exc.status in {409, 412} and attempt < 2:
                continue
            raise
        row.checklist_acknowledged_ids = sorted(acknowledged | set(patch))
        row.checklist_completed_at = timezone.now()
        row.graph_write_inflight = False
        row.checklist_inflight_ids = []
        row.checklist_inflight_etag = ''
        row.save(update_fields=['checklist_acknowledged_ids', 'checklist_completed_at', 'graph_write_inflight',
                                'checklist_inflight_ids', 'checklist_inflight_etag'])
        return


@serialized_ticket
def accept_remote_checklist(*, actor, ticket_id, graph_client=None):
    """Explicit administrator resolution: keep the remote task exactly as it is."""
    from django.core.exceptions import PermissionDenied
    from django.db import transaction
    from django.http import Http404

    from apps.accounts.permissions import is_portal_admin
    from apps.tickets.models import Ticket, TicketEvent
    from apps.tickets.permissions import visible_tickets

    from .client import configured_read_client

    if not is_portal_admin(actor):
        raise PermissionDenied
    ticket = visible_tickets(actor, Ticket.objects.all()).filter(pk=ticket_id, is_sensitive=False).first()
    if ticket is None:
        raise Http404
    original = PlannerTaskProvisioning.objects.filter(ticket=ticket, last_error_code='CHECKLIST_RECONCILIATION').first()
    if original is None or not ticket.planner_task_id:
        raise ValidationError('Este checklist não tem uma conferência pendente.')
    graph = graph_client or configured_read_client()
    details = graph.get_task_details(ticket.planner_task_id)
    if not isinstance(details, dict) or not isinstance(details.get('checklist'), dict) or not details.get('@odata.etag'):
        raise PlannerError('INVALID_PAYLOAD', 'Checklist remoto inválido.')
    with transaction.atomic():
        current = Ticket.objects.select_for_update().get(pk=ticket.pk)
        row = PlannerTaskProvisioning.objects.select_for_update().get(pk=original.pk)
        if (not visible_tickets(actor, Ticket.objects.filter(pk=current.pk)).exists()
                or current.planner_task_id != ticket.planner_task_id
                or row.last_error_code != 'CHECKLIST_RECONCILIATION'
                or row.checklist_inflight_ids != original.checklist_inflight_ids):
            raise ValidationError('O chamado mudou. Recarregue antes de confirmar.')
        row.checklist_acknowledged_ids = [item['id'] for item in row.checklist_snapshot]
        row.checklist_completed_at = timezone.now()
        row.graph_write_inflight = False
        row.checklist_inflight_ids = []
        row.checklist_inflight_etag = ''
        row.last_error_code = ''
        row.state = PlannerTaskProvisioning.State.PENDING
        row.available_at = timezone.now()
        row.save(update_fields=['checklist_acknowledged_ids', 'checklist_completed_at', 'graph_write_inflight',
                                'checklist_inflight_ids', 'checklist_inflight_etag',
                                'last_error_code', 'state', 'available_at', 'updated_at'])
        TicketEvent.objects.create(ticket=current, actor=actor, event_type='CHECKLIST_RECONCILED',
                                   is_internal=True, summary='TI confirmou a lista atual do Planner; itens ausentes não serão recriados.')
