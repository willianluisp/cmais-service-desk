from datetime import timedelta

from celery import shared_task
from django.http import Http404
from django.utils import timezone

from apps.tickets.models import Ticket

from .client import PlannerError
from .configuration import automation_enabled
from .jobs import defer_graph, integration_job
from .models import PlannerRuntime
from .services import process_pending_provisioning, sync_ticket


def _synchronize_linked_tasks(limit=25):
    if not automation_enabled(synchronize=True):
        return 0
    tickets = Ticket.objects.filter(is_sensitive=False, requester__is_active=True, planner_deleted_at__isnull=True, archived_at__isnull=True,
                                    next_planner_sync_at__lte=timezone.now()).exclude(planner_task_id__isnull=True).exclude(planner_task_id="").select_related("requester").order_by("next_planner_sync_at", "created_at")[:max(1, min(int(limit), 100))]
    processed = 0
    for ticket in tickets:
        if not automation_enabled(synchronize=True):
            break
        Ticket.objects.filter(pk=ticket.pk).update(next_planner_sync_at=timezone.now() + timedelta(seconds=120))
        try:
            sync_ticket(actor=ticket.requester, ticket_id=ticket.pk)
        except Http404:
            # Deleted or access revoked after the initial batch was selected.
            continue
        except PlannerError as exc:
            Ticket.objects.filter(pk=ticket.pk).update(
                next_planner_sync_at=timezone.now() + timedelta(seconds=max(120, exc.retry_after or 120)))
            defer_graph(exc)
            if exc.status == 429 or exc.code == 'AUTH_REQUIRED':
                break
        processed += 1
    return processed


@shared_task(ignore_result=True, soft_time_limit=600, time_limit=660)
def synchronize_linked_tasks(limit=25):
    if not automation_enabled(synchronize=True):
        return 0
    with integration_job() as acquired:
        return _synchronize_linked_tasks(limit) if acquired else 0


@shared_task(ignore_result=True, soft_time_limit=600, time_limit=660)
def provision_pending_tasks(limit=25):
    if PlannerRuntime.objects.filter(pk=1, sync_requested=True).exists():
        return run_requested_sync(limit)
    if not automation_enabled():
        return 0
    with integration_job() as acquired:
        return process_pending_provisioning(limit=limit) if acquired else 0


@shared_task(ignore_result=True, soft_time_limit=600, time_limit=660)
def run_requested_sync(limit=25):
    if not (automation_enabled() or automation_enabled(synchronize=True)):
        return 0
    if not PlannerRuntime.objects.filter(pk=1, sync_requested=True).exists():
        return 0
    with integration_job() as acquired:
        if not acquired:
            return 0
        # Clear before work: a request arriving during the run remains pending.
        PlannerRuntime.objects.filter(pk=1).update(sync_requested=False)
        try:
            processed = process_pending_provisioning(limit=limit)
            if not PlannerRuntime.objects.filter(pk=1, throttle_until__gt=timezone.now()).exists():
                processed += _synchronize_linked_tasks(limit)
            return processed
        except Exception:
            PlannerRuntime.objects.filter(pk=1).update(sync_requested=True)
            raise


@shared_task(ignore_result=True)
def publish_pending_attachments(limit=10):
    from .attachments import process_publications

    return process_publications(limit=limit)


@shared_task(ignore_result=True)
def cleanup_deleted_ticket_files():
    from apps.tickets.lifecycle import process_file_deletions

    process_file_deletions()
