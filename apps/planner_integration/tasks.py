from celery import shared_task
from django.conf import settings

from apps.tickets.models import Ticket

from .client import PlannerError
from .services import process_pending_provisioning, sync_ticket


@shared_task(ignore_result=True)
def synchronize_linked_tasks(limit=25):
    if not settings.PLANNER_SYNC_ENABLED or not settings.MICROSOFT_GRAPH_APPROVED:
        return 0
    tickets = Ticket.objects.filter(is_sensitive=False, requester__is_active=True, planner_deleted_at__isnull=True, archived_at__isnull=True).exclude(planner_task_id__isnull=True).exclude(planner_task_id="").select_related("requester").order_by("last_planner_sync_at")[:max(1, min(limit, 100))]
    processed = 0
    for ticket in tickets:
        try:
            sync_ticket(actor=ticket.requester, ticket_id=ticket.pk)
        except PlannerError as exc:
            if exc.status == 429:
                break
        processed += 1
    return processed


@shared_task(ignore_result=True)
def provision_pending_tasks(limit=25):
    return process_pending_provisioning(limit=limit)


@shared_task(ignore_result=True)
def publish_pending_attachments(limit=10):
    from .attachments import process_publications

    return process_publications(limit=limit)


@shared_task(ignore_result=True)
def cleanup_deleted_ticket_files():
    from apps.tickets.lifecycle import process_file_deletions

    process_file_deletions()
