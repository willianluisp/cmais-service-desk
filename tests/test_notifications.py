from datetime import timedelta

import pytest
from django.db import transaction
from django.test import override_settings
from django.utils import timezone

from apps.tickets.models import Category, Ticket, TicketEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def event(django_user_model):
    user = django_user_model.objects.create_user(username="notify", email="notify@example.test")
    ticket = Ticket.objects.create(
        number="SD-2026-000001",
        requester=user,
        title="SECRET",
        description="SECRET",
        category=Category.objects.create(name="TI"),
    )
    return TicketEvent.objects.create(ticket=ticket, event_type="CREATED", summary="SECRET")


def test_enqueue_is_transactional_deduplicated_and_minimal(event):
    from apps.notifications.models import NotificationOutbox
    from apps.notifications.services import enqueue_event

    with pytest.raises(RuntimeError), transaction.atomic():
        enqueue_event(event)
        raise RuntimeError("rollback")
    assert not NotificationOutbox.objects.exists()
    enqueue_event(event)
    enqueue_event(event)
    notice = NotificationOutbox.objects.get()
    assert notice.recipient == "notify@example.test"
    assert "SECRET" not in notice.subject + notice.body_text + notice.body_html
    assert str(event.ticket.pk) in notice.body_text
    event.is_internal = True
    event.save()
    assert enqueue_event(event) == []


@override_settings(NOTIFICATIONS_PROVIDER="local", EMAIL_ENABLED=True, MICROSOFT_GRAPH_APPROVED=True)
def test_worker_sends_once_and_does_not_send_future_retry(event, mailoutbox):
    from apps.notifications.models import NotificationOutbox
    from apps.notifications.services import enqueue_event, process_pending

    enqueue_event(event)
    assert process_pending() == 1
    assert process_pending() == 0
    notice = NotificationOutbox.objects.get()
    assert notice.state == NotificationOutbox.State.SENT
    assert len(mailoutbox) == 1
    notice.state = NotificationOutbox.State.PENDING
    notice.available_at = timezone.now() + timedelta(hours=1)
    notice.save()
    assert process_pending() == 0


def test_bounded_retry_sanitizes_errors(event):
    from apps.notifications.models import NotificationOutbox
    from apps.notifications.services import enqueue_event, process_pending

    enqueue_event(event)

    def failing_provider(notice):
        raise RuntimeError("SECRET password/token")

    with override_settings(NOTIFICATIONS_MAX_ATTEMPTS=2):
        assert process_pending(provider=failing_provider) == 1
        notice = NotificationOutbox.objects.get()
        assert notice.state == NotificationOutbox.State.PENDING
        assert notice.last_error_code == "DELIVERY_FAILED"
        assert notice.available_at > timezone.now()
        notice.available_at = timezone.now()
        notice.save()
        process_pending(provider=failing_provider)
    notice.refresh_from_db()
    assert notice.state == NotificationOutbox.State.FAILED
    assert notice.attempts == 2
    assert "SECRET" not in notice.last_error_code
    assert process_pending(provider=failing_provider) == 0


def test_retry_after_from_graph_is_preserved_for_outbox(event):
    from apps.notifications.models import NotificationOutbox
    from apps.notifications.services import DeliveryError, enqueue_event, process_pending

    enqueue_event(event)

    def throttled_provider(notice):
        raise DeliveryError("MAIL_THROTTLED", retry_after=71)

    assert process_pending(provider=throttled_provider) == 1
    notice = NotificationOutbox.objects.get()
    assert notice.state == NotificationOutbox.State.PENDING
    assert notice.last_error_code == "MAIL_THROTTLED"
    assert notice.available_at >= timezone.now() + timedelta(seconds=69)


@override_settings(NOTIFICATIONS_PROVIDER="smtp", NOTIFICATIONS_EXTERNAL_APPROVED=False)
def test_unapproved_external_provider_preserves_pending_without_network(event):
    from apps.notifications.models import NotificationOutbox
    from apps.notifications.services import enqueue_event, process_pending

    enqueue_event(event)
    process_pending()
    notice = NotificationOutbox.objects.get()
    assert notice.state == NotificationOutbox.State.PENDING
    assert notice.attempts == 0
    assert notice.last_error_code == ""
