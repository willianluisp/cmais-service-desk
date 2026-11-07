from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from apps.accounts.models import AccountAudit

from .models import SensitiveTicketApproval, Ticket, TicketEvent
from .permissions import visible_tickets


def can_approve(user, ticket):
    return bool(user.is_authenticated and user.is_active and ticket.is_sensitive and ticket.requester_id != user.pk
        and ticket.approver_groups.filter(pk__in=user.groups.values("pk")).exists())


class ApprovalForm(forms.Form):
    reference = forms.CharField(max_length=255, required=False, label="Referência da aprovação")
    confirm = forms.BooleanField(label="Confirmo a aprovação desta solicitação como responsável autorizado.")


@require_POST
@login_required
@transaction.atomic
def approve(request, pk):
    ticket = get_object_or_404(Ticket.objects.select_for_update(), pk=pk)
    if not visible_tickets(request.user, Ticket.objects.filter(pk=pk)).exists():
        raise PermissionDenied
    if not can_approve(request.user, ticket):
        raise PermissionDenied
    form = ApprovalForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Confirme a aprovação e use uma referência de até 255 caracteres.")
        return redirect("tickets:detail", pk=pk)
    approval, created = SensitiveTicketApproval.objects.get_or_create(ticket=ticket, defaults={
        "approved_by": request.user, "approver_name_snapshot": (request.user.get_full_name() or request.user.get_username())[:300],
        "reference": form.cleaned_data["reference"],
    })
    if created:
        TicketEvent.objects.create(ticket=ticket, actor=request.user, event_type="APPROVED",
            summary="Solicitação sensível aprovada pelo responsável autenticado. Nenhuma ação externa foi executada.",
            idempotency_key=f"sensitive-approved:{ticket.pk}")
        AccountAudit.objects.create(actor=request.user, action="SENSITIVE_TICKET_APPROVED", changes={"ticket_id": str(ticket.pk), "approval_id": approval.pk})
    messages.success(request, "Aprovação registrada. Bloqueios ou alterações em contas não são executados por este portal.")
    return redirect("tickets:detail", pk=pk)
