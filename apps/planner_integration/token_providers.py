"""Token providers that are safe to call from Celery workers."""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .client import PlannerError
from .delegated_oauth import _post_form, decrypt_token, encrypt_token, redirect_uri
from .models import MicrosoftGraphConnection


class DelegatedTokenProvider:
    def __init__(self, connection_id, *, refresher=None):
        self.connection_id = connection_id
        self.refresher = refresher or self._refresh

    def __call__(self):
        # Refresh-token rotation can invalidate a concurrent refresh. Serialize it
        # across Celery workers and re-check expiry after acquiring the lock.
        try:
            with transaction.atomic():
                connection = MicrosoftGraphConnection.objects.select_for_update().get(
                    pk=self.connection_id, is_active=True
                )
                if connection.access_token_expires_at > timezone.now() + timedelta(seconds=60):
                    return decrypt_token(connection.access_token_encrypted)
                token_data = self.refresher(decrypt_token(connection.refresh_token_encrypted))
                self._save_refresh(connection, token_data)
                return token_data["access_token"]
        except MicrosoftGraphConnection.DoesNotExist:
            raise PlannerError("AUTH_REQUIRED", "Autorização Microsoft indisponível.") from None

    def _refresh(self, refresh_token):
        values = {
            "client_id": settings.GRAPH_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "redirect_uri": redirect_uri(),
        }
        if settings.GRAPH_CLIENT_SECRET:
            values["client_secret"] = settings.GRAPH_CLIENT_SECRET
        return _post_form(
            f"https://login.microsoftonline.com/{settings.GRAPH_TENANT_ID}/oauth2/v2.0/token", values
        )

    def _save_refresh(self, connection, token_data):
        try:
            expires_in = int(token_data.get("expires_in", 0))
        except (AttributeError, TypeError, ValueError):
            expires_in = 0
        access_token = token_data.get("access_token") if isinstance(token_data, dict) else None
        if not isinstance(access_token, str) or not access_token or expires_in < 60:
            raise PlannerError("AUTH_REQUIRED", "Autorização Microsoft indisponível.")
        refresh_token = token_data.get("refresh_token") or decrypt_token(connection.refresh_token_encrypted)
        if not isinstance(refresh_token, str) or not refresh_token:
            raise PlannerError("AUTH_REQUIRED", "Autorização Microsoft indisponível.")
        connection.access_token_encrypted = encrypt_token(access_token)
        connection.refresh_token_encrypted = encrypt_token(refresh_token)
        connection.access_token_expires_at = timezone.now() + timedelta(seconds=expires_in)
        connection.save(update_fields=["access_token_encrypted", "refresh_token_encrypted", "access_token_expires_at", "updated_at"])
