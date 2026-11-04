from io import StringIO
from unittest.mock import Mock

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.planner_integration.client import GraphClient, PlannerError


def test_buckets_pagination_uses_real_ids_and_rejects_other_plans():
    graph = GraphClient(token_provider=lambda: "mock")
    graph._request_json = Mock(side_effect=[
        {"value": [{"id": "real-entry", "name": "Tarefas pendentes", "planId": "plan"}],
         "@odata.nextLink": "https://graph.microsoft.com/v1.0/next"},
        {"value": [{"id": "real-done", "name": "Finalizada", "planId": "plan"}]},
    ])
    assert [b["id"] for b in graph.list_plan_buckets("plan")] == ["real-entry", "real-done"]
    graph._request_json = Mock(return_value={"value": [{"id": "wrong", "name": "Entry", "planId": "other"}]})
    with pytest.raises(PlannerError):
        graph.list_plan_buckets("plan")


def test_bucket_command_is_offline_by_default(monkeypatch):
    monkeypatch.setattr(GraphClient, "list_plan_buckets", lambda *args: pytest.fail("network attempted"))
    output = StringIO()
    call_command("planner_buckets", stdout=output)
    assert "nenhuma chamada" in output.getvalue()


@override_settings(MICROSOFT_GRAPH_APPROVED=False, PLANNER_PLAN_ID="plan")
def test_explicit_bucket_query_is_blocked_until_approved():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="INTEGRATION_DISABLED"):
        call_command("planner_buckets", execute=True)


@override_settings(PLANNER_PLAN_ID="plan", PLANNER_ENABLED=False)
def test_bucket_command_maps_names_without_enabling_task_creation(monkeypatch):
    monkeypatch.setattr("apps.planner_integration.management.commands.planner_buckets.configured_planner_token_provider", lambda: lambda: "mock")
    monkeypatch.setattr(GraphClient, "list_plan_buckets", lambda self, plan: [
        {"id": "real-entry", "name": "Tarefas pendentes"},
        {"id": "real-working", "name": "Desenvolvendo"},
        {"id": "real-done", "name": "Finalizada"},
    ])
    output = StringIO()
    call_command("planner_buckets", execute=True, stdout=output)
    assert "PLANNER_BUCKET_ENTRADA_ID=real-entry" in output.getvalue()
    assert "PLANNER_BUCKET_EM_ANDAMENTO_ID=real-working" in output.getvalue()
    assert "PLANNER_BUCKET_CONCLUIDO_ID=real-done" in output.getvalue()


@pytest.mark.django_db
@override_settings(MICROSOFT_GRAPH_APPROVED=False, PLANNER_ENABLED=False)
def test_intake_is_automatically_queued_and_stays_pending_when_disabled(django_user_model):
    from apps.planner_integration.services import _card_description, process_pending_provisioning
    from apps.tickets.models import Category, Ticket
    from apps.tickets.services import create_ticket

    user = django_user_model.objects.create_user("employee", first_name="Colaborador", last_name="Teste")
    ticket = create_ticket(actor=user, title="Solicitação", description="x" * 3900,
                           category=Category.objects.create(name="Infra"), priority=Ticket.Priority.NORMAL)
    row = ticket.planner_provisioning
    assert row.state == "PENDING"
    assert process_pending_provisioning() == 0
    row.refresh_from_db()
    ticket.refresh_from_db()
    assert row.attempts == 0
    assert ticket.sync_state == "PENDING"
    with override_settings(PORTAL_BASE_URL="http://localhost:8010"):
        description = _card_description(ticket, row.correlation_id)
    assert len(description) <= 4000
    assert str(row.correlation_id) in description
    assert "/chamados/" not in description
    assert "Este chamado possui" not in description
    assert "Colaborador Teste" in description


@pytest.mark.django_db
def test_card_description_mentions_attachment_count_without_names_or_portal_url(
    django_user_model, settings, tmp_path
):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.planner_integration.models import AttachmentPublication
    from apps.planner_integration.services import _card_description
    from apps.tickets.models import Category
    from apps.tickets.services import create_ticket

    settings.PRIVATE_ATTACHMENT_ROOT = tmp_path
    settings.PORTAL_BASE_URL = "http://localhost:8010"
    ticket = create_ticket(
        actor=django_user_model.objects.create_user("attachment.owner"),
        title="Com evidência",
        description="Falha apresentada na tela.",
        category=Category.objects.create(name="Anexos"),
        priority="NORMAL",
        attachments=[
            SimpleUploadedFile("segredo.pdf", b"%PDF-1.4\n%%EOF", "application/pdf"),
            SimpleUploadedFile("print.png", b"\x89PNG\r\n\x1a\nimage", "image/png"),
        ],
    )

    description = _card_description(ticket, ticket.planner_provisioning.correlation_id)

    assert "Este chamado possui 2 anexos. Consulte-os no C+ Service Desk." in description
    assert "segredo.pdf" not in description
    assert "print.png" not in description
    assert "/chamados/" not in description
    assert not AttachmentPublication.objects.exists()
