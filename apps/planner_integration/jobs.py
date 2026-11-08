"""Database leases also work when Redis is unavailable; no credentials in status."""

import uuid
from contextlib import contextmanager
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import PlannerRuntime


def defer_graph(exc):
    if exc.status != 429:
        return
    until = timezone.now() + timedelta(seconds=exc.retry_after or 120)
    with transaction.atomic():
        runtime, _ = PlannerRuntime.objects.select_for_update().get_or_create(pk=1)
        if not runtime.throttle_until or runtime.throttle_until < until:
            runtime.throttle_until = until
            runtime.save(update_fields=['throttle_until'])


@contextmanager
def integration_job():
    now, lease = timezone.now(), uuid.uuid4()
    with transaction.atomic():
        runtime, _ = PlannerRuntime.objects.select_for_update().get_or_create(pk=1)
        available = not (
            (runtime.lease_until and runtime.lease_until > now)
            or (runtime.throttle_until and runtime.throttle_until > now)
        )
        if available:
            runtime.lease_id = lease
            runtime.lease_until = now + timedelta(minutes=15)
            runtime.last_started_at = now
            runtime.save(update_fields=['lease_id', 'lease_until', 'last_started_at'])
    if not available:
        yield False
        return
    completed = False
    try:
        yield True
        completed = True
    finally:
        updates = {'lease_id': None, 'lease_until': None}
        if completed:
            updates['last_finished_at'] = timezone.now()
        PlannerRuntime.objects.filter(pk=1, lease_id=lease).update(**updates)
