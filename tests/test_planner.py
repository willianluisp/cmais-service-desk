from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest
from django.core.cache import cache
from django.test import Client, override_settings
from django.utils import timezone

from apps.tickets.models import Category, Ticket, TicketEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def ticket(django_user_model):
    owner = django_user_model.objects.create_user(
        username="planner-owner", email="owner@example.test"
    )
    return Ticket.objects.create(
        number="SD-2026-000001",
        requester=owner,
        title="Acesso",
        description="Dados privados",
        category=Category.objects.create(name="Acesso"),
        planner_task_id="task-1",
        planner_plan_id="plan-1",
        sync_state=Ticket.SyncState.PENDING,
    )


def payload(**changes):
    return {
        "id": "task-1",
        "planId": "plan-1",
        "bucketId": "bucket-1",
        "percentComplete": 0,
        "@odata.etag": 'W/"1"',
        **changes,
    }


class Graph:
    def __init__(self, data):
        self.data = data

    def get_task(self, task_id):
        return self.data


@override_settings(PLANNER_PLAN_ID="plan-1", PLANNER_ENABLED=False,
                   MICROSOFT_GRAPH_APPROVED=True, GRAPH_DELEGATED_OAUTH_ENABLED=True,
                   GRAPH_AUTH_STRATEGY="delegated")
def test_manual_sync_reads_graph_with_automatic_publication_disabled(ticket, client, monkeypatch):
    from apps.planner_integration.client import configured_read_client

    monkeypatch.setattr("apps.planner_integration.client.configured_planner_token_provider", lambda: lambda: "mock")
    graph = configured_read_client()
    monkeypatch.setattr(type(graph), "get_task", lambda self, task_id: payload(bucketId="working"))
    monkeypatch.setattr(type(graph), "get_task_details", lambda self, task_id: {})
    client.force_login(ticket.requester)
    from django.urls import reverse

    with override_settings(PLANNER_IN_PROGRESS_BUCKET_ID="working"):
        response = client.post(reverse("planner:sync", args=[ticket.pk]))
    assert response.status_code == 200
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.EM_ATENDIMENTO


@override_settings(PLANNER_PLAN_ID="plan-1")
def test_confirmed_deletion_hides_ticket_preserves_audit_and_prevents_recreation(ticket, client):
    from apps.planner_integration.client import PlannerError
    from apps.planner_integration.models import PlannerTaskProvisioning
    from apps.planner_integration.services import process_pending_provisioning, sync_ticket
    from apps.tickets.permissions import visible_tickets

    outbox = PlannerTaskProvisioning.objects.create(ticket=ticket)

    class DeletedGraph:
        def get_task(self, task_id):
            raise PlannerError("TASK_NOT_FOUND", "Tarefa ausente.", status=404)

        def list_plan_buckets(self, plan_id):
            return [{"id": "bucket-1", "planId": plan_id}]

        def list_plan_tasks(self, plan_id):
            return []

    result = sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=DeletedGraph())
    assert result["deleted"]
    ticket.refresh_from_db()
    assert ticket.planner_deleted_at and ticket.planner_task_id == "task-1"
    assert ticket.events.filter(event_type="PLANNER_DELETED").count() == 1
    assert not visible_tickets(ticket.requester, Ticket.objects.all()).exists()
    assert process_pending_provisioning(graph_client=DeletedGraph(), provisioning_id=outbox.pk) == 0
    client.force_login(ticket.requester)
    assert client.get(f"/chamados/{ticket.pk}/").status_code == 404


@pytest.mark.parametrize("code,status", [("AUTH_REQUIRED", 401), ("FORBIDDEN", 403), ("GRAPH_UNAVAILABLE", 503), ("THROTTLED", 429)])
@override_settings(PLANNER_PLAN_ID="plan-1")
def test_api_failures_never_hide_ticket(ticket, code, status):
    from apps.planner_integration.client import PlannerError
    from apps.planner_integration.services import sync_ticket

    class FailedGraph:
        def get_task(self, task_id):
            raise PlannerError(code, "Consulta falhou.", status=status)

    with pytest.raises(PlannerError):
        sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=FailedGraph())
    ticket.refresh_from_db()
    assert ticket.planner_deleted_at is None
    assert not ticket.events.filter(event_type="PLANNER_DELETED").exists()


@override_settings(PLANNER_PLAN_ID="plan-1")
def test_404_with_plan_access_denied_never_hides_ticket(ticket):
    from apps.planner_integration.client import PlannerError
    from apps.planner_integration.services import sync_ticket

    class AmbiguousGraph:
        def get_task(self, task_id):
            raise PlannerError("TASK_NOT_FOUND", "Ausente.", status=404)

        def list_plan_buckets(self, plan_id):
            raise PlannerError("FORBIDDEN", "Acesso negado.", status=403)

    with pytest.raises(PlannerError):
        sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=AmbiguousGraph())
    ticket.refresh_from_db()
    assert ticket.planner_deleted_at is None


@pytest.mark.parametrize("still_listed", [True, False])
@override_settings(PLANNER_PLAN_ID="plan-1")
def test_ambiguous_404_or_recovered_task_is_preserved(ticket, still_listed):
    from apps.planner_integration.client import PlannerError
    from apps.planner_integration.services import sync_ticket

    class RecoveringGraph:
        calls = 0

        def get_task(self, task_id):
            self.calls += 1
            if self.calls == 1:
                raise PlannerError("TASK_NOT_FOUND", "Ausente.", status=404)
            return payload()

        def list_plan_buckets(self, plan_id):
            return []

        def list_plan_tasks(self, plan_id):
            return [payload()] if still_listed else []

    with pytest.raises(PlannerError):
        sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=RecoveringGraph())
    ticket.refresh_from_db()
    assert ticket.planner_deleted_at is None


def test_deleted_ticket_hidden_from_portal_admin_but_retained_for_audit(ticket, django_user_model):
    from django.contrib.auth.models import Group

    from apps.tickets.permissions import visible_tickets

    admin = django_user_model.objects.create_user("audit-admin")
    admin.groups.add(Group.objects.get_or_create(name="ADMIN_PORTAL")[0])
    ticket.planner_deleted_at = timezone.now()
    ticket.save(update_fields=["planner_deleted_at"])
    assert not visible_tickets(admin, Ticket.objects.all()).exists()
    assert Ticket.objects.filter(pk=ticket.pk).exists()


def test_htmx_error_never_reports_success(ticket, client, monkeypatch):
    from django.urls import reverse

    from apps.planner_integration.client import PlannerError

    def fail(**kwargs):
        raise PlannerError("FORBIDDEN", "Conta Microsoft sem permissão para consultar a tarefa.", status=403)

    client.force_login(ticket.requester)
    monkeypatch.setattr("apps.planner_integration.views.enforce_rate_limit", lambda *args: None)
    monkeypatch.setattr("apps.planner_integration.views.sync_ticket", fail)
    response = client.post(reverse("planner:sync", args=[ticket.pk]), HTTP_HX_REQUEST="true")
    assert response.status_code == 403
    assert response["X-Planner-Feedback"] == "error"
    assert "sem permissão" in response.content.decode()
    assert "Status atualizado" not in response.content.decode()


@override_settings(PLANNER_SYNC_ENABLED=False, MICROSOFT_GRAPH_APPROVED=True)
def test_periodic_sync_stays_disabled_by_default(ticket):
    from apps.planner_integration.tasks import synchronize_linked_tasks

    assert synchronize_linked_tasks() == 0


@override_settings(PLANNER_PLAN_ID="plan-1")
def test_sync_resolves_and_deduplicates_observations_and_outbox(ticket):
    from apps.notifications.models import NotificationOutbox
    from apps.planner_integration.services import sync_ticket

    graph = Graph(payload(percentComplete=100))
    result = sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=graph)
    assert result["changed"] and result["status"] == Ticket.Status.RESOLVIDO
    event = ticket.events.get()
    assert event.origin == TicketEvent.Origin.PLANNER_SYNC
    assert event.actor is None
    assert "Dados privados" not in event.summary
    assert NotificationOutbox.objects.count() == 1
    second = sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=graph)
    assert second["changed"] is False
    assert ticket.events.count() == NotificationOutbox.objects.count() == 1
    ticket.refresh_from_db()
    assert ticket.resolved_at and ticket.last_planner_sync_at


@pytest.mark.parametrize(
    ("percent", "bucket", "expected"),
    [
        (100, "other", "RESOLVIDO"),
        (0, "done", "RESOLVIDO"),
        (0, "working", "EM_ATENDIMENTO"),
        (100, "working", "EM_ATENDIMENTO"),
        (5, "other", "EM_ATENDIMENTO"),
        (0, "waiting", "AGUARDANDO_SOLICITANTE"),
        (0, "other", "ABERTO"),
    ],
)
@override_settings(
    PLANNER_COMPLETED_BUCKET_ID="done",
    PLANNER_IN_PROGRESS_BUCKET_ID="working",
    PLANNER_BUCKET_STATUS_MAP={"waiting": "AGUARDANDO_SOLICITANTE"},
)
def test_mapping(percent, bucket, expected):
    from apps.planner_integration.services import derive_status

    assert derive_status(percent, bucket) == expected


@override_settings(PLANNER_PLAN_ID="plan-1")
def test_closed_ticket_keeps_status_and_ignores_stale_response(ticket):
    from apps.planner_integration.client import PlannerError
    from apps.planner_integration.services import sync_ticket

    ticket.status = Ticket.Status.FECHADO
    ticket.save()
    sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=Graph(payload()))
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.FECHADO

    class RacingGraph:
        def get_task(self, task_id):
            Ticket.objects.filter(pk=ticket.pk).update(version=ticket.version + 1)
            return payload(percentComplete=100)

    with pytest.raises(PlannerError, match="atualizado") as error:
        sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=RacingGraph())
    assert error.value.code == "STALE_RESPONSE"


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "other"},
        {"planId": "other"},
        {"percentComplete": True},
        {"percentComplete": -1},
        {"percentComplete": 101},
        {"bucketId": None},
    ],
)
@override_settings(PLANNER_PLAN_ID="plan-1")
def test_invalid_graph_snapshot_never_changes_status(ticket, changes):
    from apps.planner_integration.client import PlannerError
    from apps.planner_integration.services import sync_ticket

    with pytest.raises(PlannerError):
        sync_ticket(
            actor=ticket.requester, ticket_id=ticket.pk, graph_client=Graph(payload(**changes))
        )
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.ABERTO
    assert not ticket.events.exists()
    assert ticket.sync_state == Ticket.SyncState.ERROR


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "AUTH_REQUIRED"),
        (403, "FORBIDDEN"),
        (404, "TASK_NOT_FOUND"),
        (429, "THROTTLED"),
        (500, "GRAPH_UNAVAILABLE"),
    ],
)
def test_graph_errors_are_sanitized_and_preserve_retry_after(status, code):
    from apps.planner_integration.client import GraphClient, PlannerError

    def opener(request, timeout):
        raise HTTPError(
            request.full_url, status, "SECRET", {"Retry-After": "42"}, BytesIO(b"SECRET token")
        )

    graph = GraphClient(token_provider=lambda: "server-token", opener=opener)
    with pytest.raises(PlannerError) as caught:
        graph.get_task("task-1")
    assert caught.value.code == code
    assert caught.value.retry_after == 42
    assert "SECRET" not in str(caught.value)


def test_graph_timeout_and_fixed_https_endpoint():
    from apps.planner_integration.client import GraphClient, PlannerError

    def opener(request, timeout):
        assert request.full_url == "https://graph.microsoft.com/v1.0/planner/tasks/task%2F1"
        assert request.get_header("Authorization") == "Bearer server-token"
        assert timeout <= 10
        raise URLError(TimeoutError("SECRET"))

    with pytest.raises(PlannerError) as caught:
        GraphClient(token_provider=lambda: "server-token", opener=opener).get_task("task/1")
    assert caught.value.code == "GRAPH_UNAVAILABLE"


@override_settings(
    PLANNER_ENABLED=True,
    MICROSOFT_GRAPH_APPROVED=True,
    GRAPH_TENANT_ID="tenant-id",
    GRAPH_AUTH_STRATEGY="client_credentials",
    GRAPH_CLIENT_ID="client-id",
    GRAPH_CLIENT_SECRET="test-secret",
    PLANNER_PLAN_ID="plan-1",
    PLANNER_INTAKE_BUCKET_ID="bucket-1",
)
def test_configured_graph_clients_reuse_the_server_token_provider():
    from apps.planner_integration.client import configured_client

    first = configured_client()
    second = configured_client()
    assert first.token_provider is second.token_provider


def test_client_credential_token_throttle_is_retryable_without_leaking_secret():
    from apps.planner_integration.client import ClientCredentialTokenProvider, PlannerError

    def opener(request, timeout):
        raise HTTPError(request.full_url, 429, "secret", {"Retry-After": "15"}, BytesIO(b"secret"))

    provider = ClientCredentialTokenProvider("tenant", "client", "secret", opener=opener)
    with pytest.raises(PlannerError) as caught:
        provider()
    assert caught.value.code == "AUTH_THROTTLED"
    assert caught.value.status == 429
    assert caught.value.retry_after == 15
    assert "secret" not in str(caught.value)


@override_settings(PLANNER_PLAN_ID="plan-1", PLANNER_INTAKE_BUCKET_ID="bucket-1")
def test_provisioning_links_the_card_once(ticket):
    from apps.planner_integration.models import PlannerTaskProvisioning
    from apps.planner_integration.services import process_pending_provisioning

    ticket.planner_task_id = None
    ticket.save(update_fields=["planner_task_id"])
    provisioning = PlannerTaskProvisioning.objects.create(ticket=ticket)

    class CreateGraph:
        def create_task(self, **kwargs):
            assert kwargs["plan_id"] == "plan-1"
            assert kwargs["bucket_id"] == "bucket-1"
            assert kwargs["title"] == ticket.title
            return payload(id="created-task")

    assert process_pending_provisioning(graph_client=CreateGraph()) == 1
    ticket.refresh_from_db()
    provisioning.refresh_from_db()
    assert ticket.planner_task_id == "created-task"
    assert provisioning.state == PlannerTaskProvisioning.State.LINKED
    assert process_pending_provisioning(graph_client=CreateGraph()) == 0


@override_settings(PLANNER_PLAN_ID="plan-1", PLANNER_INTAKE_BUCKET_ID="bucket-1")
def test_provisioning_can_target_one_outbox_item_without_processing_older_items(
    ticket, django_user_model
):
    from apps.planner_integration.models import PlannerTaskProvisioning
    from apps.planner_integration.services import process_pending_provisioning

    older = PlannerTaskProvisioning.objects.create(ticket=ticket)
    requester = django_user_model.objects.create_user("new-requester")
    selected_ticket = Ticket.objects.create(
        requester=requester,
        number="C+2026-000999",
        title="Chamado selecionado",
        description="Somente este deve ser publicado.",
        category=ticket.category,
        priority=Ticket.Priority.NORMAL,
    )
    selected = PlannerTaskProvisioning.objects.create(ticket=selected_ticket)

    class CreateGraph:
        def create_task(self, **kwargs):
            assert kwargs["title"] == selected_ticket.title
            return payload(id="selected-task")

    assert (
        process_pending_provisioning(
            graph_client=CreateGraph(), provisioning_id=selected.pk
        )
        == 1
    )
    older.refresh_from_db()
    selected.refresh_from_db()
    selected_ticket.refresh_from_db()
    assert older.state == PlannerTaskProvisioning.State.PENDING
    assert selected.state == PlannerTaskProvisioning.State.LINKED
    assert selected_ticket.planner_task_id == "selected-task"


@override_settings(PLANNER_PLAN_ID="plan-1", PLANNER_INTAKE_BUCKET_ID="bucket-1")
def test_pending_provisioning_reconciles_existing_title_before_post(ticket):
    from apps.planner_integration.models import PlannerTaskProvisioning
    from apps.planner_integration.services import process_pending_provisioning

    ticket.planner_task_id = None
    ticket.save(update_fields=["planner_task_id"])
    provisioning = PlannerTaskProvisioning.objects.create(ticket=ticket)

    class ExistingGraph:
        def list_plan_tasks(self, plan_id):
            return [payload(id="already-created", title=f"[{ticket.number}] {ticket.title}")]

        def create_task(self, **kwargs):
            raise AssertionError("must not create a duplicate task")

    assert (
        process_pending_provisioning(
            graph_client=ExistingGraph(), provisioning_id=provisioning.pk
        )
        == 1
    )
    provisioning.refresh_from_db()
    ticket.refresh_from_db()
    assert provisioning.state == PlannerTaskProvisioning.State.LINKED
    assert ticket.planner_task_id == "already-created"


@override_settings(PLANNER_PLAN_ID="plan-1", PLANNER_INTAKE_BUCKET_ID="bucket-1")
def test_provisioning_link_keeps_history_without_duplicate_received_notification(ticket):
    from apps.notifications.models import NotificationOutbox
    from apps.planner_integration.models import PlannerTaskProvisioning
    from apps.planner_integration.services import process_pending_provisioning

    ticket.planner_task_id = None
    ticket.save(update_fields=["planner_task_id"])
    PlannerTaskProvisioning.objects.create(ticket=ticket)

    class CreateGraph:
        def create_task(self, **kwargs):
            return payload(id="created-task")

    assert process_pending_provisioning(graph_client=CreateGraph()) == 1
    assert TicketEvent.objects.filter(event_type="PLANNER_LINKED").count() == 1
    assert NotificationOutbox.objects.count() == 0
    assert process_pending_provisioning(graph_client=CreateGraph()) == 0
    assert NotificationOutbox.objects.count() == 0


@override_settings(PLANNER_PLAN_ID="plan-1", PLANNER_INTAKE_BUCKET_ID="bucket-1")
def test_details_timeout_after_creation_never_reposts_card(ticket):
    from apps.planner_integration.client import PlannerError
    from apps.planner_integration.models import PlannerTaskProvisioning
    from apps.planner_integration.services import process_pending_provisioning

    ticket.planner_task_id = None
    ticket.save(update_fields=["planner_task_id"])
    provisioning = PlannerTaskProvisioning.objects.create(ticket=ticket)

    class DetailTimeoutGraph:
        create_calls = 0

        def create_task(self, **kwargs):
            self.create_calls += 1
            return payload(id="created-task")

        def update_task_details(self, *args, **kwargs):
            raise PlannerError("GRAPH_UNAVAILABLE", "indisponível")

    graph = DetailTimeoutGraph()
    assert process_pending_provisioning(graph_client=graph) == 1
    ticket.refresh_from_db()
    provisioning.refresh_from_db()
    assert ticket.planner_task_id == "created-task"
    assert provisioning.state == PlannerTaskProvisioning.State.RECONCILIATION
    provisioning.available_at = timezone.now()
    provisioning.save(update_fields=["available_at"])
    assert process_pending_provisioning(graph_client=graph) == 1
    assert graph.create_calls == 1


@override_settings(PLANNER_PLAN_ID="plan-1", PLANNER_INTAKE_BUCKET_ID="bucket-1")
def test_provisioning_reconciles_after_timeout_without_second_post(ticket):
    from apps.planner_integration.client import PlannerError
    from apps.planner_integration.models import PlannerTaskProvisioning
    from apps.planner_integration.services import process_pending_provisioning

    ticket.planner_task_id = None
    ticket.save(update_fields=["planner_task_id"])
    provisioning = PlannerTaskProvisioning.objects.create(ticket=ticket)

    class TimeoutGraph:
        def create_task(self, **kwargs):
            raise PlannerError("GRAPH_UNAVAILABLE", "indisponível")

    process_pending_provisioning(graph_client=TimeoutGraph())
    provisioning.refresh_from_db()
    assert provisioning.state == PlannerTaskProvisioning.State.RECONCILIATION
    provisioning.available_at = timezone.now()
    provisioning.save(update_fields=["available_at"])

    class ReconciliationGraph:
        def list_plan_tasks(self, plan_id):
            return [payload(id="recovered-task", title=f"[{ticket.number}] {ticket.title}")]

        def create_task(self, **kwargs):
            raise AssertionError("must not submit a duplicate card")

    process_pending_provisioning(graph_client=ReconciliationGraph())
    ticket.refresh_from_db()
    assert ticket.planner_task_id == "recovered-task"


@override_settings(PLANNER_PLAN_ID="plan-1")
def test_sync_projects_assignee_due_and_checklist_once(ticket):
    from apps.planner_integration.services import sync_ticket

    class DetailGraph(Graph):
        def get_task_details(self, task_id):
            return {"checklist": {"a": {"title": "A", "isChecked": True}, "b": {"title": "B", "isChecked": False}}}

    data = payload(assignments={"user-1": {"@odata.type": "#microsoft.graph.plannerAssignment"}}, dueDateTime="2026-11-01T12:00:00Z")
    graph = DetailGraph(data)
    assert sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=graph)["changed"]
    ticket.refresh_from_db()
    assert ticket.planner_assignee_ids == ["user-1"]
    assert ticket.planner_checklist_completed == 1
    assert ticket.planner_checklist_total == 2
    assert not sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=graph)["changed"]


@override_settings(ROOT_URLCONF="tests.urls_planner")
def test_endpoint_acl_csrf_post_disabled_and_rate_limit(ticket, django_user_model):
    from apps.planner_integration.views import synchronize

    cache.clear()
    url = f"/chamados/{ticket.pk}/sincronizar/"
    browser = Client(enforce_csrf_checks=True)
    assert browser.post(url).status_code == 403
    browser.force_login(ticket.requester)
    assert browser.get(url).status_code == 405
    assert browser.post(url).status_code == 403
    browser = Client()
    stranger = django_user_model.objects.create_user(username="stranger")
    browser.force_login(stranger)
    assert browser.post(url).status_code == 404
    browser.force_login(ticket.requester)
    response = browser.post(url, {"token": "UNTRUSTED"})
    assert response.status_code == 503
    assert response.json()["code"] == "INTEGRATION_DISABLED"
    assert browser.post(url).status_code == 429
    assert response.json()["changed"] is False
    assert synchronize
