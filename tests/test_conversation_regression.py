"""Exercise the real template/context/API path that the unit reader tests missed."""

from unittest.mock import Mock

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.planner_integration.client import GraphClient
from apps.tickets.models import Category, Ticket, TicketComment

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def conversation_settings(settings):
    settings.PLANNER_OBSERVATIONS_ENABLED = True
    settings.MICROSOFT_GRAPH_APPROVED = True
    settings.GRAPH_DELEGATED_OAUTH_ENABLED = True
    settings.GRAPH_AUTH_STRATEGY = "delegated"
    settings.PORTAL_BASE_URL = "http://localhost:8010"
    settings.PLANNER_PLAN_ID = "conversation-plan"
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def ticket(django_user_model):
    return Ticket.objects.create(
        number="SD-CHAT-REGRESSION", title="Conversa existente", description="Teste",
        requester=django_user_model.objects.create_user("conversation-owner"),
        category=Category.objects.create(name="Conversa"),
        planner_task_id="conversation-task", planner_plan_id="conversation-plan",
    )


@pytest.mark.parametrize("origin", ["http://localhost:8010", "https://chamados.cmais.local"])
def test_existing_conversation_is_rendered_and_read_end_to_end(ticket, client, settings, monkeypatch, origin):
    from apps.planner_integration import observations

    settings.PORTAL_BASE_URL = origin
    graph = Mock(spec=GraphClient, timeout=8)
    graph.get_task.return_value = {"id": ticket.planner_task_id, "planId": ticket.planner_plan_id}
    graph._request_json.return_value = {"value": [{
        "id": "existing-message", "content": "Mensagem já enviada",
        "createdDateTime": "2026-11-10T10:00:00Z",
    }]}
    factory = Mock(return_value=graph)
    monkeypatch.setattr(observations, "configured_read_client", factory)
    public = TicketComment.objects.create(ticket=ticket, author=ticket.requester, body="Comentário público existente")
    private = TicketComment.objects.create(ticket=ticket, author=ticket.requester, body="Comentário interno existente", is_internal=True)
    client.force_login(ticket.requester)
    response = client.get(reverse("tickets:detail", args=[ticket.pk]))
    html = response.content.decode()
    assert response.status_code == 200
    assert response.context["observations_enabled"] is True
    assert "data-observation-panel" in html
    assert 'src="/static/js/observations.js"' in html
    assert "data-observations-root" in html
    assert public.body in html and private.body not in html
    factory.assert_not_called()  # Rendering never queries Graph.
    result = client.get(reverse("tickets:observations", args=[ticket.pk])).json()
    assert result["complete"] is True
    assert result["messages"][0]["content"] == "Mensagem já enviada"
    assert TicketComment.objects.count() == 2
    public.refresh_from_db()
    private.refresh_from_db()
    assert public.body == "Comentário público existente"
    assert private.body == "Comentário interno existente"
    # The two previous improvements remain in the real template.
    assert 'id="planner-status"' in html
    assert 'class="button button-primary" data-loading-label="Consultando Planner…"' in html


@pytest.mark.parametrize("flag,value", [
    ("PLANNER_OBSERVATIONS_ENABLED", False), ("MICROSOFT_GRAPH_APPROVED", False),
    ("GRAPH_DELEGATED_OAUTH_ENABLED", False), ("GRAPH_AUTH_STRATEGY", "client_credentials"),
])
def test_disabled_conversation_remains_hidden_and_never_calls_graph(ticket, client, settings, monkeypatch, flag, value):
    from apps.planner_integration import observations

    settings.PORTAL_BASE_URL = "https://chamados.cmais.local"
    setattr(settings, flag, value)
    factory = Mock(side_effect=AssertionError("Graph must not be called"))
    monkeypatch.setattr(observations, "configured_read_client", factory)
    client.force_login(ticket.requester)
    html = client.get(reverse("tickets:detail", args=[ticket.pk])).content.decode()
    assert "data-observation-panel" not in html
    assert 'src="/static/js/observations.js"' not in html
    assert client.get(reverse("tickets:observations", args=[ticket.pk])).status_code == 404
    factory.assert_not_called()


@pytest.mark.parametrize("origin", [
    "http://chamados.cmais.local", "http://localhost:8000", "https://user:password@chamados.cmais.local",
    "https://chamados.cmais.local/?token=x", "https://chamados.cmais.local/#fragment", "https://[invalid",
])
def test_invalid_or_unapproved_origin_cannot_enable_chat(settings, origin):
    from apps.planner_integration.observations import enabled

    settings.PORTAL_BASE_URL = origin
    assert not enabled()


def test_other_user_cannot_read_existing_conversation(ticket, client, django_user_model, monkeypatch):
    from apps.planner_integration import observations

    factory = Mock(side_effect=AssertionError("Graph must not be called"))
    monkeypatch.setattr(observations, "configured_read_client", factory)
    client.force_login(django_user_model.objects.create_user("conversation-stranger"))
    assert client.get(reverse("tickets:detail", args=[ticket.pk])).status_code == 404
    assert client.get(reverse("tickets:observations", args=[ticket.pk])).status_code == 404
    factory.assert_not_called()
