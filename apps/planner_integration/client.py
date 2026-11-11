"""Graph transport: caller supplies an approved server-side token strategy.

This module does not acquire, persist or refresh Microsoft credentials.
"""

import json
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from threading import Lock
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings

_token_providers = {}
_token_providers_lock = Lock()


class TokenProvider(Protocol):
    def __call__(self) -> str: ...


class PlannerError(Exception):
    def __init__(self, code, message, *, status=503, retry_after=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.retry_after = retry_after


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def retry_after_seconds(value):
    if not value:
        return None
    try:
        seconds = int(value)
    except (ValueError, TypeError):
        try:
            seconds = int((parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None
    return max(1, min(seconds, 86400))


class GraphClient:
    def __init__(self, *, token_provider: TokenProvider, opener=None, timeout=8):
        self.token_provider = token_provider
        self.opener = opener or build_opener(NoRedirect()).open
        self.timeout = max(1, min(timeout, 10))

    def get_task(self, task_id):
        try:
            token = self.token_provider()
        except PlannerError:
            raise
        except Exception:
            raise PlannerError("AUTH_REQUIRED", "Autorização Microsoft indisponível.") from None
        if not isinstance(token, str) or not token or "\r" in token or "\n" in token:
            raise PlannerError("AUTH_REQUIRED", "Autorização Microsoft indisponível.")
        request = Request(
            "https://graph.microsoft.com/v1.0/planner/tasks/" + quote(task_id, safe=""),
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("payload too large")
            data = json.loads(raw)
        except HTTPError as exc:
            code = {
                401: "AUTH_REQUIRED",
                403: "FORBIDDEN",
                404: "TASK_NOT_FOUND",
                429: "THROTTLED",
            }.get(exc.code, "GRAPH_UNAVAILABLE")
            retry_after = (
                retry_after_seconds(exc.headers.get("Retry-After")) if exc.headers else None
            )
            exc.close()
            raise PlannerError(
                code,
                "Não foi possível consultar o Planner.",
                status=exc.code if exc.code in {401, 403, 404, 429} else 503,
                retry_after=retry_after,
            ) from None
        except (URLError, OSError, TimeoutError):
            raise PlannerError(
                "GRAPH_UNAVAILABLE", "Planner temporariamente indisponível."
            ) from None
        except (ValueError, UnicodeError):
            raise PlannerError("INVALID_PAYLOAD", "Resposta do Planner inválida.") from None
        return data

    def create_task(self, *, plan_id, bucket_id, title, priority=None):
        """Create the minimal Planner card. Workflow fields remain Planner-owned."""
        payload = {"planId": plan_id, "bucketId": bucket_id, "title": title}
        if type(priority) is int and 0 <= priority <= 10:
            payload['priority'] = priority
        url = 'https://graph.microsoft.com/v1.0/planner/tasks'
        try:
            return self._request_json(url, method='POST', payload=payload)
        except PlannerError as exc:
            # A definite 400 rejected the creation; fallback is safe here only.
            # Never retry an ambiguous timeout/5xx, throttling or authorization.
            if exc.status != 400 or 'priority' not in payload:
                raise
            return self._request_json(url, method='POST', payload={k: v for k, v in payload.items() if k != 'priority'})

    def list_my_plans(self):
        url = 'https://graph.microsoft.com/v1.0/me/planner/plans'
        plans = []
        for _ in range(100):
            data = self._request_json(url)
            if not isinstance(data, dict) or not isinstance(data.get('value'), list):
                raise PlannerError('INVALID_PAYLOAD', 'Lista de planos inválida.')
            for plan in data['value']:
                if not isinstance(plan, dict) or not all(
                    isinstance(plan.get(key), str) and 0 < len(plan[key]) <= 255
                    for key in ('id', 'title')
                ):
                    raise PlannerError('INVALID_PAYLOAD', 'Plano inválido.')
                plans.append({'id': plan['id'], 'title': plan['title']})
            url = data.get('@odata.nextLink')
            if not url:
                return plans
            if not isinstance(url, str) or not url.startswith('https://graph.microsoft.com/'):
                raise PlannerError('INVALID_PAYLOAD', 'Paginação de planos inválida.')
        raise PlannerError('INVALID_PAYLOAD', 'Paginação excedeu o limite seguro.')

    def list_plan_tasks(self, plan_id):
        url = (
            "https://graph.microsoft.com/v1.0/planner/plans/" + quote(plan_id, safe="") + "/tasks"
        )
        tasks = []
        for _ in range(100):
            data = self._request_json(url)
            if not isinstance(data, dict) or not isinstance(data.get("value"), list):
                raise PlannerError("INVALID_PAYLOAD", "Resposta do Planner inválida.")
            tasks.extend(data["value"])
            next_link = data.get("@odata.nextLink")
            if not next_link:
                return tasks
            if not isinstance(next_link, str) or not next_link.startswith("https://graph.microsoft.com/"):
                raise PlannerError("INVALID_PAYLOAD", "Paginação do Planner inválida.")
            url = next_link
        raise PlannerError("INVALID_PAYLOAD", "Paginação do Planner excedeu o limite seguro.")

    def get_user(self, user_id):
        return self._request_json(
            "https://graph.microsoft.com/v1.0/users/" + quote(user_id, safe="")
            + "?$select=id,displayName"
        )

    def get_task_details(self, task_id):
        return self._request_json(
            "https://graph.microsoft.com/v1.0/planner/tasks/"
            + quote(task_id, safe="")
            + "/details"
        )

    def list_plan_buckets(self, plan_id):
        url = "https://graph.microsoft.com/v1.0/planner/plans/" + quote(plan_id, safe="") + "/buckets"
        buckets = []
        for _ in range(100):
            data = self._request_json(url)
            if not isinstance(data, dict) or not isinstance(data.get("value"), list):
                raise PlannerError("INVALID_PAYLOAD", "Resposta de buckets inválida.")
            for bucket in data["value"]:
                if not isinstance(bucket, dict) or bucket.get("planId") != plan_id or not all(
                    isinstance(bucket.get(key), str) and bucket[key] for key in ("id", "name")
                ):
                    raise PlannerError("INVALID_PAYLOAD", "Bucket inválido ou plano divergente.")
                buckets.append(bucket)
            url = data.get("@odata.nextLink")
            if not url:
                return buckets
            if not isinstance(url, str) or not url.startswith("https://graph.microsoft.com/"):
                raise PlannerError("INVALID_PAYLOAD", "Paginação de buckets inválida.")
        raise PlannerError("INVALID_PAYLOAD", "Paginação excedeu o limite seguro.")

    def update_task_details(self, task_id, *, description, etag):
        details = self.get_task_details(task_id)
        etag = details.get("@odata.etag") if isinstance(details, dict) else None
        if not isinstance(etag, str) or not etag:
            raise PlannerError("INVALID_PAYLOAD", "ETag de detalhes do Planner ausente.")
        return self._request_json(
            "https://graph.microsoft.com/v1.0/planner/tasks/"
            + quote(task_id, safe="")
            + "/details",
            method="PATCH",
            payload={"description": description},
            extra_headers={"If-Match": etag},
        )

    def _request_json(self, url, *, method="GET", payload=None, extra_headers=None, raw_body=None, content_type=None):
        try:
            token = self.token_provider()
        except PlannerError:
            raise
        except Exception:
            raise PlannerError("AUTH_REQUIRED", "Autorização Microsoft indisponível.") from None
        if not isinstance(token, str) or not token or "\r" in token or "\n" in token:
            raise PlannerError("AUTH_REQUIRED", "Autorização Microsoft indisponível.")
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        headers.update(extra_headers or {})
        body = raw_body
        if raw_body is not None:
            headers["Content-Type"] = content_type or "application/octet-stream"
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, method=method, headers=headers)
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read(65537)
                if response.status == 204 and method == "PATCH":
                    return {}
            if len(raw) > 65536:
                raise ValueError("payload too large")
            return json.loads(raw)
        except HTTPError as exc:
            code = {400: 'INVALID_REQUEST', 401: "AUTH_REQUIRED", 403: "FORBIDDEN", 404: "TASK_NOT_FOUND", 409: "CONFLICT", 412: 'CONFLICT', 429: "THROTTLED"}.get(exc.code, "GRAPH_UNAVAILABLE")
            retry_after = retry_after_seconds(exc.headers.get("Retry-After")) if exc.headers else None
            exc.close()
            raise PlannerError(code, "Não foi possível consultar o Planner.", status=exc.code, retry_after=retry_after) from None
        except (URLError, OSError, TimeoutError):
            raise PlannerError("GRAPH_UNAVAILABLE", "Planner temporariamente indisponível.") from None
        except (ValueError, UnicodeError):
            raise PlannerError("INVALID_PAYLOAD", "Resposta do Planner inválida.") from None


def configured_client():
    from .configuration import automation_enabled, bucket_id, selected_plan_id

    if not automation_enabled():
        raise PlannerError("INTEGRATION_DISABLED", "Integração Planner não está aprovada.")
    if not all((
        getattr(settings, "GRAPH_TENANT_ID", ""),
        getattr(settings, "GRAPH_CLIENT_ID", ""),
        selected_plan_id(),
        bucket_id("PLANNER_INTAKE_BUCKET_ID"),
    )):
        raise PlannerError("INTEGRATION_DISABLED", "Configuração do Planner incompleta.")
    return GraphClient(token_provider=configured_planner_token_provider())


def configured_read_client():
    """Authorized reads are independent of automatic task publication."""
    from .configuration import selected_plan_id

    if not settings.MICROSOFT_GRAPH_APPROVED or not selected_plan_id():
        raise PlannerError("INTEGRATION_DISABLED", "Consulta ao Planner não está autorizada.")
    return GraphClient(token_provider=configured_planner_token_provider())


def configured_planner_token_provider():
    if not getattr(settings, "MICROSOFT_GRAPH_APPROVED", False):
        raise PlannerError("INTEGRATION_DISABLED", "Integração Microsoft não está aprovada.")
    strategy = getattr(settings, "GRAPH_AUTH_STRATEGY", "client_credentials")
    if strategy == "delegated":
        if not getattr(settings, "GRAPH_DELEGATED_OAUTH_ENABLED", False):
            raise PlannerError("INTEGRATION_DISABLED", "OAuth delegado não está aprovado.")
        from .models import MicrosoftGraphConnection
        from .token_providers import DelegatedTokenProvider

        connection = MicrosoftGraphConnection.objects.filter(is_active=True).only("pk").first()
        if connection is None:
            raise PlannerError("AUTH_REQUIRED", "Nenhuma conta Microsoft autorizada para o Planner.")
        return DelegatedTokenProvider(connection.pk)
    if strategy != "client_credentials":
        raise PlannerError("INTEGRATION_DISABLED", "Estratégia Microsoft inválida.")
    return configured_token_provider()


def configured_token_provider():
    """Return a process-local provider so Planner and Mail reuse one token."""
    tenant = getattr(settings, "GRAPH_TENANT_ID", "")
    client_id = getattr(settings, "GRAPH_CLIENT_ID", "")
    secret = getattr(settings, "GRAPH_CLIENT_SECRET", "")
    if not all((tenant, client_id, secret)):
        raise PlannerError("AUTH_REQUIRED", "Autorização Microsoft indisponível.")
    # Keep no plaintext secret in the cache key while allowing credential rotation.
    key = (tenant, client_id, sha256(secret.encode()).digest())
    with _token_providers_lock:
        provider = _token_providers.get(key)
        if provider is None:
            provider = ClientCredentialTokenProvider(tenant, client_id, secret)
            _token_providers.clear()
            _token_providers[key] = provider
        return provider


class ClientCredentialTokenProvider:
    """Server-side OAuth client-credentials token; it is unrelated to LDAP sessions."""

    def __init__(self, tenant_id, client_id, client_secret, opener=None):
        self.tenant_id, self.client_id, self.client_secret = tenant_id, client_id, client_secret
        self.opener = opener or build_opener(NoRedirect()).open
        self._token, self._expires_at = "", 0.0

    def __call__(self):
        if self._token and time.monotonic() < self._expires_at - 60:
            return self._token
        from urllib.parse import urlencode

        request = Request(
            "https://login.microsoftonline.com/" + quote(self.tenant_id, safe="") + "/oauth2/v2.0/token",
            data=urlencode({"client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "client_credentials", "scope": "https://graph.microsoft.com/.default"}).encode(),
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with self.opener(request, timeout=8) as response:
                data = json.loads(response.read(65537))
            token, expires = data.get("access_token"), int(data.get("expires_in", 0))
        except HTTPError as exc:
            retry_after = retry_after_seconds(exc.headers.get("Retry-After")) if exc.headers else None
            status = 429 if exc.code == 429 else 503
            code = "AUTH_THROTTLED" if exc.code == 429 else "AUTH_REQUIRED"
            exc.close()
            raise PlannerError(
                code,
                "Autorização Microsoft indisponível.",
                status=status,
                retry_after=retry_after,
            ) from None
        except (URLError, OSError, ValueError, TypeError):
            raise PlannerError("AUTH_REQUIRED", "Autorização Microsoft indisponível.") from None
        if not isinstance(token, str) or not token or expires < 60:
            raise PlannerError("AUTH_REQUIRED", "Autorização Microsoft indisponível.")
        self._token, self._expires_at = token, time.monotonic() + expires
        return token
