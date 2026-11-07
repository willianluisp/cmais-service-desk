import hashlib
import json
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from django.utils.html import escape

from apps.planner_integration.client import (
    NoRedirect,
    PlannerError,
    configured_token_provider,
    retry_after_seconds,
)

from .models import NotificationOutbox


class ProviderDisabled(Exception):
    pass


class DeliveryError(Exception):
    def __init__(self, code="DELIVERY_FAILED", *, retry_after=None):
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


def enqueue_event(event):
    """Call inside the ticket/event transaction; never send from this function."""
    if event.is_internal:
        return []
    ticket = event.ticket
    if ticket.is_sensitive:
        return []
    from apps.tickets.models import Ticket

    if event.event_type == "CREATED":
        stage, label, text_intro = "ABERTO", "Recebido", "Seu chamado foi recebido pelo C+ Service Desk."
    elif event.event_type == "PLANNER_CHANGED":
        stage = Ticket.portal_status_for(event.payload.get("status"))
        previous = Ticket.portal_status_for(event.payload.get("previous_status"))
        if not stage or stage == previous or stage == "ABERTO":
            return []
        label = Ticket.PORTAL_STATUS_LABELS[stage]
        text_intro = f"Seu chamado está {label.lower()}, conforme atualização identificada no Planner."
    else:
        return []
    recipients = {ticket.requester.email}
    rows = []
    for recipient in sorted(recipients):
        try:
            validate_email(recipient)
        except ValidationError:
            continue
        recipient = recipient.casefold()
        key = hashlib.sha256(f"{event.pk}:{recipient}:email:ticket-event-v1".encode()).hexdigest()
        link = f"{settings.PORTAL_BASE_URL.rstrip('/')}/chamados/{ticket.pk}/"
        text = (
            f"{text_intro}\nProtocolo: {ticket.number}.\n"
            f"Estado: {Ticket.PORTAL_STATUS_LABELS[stage]}.\n"
            f"Atualização identificada em: {timezone.localtime(event.detected_at).strftime('%d/%m/%Y %H:%M')}.\n"
            f"Consulte o portal autenticado: {link}"
        )
        row, _ = NotificationOutbox.objects.get_or_create(
            idempotency_key=key,
            defaults={
                "event": event,
                "ticket": ticket,
                "recipient": recipient,
                "subject": f"C+ Service Desk — {ticket.number} — {label}",
                "body_text": text,
                "body_html": "<p>" + escape(text).replace("\n", "<br>") + "</p>",
            },
        )
        rows.append(row)
    return rows


def deliver_local(notice):
    if (notice.ticket_id and notice.ticket.is_sensitive) or (notice.event_id and notice.event.ticket.is_sensitive):
        raise ProviderDisabled
    if not (settings.EMAIL_ENABLED and settings.MICROSOFT_GRAPH_APPROVED):
        raise ProviderDisabled
    provider = getattr(settings, "NOTIFICATIONS_PROVIDER", "console")
    if notice.template_key == "password-reset" and provider != "graph":
        raise ProviderDisabled
    if provider == "console":
        backend = "django.core.mail.backends.console.EmailBackend"
    elif provider == "local":
        backend = "django.core.mail.backends.locmem.EmailBackend"
    elif provider == "graph":
        return deliver_graph(notice)
    else:
        raise ProviderDisabled
    message = EmailMultiAlternatives(
        notice.subject,
        notice.body_text,
        settings.DEFAULT_FROM_EMAIL,
        [notice.recipient],
        connection=get_connection(backend),
        headers={"Message-ID": f"<{notice.idempotency_key}@service-desk.invalid>"},
    )
    if notice.body_html:
        message.attach_alternative(notice.body_html, "text/html")
    if message.send(fail_silently=False) != 1:
        raise RuntimeError("delivery failed")


def deliver_graph(notice, *, opener=None):
    """Submit through Outlook/Graph; HTTP 202 means accepted, not delivered."""
    if (notice.ticket_id and notice.ticket.is_sensitive) or (notice.event_id and notice.event.ticket.is_sensitive):
        raise ProviderDisabled
    if not (
        getattr(settings, "EMAIL_ENABLED", False)
        and getattr(settings, "MICROSOFT_GRAPH_APPROVED", False)
        and getattr(settings, "GRAPH_MAILBOX_ID", "")
    ):
        raise ProviderDisabled
    try:
        token = configured_token_provider()()
    except PlannerError as exc:
        raise DeliveryError(
            "MAIL_THROTTLED" if exc.status == 429 else "MAIL_AUTH_FAILED",
            retry_after=exc.retry_after,
        ) from None
    payload = {
        "message": {
            "subject": notice.subject,
            "body": {"contentType": "HTML", "content": notice.body_html or escape(notice.body_text)},
            "toRecipients": [{"emailAddress": {"address": notice.recipient}}],
            "internetMessageHeaders": [{"name": "X-CMais-Notification", "value": notice.idempotency_key}],
        },
        "saveToSentItems": False,
    }
    request = Request(
        "https://graph.microsoft.com/v1.0/users/" + quote(settings.GRAPH_MAILBOX_ID, safe="") + "/sendMail",
        data=json.dumps(payload, separators=(",", ":")).encode(),
        method="POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with (opener or build_opener(NoRedirect())).open(request, timeout=8) as response:
            status = response.status
    except HTTPError as exc:
        retry_after = retry_after_seconds(exc.headers.get("Retry-After")) if exc.headers else None
        exc.close()
        raise DeliveryError(
            "MAIL_THROTTLED" if exc.code == 429 else "MAIL_SUBMISSION_FAILED",
            retry_after=retry_after,
        ) from None
    except (URLError, OSError, TimeoutError):
        # Graph sendMail has no guaranteed idempotency key. A timeout can occur
        # after acceptance, so do not resend this message automatically.
        raise DeliveryError("MAIL_ACCEPTANCE_UNKNOWN") from None
    if status != 202:
        raise DeliveryError("MAIL_SUBMISSION_FAILED")


def process_pending(*, limit=50, provider=None):
    """Bounded at-least-once delivery; row lock spans provider call.

    A provider must honor the logical idempotency key for crash-safe exactly-once
    acceptance. SMTP cannot guarantee that property.
    """
    if provider is None and not (settings.EMAIL_ENABLED and settings.MICROSOFT_GRAPH_APPROVED):
        return 0
    limit = max(1, min(int(limit), 100))
    max_attempts = max(1, min(int(getattr(settings, "NOTIFICATIONS_MAX_ATTEMPTS", 5)), 10))
    processed = 0
    for _ in range(limit):
        with transaction.atomic():
            ready = NotificationOutbox.objects.filter(
                state=NotificationOutbox.State.PENDING,
                available_at__lte=timezone.now(),
            )
            candidate = ready.select_related('event').first()
            if candidate is None:
                break
            ticket_id = candidate.ticket_id or (candidate.event.ticket_id if candidate.event_id else None)
            if ticket_id:
                from apps.tickets.models import Ticket

                ticket = Ticket.objects.select_for_update().filter(pk=ticket_id).first()
                if ticket is None or ticket.archived_at or ticket.is_sensitive:
                    ready.filter(pk=candidate.pk).update(state='FAILED', last_error_code='SENSITIVE_TICKET' if ticket and ticket.is_sensitive else 'TICKET_ARCHIVED')
                    continue
            notice = ready.select_for_update().filter(pk=candidate.pk).first()
            if notice is None:
                continue
            notice.attempts += 1
            try:
                if notice.ticket_id and notice.recipient.casefold() != notice.ticket.requester.email.casefold():
                    raise DeliveryError("RECIPIENT_CHANGED")
                (provider or deliver_local)(notice)
            except ProviderDisabled:
                notice.state = NotificationOutbox.State.FAILED
                notice.last_error_code = "PROVIDER_DISABLED"
            except DeliveryError as exc:
                notice.last_error_code = exc.code
                notice.state = (
                    NotificationOutbox.State.FAILED
                    if notice.attempts >= max_attempts or exc.code in {"MAIL_ACCEPTANCE_UNKNOWN", "RECIPIENT_CHANGED"}
                    else NotificationOutbox.State.PENDING
                )
                delay = exc.retry_after or min(30 * 2 ** (notice.attempts - 1), 3600)
                notice.available_at = timezone.now() + timedelta(seconds=delay)
            except Exception:
                notice.last_error_code = "DELIVERY_FAILED"
                notice.state = (
                    NotificationOutbox.State.FAILED
                    if notice.attempts >= max_attempts
                    else NotificationOutbox.State.PENDING
                )
                notice.available_at = timezone.now() + timedelta(
                    seconds=min(30 * 2 ** (notice.attempts - 1), 3600),
                )
            else:
                notice.state = NotificationOutbox.State.SENT
                notice.sent_at = timezone.now()
                notice.last_error_code = ""
            notice.save(
                update_fields=["attempts", "state", "last_error_code", "available_at", "sent_at"]
            )
            processed += 1
    return processed
