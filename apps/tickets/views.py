from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache

from .forms import TicketForm
from .models import Attachment, Ticket
from .permissions import visible_tickets
from .services import create_ticket


def _ticket(request, pk):
    return get_object_or_404(
        visible_tickets(request.user, Ticket.objects.select_related("requester", "category", "assignee", "company", "intake_context")),
        pk=pk,
    )


@login_required
@never_cache
def ticket_list(request):
    tickets = visible_tickets(request.user, Ticket.objects.all())
    if request.GET.get("view") == "mine":
        tickets = tickets.filter(requester=request.user)
    query = request.GET.get("q", "").strip()[:160]
    status = request.GET.get("status", "")
    priority = request.GET.get("priority", "")
    if query:
        tickets = tickets.filter(Q(number__icontains=query) | Q(title__icontains=query))
    if status in Ticket.Status.values:
        normalized = Ticket.portal_status_for(status)
        tickets = tickets.filter(status__in=Ticket.PORTAL_STATUS_GROUPS[normalized])
        status = normalized
    if priority in Ticket.Priority.values:
        tickets = tickets.filter(priority=priority)
    raw_counts = dict(tickets.order_by().values("status").annotate(total=Count("pk")).values_list("status", "total"))
    counts = {key: sum(raw_counts.get(value, 0) for value in values)
              for key, values in Ticket.PORTAL_STATUS_GROUPS.items()}
    page = Paginator(tickets.select_related("category", "requester", "assignee"), 20).get_page(
        request.GET.get("page")
    )
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "tickets/list.html", {
        "page_obj": page, "counts": counts, "q": query, "status": status,
        "priority": priority, "statuses": Ticket.PORTAL_STATUS_LABELS.items(),
        "priorities": Ticket.Priority.choices, "filters_query": params.urlencode(),
        "active_page": "tickets",
    })


@login_required
@never_cache
def ticket_create(request, standard=False):
    if request.method == "GET" and not standard:
        from apps.custom_forms.views import choose

        return choose(request)
    from apps.custom_forms.services import standard_support

    state, support = standard_support(request.user)
    if state == "unavailable":
        raise Http404
    if support:
        from apps.custom_forms.views import request_form

        return request_form(request, support.pk)
    files = request.FILES.copy()
    if request.FILES:
        files.setlist("attachments", request.FILES.getlist("attachments"))
    initial = {}
    if request.method == "GET":
        from apps.sectors.intake import intake_selection

        initial, response = intake_selection(request)
        if response is not None:
            return response
    form = TicketForm(request.POST if request.method == "POST" else None, files or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            ticket = create_ticket(actor=request.user,
                description="Solicitação de suporte técnico pelo portal.", **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Chamado {ticket.number} registrado com sucesso. Você pode acompanhar as atualizações nesta página.")
            return redirect("tickets:detail", pk=ticket.pk)
    return render(request, "tickets/create.html", {"form": form, "active_page": "new_ticket"})


def _detail(request, ticket, *, response_status=200):
    from apps.custom_forms.models import FormSubmission
    from apps.custom_forms.services import answer_rows
    from apps.planner_integration.assignees import ticket_assignee_names

    events = ticket.events.select_related("actor")
    events = events.filter(is_internal=False)
    attachments = list(ticket.attachments.all())
    submission = FormSubmission.objects.filter(ticket=ticket).first()
    return render(request, "tickets/detail.html", {
        "ticket": ticket, "events": events, "attachments": attachments,
        "planner_assignee_names": ticket_assignee_names(ticket) if not ticket.is_sensitive else [],
        "comments": ticket.comments.filter(is_internal=False).select_related("author"),
        "custom_submission": submission, "custom_answers": answer_rows(submission, attachments) if submission else [],
        "is_owner": ticket.requester_id == request.user.pk,
        "can_delete_ticket": request.user.is_active and request.user.groups.filter(name="ADMIN_PORTAL").exists(),
        "active_page": "tickets",
    }, status=response_status)


@login_required
@never_cache
def ticket_detail(request, pk):
    return _detail(request, _ticket(request, pk))


@login_required
@never_cache
def attachment_download(request, pk, attachment_id):
    ticket = _ticket(request, pk)
    attachment = get_object_or_404(Attachment, pk=attachment_id, ticket=ticket)
    from .uploads import private_storage

    try:
        file = private_storage().open(attachment.storage_key, "rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    response = FileResponse(file, as_attachment=True, filename=attachment.original_name,
                            content_type=attachment.mime_type)
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@never_cache
def attachment_preview(request, pk, attachment_id):
    ticket = _ticket(request, pk)
    attachment = get_object_or_404(Attachment, pk=attachment_id, ticket=ticket)
    if attachment.mime_type not in {"application/pdf", "image/png", "image/jpeg"}:
        raise Http404
    from .uploads import private_storage

    try:
        file = private_storage().open(attachment.storage_key, "rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    response = FileResponse(
        file,
        as_attachment=False,
        filename=attachment.original_name,
        content_type=attachment.mime_type,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'none'; style-src 'none'; object-src 'none'; "
        "frame-ancestors 'self'; sandbox"
    )
    return response
