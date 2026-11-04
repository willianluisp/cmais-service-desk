import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db


@override_settings(MICROSOFT_GRAPH_APPROVED=True, GRAPH_DELEGATED_OAUTH_ENABLED=True,
                   PLANNER_ENABLED=False, EMAIL_ENABLED=False, PLANNER_TEST_ENABLED=False)
def test_oauth_approval_does_not_process_planner_or_email_queues(django_user_model, monkeypatch):
    from apps.notifications.models import NotificationOutbox
    from apps.notifications.services import process_pending
    from apps.planner_integration.models import PlannerTaskProvisioning
    from apps.planner_integration.services import process_pending_provisioning
    from apps.planner_integration.tasks import synchronize_linked_tasks
    from apps.tickets.models import Category, Ticket

    def forbidden(*args, **kwargs):
        pytest.fail("OAuth-only approval must not obtain tokens for queue processing")

    monkeypatch.setattr("apps.planner_integration.services.configured_client", forbidden)
    monkeypatch.setattr("apps.notifications.services.configured_token_provider", forbidden)
    user = django_user_model.objects.create_user("synthetic.employee")
    ticket = Ticket.objects.create(number="OAUTH-ONLY-TEST", requester=user, title="Synthetic",
                                   category=Category.objects.create(name="Synthetic"))
    PlannerTaskProvisioning.objects.create(ticket=ticket)
    NotificationOutbox.objects.create(idempotency_key="oauth-only", recipient="synthetic@example.test",
                                     subject="Synthetic", body_text="Synthetic")
    before = list(PlannerTaskProvisioning.objects.values())
    before_mail = list(NotificationOutbox.objects.values())
    assert process_pending_provisioning() == 0
    assert process_pending() == 0
    assert synchronize_linked_tasks() == 0
    assert list(PlannerTaskProvisioning.objects.values()) == before
    assert list(NotificationOutbox.objects.values()) == before_mail
