"""Delegated Microsoft authorization-code flow for the isolated Planner account."""

import base64
import hashlib
import json
import secrets
import time
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from .client import NoRedirect, PlannerError, retry_after_seconds
from .models import MicrosoftGraphConnection

SESSION_KEY = "graph_delegated_oauth"
STATE_TTL_SECONDS = 600
SCOPES = ("openid", "profile", "offline_access", "User.Read", "Tasks.ReadWrite")
TOKEN_ERROR_CATEGORIES = {
    "invalid_client": "OAUTH_INVALID_CLIENT",
    "invalid_grant": "OAUTH_INVALID_GRANT",
    "invalid_request": "OAUTH_INVALID_REQUEST",
    "unauthorized_client": "OAUTH_UNAUTHORIZED_CLIENT",
    "interaction_required": "OAUTH_INTERACTION_REQUIRED",
    "temporarily_unavailable": "OAUTH_PROVIDER_UNAVAILABLE",
    "server_error": "OAUTH_PROVIDER_UNAVAILABLE",
}


def requested_scopes():
    return (*SCOPES, "Sites.Selected") if settings.GRAPH_ATTACHMENT_SCOPE_ENABLED else SCOPES


def redirect_uri():
    base_url = getattr(settings, "PORTAL_BASE_URL", "").rstrip("/")
    try:
        parsed = urlsplit(base_url)
        valid = (parsed.scheme == "https" or (
            parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
        )) and parsed.hostname and not (parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path)
    except ValueError:
        valid = False
    if not valid:
        raise PlannerError("OAUTH_CONFIGURATION", "Configuração OAuth Microsoft inválida.")
    return f"{base_url}/integracoes/microsoft/callback/"


def _fernet():
    key = getattr(settings, "GRAPH_TOKEN_ENCRYPTION_KEY", "")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        raise PlannerError("OAUTH_CONFIGURATION", "Criptografia de tokens Microsoft não configurada.") from None


def encrypt_token(value):
    if not isinstance(value, str) or not value:
        raise PlannerError("AUTH_REQUIRED", "Autorização Microsoft indisponível.")
    return _fernet().encrypt(value.encode()).decode()


def decrypt_token(value):
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, UnicodeError, AttributeError):
        raise PlannerError("AUTH_REQUIRED", "Autorização Microsoft indisponível.") from None


def authorization_url(request):
    tenant_id = getattr(settings, "GRAPH_TENANT_ID", "")
    client_id = getattr(settings, "GRAPH_CLIENT_ID", "")
    if not tenant_id or not client_id:
        raise PlannerError("OAUTH_CONFIGURATION", "Configuração OAuth Microsoft incompleta.")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    request.session[SESSION_KEY] = {
        "state": state,
        "code_verifier": verifier,
        "created_at": int(time.time()),
        "tenant_id": settings.GRAPH_TENANT_ID,
        "client_id": settings.GRAPH_CLIENT_ID,
        "redirect_uri": redirect_uri(),
    }
    request.session.modified = True
    return "https://login.microsoftonline.com/" + quote(tenant_id, safe="") + "/oauth2/v2.0/authorize?" + urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "response_mode": "query",
        "scope": " ".join(requested_scopes()),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })


def consume_state(request, state):
    pending = request.session.pop(SESSION_KEY, None)
    if not isinstance(pending, dict) or not isinstance(state, str):
        return None
    created_at = pending.get("created_at")
    expected = pending.get("state")
    if not isinstance(created_at, int) or not 0 <= time.time() - created_at <= STATE_TTL_SECONDS:
        return None
    if (pending.get("tenant_id") != settings.GRAPH_TENANT_ID
            or pending.get("client_id") != settings.GRAPH_CLIENT_ID
            or pending.get("redirect_uri") != redirect_uri()):
        return None
    if not isinstance(expected, str) or not secrets.compare_digest(expected, state):
        return None
    return pending.get("code_verifier") if isinstance(pending.get("code_verifier"), str) else None


@sensitive_variables()
def _post_form(url, values, *, opener=None):
    request = Request(
        url,
        data=urlencode(values).encode(),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        with (opener or build_opener(NoRedirect())).open(request, timeout=8) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError
        return json.loads(raw)
    except HTTPError as exc:
        if exc.code == 429:
            retry_after = retry_after_seconds(exc.headers.get('Retry-After')) if exc.headers else None
            exc.close()
            raise PlannerError('AUTH_THROTTLED', 'Autorização Microsoft temporariamente limitada.',
                               status=429, retry_after=retry_after) from None
        try:
            raw = exc.read(65537)
            data = json.loads(raw) if len(raw) <= 65536 else {}
            provider_code = data.get("error") if isinstance(data, dict) else None
        except (OSError, ValueError, UnicodeError):
            provider_code = None
        category = TOKEN_ERROR_CATEGORIES.get(provider_code, "OAUTH_TOKEN_REJECTED")
        exc.close()
        raise PlannerError(category, "A Microsoft rejeitou a solicitação de token.", status=400) from None
    except (URLError, OSError, TimeoutError):
        raise PlannerError(
            "OAUTH_PROVIDER_UNAVAILABLE", "Endpoint de token Microsoft indisponível."
        ) from None
    except (ValueError, UnicodeError):
        raise PlannerError("OAUTH_INVALID_RESPONSE", "Resposta de token Microsoft inválida.") from None


@sensitive_variables()
def exchange_authorization_code(*, code, code_verifier, opener=None):
    from .oauth_configuration import client_secret
    client_id = getattr(settings, "GRAPH_CLIENT_ID", "")
    tenant_id = getattr(settings, "GRAPH_TENANT_ID", "")
    if not client_id or not tenant_id or not code or not code_verifier:
        raise PlannerError("OAUTH_CONFIGURATION", "Configuração OAuth Microsoft incompleta.")
    values = {
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(),
        "code_verifier": code_verifier,
        "scope": " ".join(requested_scopes()),
    }
    secret = client_secret()
    if secret:
        values["client_secret"] = secret
    data = _post_form(
        "https://login.microsoftonline.com/" + quote(tenant_id, safe="") + "/oauth2/v2.0/token",
        values,
        opener=opener,
    )
    if not isinstance(data, dict) or not isinstance(data.get("access_token"), str):
        raise PlannerError("OAUTH_INVALID_RESPONSE", "Resposta de token Microsoft inválida.")
    return data


def microsoft_identity(access_token, *, opener=None):
    request = Request(
        "https://graph.microsoft.com/v1.0/me?$select=id,userPrincipalName",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    try:
        with (opener or build_opener(NoRedirect())).open(request, timeout=8) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError
        data = json.loads(raw)
    except HTTPError:
        raise PlannerError(
            "OAUTH_IDENTITY_DENIED", "Consulta da identidade Microsoft rejeitada.", status=400
        ) from None
    except (URLError, OSError, TimeoutError):
        raise PlannerError(
            "OAUTH_IDENTITY_UNAVAILABLE", "Consulta da identidade Microsoft indisponível."
        ) from None
    except (ValueError, UnicodeError):
        raise PlannerError("OAUTH_INVALID_RESPONSE", "Resposta de identidade inválida.") from None
    if not isinstance(data, dict) or not all(isinstance(data.get(key), str) and data[key] for key in ("id", "userPrincipalName")):
        raise PlannerError("OAUTH_INVALID_RESPONSE", "Resposta de identidade inválida.")
    return data


@sensitive_variables()
def store_connection(*, user, tenant_id, microsoft_user_id, microsoft_user_principal_name, token_data):
    access_token = token_data.get("access_token") if isinstance(token_data, dict) else None
    refresh_token = token_data.get("refresh_token") if isinstance(token_data, dict) else None
    try:
        expires_in = int(token_data.get("expires_in", 0))
    except (TypeError, ValueError):
        expires_in = 0
    if not isinstance(access_token, str) or not isinstance(refresh_token, str) or expires_in < 60:
        raise PlannerError("AUTH_REQUIRED", "Autorização Microsoft incompleta; autorize novamente.")
    scopes = token_data.get("scope", "")
    if not isinstance(scopes, str) or "Tasks.ReadWrite" not in scopes.split():
        raise PlannerError("OAUTH_INSUFFICIENT_SCOPE", "Permissão Planner ausente na conta Microsoft autorizada.")
    with transaction.atomic():
        existing_identity = (
            MicrosoftGraphConnection.objects.select_for_update()
            .filter(microsoft_user_id=microsoft_user_id)
            .exclude(user=user)
            .first()
        )
        if existing_identity is not None:
            raise PlannerError("AUTH_REQUIRED", "Conta Microsoft já vinculada a outro administrador local.")
        MicrosoftGraphConnection.objects.filter(is_active=True).update(is_active=False)
        connection, _ = MicrosoftGraphConnection.objects.update_or_create(
            user=user,
            defaults={
                "tenant_id": tenant_id,
                "microsoft_user_id": microsoft_user_id,
                "microsoft_user_principal_name": microsoft_user_principal_name,
                "scopes": scopes,
                "access_token_encrypted": encrypt_token(access_token),
                "refresh_token_encrypted": encrypt_token(refresh_token),
                "access_token_expires_at": timezone.now() + timedelta(seconds=expires_in),
                "is_active": True,
            },
        )
    return connection
