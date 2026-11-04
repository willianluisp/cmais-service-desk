from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def compose():
    path = ROOT / "compose.yaml"
    assert path.is_file(), "Compose deve existir para operar os cinco serviços."
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_database_and_broker_are_isolated_from_host(compose):
    for name in ("db", "redis"):
        service = compose["services"][name]
        assert not service.get("ports")
        assert all(compose["networks"][network].get("internal") for network in service["networks"])


def test_only_web_publishes_a_localhost_port(compose):
    published = {
        name: service["ports"]
        for name, service in compose["services"].items()
        if service.get("ports")
    }
    assert list(published) == ["web"]
    assert all(port.startswith("127.0.0.1:") for port in published["web"])


@pytest.mark.parametrize("name", ["web", "worker", "beat"])
def test_application_services_use_nonroot_and_wait_for_dependencies(compose, name):
    service = compose["services"][name]
    assert service["user"] == "10001:10001"
    assert service["depends_on"]["db"]["condition"] == "service_healthy"
    assert service["depends_on"]["redis"]["condition"] == "service_healthy"
    assert "migrate" not in str(service["command"])
    assert service["security_opt"] == ["no-new-privileges:true"]


def test_every_service_has_healthcheck_and_persistent_data_volumes(compose):
    assert set(compose["services"]) == {"web", "db", "redis", "worker", "beat"}
    for service in compose["services"].values():
        assert service["healthcheck"]["test"]
    assert {"postgres_data", "redis_data", "attachments", "beat_state"} <= set(compose["volumes"])


def test_isolated_services_share_localhost_and_disabled_integrations():
    isolated = yaml.safe_load((ROOT / "compose.isolated.yaml").read_text(encoding="utf-8"))
    for name in ("web", "worker", "beat"):
        environment = isolated["services"][name]["environment"]
        assert environment["PORTAL_BASE_URL"] == "http://localhost:8010"
        assert environment["ALLOWED_HOSTS"] == "localhost"
        assert environment["CSRF_TRUSTED_ORIGINS"] == "http://localhost:8010"
        assert environment["SESSION_COOKIE_NAME"] == "cmais_isolated_sessionid"
        assert environment["CSRF_COOKIE_NAME"] == "cmais_isolated_csrftoken"
        for flag in ("MICROSOFT_GRAPH_APPROVED", "GRAPH_DELEGATED_OAUTH_ENABLED", "PLANNER_ENABLED", "EMAIL_ENABLED"):
            assert environment[flag] == "false"


def test_oauth_only_override_enables_only_web_authorization():
    override = yaml.safe_load((ROOT / "compose.oauth.isolated.yaml").read_text(encoding="utf-8"))
    assert set(override["services"]) == {"web"}
    environment = override["services"]["web"]["environment"]
    assert environment["MICROSOFT_GRAPH_APPROVED"] == "true"
    assert environment["GRAPH_DELEGATED_OAUTH_ENABLED"] == "true"
    for flag in ("PLANNER_ENABLED", "PLANNER_TEST_ENABLED", "EMAIL_ENABLED", "PLANNER_ATTACHMENTS_ENABLED",
                 "GRAPH_ATTACHMENTS_STORAGE_APPROVED", "GRAPH_ATTACHMENT_SCOPE_ENABLED"):
        assert environment[flag] == "false"


def test_controlled_planner_test_override_enables_no_automatic_processing():
    override = yaml.safe_load(
        (ROOT / "compose.planner-test.isolated.yaml").read_text(encoding="utf-8")
    )
    assert set(override["services"]) == {"web"}
    environment = override["services"]["web"]["environment"]
    assert environment["MICROSOFT_GRAPH_APPROVED"] == "true"
    assert environment["GRAPH_DELEGATED_OAUTH_ENABLED"] == "true"
    assert environment["PLANNER_TEST_ENABLED"] == "true"
    for flag in (
        "PLANNER_ENABLED",
        "EMAIL_ENABLED",
        "PLANNER_ATTACHMENTS_ENABLED",
        "GRAPH_ATTACHMENTS_STORAGE_APPROVED",
        "GRAPH_ATTACHMENT_SCOPE_ENABLED",
    ):
        assert environment[flag] == "false"
