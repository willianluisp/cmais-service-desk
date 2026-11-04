import hashlib
import json
from io import BytesIO
from unittest.mock import Mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.planner_integration.attachments import (
    AttachmentGraphClient,
    approved_url,
    process_publications,
)
from apps.planner_integration.client import PlannerError
from apps.tickets.models import Category
from apps.tickets.services import create_ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def publication(settings, tmp_path, django_user_model):
    from apps.planner_integration.models import AttachmentPublication

    settings.PRIVATE_ATTACHMENT_ROOT = tmp_path
    settings.MICROSOFT_GRAPH_APPROVED = True
    settings.PLANNER_ENABLED = True
    settings.PLANNER_ATTACHMENTS_ENABLED = True
    settings.GRAPH_ATTACHMENTS_STORAGE_APPROVED = True
    settings.GRAPH_AUTH_STRATEGY = "delegated"
    settings.GRAPH_ATTACHMENTS_DRIVE_ID = "drive"
    settings.GRAPH_ATTACHMENTS_FOLDER_ID = "folder"
    settings.GRAPH_ATTACHMENTS_HOST = "example.sharepoint.com"
    ticket = create_ticket(
        actor=django_user_model.objects.create_user("owner"), title="Attachment test",
        description="Test", category=Category.objects.create(name="Test"), priority="NORMAL",
        attachments=[SimpleUploadedFile("teste.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")],
    )
    ticket.planner_task_id = "task"
    ticket.save(update_fields=["planner_task_id"])
    # Legacy publication rows remain supported for existing data, but new
    # uploads no longer create them automatically.
    return AttachmentPublication.objects.create(attachment=ticket.attachments.get())


@pytest.fixture
def graph():
    client = Mock(spec=AttachmentGraphClient)
    client.upload_attachment.return_value = {"id": "item", "webUrl": "https://example.sharepoint.com/sites/ti/file.pdf"}
    return client


def test_publication_is_idempotent_and_keeps_local_file(publication, graph):
    from apps.tickets.uploads import private_storage

    assert process_publications(graph_client=graph) == 1
    assert process_publications(graph_client=graph) == 0
    publication.refresh_from_db()
    assert publication.state == "PUBLISHED"
    assert private_storage().exists(publication.attachment.storage_key)
    graph.upload_attachment.assert_called_once()
    graph.attach_reference.assert_called_once()
    graph.assert_no_sharing_links.assert_called_once_with("drive", "item")
    assert publication.attachment.ticket.events.filter(event_type="PLANNER_ATTACHMENT_PUBLISHED").count() == 1


@pytest.mark.parametrize("flag", ["MICROSOFT_GRAPH_APPROVED", "PLANNER_ENABLED", "PLANNER_ATTACHMENTS_ENABLED", "GRAPH_ATTACHMENTS_STORAGE_APPROVED"])
def test_disabled_publication_never_contacts_graph(publication, graph, settings, flag):
    setattr(settings, flag, False)
    assert process_publications(graph_client=graph) == 0
    assert not graph.mock_calls
    publication.refresh_from_db()
    assert publication.attempts == 0


def test_waits_for_planner_task(publication, graph):
    ticket = publication.attachment.ticket
    ticket.planner_task_id = None
    ticket.save(update_fields=["planner_task_id"])
    assert process_publications(graph_client=graph) == 0
    assert not graph.mock_calls


def test_reference_failure_reuses_uploaded_file_and_retry_after(publication, graph):
    graph.attach_reference.side_effect = [PlannerError("THROTTLED", "secret", retry_after=120), None]
    process_publications(graph_client=graph)
    publication.refresh_from_db()
    assert publication.state == "UPLOADED"
    assert publication.remote_item_id == "item"
    assert publication.available_at > timezone.now()
    assert publication.last_error_code == "THROTTLED"
    publication.available_at = timezone.now()
    publication.save(update_fields=["available_at"])
    process_publications(graph_client=graph)
    graph.upload_attachment.assert_called_once()
    publication.refresh_from_db()
    assert publication.state == "PUBLISHED"


def test_modified_local_file_is_not_uploaded(publication, graph):
    from apps.tickets.uploads import private_storage

    with private_storage().open(publication.attachment.storage_key, "wb") as stream:
        stream.write(b"tampered")
    process_publications(graph_client=graph)
    publication.refresh_from_db()
    assert publication.state == "FAILED"
    assert publication.last_error_code == "LOCAL_INTEGRITY_ERROR"
    graph.upload_attachment.assert_not_called()


def test_file_sharing_link_prevents_planner_reference(publication, graph):
    graph.assert_no_sharing_links.side_effect = PlannerError("SHARING_LINK_DETECTED", "private")
    process_publications(graph_client=graph)
    graph.attach_reference.assert_not_called()
    publication.refresh_from_db()
    assert publication.state == "UPLOADED"
    assert publication.last_error_code == "SHARING_LINK_DETECTED"


def test_oauth_requests_selected_scope_only_after_configuration(settings):
    from apps.planner_integration.delegated_oauth import requested_scopes

    settings.GRAPH_ATTACHMENT_SCOPE_ENABLED = False
    assert "Sites.Selected" not in requested_scopes()
    settings.GRAPH_ATTACHMENT_SCOPE_ENABLED = True
    assert "Sites.Selected" in requested_scopes()
    assert "Sites.ReadWrite.All" not in requested_scopes()


def test_existing_reference_does_not_patch_again(publication):
    client = AttachmentGraphClient(token_provider=lambda: "mock")
    client.get_task_details = Mock(return_value={"@odata.etag": "etag", "references": {
        "https%3A//example%2Esharepoint%2Ecom/sites/ti/file%2Epdf": {"alias": "file"},
    }})
    client._request_json = Mock()
    client.attach_reference("task", "https://example.sharepoint.com/sites/ti/file.pdf", "file")
    client._request_json.assert_not_called()


@pytest.mark.parametrize("url", ["http://example.sharepoint.com/file", "https://evil.test/file",
    "https://example.sharepoint.com@evil.test/file", "https://example.sharepoint.com/file?token=secret"])
def test_rejects_noncorporate_or_token_urls(publication, url):
    with pytest.raises(PlannerError):
        approved_url(url)


def test_sharing_links_block_publication(publication):
    client = AttachmentGraphClient(token_provider=lambda: "mock")
    client._request_json = Mock(return_value={"value": [{"link": {"scope": "anonymous"}}]})
    with pytest.raises(PlannerError, match="compartilhamento"):
        client.assert_no_sharing_links("drive", "item")


def test_reference_preserves_other_fields_and_uses_details_etag(publication):
    client = AttachmentGraphClient(token_provider=lambda: "mock")
    client.get_task_details = Mock(return_value={"@odata.etag": "details-etag", "references": {"existing": {}}})
    client._request_json = Mock(return_value={})
    client.attach_reference("task", "https://example.sharepoint.com/sites/ti/file.pdf", "teste.pdf")
    kwargs = client._request_json.call_args.kwargs
    assert kwargs["extra_headers"] == {"If-Match": "details-etag"}
    assert set(kwargs["payload"]) == {"references"}
    key = next(iter(kwargs["payload"]["references"]))
    assert key == "https%3A//example%2Esharepoint%2Ecom/sites/ti/file%2Epdf"


def test_upload_reconciles_same_deterministic_filename(publication):
    attachment = publication.attachment
    data = b"%PDF-1.4\n%%EOF"
    name = f"{attachment.pk}-{hashlib.sha256(data).hexdigest()}.pdf"
    item = {"id": "item", "name": name, "size": len(data), "file": {},
            "parentReference": {"driveId": "drive", "id": "folder"},
            "webUrl": "https://example.sharepoint.com/sites/ti/file.pdf"}
    client = AttachmentGraphClient(token_provider=lambda: "mock")
    client._request_json = Mock(side_effect=[PlannerError("TASK_NOT_FOUND", "not found"), item, item])
    assert client.upload_attachment(attachment, data, "drive", "folder") == item
    assert client.upload_attachment(attachment, data, "drive", "folder") == item
    calls = client._request_json.call_args_list
    assert calls[1].kwargs["method"] == "PUT"
    assert calls[1].kwargs["raw_body"] == data
    assert calls[0].args[0] == calls[2].args[0]
    assert calls[1].args[0] == calls[0].args[0] + ":/content"


def test_graph_sends_binary_body_without_json_conversion():
    class Response(BytesIO):
        status = 201

    def opener(request, timeout):
        assert request.data == b"binary"
        assert request.get_header("Content-type") == "application/pdf"
        return Response(json.dumps({"id": "item"}).encode())

    client = AttachmentGraphClient(token_provider=lambda: "mock", opener=opener)
    assert client._request_json("https://graph.microsoft.com/v1.0/mock", method="PUT",
                                raw_body=b"binary", content_type="application/pdf") == {"id": "item"}
