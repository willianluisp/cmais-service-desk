from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.notifications.models import NotificationOutbox
from apps.notifications.services import enqueue_event, process_pending
from apps.planner_integration.services import sync_ticket
from apps.tickets.models import Category, TicketEvent
from apps.tickets.services import create_ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def ticket(django_user_model, settings):
    settings.PLANNER_PLAN_ID = "plan"
    settings.PORTAL_BASE_URL = "http://localhost:8010"
    settings.NOTIFICATIONS_TI_RECIPIENTS = ["unauthorized@example.test"]
    return create_ticket(actor=django_user_model.objects.create_user("owner", email="owner@example.test"),
                         title="Private title", description="Private description",
                         category=Category.objects.create(name="Test"), priority="NORMAL")


def graph(percent):
    client = Mock()
    client.get_task.return_value = {"id": "task", "planId": "plan", "bucketId": "bucket",
                                    "percentComplete": percent, "@odata.etag": str(percent)}
    client.get_task_details.return_value = {"checklist": {}}
    return client


def test_three_stage_notifications_are_deduplicated_and_private(ticket):
    ticket.planner_task_id = "task"
    ticket.save(update_fields=["planner_task_id"])
    for percent in (0, 20, 20, 40, 100, 100):
        sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=graph(percent))
    notices = list(NotificationOutbox.objects.order_by("pk"))
    assert len(notices) == 3
    assert all(n.recipient == "owner@example.test" for n in notices)
    assert [n.subject.rsplit(" — ", 1)[1] for n in notices] == ["Recebido", "Em andamento", "Finalizado"]
    assert all("Private" not in n.body_text + n.subject for n in notices)
    assert all("http://localhost:8010/chamados/" in n.body_text for n in notices)
    # Initial bucket detection, start, progress-only change, completion: all
    # remain in history, while only start/completion add status notifications.
    assert ticket.events.filter(origin=TicketEvent.Origin.PLANNER_SYNC).count() == 4
    ticket.refresh_from_db()
    assert ticket.portal_status_label == "Finalizado"
    assert ticket.last_planner_sync_at


def test_no_email_is_invented_for_unregistered_employee(ticket):
    ticket.requester.email = ""
    ticket.requester.save(update_fields=["email"])
    NotificationOutbox.objects.all().delete()
    assert enqueue_event(ticket.events.get(event_type="CREATED")) == []
    assert not NotificationOutbox.objects.exists()


def test_pending_notifications_are_not_consumed_when_disabled(ticket, monkeypatch, settings):
    settings.EMAIL_ENABLED = False
    settings.MICROSOFT_GRAPH_APPROVED = False
    monkeypatch.setattr("apps.notifications.services.deliver_local", lambda notice: pytest.fail("delivery attempted"))
    assert process_pending() == 0
    notice = NotificationOutbox.objects.get()
    assert notice.state == "PENDING" and notice.attempts == 0


def test_ambiguous_mail_acceptance_is_not_automatically_repeated(ticket):
    from apps.notifications.services import DeliveryError

    provider = Mock(side_effect=DeliveryError("MAIL_ACCEPTANCE_UNKNOWN"))
    assert process_pending(provider=provider) == 1
    assert process_pending(provider=provider) == 0
    provider.assert_called_once()
    notice = NotificationOutbox.objects.get()
    assert notice.state == "FAILED"
    assert notice.last_error_code == "MAIL_ACCEPTANCE_UNKNOWN"


def test_email_changed_after_enqueue_does_not_leak_to_old_address(ticket):
    ticket.requester.email = "new-address@example.test"
    ticket.requester.save(update_fields=["email"])
    provider = Mock()
    process_pending(provider=provider)
    provider.assert_not_called()
    assert NotificationOutbox.objects.get().last_error_code == "RECIPIENT_CHANGED"


def test_mail_transport_timeout_has_unknown_acceptance(ticket, monkeypatch, settings):
    from urllib.error import URLError

    from apps.notifications.services import DeliveryError, deliver_graph

    settings.EMAIL_ENABLED = True
    settings.MICROSOFT_GRAPH_APPROVED = True
    settings.GRAPH_MAILBOX_ID = "sender@example.test"
    monkeypatch.setattr("apps.notifications.services.configured_token_provider", lambda: lambda: "mock-token")
    opener = Mock()
    opener.open.side_effect = URLError(TimeoutError("secret remote response"))
    with pytest.raises(DeliveryError) as error:
        deliver_graph(NotificationOutbox.objects.get(), opener=opener)
    assert error.value.code == "MAIL_ACCEPTANCE_UNKNOWN"
    assert "secret" not in str(error.value)


def test_notification_uses_observed_event_status_not_later_ticket_state(ticket):
    event = TicketEvent.objects.create(ticket=ticket, event_type="PLANNER_CHANGED", summary="changed",
                                      payload={"previous_status": "ABERTO", "status": "EM_ATENDIMENTO"})
    ticket.status = "RESOLVIDO"
    ticket.save(update_fields=["status"])
    assert "Em andamento" in enqueue_event(event)[0].subject


@pytest.mark.parametrize(("internal", "label"), [
    ("ABERTO", "Aberto"), ("EM_ATENDIMENTO", "Em andamento"),
    ("AGUARDANDO_SOLICITANTE", "Em andamento"), ("RESOLVIDO", "Finalizado"), ("FECHADO", "Finalizado"),
])
def test_portal_labels_and_timestamps_preserve_legacy_codes(ticket, client, internal, label):
    ticket.status = internal
    ticket.save(update_fields=["status"])
    client.force_login(ticket.requester)
    for path in ("/", "/chamados/", f"/chamados/{ticket.pk}/"):
        response = client.get(path)
        assert response.status_code == 200
        assert label in response.content.decode()
        assert timezone.localtime(ticket.updated_at).strftime("%d/%m/%Y %H:%M") in response.content.decode()
    ticket.refresh_from_db()
    assert ticket.status == internal


def test_htmx_returns_current_status_without_parallel_management(ticket, client, monkeypatch):
    ticket.planner_task_id = "task"
    ticket.save(update_fields=["planner_task_id"])
    client.force_login(ticket.requester)
    monkeypatch.setattr("apps.planner_integration.services.configured_read_client", lambda: graph(100))
    monkeypatch.setattr("apps.planner_integration.views.enforce_rate_limit", lambda *args: None)
    response = client.post(f"/chamados/{ticket.pk}/sincronizar/", HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert b'hx-swap-oob="true"' in response.content
    assert "Finalizado" in response.content.decode()
    assert client.post(f"/chamados/{ticket.pk}/status/", {"status": "ABERTO"}).status_code == 404
