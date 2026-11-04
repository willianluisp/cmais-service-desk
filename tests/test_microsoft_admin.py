from unittest.mock import Mock

import pytest
from django.test import Client
from django.utils import timezone

from apps.planner_integration.configuration import BUCKET_FIELDS, bucket_id
from apps.planner_integration.models import (
    DEMANDAS_PLAN_ID,
    PlannerConfiguration,
    PlannerTestAttempt,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(django_user_model, settings):
    settings.PLANNER_PLAN_ID = DEMANDAS_PLAN_ID
    user = django_user_model.objects.create_superuser("admin", "admin@example.test", "password")
    client = Client()
    client.force_login(user)
    return client


def test_panel_is_local_and_never_shows_tokens(admin_client, monkeypatch):
    monkeypatch.setattr("apps.planner_integration.admin_panel.graph", lambda: pytest.fail("network"))
    response = admin_client.get("/integracoes/")
    assert response.status_code == 200
    assert "Conexão pendente" in response.content.decode()
    assert "Teste real desabilitado" in response.content.decode()
    assert b"access_token_encrypted" not in response.content


def test_staff_cannot_manage_microsoft(django_user_model):
    client = Client()
    client.force_login(django_user_model.objects.create_user("staff", is_staff=True))
    assert client.get("/integracoes/").status_code == 403
    for path in ("buckets", "mapeamento", "teste"):
        assert client.post(f"/integracoes/microsoft/{path}/").status_code == 403
    assert client.get("/integracoes/microsoft/conectar/").status_code == 403
    assert client.post("/integracoes/microsoft/conectar/").status_code == 405


def test_operations_require_csrf_and_post(admin_client):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.cookies = admin_client.cookies
    for path in ("buckets", "mapeamento", "teste"):
        assert admin_client.get(f"/integracoes/microsoft/{path}/").status_code == 405
        assert csrf_client.post(f"/integracoes/microsoft/{path}/").status_code == 403


def test_mapping_accepts_only_observed_distinct_ids(admin_client):
    config = PlannerConfiguration.objects.create(buckets=[
        {"id": str(i), "name": label} for i, label in enumerate(BUCKET_FIELDS.values())
    ], buckets_checked_at=timezone.now())
    mapping = {field: str(i) for i, field in enumerate(BUCKET_FIELDS)}
    admin_client.post("/integracoes/microsoft/mapeamento/", mapping)
    config.refresh_from_db()
    assert config.bucket_mapping == mapping
    assert bucket_id("PLANNER_INTAKE_BUCKET_ID") == "0"
    admin_client.post("/integracoes/microsoft/mapeamento/", {field: "invented" for field in BUCKET_FIELDS})
    config.refresh_from_db()
    assert config.bucket_mapping == mapping


def test_disabled_actions_do_not_call_graph(admin_client, monkeypatch):
    monkeypatch.setattr("apps.planner_integration.admin_panel.GraphClient", lambda **kwargs: pytest.fail("network"))
    admin_client.post("/integracoes/microsoft/buckets/")
    admin_client.post("/integracoes/microsoft/teste/", {"confirm": "CRIAR TAREFA DE TESTE"})
    assert not PlannerTestAttempt.objects.exists()


def test_controlled_test_requires_confirmation_and_deduplicates(admin_client, monkeypatch, settings):
    settings.MICROSOFT_GRAPH_APPROVED = True
    settings.PLANNER_TEST_ENABLED = True
    settings.PLANNER_INTAKE_BUCKET_ID = "entry"
    graph = Mock()
    graph.create_task.return_value = {"id": "test-task", "planId": DEMANDAS_PLAN_ID}
    monkeypatch.setattr("apps.planner_integration.admin_panel.graph", lambda: graph)
    admin_client.get("/integracoes/")
    data = {"nonce": admin_client.session["planner_test_nonce"], "confirm": "wrong"}
    admin_client.post("/integracoes/microsoft/teste/", data)
    graph.create_task.assert_not_called()
    data["confirm"] = "CRIAR TAREFA DE TESTE"
    admin_client.post("/integracoes/microsoft/teste/", data)
    admin_client.post("/integracoes/microsoft/teste/", data)
    graph.create_task.assert_called_once()
    assert PlannerTestAttempt.objects.get().task_id == "test-task"


def test_bucket_errors_do_not_leak_remote_payload(admin_client, monkeypatch):
    from apps.planner_integration.client import PlannerError

    graph = Mock()
    graph.list_plan_buckets.side_effect = PlannerError("SECRET", "SECRET remote credentials")
    monkeypatch.setattr("apps.planner_integration.admin_panel.graph", lambda: graph)
    response = admin_client.post("/integracoes/microsoft/buckets/", follow=True)
    assert b"SECRET" not in response.content
    assert "Consulta indisponível" in response.content.decode()


def test_bucket_snapshot_is_persisted_and_status_mapping_is_used(admin_client, monkeypatch):
    from apps.planner_integration.services import derive_status

    graph = Mock()
    graph.list_plan_buckets.return_value = [
        {"id": str(i), "name": label, "planId": DEMANDAS_PLAN_ID}
        for i, label in enumerate(BUCKET_FIELDS.values())
    ]
    monkeypatch.setattr("apps.planner_integration.admin_panel.graph", lambda: graph)
    admin_client.post("/integracoes/microsoft/buckets/")
    graph.list_plan_buckets.assert_called_once_with(DEMANDAS_PLAN_ID)
    mapping = {field: str(i) for i, field in enumerate(BUCKET_FIELDS)}
    admin_client.post("/integracoes/microsoft/mapeamento/", mapping)
    assert derive_status(0, "1") == "EM_ATENDIMENTO"
    assert derive_status(0, "2") == "RESOLVIDO"


def test_uncertain_creation_is_not_retried(admin_client, monkeypatch, settings):
    from apps.planner_integration.client import PlannerError

    settings.MICROSOFT_GRAPH_APPROVED = True
    settings.PLANNER_TEST_ENABLED = True
    settings.PLANNER_INTAKE_BUCKET_ID = "entry"
    graph = Mock()
    graph.create_task.side_effect = PlannerError("GRAPH_UNAVAILABLE", "private failure")
    monkeypatch.setattr("apps.planner_integration.admin_panel.graph", lambda: graph)
    admin_client.get("/integracoes/")
    data = {"nonce": admin_client.session["planner_test_nonce"], "confirm": "CRIAR TAREFA DE TESTE"}
    admin_client.post("/integracoes/microsoft/teste/", data)
    admin_client.post("/integracoes/microsoft/teste/", data)
    graph.create_task.assert_called_once()
    assert PlannerTestAttempt.objects.get().state == "VERIFY"
