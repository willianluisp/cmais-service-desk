from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Category, Ticket, TicketEvent, TicketSequence


def _active(actor):
    if not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied


@transaction.atomic
def create_ticket(*, actor, title, description, category=None, priority, attachments=None, submission_key=None,
                  sector=None, service_location=None, is_sensitive=False, restricted_group_ids=(), approver_group_ids=()):
    """Persist the intake and durable Planner-provisioning intent only."""
    _active(actor)
    if submission_key:
        # Serialize browser resubmissions for this requester, before allocating
        # a protocol, writing files or adding outbox records.
        get_user_model().objects.select_for_update(no_key=True).get(pk=actor.pk)
        previous = Ticket.objects.filter(submission_key=submission_key).first()
        if previous:
            if previous.requester_id != actor.pk or previous.archived_at or previous.planner_deleted_at:
                raise ValidationError("Envio já utilizado. Abra um novo formulário de chamado.")
            return previous
    if sector is not None:
        from apps.sectors.models import Sector

        sector = Sector.objects.select_for_update().filter(pk=sector.pk, is_active=True).first()
        if sector is None:
            raise ValidationError({"sector": "Selecione um setor ativo."})
    if category is None:
        category, _ = Category.objects.get_or_create(name='Atendimento geral')
    if not category.is_active:
        raise ValidationError("Categoria indisponível.")
    year = timezone.localdate().year
    TicketSequence.objects.get_or_create(year=year)
    TicketSequence.objects.filter(year=year).update(value=F("value") + 1)
    counter = TicketSequence.objects.get(year=year)
    ticket = Ticket(
        number=f"C+{year}-{counter.value:06d}", requester=actor, title=title,
        description=description, category=category, priority=priority,
        sync_state=Ticket.SyncState.DISABLED if is_sensitive else Ticket.SyncState.PENDING,
        submission_key=submission_key,
        is_sensitive=is_sensitive,
    )
    ticket.full_clean()
    ticket.save(force_insert=True)
    if is_sensitive:
        access_group_ids = set(restricted_group_ids) | set(approver_group_ids)
        if not access_group_ids:
            raise ValidationError("Solicitação sensível exige grupos explícitos de acesso.")
        ticket.restricted_groups.set(access_group_ids)
    context_payload = {}
    if sector is not None or service_location is not None:
        from apps.sectors.intake import save_intake_context

        context = save_intake_context(ticket=ticket, sector=sector, service_location=service_location)
        context_payload = {"intake_context": {"sector_id": context.sector_id,
            "sector_name": context.sector_name_snapshot, "service_location": context.service_location}}
    event = TicketEvent.objects.create(
        ticket=ticket, actor=actor, event_type="CREATED", origin=TicketEvent.Origin.PORTAL,
        summary="Chamado aberto pelo solicitante.",
        payload=context_payload,
        idempotency_key=f"portal:{ticket.pk}:created",
    )
    from apps.notifications.services import enqueue_event
    from apps.planner_integration.models import PlannerTaskProvisioning

    if not is_sensitive:
        PlannerTaskProvisioning.objects.create(ticket=ticket)
        enqueue_event(event)
    for attachment in attachments or []:
        from .uploads import save_attachment

        save_attachment(ticket=ticket, actor=actor, upload=attachment)
    return ticket


@transaction.atomic
def archive_test_tickets(*, ticket_ids):
    """Explicit maintenance operation; never deletes files or calls Graph."""
    from apps.notifications.models import NotificationOutbox
    from apps.planner_integration.models import PlannerTaskProvisioning

    now = timezone.now()
    tickets = list(Ticket.objects.select_for_update().filter(pk__in=ticket_ids))
    for ticket in tickets:
        if not ticket.archived_at:
            ticket.archived_at = now
            ticket.archive_reason = "TEST_CLEANUP"
            ticket.version += 1
            ticket.save(update_fields=["archived_at", "archive_reason", "version"])
        TicketEvent.objects.get_or_create(
            idempotency_key=f"test-archived:{ticket.pk}",
            defaults={"ticket": ticket, "event_type": "TEST_ARCHIVED",
                      "origin": TicketEvent.Origin.SYSTEM,
                      "summary": "Chamado de teste arquivado por autorização; dados e anexos preservados."},
        )
        PlannerTaskProvisioning.objects.filter(ticket=ticket).update(
            state=PlannerTaskProvisioning.State.CANCELLED,
            last_error_code="TEST_ARCHIVED", updated_at=now,
        )
        NotificationOutbox.objects.filter(ticket=ticket, state="PENDING").update(
            state="FAILED", last_error_code="TEST_ARCHIVED",
        )
    return len(tickets)
