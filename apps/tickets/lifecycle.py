"""Individual lifecycle operations; never delete Microsoft resources."""
from django.contrib.auth import authenticate
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, SuspiciousFileOperation, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from apps.accounts.permissions import is_portal_admin
from apps.notifications.models import NotificationOutbox
from apps.planner_integration.models import AttachmentPublication, PlannerTaskProvisioning

from .models import PrivateFileDeletion, Ticket, TicketDeletionAudit
from .uploads import private_storage


def authorize(actor):
    if not (actor.is_authenticated and actor.is_active and actor.groups.filter(name="ADMIN_PORTAL").exists()):
        raise PermissionDenied


def locked_ticket(actor, ticket_id):
    authorize(actor)
    ticket = Ticket.objects.select_for_update().filter(pk=ticket_id).first()
    from .permissions import authorized_tickets

    if ticket is None or not authorized_tickets(actor, Ticket.objects.filter(pk=ticket_id)).exists():
        raise Http404
    return ticket


def cancel_pending(ticket):
    PlannerTaskProvisioning.objects.filter(ticket=ticket).update(state='CANCELLED', last_error_code='ADMIN_ARCHIVED')
    AttachmentPublication.objects.filter(attachment__ticket=ticket, state__in=['PENDING', 'UPLOADED']).update(state='CANCELLED', last_error_code='ADMIN_ARCHIVED')
    NotificationOutbox.objects.filter(Q(ticket=ticket) | Q(event__ticket=ticket), state='PENDING').update(state='FAILED', last_error_code='ADMIN_ARCHIVED')


@transaction.atomic
def archive_ticket(*, actor, ticket_id, soft_delete=False):
    ticket = locked_ticket(actor, ticket_id)
    if ticket.archived_at:
        return
    ticket.archived_at = timezone.now()
    ticket.archive_reason = 'ADMIN_ARCHIVED'
    ticket.version += 1
    ticket.save(update_fields=['archived_at', 'archive_reason', 'version'])
    cancel_pending(ticket)
    TicketDeletionAudit.objects.create(ticket_id=ticket.pk, number=ticket.number, actor=actor,
                                       action='SOFT_DELETE' if soft_delete else 'ARCHIVE')


@transaction.atomic
def restore_ticket(*, actor, ticket_id):
    ticket = locked_ticket(actor, ticket_id)
    if not ticket.archived_at:
        raise ValidationError('O chamado não está arquivado.')
    ticket.archived_at = None
    ticket.archive_reason = 'RESTORED_PLANNER_DELETED' if ticket.planner_deleted_at else ''
    ticket.version += 1
    ticket.save(update_fields=['archived_at', 'archive_reason', 'version'])
    # A known deleted Planner task is never provisioned again by restoration.
    if not ticket.planner_deleted_at:
        provision = PlannerTaskProvisioning.objects.filter(ticket=ticket, state='CANCELLED').first()
        if provision:
            # A linked card may have been archived before its description PATCH.
            # Retry details on the existing ID; never create another card.
            provision.state = 'PENDING' if ticket.planner_task_id else ('RECONCILIATION' if provision.attempts else 'PENDING')
            provision.last_error_code = ''
            provision.available_at = timezone.now()
            provision.save(update_fields=['state', 'last_error_code', 'available_at', 'updated_at'])
        AttachmentPublication.objects.filter(attachment__ticket=ticket, state='CANCELLED', last_error_code='ADMIN_ARCHIVED').update(state='PENDING', last_error_code='')
    TicketDeletionAudit.objects.create(ticket_id=ticket.pk, number=ticket.number, actor=actor, action='RESTORE')


@sensitive_variables('password')
@transaction.atomic
def permanently_delete_ticket(*, actor, ticket_id, number, irreversible, password, request=None, expected_version=None):
    ticket = locked_ticket(actor, ticket_id)
    if not ticket.archived_at:
        raise ValidationError('Arquive o chamado antes de excluir permanentemente.')
    if expected_version is not None and ticket.version != expected_version:
        raise ValidationError('O chamado foi alterado. Abra novamente a confirmação.')
    if number != ticket.number or irreversible is not True:
        raise ValidationError('Digite o número exato e confirme a irreversibilidade.')
    key = f'ticket-delete-auth:{actor.pk}'
    try:
        cache.add(key, 0, timeout=300)
        attempts = cache.incr(key)
    except Exception as exc:
        raise ValidationError('Reautenticação indisponível. Tente mais tarde.') from exc
    if attempts > 5:
        raise ValidationError('Limite de tentativas atingido. Aguarde cinco minutos.')
    verified = authenticate(request=request, username=actor.username, password=password)
    if verified is None or verified.pk != actor.pk or not is_portal_admin(verified):
        raise ValidationError('Não foi possível confirmar sua senha e autorização atuais.')
    cancel_pending(ticket)
    audit = TicketDeletionAudit.objects.create(ticket_id=ticket.pk, number=ticket.number,
        actor=actor, action='PERMANENT_DELETE', details={
            'planner_task_id': ticket.planner_task_id,
            'remote_attachments': list(AttachmentPublication.objects.filter(attachment__ticket=ticket).exclude(remote_item_id='').values('drive_id', 'remote_item_id')),
        })
    for key in ticket.attachments.values_list('storage_key', flat=True):
        PrivateFileDeletion.objects.create(audit=audit, storage_key=key)
    NotificationOutbox.objects.filter(Q(ticket=ticket) | Q(event__ticket=ticket)).delete()
    AttachmentPublication.objects.filter(attachment__ticket=ticket).delete()
    PlannerTaskProvisioning.objects.filter(ticket=ticket).delete()
    ticket.access_grants.all().delete()
    ticket.comments.all().delete()
    ticket.events.all().delete()
    ticket.attachments.all().delete()
    ticket.delete()
    transaction.on_commit(lambda: process_file_deletions(audit_id=audit.pk))


def process_file_deletions(*, audit_id=None, limit=100):
    rows = PrivateFileDeletion.objects.filter(completed_at__isnull=True)
    if audit_id is not None:
        rows = rows.filter(audit_id=audit_id)
    for pk in list(rows.order_by('pk').values_list('pk', flat=True)[:limit]):
        with transaction.atomic():
            row = PrivateFileDeletion.objects.select_for_update().get(pk=pk)
            if row.completed_at:
                continue
            row.attempts += 1
            try:
                private_storage().delete(row.storage_key)
            except (OSError, ValueError, SuspiciousFileOperation):
                row.last_error_code = 'FILE_DELETE_FAILED'
            else:
                row.completed_at = timezone.now()
                row.last_error_code = ''
            row.save()
