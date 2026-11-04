import hashlib
import re
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.db import transaction

from .models import Attachment, Ticket
from .permissions import visible_tickets

MAX_UPLOAD_SIZE = 2 * 1024 * 1024


def private_storage():
    return FileSystemStorage(location=getattr(
        settings, "PRIVATE_ATTACHMENT_ROOT", settings.MEDIA_ROOT / "private-attachments",
    ))


def validate_upload(upload):
    if not upload.size or upload.size > MAX_UPLOAD_SIZE:
        raise ValidationError("O anexo deve ter entre 1 byte e 2 MB.")
    data = upload.read(MAX_UPLOAD_SIZE + 1)
    upload.seek(0)
    extension = Path(upload.name).suffix.lower()
    mime = None
    if extension == ".pdf" and data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF"):
        mime = "application/pdf"
    elif extension == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif extension in (".jpg", ".jpeg") and data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        mime = "image/jpeg"
    if len(data) > MAX_UPLOAD_SIZE or not mime or upload.content_type != mime:
        raise ValidationError("Use um PDF, PNG ou JPEG válido, com extensão e tipo correspondentes.")
    return data, mime, extension


@transaction.atomic
def save_attachment(*, ticket, actor, upload):
    ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
    if not visible_tickets(actor, Ticket.objects.filter(pk=ticket.pk)).exists():
        raise PermissionDenied
    data, mime, extension = validate_upload(upload)
    name = upload.name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^\w.() -]", "_", name, flags=re.UNICODE)[:160]
    key = f"{ticket.pk}/{uuid.uuid4().hex}{extension}"
    storage = private_storage()
    saved_key = storage.save(key, ContentFile(data))
    try:
        attachment = Attachment.objects.create(
            ticket=ticket, uploader=actor, original_name=name, storage_key=saved_key,
            mime_type=mime, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
        )
        return attachment
    except Exception:
        storage.delete(saved_key)
        raise
