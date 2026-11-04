import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.planner_integration.models import PlannerTaskProvisioning
from apps.tickets.models import Category, Ticket
from apps.tickets.permissions import visible_tickets
from apps.tickets.services import archive_test_tickets, create_ticket
from apps.tickets.uploads import private_storage

pytestmark = pytest.mark.django_db


@pytest.fixture
def intake(django_user_model):
    return {"actor": django_user_model.objects.create_user("review.employee"),
            "title": "Teste descartável", "description": "Teste sem integração externa",
            "category": Category.objects.create(name="Revisão"), "priority": "NORMAL"}


def test_archive_cancels_outbox_preserves_files_history_and_future_intake(intake, settings, tmp_path):
    settings.PRIVATE_ATTACHMENT_ROOT = tmp_path
    ticket = create_ticket(**intake, attachments=[SimpleUploadedFile("evidencia.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")])
    attachment = ticket.attachments.get()
    assert archive_test_tickets(ticket_ids=[ticket.pk]) == 1
    archive_test_tickets(ticket_ids=[ticket.pk])
    ticket.refresh_from_db()
    assert ticket.archived_at and ticket.archive_reason == "TEST_CLEANUP"
    assert ticket.planner_provisioning.state == "CANCELLED"
    assert not visible_tickets(intake["actor"], Ticket.objects.all()).exists()
    assert ticket.events.filter(event_type="TEST_ARCHIVED").count() == 1
    assert ticket.attachments.count() == 1
    assert private_storage().exists(attachment.storage_key)
    fresh = create_ticket(**intake)
    assert fresh.planner_provisioning.state == "PENDING"
    assert visible_tickets(intake["actor"], Ticket.objects.all()).get() == fresh


def test_browser_resubmission_allocates_only_one_protocol_outbox_and_upload(intake, settings, tmp_path):
    settings.PRIVATE_ATTACHMENT_ROOT = tmp_path
    key = uuid.uuid4()
    first = create_ticket(**intake, submission_key=key,
                          attachments=[SimpleUploadedFile("print.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")])
    second = create_ticket(**intake, submission_key=key)
    assert first.pk == second.pk
    assert Ticket.objects.count() == PlannerTaskProvisioning.objects.count() == 1
    assert first.attachments.count() == first.events.count() == 1


def test_list_prefers_planner_responsible_over_legacy_local_assignment(intake, client):
    ticket = create_ticket(**intake)
    ticket.planner_assignee_names = ["Responsável do Planner"]
    ticket.assignee = intake["actor"]
    ticket.save()
    client.force_login(intake["actor"])
    response = client.get("/chamados/")
    assert "Responsável do Planner" in response.content.decode()


def test_deleted_htmx_redirects_to_list_and_displays_confirmation(intake, client, monkeypatch):
    from apps.planner_integration.client import PlannerError
    from apps.planner_integration.services import sync_ticket

    ticket = create_ticket(**intake)
    ticket.planner_task_id, ticket.planner_plan_id = "deleted-task", "plan"
    ticket.save()

    class Graph:
        def get_task(self, task_id):
            raise PlannerError("TASK_NOT_FOUND", "Ausente", status=404)

        def list_plan_buckets(self, plan_id):
            return []

        def list_plan_tasks(self, plan_id):
            return []

    monkeypatch.setattr("apps.planner_integration.views.enforce_rate_limit", lambda *args: None)
    monkeypatch.setattr("apps.planner_integration.views.sync_ticket", lambda **kwargs: sync_ticket(**kwargs, graph_client=Graph()))
    from django.test import override_settings

    client.force_login(intake["actor"])
    with override_settings(PLANNER_PLAN_ID="plan"):
        response = client.post(f"/chamados/{ticket.pk}/sincronizar/", HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and response["HX-Redirect"] == "/chamados/"
    page = client.get("/chamados/")
    assert "Exclusão confirmada no Planner" in page.content.decode()
    assert ticket.number not in page.content.decode()
    ticket.refresh_from_db()
    assert ticket.planner_provisioning.state == "CANCELLED"
