from io import BytesIO
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.planner_integration.client import GraphClient, PlannerError
from apps.planner_integration.services import sync_ticket
from apps.tickets.models import Category, Ticket

USER_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolated_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def ticket(django_user_model, settings):
    settings.PLANNER_PLAN_ID = "plan"
    return Ticket.objects.create(
        number="SD-ASSIGNEE", title="Acesso", description="Teste",
        category=Category.objects.create(name="Acesso"),
        requester=django_user_model.objects.create_user("assignee-owner"),
        planner_task_id="task", planner_plan_id="plan",
        planner_assignee_ids=[USER_ID], planner_assignee_names=[USER_ID],
    )


def graph_for(*ids):
    graph = Mock()
    graph.get_task.return_value = {
        "id": "task", "planId": "plan", "bucketId": "bucket", "percentComplete": 50,
        "assignments": {user_id: {} for user_id in ids},
    }
    graph.get_task_details.return_value = {}
    graph.get_user.return_value = {"id": USER_ID, "displayName": "Ana Contadora"}
    return graph


def test_sync_resolves_names_preserves_ids_and_reuses_cache(ticket):
    graph = graph_for(USER_ID)
    sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=graph)
    ticket.refresh_from_db()
    assert ticket.planner_assignee_ids == [USER_ID]
    assert ticket.planner_assignee_names == ["Ana Contadora"]
    assert not sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=graph)["changed"]
    graph.get_user.assert_called_once_with(USER_ID)


@pytest.mark.parametrize("status", [401, 403, 404, 429, 503])
def test_directory_failure_does_not_break_sync_and_is_cached(ticket, status):
    graph = graph_for(USER_ID)
    graph.get_user.side_effect = PlannerError("DIRECTORY_ERROR", "private", status=status)
    sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=graph)
    sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=graph)
    ticket.refresh_from_db()
    assert ticket.planner_assignee_names == ["Responsável indisponível"]
    assert ticket.planner_assignee_ids == [USER_ID]
    assert ticket.planner_percent_complete == 50
    assert ticket.sync_state == Ticket.SyncState.SYNCED
    graph.get_user.assert_called_once_with(USER_ID)


@pytest.mark.parametrize("profile", [None, [], {}, {"id": OTHER_ID, "displayName": "Wrong"},
    {"id": USER_ID, "displayName": " "}, {"id": USER_ID, "displayName": USER_ID}])
def test_malformed_profiles_never_become_names(ticket, profile):
    graph = graph_for(USER_ID)
    graph.get_user.return_value = profile
    sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=graph)
    ticket.refresh_from_db()
    assert ticket.planner_assignee_names == ["Responsável indisponível"]


def test_directory_outage_stops_lookups_for_other_assignees(ticket):
    graph = graph_for(USER_ID, OTHER_ID)
    graph.get_user.side_effect = PlannerError("THROTTLED", "private", status=429, retry_after=120)
    sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=graph)
    ticket.refresh_from_db()
    assert len(ticket.planner_assignee_names) == 2
    assert graph.get_user.call_count == 1


def test_multiple_assignees_keep_mapping_when_one_is_missing(ticket):
    graph = graph_for(USER_ID, OTHER_ID)
    def lookup(user_id):
        if user_id == OTHER_ID:
            raise PlannerError("NOT_FOUND", "missing", status=404)
        return {"id": USER_ID, "displayName": "Ana Contadora"}
    graph.get_user.side_effect = lookup
    sync_ticket(actor=ticket.requester, ticket_id=ticket.pk, graph_client=graph)
    ticket.refresh_from_db()
    assert dict(zip(ticket.planner_assignee_ids, ticket.planner_assignee_names, strict=True)) == {
        USER_ID: "Ana Contadora", OTHER_ID: "Responsável indisponível",
    }
    assert graph.get_user.call_count == 2


def test_cache_expires_and_is_separated_by_tenant(settings, monkeypatch):
    from apps.planner_integration.assignees import resolve_assignee_names

    now = [1000]
    monkeypatch.setattr("django.core.cache.backends.base.time.time", lambda: now[0])
    graph = graph_for(USER_ID)
    assert resolve_assignee_names([USER_ID, USER_ID], graph_client=graph) == ["Ana Contadora"] * 2
    graph.get_user.return_value = {"id": USER_ID, "displayName": "Ana Atualizada"}
    now[0] += 3601
    assert resolve_assignee_names([USER_ID], graph_client=graph) == ["Ana Atualizada"]
    settings.GRAPH_TENANT_ID = "another-tenant"
    resolve_assignee_names([USER_ID], graph_client=graph)
    assert graph.get_user.call_count == 3


def test_empty_and_invalid_assignments_never_query_directory():
    from apps.planner_integration.assignees import resolve_assignee_names

    graph = graph_for()
    assert resolve_assignee_names([], graph_client=graph) == []
    assert resolve_assignee_names(["../me", None], graph_client=graph) == ["Responsável indisponível"] * 2
    graph.get_user.assert_not_called()


def test_legacy_detail_resolves_without_database_writes_and_escapes_names(ticket, client, monkeypatch):
    graph = graph_for(USER_ID)
    graph.get_user.return_value = {"id": USER_ID, "displayName": "<script>Ana</script>"}
    monkeypatch.setattr("apps.planner_integration.assignees.configured_read_client", lambda: graph)
    client.force_login(ticket.requester)
    for _ in range(2):
        response = client.get(reverse("tickets:detail", args=[ticket.pk]))
        assert response.status_code == 200
        html = response.content.decode()
        assert "&lt;script&gt;Ana&lt;/script&gt;" in html
        assert USER_ID not in html
    graph.get_user.assert_called_once_with(USER_ID)
    ticket.refresh_from_db()
    assert ticket.planner_assignee_names == [USER_ID]


def test_detail_directory_unavailable_and_acl(ticket, client, monkeypatch, django_user_model):
    lookup = Mock(side_effect=PlannerError("FORBIDDEN", "private", status=403))
    monkeypatch.setattr("apps.planner_integration.assignees.configured_read_client", lookup)
    client.force_login(django_user_model.objects.create_user("stranger"))
    assert client.get(reverse("tickets:detail", args=[ticket.pk])).status_code == 404
    lookup.assert_not_called()
    client.force_login(ticket.requester)
    response = client.get(reverse("tickets:detail", args=[ticket.pk]))
    assert response.status_code == 200
    assert USER_ID not in response.content.decode()
    assert "Responsável indisponível" in response.content.decode()


def test_refresh_is_primary_near_status_and_hidden_for_sensitive_ticket(ticket, client, monkeypatch):
    monkeypatch.setattr("apps.planner_integration.assignees.configured_read_client", lambda: graph_for(USER_ID))
    client.force_login(ticket.requester)
    html = client.get(reverse("tickets:detail", args=[ticket.pk])).content.decode()
    # The action precedes the metadata, next to the main status rather than below the history.
    assert html.index("Atualizar status</button>") < html.index("Informações da solicitação")
    assert 'class="button button-primary" data-loading-label="Consultando Planner…"' in html
    assert "ui-icons.svg#refresh" in html
    assert html.count('hx-post=') == 1
    ticket.is_sensitive = True
    ticket.save(update_fields=["is_sensitive"])
    html = client.get(reverse("tickets:detail", args=[ticket.pk])).content.decode()
    assert "Atualizar status</button>" not in html


def test_graph_user_lookup_is_read_only_and_selects_basic_fields():
    response = Mock()
    response.status = 200
    response.read.return_value = ('{"id":"' + USER_ID + '","displayName":"Ana"}').encode()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener = Mock(return_value=response)
    graph = GraphClient(token_provider=lambda: "secret", opener=opener)
    assert graph.get_user(USER_ID)["displayName"] == "Ana"
    request = opener.call_args.args[0]
    assert request.full_url == f"https://graph.microsoft.com/v1.0/users/{USER_ID}?$select=id,displayName"
    assert request.get_method() == "GET"


def test_user_not_found_is_sanitized():
    def opener(request, timeout):
        raise HTTPError(request.full_url, 404, "secret", {}, BytesIO(b"secret"))

    with pytest.raises(PlannerError) as error:
        GraphClient(token_provider=lambda: "secret", opener=opener).get_user(USER_ID)
    assert error.value.status == 404
    assert "secret" not in str(error.value)
