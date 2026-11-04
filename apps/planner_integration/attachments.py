"""Publish private attachment copies to an administrator-approved SharePoint folder.

No createLink, invitation or permission-grant endpoint is used. SharePoint ACLs
must be configured and homologated independently before storage approval.
"""

import hashlib
from datetime import timedelta
from urllib.parse import quote, urlsplit

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.tickets.models import TicketEvent
from apps.tickets.uploads import MAX_UPLOAD_SIZE, private_storage

from .client import GraphClient, PlannerError, configured_planner_token_provider
from .models import AttachmentPublication


def approved_url(value):
    host = settings.GRAPH_ATTACHMENTS_HOST.lower()
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname == host
                 and not parsed.username and not parsed.password and parsed.port in (None, 443)
                 and not parsed.query and not parsed.fragment and parsed.path.startswith("/"))
    except (ValueError, TypeError):
        valid = False
    if not host.endswith(".sharepoint.com") or not valid:
        raise PlannerError("UNSAFE_FILE_URL", "Endereço do arquivo corporativo inválido.")
    return value


class AttachmentGraphClient(GraphClient):
    def folder_is_private(self, drive, folder):
        prefix = f"https://graph.microsoft.com/v1.0/drives/{quote(drive, safe='')}/items/{quote(folder, safe='')}"
        item = self._request_json(prefix)
        if not isinstance(item, dict) or "folder" not in item or item.get("id") != folder:
            raise PlannerError("INVALID_FOLDER", "Pasta corporativa inválida.")
        approved_url(item.get("webUrl"))
        self.assert_no_sharing_links(drive, folder)

    def assert_no_sharing_links(self, drive, item_id):
        url = f"https://graph.microsoft.com/v1.0/drives/{quote(drive, safe='')}/items/{quote(item_id, safe='')}/permissions"
        for _ in range(100):
            data = self._request_json(url)
            if not isinstance(data, dict) or not isinstance(data.get("value"), list):
                raise PlannerError("INVALID_PERMISSIONS", "Permissões corporativas não verificadas.")
            # Reject existing sharing links too, not just links created here.
            if any(not isinstance(p, dict) or "link" in p for p in data["value"]):
                raise PlannerError("SHARING_LINK_DETECTED", "Revise o compartilhamento da pasta corporativa.")
            url = data.get("@odata.nextLink")
            if not url:
                return
            if not isinstance(url, str) or not url.startswith("https://graph.microsoft.com/"):
                raise PlannerError("INVALID_PERMISSIONS", "Paginação de permissões inválida.")
        raise PlannerError("INVALID_PERMISSIONS", "Paginação de permissões excedeu o limite.")

    def upload_attachment(self, attachment, data, drive, folder):
        extension = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}.get(attachment.mime_type)
        if not extension or not 0 < len(data) <= MAX_UPLOAD_SIZE:
            raise PlannerError("INVALID_LOCAL_FILE", "Arquivo local inválido.")
        # Deterministic opaque key: retry overwrites the same managed object,
        # never appends a second filename. TI should have read-only file access.
        filename = f"{attachment.pk}-{attachment.sha256}{extension}"
        url = (f"https://graph.microsoft.com/v1.0/drives/{quote(drive, safe='')}/items/"
               f"{quote(folder, safe='')}:/{quote(filename, safe='')}")
        try:
            item = self._request_json(url)
        except PlannerError as exc:
            if exc.code != "TASK_NOT_FOUND":
                raise
            item = self._request_json(url + ":/content", method="PUT", raw_body=data,
                                      content_type=attachment.mime_type)
        parent = item.get("parentReference", {}) if isinstance(item, dict) else {}
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]
                or item.get("size") != len(data) or item.get("name") != filename
                or "file" not in item or parent.get("driveId") != drive or parent.get("id") != folder):
            raise PlannerError("INVALID_REMOTE_FILE", "Arquivo remoto divergente.")
        approved_url(item.get("webUrl"))
        return item

    def attach_reference(self, task_id, web_url, alias):
        web_url = approved_url(web_url)
        details = self.get_task_details(task_id)
        if not isinstance(details, dict) or not details.get("@odata.etag"):
            raise PlannerError("INVALID_PAYLOAD", "ETag de detalhes ausente.")
        # Planner open-type property names require URL characters (including
        # dots and percent signs) encoded. quote deliberately preserves slash.
        key = quote(web_url, safe="/").replace(".", "%2E")
        if key in details.get("references", {}):
            return
        self._request_json(
            "https://graph.microsoft.com/v1.0/planner/tasks/" + quote(task_id, safe="") + "/details",
            method="PATCH", extra_headers={"If-Match": details["@odata.etag"]},
            payload={"references": {key: {"@odata.type": "microsoft.graph.plannerExternalReference",
                                          "alias": alias[:160], "type": "Other"}}},
        )


def process_publications(*, limit=10, graph_client=None):
    if not all((settings.MICROSOFT_GRAPH_APPROVED, settings.PLANNER_ENABLED,
                settings.PLANNER_ATTACHMENTS_ENABLED, settings.GRAPH_ATTACHMENTS_STORAGE_APPROVED)):
        return 0
    drive, folder = settings.GRAPH_ATTACHMENTS_DRIVE_ID, settings.GRAPH_ATTACHMENTS_FOLDER_ID
    if not drive or not folder or not settings.GRAPH_ATTACHMENTS_HOST or settings.GRAPH_AUTH_STRATEGY != "delegated":
        return 0
    processed = 0
    for _ in range(max(1, min(int(limit), 25))):
        with transaction.atomic():
            rows = AttachmentPublication.objects.filter(
                state__in=["PENDING", "UPLOADED"], available_at__lte=timezone.now(),
            ).exclude(attachment__ticket__planner_task_id__isnull=True).exclude(
                attachment__ticket__planner_task_id="",
            )
            rows = rows.select_for_update(skip_locked=True) if connection.features.has_select_for_update_skip_locked else rows.select_for_update()
            row = rows.order_by("available_at", "pk").first()
            if row is None:
                break
            row.attempts += 1
            attachment = row.attachment
            try:
                client = graph_client or AttachmentGraphClient(token_provider=configured_planner_token_provider())
                if row.drive_id and (row.drive_id != drive or row.folder_id != folder):
                    raise PlannerError("STORAGE_CHANGED", "Destino alterado; revisão necessária.")
                client.folder_is_private(drive, folder)
                if not row.remote_item_id:
                    with private_storage().open(attachment.storage_key, "rb") as stream:
                        data = stream.read(MAX_UPLOAD_SIZE + 1)
                    if len(data) != attachment.size or hashlib.sha256(data).hexdigest() != attachment.sha256:
                        raise PlannerError("LOCAL_INTEGRITY_ERROR", "Integridade do anexo não confirmada.")
                    item = client.upload_attachment(attachment, data, drive, folder)
                    row.remote_web_url = approved_url(item["webUrl"])
                    row.remote_item_id = item["id"]
                    row.drive_id, row.folder_id, row.state = drive, folder, "UPLOADED"
                client.assert_no_sharing_links(drive, row.remote_item_id)
                client.attach_reference(attachment.ticket.planner_task_id, row.remote_web_url, attachment.original_name)
                row.state, row.published_at, row.last_error_code = "PUBLISHED", timezone.now(), ""
                TicketEvent.objects.get_or_create(
                    idempotency_key=f"planner-attachment:{attachment.pk}",
                    defaults={"ticket": attachment.ticket, "event_type": "PLANNER_ATTACHMENT_PUBLISHED",
                              "origin": TicketEvent.Origin.SYSTEM, "summary": "Anexo disponibilizado à TI no armazenamento corporativo."},
                )
            except PlannerError as exc:
                row.last_error_code = exc.code if exc.code in {
                    "AUTH_REQUIRED", "FORBIDDEN", "THROTTLED", "GRAPH_UNAVAILABLE", "CONFLICT",
                    "LOCAL_INTEGRITY_ERROR", "UNSAFE_FILE_URL", "STORAGE_CHANGED", "SHARING_LINK_DETECTED",
                    "INVALID_PERMISSIONS", "INVALID_FOLDER", "INVALID_REMOTE_FILE", "INVALID_PAYLOAD",
                } else "PUBLICATION_FAILED"
                if row.attempts >= 8 or exc.code in {"LOCAL_INTEGRITY_ERROR", "UNSAFE_FILE_URL", "STORAGE_CHANGED"}:
                    row.state = "FAILED"
                row.available_at = timezone.now() + timedelta(seconds=exc.retry_after or min(60 * 2 ** row.attempts, 3600))
            except (OSError, ValueError, KeyError, TypeError):
                row.state, row.last_error_code = "FAILED", "PUBLICATION_FAILED"
            row.save()
            processed += 1
    return processed
