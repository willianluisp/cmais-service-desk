import hashlib
import json
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.notifications.services import enqueue_event
from apps.tickets.models import Ticket, TicketEvent
from apps.tickets.permissions import visible_tickets

from .client import PlannerError, configured_client, configured_read_client
from .configuration import automation_enabled, bucket_id, selected_plan_id
from .jobs import defer_graph
from .models import PlannerTaskProvisioning


def _card_title(ticket):
    from apps.custom_forms.models import FormSubmission

    submission = FormSubmission.objects.filter(ticket=ticket).first()
    if submission:
        return submission.schema_snapshot["title"]
    return ticket.title[:255]


def _reconciliation_matches(client, tasks, ticket, provisioning, details_cache):
    """Titles are presentation only; exact durable metadata identifies a ticket.

    Legacy protocol-prefixed cards remain recoverable. A POST lost before its
    description PATCH is intentionally ambiguous and requires manual recovery.
    """
    matches = []
    linked_ids = set(Ticket.objects.exclude(planner_task_id__isnull=True)
                     .values_list("planner_task_id", flat=True))
    correlation = f"Correlação C+ Service Desk: {provisioning.correlation_id}"
    protocol = f"Protocolo: {ticket.number}"
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str):
            continue
        task_id = task["id"]
        if task_id in linked_ids:
            continue
        legacy_match = task.get("title", "").startswith(f"[{ticket.number}] ")
        if provisioning.state == 'PENDING' and not provisioning.attempts and not legacy_match:
            # A fresh durable intent has never issued a POST. Only legacy cards
            # can predate it; do not read unrelated task details on every intake.
            continue
        if task_id not in details_cache and hasattr(client, "get_task_details"):
            details_cache[task_id] = client.get_task_details(task_id)
        details = details_cache.get(task_id, {})
        description = details.get("description", "") if isinstance(details, dict) else ""
        lines = description.splitlines() if isinstance(description, str) else []
        correlations = [line for line in lines if line.startswith("Correlação C+ Service Desk: ")]
        identified = correlation in lines if correlations else protocol in lines or legacy_match
        if identified:
            matches.append(task)
    return matches


def _card_description(ticket, correlation_id):
    metadata = (
        f"Protocolo: {ticket.number}\n"
        f"Empresa: {ticket.company_name_snapshot or 'Não informada (chamado anterior)'}\n"
        f"Departamento: {ticket.intake_context.sector_name_snapshot if hasattr(ticket, 'intake_context') else 'Não informado'}\n"
        f"Local do atendimento: {ticket.intake_context.service_location if hasattr(ticket, 'intake_context') else 'Não informado'}\n"
        f"Categoria: {ticket.category}\nPrioridade: {ticket.get_priority_display()}\n"
        f"Solicitante: {ticket.requester.get_full_name() or ticket.requester.username}\n\n"
    )
    attachment_count = ticket.attachments.count()
    attachment_notice = (
        f"\n\nEste chamado possui {attachment_count} "
        f"{'anexo' if attachment_count == 1 else 'anexos'}. "
        f"{'Consulte-o' if attachment_count == 1 else 'Consulte-os'} no C+ Service Desk."
        if attachment_count
        else ""
    )
    suffix = f"\n\nCorrelação C+ Service Desk: {correlation_id}{attachment_notice}"
    # Keep the correlation and attachment notice even for long requests.
    return metadata + f"Solicitação:\n{ticket.description}"[:max(0, 4000 - len(metadata) - len(suffix))] + suffix


def _link_created_task(provisioning, task):
    ticket = provisioning.ticket
    task_id = task.get("id") if isinstance(task, dict) else None
    if not isinstance(task_id, str) or not task_id or len(task_id) > 255:
        raise PlannerError("INVALID_PAYLOAD", "Resposta do Planner inválida.")
    plan_id = task.get("planId", selected_plan_id())
    bucket_id = task.get("bucketId", getattr(settings, "PLANNER_INTAKE_BUCKET_ID", ""))
    if plan_id != selected_plan_id() or not isinstance(bucket_id, str):
        raise PlannerError("INVALID_PAYLOAD", "Resposta do Planner inválida.")
    ticket.planner_task_id = task_id
    ticket.planner_plan_id = plan_id
    ticket.planner_bucket_id = bucket_id
    ticket.planner_percent_complete = int(task.get("percentComplete", 0) or 0)
    ticket.planner_etag = task.get("@odata.etag", "") if isinstance(task.get("@odata.etag", ""), str) else ""
    ticket.sync_state, ticket.sync_error_code = Ticket.SyncState.SYNCED, ""
    ticket.version += 1
    ticket.updated_at = timezone.now()
    ticket.save(update_fields=["planner_task_id", "planner_plan_id", "planner_bucket_id", "planner_percent_complete", "planner_etag", "sync_state", "sync_error_code", "version", "updated_at"])
    event, created = TicketEvent.objects.get_or_create(
        idempotency_key=f"planner-linked:{ticket.pk}:{task_id}",
        defaults={
            "ticket": ticket,
            "event_type": "PLANNER_LINKED",
            "origin": TicketEvent.Origin.SYSTEM,
            "summary": "Chamado vinculado ao Microsoft Planner.",
            "is_internal": False,
        },
    )
    provisioning.state, provisioning.last_error_code = PlannerTaskProvisioning.State.LINKED, ""
    provisioning.save(update_fields=["state", "last_error_code", "updated_at"])
    if created and not ticket.archived_at and not ticket.planner_deleted_at:
        enqueue_event(event)


def _persist_link(provisioning, task):
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=provisioning.ticket_id)
        current = PlannerTaskProvisioning.objects.select_for_update().get(pk=provisioning.pk)
        current.ticket = ticket
        _link_created_task(current, task)
        # An archive during the HTTP request must remain cancelled locally.
        if ticket.archived_at or ticket.planner_deleted_at:
            current.state = PlannerTaskProvisioning.State.CANCELLED
        else:
            # The description PATCH is a separate remote request. Keep durable
            # work until it succeeds, including a crash immediately after linking.
            current.state = PlannerTaskProvisioning.State.PENDING
        current.save(update_fields=['state', 'updated_at'])
        provisioning.ticket = ticket
        provisioning.state = current.state


def _provisioning_active(provisioning):
    return PlannerTaskProvisioning.objects.filter(
        pk=provisioning.pk, ticket__archived_at__isnull=True,
        ticket__planner_deleted_at__isnull=True, ticket__is_sensitive=False,
    ).exclude(state='CANCELLED').exists()


def process_pending_provisioning(*, limit=25, graph_client=None, provisioning_id=None):
    """Claim durably before HTTP; never blindly repeat an uncertain creation."""
    if graph_client is None and not automation_enabled():
        return 0
    limit = 1 if provisioning_id is not None else max(1, min(int(limit), 100))
    processed = 0
    plan_tasks = None
    details_cache = {}
    for _ in range(limit):
        if graph_client is None and not automation_enabled():
            break
        with transaction.atomic():
            ready = PlannerTaskProvisioning.objects.filter(
                ticket__is_sensitive=False,
                ticket__planner_deleted_at__isnull=True,
                ticket__archived_at__isnull=True,
                state__in=['PENDING', 'RECONCILIATION'],
                available_at__lte=timezone.now(),
            )
            if provisioning_id is not None:
                ready = ready.filter(pk=provisioning_id)
            candidate = ready.order_by('available_at', 'pk').first()
            if candidate is None:
                break
            ticket = Ticket.objects.select_for_update().get(pk=candidate.ticket_id)
            provisioning = ready.select_for_update().filter(pk=candidate.pk).first()
            if provisioning is None or ticket.archived_at or ticket.planner_deleted_at or ticket.is_sensitive:
                continue
            provisioning.ticket = ticket
            # A second worker cannot claim this row while the first does HTTP.
            provisioning.available_at = timezone.now() + timedelta(minutes=15)
            provisioning.save(update_fields=['available_at', 'updated_at'])
        post_attempted = False
        try:
            client = graph_client or configured_client()
            if ticket.planner_task_id:
                if not _provisioning_active(provisioning):
                    continue
                if hasattr(client, 'update_task_details'):
                    client.update_task_details(ticket.planner_task_id,
                        description=_card_description(ticket, provisioning.correlation_id), etag='')
                PlannerTaskProvisioning.objects.filter(pk=provisioning.pk).exclude(state='CANCELLED').update(
                    state='LINKED', last_error_code='', updated_at=timezone.now())
                Ticket.objects.filter(pk=ticket.pk, archived_at__isnull=True).update(sync_state=Ticket.SyncState.SYNCED, sync_error_code='')
                processed += 1
                continue
            matches = []
            if hasattr(client, 'list_plan_tasks'):
                if plan_tasks is None:
                    plan_tasks = client.list_plan_tasks(selected_plan_id())
                matches = _reconciliation_matches(client, plan_tasks, ticket, provisioning, details_cache)
            if len(matches) > 1:
                PlannerTaskProvisioning.objects.filter(pk=provisioning.pk).exclude(state='CANCELLED').update(
                    state='FAILED', last_error_code='DUPLICATE_RECONCILIATION', updated_at=timezone.now())
                Ticket.objects.filter(pk=ticket.pk).update(sync_state=Ticket.SyncState.ERROR,
                                                         sync_error_code='DUPLICATE_RECONCILIATION')
                processed += 1
                continue
            if len(matches) == 1:
                _persist_link(provisioning, matches[0])
            elif provisioning.state == 'RECONCILIATION':
                # Eventual consistency means absence is not permission to POST.
                PlannerTaskProvisioning.objects.filter(pk=provisioning.pk).exclude(state='CANCELLED').update(
                    available_at=timezone.now() + timedelta(seconds=120),
                    last_error_code='RECONCILIATION_PENDING', updated_at=timezone.now())
                processed += 1
                continue
            else:
                # Commit the ambiguous intent BEFORE POST, even if the process
                # is killed before it can persist the Graph response.
                with transaction.atomic():
                    current_ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
                    current = PlannerTaskProvisioning.objects.select_for_update().get(pk=provisioning.pk)
                    if current_ticket.archived_at or current_ticket.is_sensitive or current.state == 'CANCELLED':
                        continue
                    provisioning.attempts += 1
                    current.state = 'RECONCILIATION'
                    current.attempts = provisioning.attempts
                    current.save(update_fields=['state', 'attempts', 'updated_at'])
                post_attempted = True
                created = client.create_task(plan_id=selected_plan_id(),
                    bucket_id=bucket_id('PLANNER_INTAKE_BUCKET_ID'), title=_card_title(ticket))
                _persist_link(provisioning, created)
            if _provisioning_active(provisioning) and hasattr(client, 'update_task_details'):
                client.update_task_details(provisioning.ticket.planner_task_id,
                    description=_card_description(ticket, provisioning.correlation_id), etag='')
            PlannerTaskProvisioning.objects.filter(pk=provisioning.pk).exclude(state='CANCELLED').update(
                state='LINKED', last_error_code='', updated_at=timezone.now())
        except PlannerError as exc:
            uncertain = (post_attempted and exc.code in {'GRAPH_UNAVAILABLE', 'INVALID_PAYLOAD'})
            # Preserve previous ambiguity when reconciliation itself fails.
            uncertain = uncertain or provisioning.state == 'RECONCILIATION'
            state = 'RECONCILIATION' if uncertain else 'PENDING'
            delay = exc.retry_after or min(60 * 2 ** min(provisioning.attempts, 6), 3600)
            PlannerTaskProvisioning.objects.filter(pk=provisioning.pk).exclude(state='CANCELLED').update(
                state=state, attempts=provisioning.attempts, last_error_code=exc.code,
                available_at=timezone.now() + timedelta(seconds=delay), updated_at=timezone.now())
            Ticket.objects.filter(pk=ticket.pk, archived_at__isnull=True).update(sync_state=Ticket.SyncState.ERROR, sync_error_code=exc.code)
            defer_graph(exc)
            if exc.status == 429 or exc.code == 'AUTH_REQUIRED':
                return processed + 1
        processed += 1
    return processed


def derive_status(percent, bucket):
    if bucket == bucket_id("PLANNER_COMPLETED_BUCKET_ID"):
        return Ticket.Status.RESOLVIDO
    if bucket == bucket_id("PLANNER_IN_PROGRESS_BUCKET_ID"):
        return Ticket.Status.EM_ATENDIMENTO
    if bucket == bucket_id("PLANNER_INTAKE_BUCKET_ID"):
        return Ticket.Status.ABERTO
    if percent == 100:
        return Ticket.Status.RESOLVIDO
    mapped = getattr(settings, "PLANNER_BUCKET_STATUS_MAP", {}).get(bucket)
    if mapped in Ticket.Status.values and mapped != Ticket.Status.FECHADO:
        return mapped
    return Ticket.Status.EM_ATENDIMENTO if percent > 0 else Ticket.Status.ABERTO


def enforce_rate_limit(actor, ticket_id):
    seconds = max(1, int(getattr(settings, "PLANNER_SYNC_MIN_INTERVAL", 15)))
    try:
        allowed_user = cache.add(f"planner:sync:user:{actor.pk}", True, timeout=seconds)
        allowed_ticket = cache.add(f"planner:sync:ticket:{ticket_id}", True, timeout=seconds)
    except Exception:
        raise PlannerError(
            "RATE_LIMIT_UNAVAILABLE", "Controle de sincronização indisponível. Tente novamente."
        ) from None
    if not allowed_user or not allowed_ticket:
        raise PlannerError(
            "THROTTLED", "Aguarde antes de atualizar novamente.", status=429, retry_after=seconds
        )


def validate_snapshot(data, ticket):
    plan_id = selected_plan_id()
    if not plan_id:
        raise PlannerError("PLAN_NOT_CONFIGURED", "Plano do Planner não configurado.")
    if (
        not isinstance(data, dict)
        or data.get("id") != ticket.planner_task_id
        or data.get("planId") != plan_id
        or (ticket.planner_plan_id and ticket.planner_plan_id != plan_id)
        or not isinstance(data.get("bucketId"), str)
        or not data["bucketId"]
        or len(data["bucketId"]) > 255
        or type(data.get("percentComplete")) is not int
        or not 0 <= data["percentComplete"] <= 100
        or not isinstance(data.get("@odata.etag", ""), str)
        or len(data.get("@odata.etag", "")) > 255
    ):
        raise PlannerError("INVALID_PAYLOAD", "Resposta do Planner inválida ou plano divergente.")
    return data


def _result(ticket, changed, events):
    return {
        "changed": changed,
        "status": ticket.status,
        "status_label": ticket.portal_status_label,
        "updated_at_display": timezone.localtime(ticket.updated_at).strftime("%d/%m/%Y %H:%M"),
        "synced_at_display": timezone.localtime(ticket.last_planner_sync_at).strftime("%d/%m/%Y %H:%M"),
        "percent_complete": ticket.planner_percent_complete,
        "last_synced_at": ticket.last_planner_sync_at.isoformat(),
        "events": events,
    }


def planner_projection(task, details):
    assignments = task.get("assignments", {}) if isinstance(task.get("assignments"), dict) else {}
    ids = sorted(key for key, value in assignments.items() if isinstance(value, dict))
    checklist = details.get("checklist", {}) if isinstance(details, dict) else {}
    if not isinstance(checklist, dict):
        checklist = {}
    items = [
        {"id": key, "title": value.get("title", ""), "is_checked": bool(value.get("isChecked"))}
        for key, value in checklist.items() if isinstance(value, dict)
    ]
    due = task.get("dueDateTime")
    return {
        "planner_assignee_ids": ids,
        "planner_assignee_names": ids,
        "planner_due_at": parse_datetime(due) if isinstance(due, str) else None,
        "planner_checklist": items,
        "planner_checklist_total": len(items),
        "planner_checklist_completed": sum(item["is_checked"] for item in items),
    }


def _confirm_deleted(ticket, client):
    # A task 404 can also hide an access problem. Verify plan access and absence
    # from its complete list before requiring a second task-specific 404.
    if ticket.planner_plan_id != selected_plan_id():
        raise PlannerError("DELETION_UNCONFIRMED", "Plano divergente; dados preservados.")
    client.list_plan_buckets(ticket.planner_plan_id)
    tasks = client.list_plan_tasks(ticket.planner_plan_id)
    if any(task.get("id") == ticket.planner_task_id for task in tasks):
        raise PlannerError("DELETION_UNCONFIRMED", "Tarefa não localizada com segurança; tente novamente.")
    try:
        client.get_task(ticket.planner_task_id)
    except PlannerError as exc:
        if exc.code == "TASK_NOT_FOUND" and exc.status == 404:
            return
        raise
    raise PlannerError("DELETION_UNCONFIRMED", "Tarefa voltou a estar disponível; tente novamente.")


def _mark_deleted(*, actor, original):
    with transaction.atomic():
        current = Ticket.objects.select_for_update().filter(pk=original.pk).first()
        if current is None:
            raise Http404
        if not visible_tickets(actor, Ticket.objects.filter(pk=current.pk)).exists():
            raise Http404
        if current.version != original.version or current.planner_task_id != original.planner_task_id:
            raise PlannerError("STALE_RESPONSE", "Chamado atualizado durante a consulta.", status=409)
        now = timezone.now()
        current.planner_deleted_at = now
        current.archived_at = now
        current.archive_reason = "PLANNER_DELETED"
        current.last_planner_sync_at = now
        current.sync_state = Ticket.SyncState.SYNCED
        current.sync_error_code = ""
        current.version += 1
        current.save(update_fields=["planner_deleted_at", "archived_at", "archive_reason", "last_planner_sync_at", "sync_state", "sync_error_code", "version"])
        PlannerTaskProvisioning.objects.filter(ticket=current).update(
            state=PlannerTaskProvisioning.State.CANCELLED,
            last_error_code="PLANNER_DELETED", updated_at=now,
        )
        TicketEvent.objects.get_or_create(
            idempotency_key=f"planner-deleted:{current.pk}:{current.planner_task_id}",
            defaults={"ticket": current, "event_type": "PLANNER_DELETED",
                      "origin": TicketEvent.Origin.PLANNER_SYNC,
                      "summary": "Exclusão da tarefa confirmada no Planner. Registro preservado para auditoria."},
        )
        return {"changed": True, "deleted": True}


def sync_ticket(*, actor, ticket_id, graph_client=None):
    original = visible_tickets(actor, Ticket.objects.all()).filter(pk=ticket_id).first()
    if original is None:
        raise Http404
    if original.is_sensitive:
        raise PlannerError("SENSITIVE_TICKET", "Solicitação sensível disponível somente no portal restrito.", status=403)
    if original.planner_deleted_at:
        raise PlannerError('TASK_NOT_LINKED', 'A tarefa foi removida no Planner; o chamado foi restaurado somente no portal.', status=409)
    graph_client = graph_client or configured_read_client()
    if not original.planner_task_id:
        raise PlannerError(
            "TASK_NOT_LINKED", "Chamado aguardando envio automático ao Planner.", status=409
        )
    try:
        try:
            snapshot = graph_client.get_task(original.planner_task_id)
        except PlannerError as exc:
            if exc.code != "TASK_NOT_FOUND" or exc.status != 404:
                raise
            _confirm_deleted(original, graph_client)
            return _mark_deleted(actor=actor, original=original)
        data = validate_snapshot(snapshot, original)
        details = graph_client.get_task_details(original.planner_task_id) if hasattr(graph_client, "get_task_details") else {}
        projection = planner_projection(data, details)
    except PlannerError as exc:
        Ticket.objects.filter(pk=original.pk, version=original.version).update(
            sync_state=Ticket.SyncState.ERROR,
            sync_error_code=exc.code,
        )
        raise
    with transaction.atomic():
        # ``visible_tickets`` uses DISTINCT for shared TicketAccess grants;
        # PostgreSQL does not allow that construct with FOR UPDATE. Lock the
        # single ticket first, then repeat the access check inside the same
        # transaction before persisting the projection.
        current = Ticket.objects.select_for_update().filter(pk=ticket_id).first()
        if current is None or not visible_tickets(
            actor, Ticket.objects.filter(pk=current.pk)
        ).exists():
            raise Http404
        if current.planner_task_id != original.planner_task_id:
            raise PlannerError(
                "STALE_RESPONSE", "Chamado atualizado durante a consulta.", status=409
            )
        status = derive_status(data["percentComplete"], data["bucketId"])
        if current.status == Ticket.Status.FECHADO:
            status = current.status
        changed = (current.planner_bucket_id, current.planner_percent_complete, current.status) != (
            data["bucketId"],
            data["percentComplete"],
            status,
        ) or any(getattr(current, key) != value for key, value in projection.items())
        if current.version != original.version and changed:
            raise PlannerError(
                "STALE_RESPONSE", "Chamado atualizado durante a consulta.", status=409
            )
        now = timezone.now()
        events = []
        fields = ["last_planner_sync_at", "sync_state", "sync_error_code", "planner_etag"]
        current.last_planner_sync_at = now
        current.sync_state = Ticket.SyncState.SYNCED
        current.sync_error_code = ""
        current.planner_etag = data.get("@odata.etag", "")
        if changed:
            previous_status = current.status
            current.status = status
            current.planner_bucket_id = data["bucketId"]
            current.planner_percent_complete = data["percentComplete"]
            current.planner_plan_id = data["planId"]
            for key, value in projection.items():
                setattr(current, key, value)
            current.updated_at = now
            current.version += 1
            if status == Ticket.Status.RESOLVIDO and previous_status != status:
                current.resolved_at = now
            elif status != Ticket.Status.RESOLVIDO and status != Ticket.Status.FECHADO:
                current.resolved_at = None
            fields += [
                "status",
                "planner_bucket_id",
                "planner_percent_complete",
                "planner_plan_id",
                *projection.keys(),
                "updated_at",
                "version",
                "resolved_at",
            ]
            digest = hashlib.sha256(
                json.dumps(
                    {
                        "task": current.planner_task_id,
                        "version": current.version,
                        "bucket": current.planner_bucket_id,
                        "percent": current.planner_percent_complete,
                        "status": status,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            summary = (
                "Mudança detectada no Planner. Estado atual: " + current.get_status_display() + "."
            )
            event, _ = TicketEvent.objects.get_or_create(
                idempotency_key="planner:" + digest,
                defaults={
                    "ticket": current,
                    "event_type": "PLANNER_CHANGED",
                    "origin": TicketEvent.Origin.PLANNER_SYNC,
                    "actor": None,
                    "payload": {
                        "previous_status": previous_status,
                        "status": status,
                        "percent_complete": current.planner_percent_complete,
                        "assignee_ids": current.planner_assignee_ids,
                        "due_at": current.planner_due_at.isoformat() if current.planner_due_at else None,
                        "checklist_completed": current.planner_checklist_completed,
                        "checklist_total": current.planner_checklist_total,
                    },
                    "summary": summary,
                    "detected_at": now,
                },
            )
            enqueue_event(event)
            events.append({"id": event.pk, "summary": summary, "detected_at": now.isoformat()})
        current.save(update_fields=fields)
        return _result(current, changed, events)
