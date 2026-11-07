from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest
from django.db import OperationalError
from django.test import Client, override_settings

from apps.planner_integration.client import PlannerError
from apps.planner_integration.delegated_oauth import (
    exchange_authorization_code,
    microsoft_identity,
)


@pytest.fixture(autouse=True)
def delegated_web_application(settings):
    settings.GRAPH_AUTH_STRATEGY = "delegated"
    settings.GRAPH_CLIENT_SECRET = "synthetic-secret"


@pytest.mark.django_db
@override_settings(
    MICROSOFT_GRAPH_APPROVED=True,
    GRAPH_DELEGATED_OAUTH_ENABLED=True,
    GRAPH_TENANT_ID="tenant-id",
    GRAPH_CLIENT_ID="client-id",
    GRAPH_CLIENT_SECRET="client-secret",
    GRAPH_TOKEN_ENCRYPTION_KEY="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    PORTAL_BASE_URL="http://localhost:8010",
)
def test_connect_starts_authorization_code_with_pkce_and_callback_state(django_user_model):
    user = django_user_model.objects.create_superuser("admin", "admin@example.test", "password")
    client = Client()
    client.force_login(user)

    response = client.get("/integracoes/microsoft/conectar/")

    assert response.status_code == 302
    query = parse_qs(urlparse(response["Location"]).query)
    assert response["Location"].startswith(
        "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/authorize?"
    )
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == ["http://localhost:8010/integracoes/microsoft/callback/"]
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["state"][0]) >= 32
    assert "Tasks.ReadWrite" in query["scope"][0]
    assert "User.Read" in query["scope"][0]
    assert "offline_access" in query["scope"][0]
    assert client.session["graph_delegated_oauth"]["state"] == query["state"][0]
    assert client.session["graph_delegated_oauth"]["code_verifier"] != query["code_challenge"][0]

    # OAuth starts as a normal same-origin navigation.  It must not be a form
    # submission whose external redirect is blocked by CSP form-action 'self'.
    assert client.post("/integracoes/microsoft/conectar/").status_code == 405


@pytest.mark.django_db
@override_settings(
    MICROSOFT_GRAPH_APPROVED=True,
    GRAPH_DELEGATED_OAUTH_ENABLED=True,
)
def test_integration_panel_uses_internal_oauth_link_and_keeps_strict_csp(django_user_model):
    user = django_user_model.objects.create_superuser("admin", "admin@example.test", "password")
    client = Client()
    client.force_login(user)

    with override_settings(
        GRAPH_TENANT_ID='synthetic-tenant', GRAPH_CLIENT_ID='synthetic-client',
        GRAPH_TOKEN_ENCRYPTION_KEY='MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=',
        PORTAL_BASE_URL='http://localhost:8010',
    ):
        response = client.get("/integracoes/")

    assert response.status_code == 200
    body = response.content.decode()
    assert 'href="/integracoes/microsoft/conectar/"' in body
    assert 'action="/integracoes/microsoft/conectar/"' not in body
    assert 'name="htmx-config"' in body
    assert 'content=\'{"includeIndicatorStyles":false}\'' in body
    csp = response.headers["Content-Security-Policy"]
    assert "style-src 'self'" in csp and "'unsafe-inline'" not in csp
    assert "form-action 'self'" in csp and "form-action *" not in csp


@pytest.mark.django_db
@override_settings(
    MICROSOFT_GRAPH_APPROVED=True,
    GRAPH_DELEGATED_OAUTH_ENABLED=True,
    GRAPH_TENANT_ID="tenant-id",
    GRAPH_CLIENT_ID="client-id",
    GRAPH_CLIENT_SECRET="client-secret",
    GRAPH_TOKEN_ENCRYPTION_KEY="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    PORTAL_BASE_URL="http://localhost:8010",
)
def test_callback_rejects_invalid_state_without_exchanging_code(django_user_model, monkeypatch):
    user = django_user_model.objects.create_superuser("admin", "admin@example.test", "password")
    client = Client()
    client.force_login(user)
    client.get("/integracoes/microsoft/conectar/")
    monkeypatch.setattr(
        "apps.planner_integration.views.exchange_authorization_code", lambda **kwargs: pytest.fail("called")
    )

    response = client.get("/integracoes/microsoft/callback/?code=code&state=wrong")

    assert response.status_code == 400
    assert "graph_delegated_oauth" not in client.session


@pytest.mark.django_db
@override_settings(
    MICROSOFT_GRAPH_APPROVED=True,
    GRAPH_DELEGATED_OAUTH_ENABLED=True,
    GRAPH_TENANT_ID="tenant-id",
    GRAPH_CLIENT_ID="client-id",
    GRAPH_CLIENT_SECRET="client-secret",
    GRAPH_TOKEN_ENCRYPTION_KEY="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    PORTAL_BASE_URL="http://localhost:8010",
)
def test_callback_stores_encrypted_connection_and_keeps_local_session(django_user_model, monkeypatch):
    from apps.planner_integration.models import MicrosoftGraphConnection

    user = django_user_model.objects.create_superuser("admin", "admin@example.test", "password")
    client = Client()
    client.force_login(user)
    client.get("/integracoes/microsoft/conectar/")
    state = client.session["graph_delegated_oauth"]["state"]
    monkeypatch.setattr("apps.planner_integration.views.exchange_authorization_code", lambda **kwargs: {
        "access_token": "access-token", "refresh_token": "refresh-token", "expires_in": 3600,
        "scope": "openid profile offline_access Tasks.ReadWrite",
    })
    monkeypatch.setattr("apps.planner_integration.views.microsoft_identity", lambda token: {
        "id": "entra-id", "userPrincipalName": "planner@example.test"
    })

    response = client.get(f"/integracoes/microsoft/callback/?code=code&state={state}")

    assert response.status_code == 302
    assert response["Location"] == "/integracoes/"
    connection = MicrosoftGraphConnection.objects.get(user=user)
    assert connection.is_active
    assert "access-token" not in connection.access_token_encrypted
    assert client.session["_auth_user_id"] == str(user.pk)


class RejectingTokenOpener:
    def __init__(self, payload):
        self.payload = payload

    def open(self, request, timeout):
        raise HTTPError(request.full_url, 401, "rejected", {}, BytesIO(self.payload))


@override_settings(
    GRAPH_TENANT_ID="tenant-id",
    GRAPH_CLIENT_ID="client-id",
    GRAPH_CLIENT_SECRET="client-secret",
    PORTAL_BASE_URL="http://localhost:8010",
)
@pytest.mark.django_db
def test_token_exchange_categorizes_invalid_client_without_leaking_provider_details():
    provider_payload = b'{"error":"invalid_client","error_description":"secret-value-must-not-leak"}'

    with pytest.raises(PlannerError) as captured:
        exchange_authorization_code(
            code="authorization-code-must-not-leak",
            code_verifier="pkce-verifier-must-not-leak",
            opener=RejectingTokenOpener(provider_payload),
        )

    assert captured.value.code == "OAUTH_INVALID_CLIENT"
    assert "secret-value-must-not-leak" not in str(captured.value)
    assert "authorization-code-must-not-leak" not in str(captured.value)


@pytest.mark.django_db
@override_settings(
    MICROSOFT_GRAPH_APPROVED=True,
    GRAPH_DELEGATED_OAUTH_ENABLED=True,
    GRAPH_TENANT_ID="tenant-id",
    GRAPH_CLIENT_ID="client-id",
    PORTAL_BASE_URL="http://localhost:8010",
)
def test_callback_reports_safe_stage_and_category_without_oauth_secrets(
    django_user_model, monkeypatch, caplog, settings
):
    settings.GRAPH_TOKEN_ENCRYPTION_KEY = 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='
    user = django_user_model.objects.create_superuser("admin", "admin@example.test", "password")
    client = Client()
    client.force_login(user)
    client.get("/integracoes/microsoft/conectar/")
    state = client.session["graph_delegated_oauth"]["state"]
    monkeypatch.setattr(
        "apps.planner_integration.views.exchange_authorization_code",
        lambda **kwargs: (_ for _ in ()).throw(
            PlannerError("OAUTH_INVALID_CLIENT", "provider-secret-must-not-leak")
        ),
    )

    response = client.get(
        "/integracoes/microsoft/callback/",
        {"code": "authorization-code-must-not-leak", "state": state},
    )

    body = response.content.decode()
    assert response.status_code == 400
    assert "troca do código" in body
    assert "credencial da aplicação rejeitada" in body
    assert "provider-secret-must-not-leak" not in body
    assert "authorization-code-must-not-leak" not in body
    assert "stage=token_exchange category=OAUTH_INVALID_CLIENT" in caplog.text
    assert "provider-secret-must-not-leak" not in caplog.text
    assert "authorization-code-must-not-leak" not in caplog.text


def test_identity_lookup_categorizes_graph_denial_without_reading_error_body():
    with pytest.raises(PlannerError) as captured:
        microsoft_identity(
            "access-token-must-not-leak",
            opener=RejectingTokenOpener(b'{"sensitive":"provider-details"}'),
        )

    assert captured.value.code == "OAUTH_IDENTITY_DENIED"
    assert "access-token-must-not-leak" not in str(captured.value)
    assert "provider-details" not in str(captured.value)


@pytest.mark.django_db
@override_settings(
    MICROSOFT_GRAPH_APPROVED=True,
    GRAPH_DELEGATED_OAUTH_ENABLED=True,
    GRAPH_TENANT_ID="tenant-id",
    GRAPH_CLIENT_ID="client-id",
    PORTAL_BASE_URL="http://localhost:8010",
)
def test_callback_reports_safe_storage_failure(django_user_model, monkeypatch, settings):
    settings.GRAPH_TOKEN_ENCRYPTION_KEY = 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='
    user = django_user_model.objects.create_superuser("admin", "admin@example.test", "password")
    client = Client()
    client.force_login(user)
    client.get("/integracoes/microsoft/conectar/")
    state = client.session["graph_delegated_oauth"]["state"]
    monkeypatch.setattr(
        "apps.planner_integration.views.exchange_authorization_code",
        lambda **kwargs: {"access_token": "access", "refresh_token": "refresh"},
    )
    monkeypatch.setattr(
        "apps.planner_integration.views.microsoft_identity",
        lambda token: {"id": "entra-id", "userPrincipalName": "admin@example.test"},
    )
    monkeypatch.setattr(
        "apps.planner_integration.views.store_connection",
        lambda **kwargs: (_ for _ in ()).throw(OperationalError("database-details")),
    )

    response = client.get(
        "/integracoes/microsoft/callback/", {"code": "code", "state": state}
    )

    body = response.content.decode()
    assert response.status_code == 400
    assert "armazenamento criptografado" in body
    assert "armazenamento temporariamente indisponível" in body
    assert "database-details" not in body


@pytest.mark.django_db
@override_settings(GRAPH_TOKEN_ENCRYPTION_KEY="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
def test_delegated_provider_refreshes_and_never_stores_plaintext(django_user_model):
    from apps.planner_integration.delegated_oauth import store_connection
    from apps.planner_integration.token_providers import DelegatedTokenProvider

    user = django_user_model.objects.create_user("planner-admin", "admin@example.test", "password")
    connection = store_connection(
        user=user,
        tenant_id="tenant-id",
        microsoft_user_id="entra-user-id",
        microsoft_user_principal_name="planner@example.test",
        token_data={"access_token": "old-access", "refresh_token": "refresh-token", "expires_in": 60,
                    "scope": "User.Read Tasks.ReadWrite"},
    )
    connection.refresh_from_db()
    assert "old-access" not in connection.access_token_encrypted
    assert "refresh-token" not in connection.refresh_token_encrypted

    provider = DelegatedTokenProvider(connection.pk, refresher=lambda refresh: {
        "access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600,
    })
    assert provider() == "new-access"
    connection.refresh_from_db()
    assert "new-access" not in connection.access_token_encrypted
    assert "new-refresh" not in connection.refresh_token_encrypted
