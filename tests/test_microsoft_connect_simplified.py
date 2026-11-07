from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client
from django.utils import timezone

from apps.planner_integration.delegated_oauth import decrypt_token
from apps.planner_integration.models import MicrosoftGraphConnection

pytestmark = pytest.mark.django_db
KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


@pytest.fixture
def admin_client(settings, django_user_model):
    settings.GRAPH_AUTH_STRATEGY = "delegated"
    settings.MICROSOFT_GRAPH_APPROVED = True
    settings.GRAPH_DELEGATED_OAUTH_ENABLED = True
    settings.GRAPH_TENANT_ID = "synthetic-tenant"
    settings.GRAPH_CLIENT_ID = "synthetic-client"
    settings.GRAPH_CLIENT_SECRET = "synthetic-secret"
    settings.GRAPH_TOKEN_ENCRYPTION_KEY = KEY
    settings.PORTAL_BASE_URL = "http://localhost:8010"
    settings.PLANNER_ENABLED = False
    settings.PLANNER_SYNC_ENABLED = False
    settings.PLANNER_ATTACHMENTS_ENABLED = False
    user = django_user_model.objects.create_superuser("simplified", password="test-password")
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.parametrize("flag", ["MICROSOFT_GRAPH_APPROVED", "GRAPH_DELEGATED_OAUTH_ENABLED"])
def test_missing_approval_explained_and_blocks_login(admin_client, settings, flag):
    setattr(settings, flag, False)
    panel = admin_client.get("/integracoes/")
    assert not panel.context["can_connect"]
    assert "aprovação" in panel.content.decode().lower()
    response = admin_client.get("/integracoes/microsoft/conectar/")
    assert response.status_code == 403
    assert "graph_delegated_oauth" not in admin_client.session


def test_initial_secret_saved_encrypted_without_approving_anything(admin_client, settings, caplog):
    from apps.planner_integration.models import MicrosoftOAuthConfiguration

    settings.GRAPH_CLIENT_SECRET = ""
    settings.MICROSOFT_GRAPH_APPROVED = False
    settings.GRAPH_DELEGATED_OAUTH_ENABLED = False
    response = admin_client.post("/integracoes/microsoft/configurar/", {"client_secret": "local-secret-value"})
    assert response.status_code == 302
    config = MicrosoftOAuthConfiguration.objects.get(pk=1)
    assert decrypt_token(config.client_secret_encrypted) == "local-secret-value"
    panel = admin_client.get("/integracoes/")
    assert "local-secret-value" not in panel.content.decode() + caplog.text
    assert not panel.context["can_connect"]
    assert not settings.MICROSOFT_GRAPH_APPROVED and not settings.GRAPH_DELEGATED_OAUTH_ENABLED


def test_complete_connection_disconnect_and_reconnect_without_env_changes(admin_client, settings, monkeypatch):
    settings.GRAPH_CLIENT_SECRET = ""
    assert not admin_client.get("/integracoes/").context["can_connect"]
    admin_client.post("/integracoes/microsoft/configurar/", {"client_secret": "local-secret-value"})
    assert admin_client.get("/integracoes/").context["can_connect"]
    exchanges = []

    def exchange(url, values, **kwargs):
        exchanges.append(values)
        return {"access_token": "access-value", "refresh_token": "refresh-value", "expires_in": 3600,
                "scope": "User.Read Tasks.ReadWrite"}

    monkeypatch.setattr("apps.planner_integration.delegated_oauth._post_form", exchange)
    monkeypatch.setattr("apps.planner_integration.views.microsoft_identity", lambda token: {
        "id": "synthetic-user", "userPrincipalName": "synthetic@example.test"})
    for _ in range(2):
        response = admin_client.get("/integracoes/microsoft/conectar/")
        parsed = urlparse(response["Location"])
        assert parsed.netloc == "login.microsoftonline.com"
        query = parse_qs(parsed.query)
        assert query["code_challenge_method"] == ["S256"]
        assert "Sites.Selected" not in query["scope"][0]
        state = query["state"][0]
        verifier = admin_client.session["graph_delegated_oauth"]["code_verifier"]
        response = admin_client.get("/integracoes/microsoft/callback/", {"state": state, "code": "synthetic-code"})
        assert response.status_code == 302
        assert exchanges[-1]["client_secret"] == "local-secret-value"
        assert exchanges[-1]["code_verifier"] == verifier
        connection = MicrosoftGraphConnection.objects.get(is_active=True)
        assert decrypt_token(connection.access_token_encrypted) == "access-value"
        assert decrypt_token(connection.refresh_token_encrypted) == "refresh-value"
        assert "Conectado" in admin_client.get("/integracoes/").content.decode()
        assert admin_client.get("/integracoes/microsoft/callback/", {"state": state, "code": "replay"}).status_code == 400
        assert admin_client.get("/integracoes/microsoft/desconectar/").status_code == 405
        assert admin_client.post("/integracoes/microsoft/desconectar/").status_code == 302
        connection.refresh_from_db()
        assert not connection.is_active
        assert connection.access_token_encrypted == connection.refresh_token_encrypted == ""
        assert admin_client.session.get("_auth_user_id")
    assert not settings.PLANNER_ENABLED and not settings.PLANNER_SYNC_ENABLED
    assert not settings.PLANNER_ATTACHMENTS_ENABLED


def test_expired_state_and_provider_denial_offer_retry_without_leaking_details(admin_client, monkeypatch, caplog):
    monkeypatch.setattr("apps.planner_integration.views.exchange_authorization_code", lambda **kw: pytest.fail("network"))
    admin_client.get("/integracoes/microsoft/conectar/")
    session = admin_client.session
    state = session["graph_delegated_oauth"]["state"]
    session["graph_delegated_oauth"]["created_at"] = 1
    session.save()
    response = admin_client.get("/integracoes/microsoft/callback/", {"state": state, "code": "hidden-code"})
    assert response.status_code == 400
    assert "expirada" in response.content.decode()
    assert b'/integracoes/' in response.content
    admin_client.get("/integracoes/microsoft/conectar/")
    state = admin_client.session["graph_delegated_oauth"]["state"]
    response = admin_client.get("/integracoes/microsoft/callback/", {
        "state": state, "error": "access_denied", "error_description": "hidden-provider-detail"})
    assert response.status_code == 400
    assert "consentimento" in response.content.decode()
    assert "hidden-provider-detail" not in response.content.decode() + caplog.text


@pytest.mark.parametrize("scope", [None, "User.Read", "Tasks.ReadWrite.All"])
def test_missing_scope_cannot_create_connection(admin_client, monkeypatch, scope):
    monkeypatch.setattr("apps.planner_integration.views.exchange_authorization_code", lambda **kw: {
        "access_token": "access", "refresh_token": "refresh", "expires_in": 3600, "scope": scope})
    monkeypatch.setattr("apps.planner_integration.views.microsoft_identity", lambda token: {
        "id": "synthetic-user", "userPrincipalName": "synthetic@example.test"})
    admin_client.get("/integracoes/microsoft/conectar/")
    state = admin_client.session["graph_delegated_oauth"]["state"]
    response = admin_client.get("/integracoes/microsoft/callback/", {"state": state, "code": "code"})
    assert response.status_code == 400
    assert "permissão Planner" in response.content.decode()
    assert not MicrosoftGraphConnection.objects.exists()


def test_expired_connection_explains_renewal_and_allows_reconnect(admin_client):
    from django.contrib.auth import get_user_model

    MicrosoftGraphConnection.objects.create(
        user=get_user_model().objects.get(username="simplified"), is_active=True,
        microsoft_user_id="synthetic-user", access_token_encrypted="ciphertext", refresh_token_encrypted="ciphertext",
        access_token_expires_at=timezone.now() - timedelta(minutes=1))
    panel = admin_client.get("/integracoes/")
    assert panel.context["can_connect"]
    assert "expirado" in panel.content.decode()


def test_configuration_and_disconnect_require_admin_and_csrf(admin_client, django_user_model):
    client = Client(enforce_csrf_checks=True)
    client.force_login(django_user_model.objects.get(username="simplified"))
    for action in ("configurar", "desconectar"):
        assert client.post(f"/integracoes/microsoft/{action}/").status_code == 403
    user = django_user_model.objects.create_user("ordinary", password="password")
    admin_client.force_login(user)
    for action in ("configurar", "desconectar"):
        assert admin_client.post(f"/integracoes/microsoft/{action}/").status_code == 403


def test_revoked_refresh_requires_reconnect_and_erases_unusable_tokens(admin_client, monkeypatch):
    from django.contrib.auth import get_user_model

    from apps.planner_integration.client import PlannerError
    from apps.planner_integration.delegated_oauth import encrypt_token
    from apps.planner_integration.token_providers import DelegatedTokenProvider

    connection = MicrosoftGraphConnection.objects.create(
        user=get_user_model().objects.get(username="simplified"), is_active=True,
        microsoft_user_id="synthetic-user", access_token_encrypted=encrypt_token("old-access"),
        refresh_token_encrypted=encrypt_token("old-refresh"),
        access_token_expires_at=timezone.now() - timedelta(minutes=1))

    def revoked(refresh):
        raise PlannerError("OAUTH_INVALID_GRANT", "hidden-provider-detail")

    with pytest.raises(PlannerError, match="Reconecte"):
        DelegatedTokenProvider(connection.pk, refresher=revoked)()
    connection.refresh_from_db()
    assert not connection.is_active
    assert connection.access_token_encrypted == connection.refresh_token_encrypted == ""
    panel = admin_client.get("/integracoes/")
    assert "Desconectado" in panel.content.decode()
    assert panel.context["can_connect"]


def test_refresh_reuses_local_secret_without_environment_edit(admin_client, settings, monkeypatch):
    from django.contrib.auth import get_user_model

    from apps.planner_integration.delegated_oauth import encrypt_token
    from apps.planner_integration.token_providers import DelegatedTokenProvider

    settings.GRAPH_CLIENT_SECRET = ""
    admin_client.post("/integracoes/microsoft/configurar/", {"client_secret": "local-refresh-secret"})
    connection = MicrosoftGraphConnection.objects.create(
        user=get_user_model().objects.get(username="simplified"), is_active=True,
        microsoft_user_id="synthetic-user", access_token_encrypted=encrypt_token("old-access"),
        refresh_token_encrypted=encrypt_token("old-refresh"),
        access_token_expires_at=timezone.now() - timedelta(minutes=1))

    def refresh(url, values):
        assert values["client_secret"] == "local-refresh-secret"
        assert values["refresh_token"] == "old-refresh"
        return {"access_token": "renewed-access", "refresh_token": "renewed-refresh", "expires_in": 3600}

    monkeypatch.setattr("apps.planner_integration.token_providers._post_form", refresh)
    assert DelegatedTokenProvider(connection.pk)() == "renewed-access"
    connection.refresh_from_db()
    assert decrypt_token(connection.refresh_token_encrypted) == "renewed-refresh"


def test_switching_strategy_or_application_does_not_reuse_pending_login(admin_client, settings):
    settings.GRAPH_AUTH_STRATEGY = "client_credentials"
    assert not admin_client.get("/integracoes/").context["can_connect"]
    assert admin_client.get("/integracoes/microsoft/conectar/").status_code == 503
    settings.GRAPH_AUTH_STRATEGY = "delegated"
    admin_client.get("/integracoes/microsoft/conectar/")
    state = admin_client.session["graph_delegated_oauth"]["state"]
    settings.GRAPH_CLIENT_ID = "different-application"
    assert admin_client.get("/integracoes/microsoft/callback/", {"state": state, "code": "code"}).status_code == 400


def test_expired_local_login_explains_reauthentication_without_echoing_code(admin_client):
    admin_client.get("/integracoes/microsoft/conectar/")
    state = admin_client.session["graph_delegated_oauth"]["state"]
    admin_client.logout()
    response = admin_client.get("/integracoes/microsoft/callback/", {"state": state, "code": "hidden-expired-code"})
    assert response.status_code == 400
    assert "sessão local expirou" in response.content.decode()
    assert "hidden-expired-code" not in response.content.decode()


def test_admin_can_rotate_injected_secret_in_panel(admin_client, monkeypatch):
    from apps.planner_integration.oauth_configuration import client_secret

    assert client_secret() == "synthetic-secret"
    admin_client.post("/integracoes/microsoft/configurar/", {"client_secret": "replacement-secret"})
    assert client_secret() == "replacement-secret"


def test_secret_for_other_application_is_not_reused(admin_client, settings):
    from apps.planner_integration.oauth_configuration import client_secret

    settings.GRAPH_CLIENT_SECRET = ""
    admin_client.post("/integracoes/microsoft/configurar/", {"client_secret": "scoped-secret"})
    settings.GRAPH_CLIENT_ID = "other-client"
    assert client_secret() == ""
    assert not admin_client.get("/integracoes/").context["can_connect"]


def test_old_failed_refresh_cannot_erase_a_concurrent_reconnection(admin_client, monkeypatch):
    from django.contrib.auth import get_user_model
    from django.db.models.query import QuerySet

    from apps.planner_integration.client import PlannerError
    from apps.planner_integration.delegated_oauth import store_connection
    from apps.planner_integration.token_providers import DelegatedTokenProvider

    user = get_user_model().objects.get(username="simplified")

    def connect(access, refresh):
        return store_connection(user=user, tenant_id="synthetic-tenant", microsoft_user_id="same-account",
            microsoft_user_principal_name="synthetic@example.test", token_data={
                "access_token": access, "refresh_token": refresh, "expires_in": 60,
                "scope": "User.Read Tasks.ReadWrite"})

    old = connect("old-access", "old-refresh")
    update = QuerySet.update
    reconnected = []

    def reconnect_at_invalidation(queryset, **values):
        if queryset.model == MicrosoftGraphConnection and values.get("access_token_encrypted") == "" and not reconnected:
            reconnected.append(True)
            connect("new-access", "new-refresh")
        return update(queryset, **values)

    monkeypatch.setattr(QuerySet, "update", reconnect_at_invalidation)

    def revoked(refresh):
        raise PlannerError("OAUTH_INVALID_GRANT", "synthetic failure")

    with pytest.raises(PlannerError):
        DelegatedTokenProvider(old.pk, refresher=revoked)()
    old.refresh_from_db()
    assert old.is_active
    assert decrypt_token(old.access_token_encrypted) == "new-access"
    assert decrypt_token(old.refresh_token_encrypted) == "new-refresh"
