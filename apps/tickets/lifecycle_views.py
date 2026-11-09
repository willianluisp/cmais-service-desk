import secrets
import time

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .lifecycle import archive_ticket, authorize, permanently_delete_ticket, restore_ticket
from .models import Ticket
from .permissions import authorized_tickets


class PermanentDeletionForm(forms.Form):
    number = forms.CharField(label='Número exato do chamado', strip=False)
    irreversible = forms.BooleanField(label='Entendo que esta exclusão é irreversível')
    password = forms.CharField(label='Minha senha atual', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))
    confirmation_token = forms.CharField(widget=forms.HiddenInput)


class SoftDeletionForm(forms.Form):
    confirm = forms.BooleanField(label="Confirmo a exclusão lógica deste chamado. Ele poderá ser recuperado pela administração.")


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def soft_delete(request, pk):
    if not (request.user.is_active and request.user.groups.filter(name="ADMIN_PORTAL").exists()):
        raise PermissionDenied
    ticket = get_object_or_404(authorized_tickets(request.user, Ticket.objects.all()), pk=pk, archived_at__isnull=True)
    form = SoftDeletionForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        archive_ticket(actor=request.user, ticket_id=pk, soft_delete=True)
        messages.success(request, 'Chamado excluído. Recuperação disponível em chamados arquivados.')
        return redirect('tickets:list')
    return render(request, 'tickets/soft_delete.html', {'ticket': ticket, 'form': form})


@login_required
@never_cache
@require_GET
def archived(request):
    authorize(request.user)
    query = request.GET.get('q', '').strip()[:160]
    tickets = authorized_tickets(request.user, Ticket.objects.filter(archived_at__isnull=False))
    if query:
        tickets = tickets.filter(number__icontains=query)
    return render(request, 'tickets/archived.html', {'page_obj': Paginator(tickets, 20).get_page(request.GET.get('page')), 'q': query})


@login_required
@require_POST
def archive(request, pk):
    archive_ticket(actor=request.user, ticket_id=pk)
    messages.success(request, 'Chamado arquivado. Ele pode ser restaurado na área de arquivados.')
    return redirect('tickets:list')


@login_required
@require_POST
def restore(request, pk):
    try:
        restore_ticket(actor=request.user, ticket_id=pk)
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    else:
        messages.success(request, 'Chamado restaurado. Notificações antigas não serão reenviadas.')
    return redirect('tickets:archived')


@sensitive_post_parameters('password')
@sensitive_variables()
@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def permanent_delete(request, pk):
    authorize(request.user)
    ticket = get_object_or_404(authorized_tickets(request.user, Ticket.objects.all()), pk=pk, archived_at__isnull=False)
    session_key = f'ticket_delete:{pk}'
    if request.method == 'GET':
        token = secrets.token_urlsafe(32)
        request.session[session_key] = {'token': token, 'version': ticket.version, 'expires': time.time() + 600}
        form = PermanentDeletionForm(initial={'confirmation_token': token})
    else:
        form = PermanentDeletionForm(request.POST)
        token = request.session.get(session_key, {}).get('token', '')
        if form.is_valid():
            intent = request.session.get(session_key, {})
            if (not token or not secrets.compare_digest(token, form.cleaned_data['confirmation_token'])
                    or intent.get('version') != ticket.version or intent.get('expires', 0) < time.time()):
                form.add_error(None, 'Abra novamente a tela de confirmação antes de excluir.')
            else:
                try:
                    permanently_delete_ticket(actor=request.user, ticket_id=pk, request=request,
                        expected_version=intent['version'],
                        **{k: v for k, v in form.cleaned_data.items() if k != 'confirmation_token'})
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    request.session.pop(session_key, None)
                    messages.success(request, 'Chamado excluído permanentemente. Limpeza local de arquivos registrada.')
                    return redirect('tickets:archived')
    return render(request, 'tickets/permanent_delete.html', {'ticket': ticket, 'form': form, 'confirmation_token': token})
