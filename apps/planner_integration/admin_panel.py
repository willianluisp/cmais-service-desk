import secrets
import uuid
from functools import wraps

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import AccountAudit
from apps.accounts.permissions import is_portal_admin

from .client import GraphClient, PlannerError, configured_planner_token_provider
from .configuration import BUCKET_FIELDS, automation_enabled, bucket_id, selected_plan_id
from .models import (
    MicrosoftGraphConnection,
    MicrosoftOAuthConfiguration,
    PlannerConfiguration,
    PlannerRuntime,
    PlannerTaskProvisioning,
    PlannerTestAttempt,
)
from .oauth_configuration import readiness


def administrator(view):
    @wraps(view)
    @login_required
    def protected(request, *args, **kwargs):
        if not is_portal_admin(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return protected


class MappingForm(forms.Form):
    def __init__(self, *args, config=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "Selecione um bucket consultado na Microsoft")]
        if config:
            choices += [(b["id"], b["name"]) for b in config.buckets]
        for field, label in BUCKET_FIELDS.items():
            self.fields[field] = forms.ChoiceField(label=label, choices=choices,
                                                 required=field == 'PLANNER_INTAKE_BUCKET_ID')

    def clean(self):
        data = super().clean()
        values = [data.get(key) for key in BUCKET_FIELDS if data.get(key)]
        if len(values) != len(set(values)):
            raise forms.ValidationError("Selecione um bucket diferente para cada status.")
        return data


def graph():
    if not settings.MICROSOFT_GRAPH_APPROVED:
        raise PlannerError('INTEGRATION_DISABLED', 'Integração não aprovada.')
    return GraphClient(token_provider=configured_planner_token_provider())


def action_availability(config):
    """Local preconditions only: never refresh a token or contact Microsoft here."""
    connection_readiness = readiness()
    can_connect = connection_readiness['can_connect']
    remote_ready = False
    if settings.MICROSOFT_GRAPH_APPROVED:
        try:
            configured_planner_token_provider()
            remote_ready = settings.GRAPH_AUTH_STRATEGY != 'delegated' or can_connect
        except PlannerError:
            pass
    return {
        **connection_readiness,
        'can_query_buckets': remote_ready,
        'can_save_mapping': bool(config and config.buckets_checked_at and config.buckets),
        'can_test_task': bool(remote_ready and settings.PLANNER_TEST_ENABLED
                              and bucket_id('PLANNER_INTAKE_BUCKET_ID')),
    }


@require_GET
@never_cache
@administrator
def panel(request):
    from datetime import timedelta

    from apps.tickets.models import Ticket

    config = PlannerConfiguration.objects.filter(plan_id=selected_plan_id()).first()
    runtime = PlannerRuntime.objects.filter(pk=1).first()
    connection = MicrosoftGraphConnection.objects.filter(is_active=True).only(
        "microsoft_user_principal_name", "access_token_expires_at", "updated_at"
    ).first()
    request.session.setdefault("planner_test_nonce", secrets.token_urlsafe(32))
    return render(request, "portal/integrations.html", {
        "active_page": "integrations", "connection": connection,
        "oauth_secret_form": OAuthSecretForm(),
        "access_expired": connection and connection.access_token_expires_at <= timezone.now(),
        "oauth_enabled": settings.MICROSOFT_GRAPH_APPROVED and settings.GRAPH_DELEGATED_OAUTH_ENABLED,
        "planner_enabled": automation_enabled(),
        "sync_enabled": automation_enabled(synchronize=True),
        "runtime": runtime,
        "worker_overdue": bool(automation_enabled() and (not runtime or not runtime.last_finished_at
                                or runtime.last_finished_at < timezone.now() - timedelta(minutes=10))),
        "sync_error_count": Ticket.objects.filter(is_sensitive=False, archived_at__isnull=True,
                                                   sync_state=Ticket.SyncState.ERROR).count(),
        "uncertain_sends": PlannerTaskProvisioning.objects.filter(
            state__in=['RECONCILIATION', 'FAILED'], ticket__is_sensitive=False,
            ticket__archived_at__isnull=True, ticket__planner_task_id__isnull=True,
        ).select_related('ticket')[:25],
        "recovery_choices": request.session.get('planner_recovery', {}).get('tasks', [])
            if request.session.get('planner_recovery', {}).get('plan_id') == selected_plan_id() else [],
        "test_enabled": settings.PLANNER_TEST_ENABLED and settings.MICROSOFT_GRAPH_APPROVED,
        "config": config, "plan_id": selected_plan_id(),
        "mapping_form": MappingForm(config=config, initial=config.bucket_mapping if config else {}),
        "queue": list(PlannerTaskProvisioning.objects.values("state").annotate(total=Count("pk"))),
        "errors": PlannerTaskProvisioning.objects.exclude(state=PlannerTaskProvisioning.State.CANCELLED).exclude(last_error_code="").values_list("last_error_code", flat=True).distinct()[:10],
        "attempts": PlannerTestAttempt.objects.order_by("-created_at")[:10],
        "test_nonce": request.session["planner_test_nonce"],
        **action_availability(config),
    })


class OAuthSecretForm(forms.Form):
    client_secret = forms.CharField(
        label="Valor do Client Secret", max_length=4096, strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )


@require_POST
@never_cache
@administrator
@sensitive_post_parameters("client_secret")
@sensitive_variables()
def configure_oauth(request):
    from .delegated_oauth import encrypt_token

    form = OAuthSecretForm(request.POST)
    if not readiness()['can_configure_secret'] or not form.is_valid():
        messages.error(request, "Não foi possível salvar o segredo. Confira os pré-requisitos da configuração inicial.")
        return redirect("integrations")
    with transaction.atomic():
        MicrosoftOAuthConfiguration.objects.update_or_create(pk=1, defaults={
            "tenant_id": settings.GRAPH_TENANT_ID, "client_id": settings.GRAPH_CLIENT_ID,
            "client_secret_encrypted": encrypt_token(form.cleaned_data["client_secret"]),
        })
        AccountAudit.objects.create(actor=request.user, action="MICROSOFT_OAUTH_CONFIGURED")
    messages.success(request, "Segredo salvo com criptografia. As aprovações de segurança e permissões corporativas não foram alteradas.")
    return redirect("integrations")


@require_POST
@never_cache
@administrator
def disconnect_microsoft(request):
    from .delegated_oauth import SESSION_KEY

    with transaction.atomic():
        MicrosoftGraphConnection.objects.filter(is_active=True).update(
            is_active=False, access_token_encrypted="", refresh_token_encrypted="", updated_at=timezone.now(),
        )
        PlannerRuntime.objects.get_or_create(pk=1)
        PlannerRuntime.objects.filter(pk=1).update(automation_enabled=False, sync_requested=False,
                                                 connection_error='', connection_checked_at=None)
        AccountAudit.objects.create(actor=request.user, action="MICROSOFT_DISCONNECTED")
    request.session.pop(SESSION_KEY, None)
    messages.success(request, "Conta Microsoft desconectada deste portal. Para conectar novamente, use Conectar Microsoft. O consentimento corporativo permanece sob gestão do Microsoft Entra.")
    return redirect("integrations")


@require_POST
@administrator
def refresh_buckets(request):
    if not action_availability(None)['can_query_buckets']:
        messages.error(request, "Consulta indisponível. Verifique a autorização Microsoft e a configuração do plano.")
        return redirect('integrations')
    try:
        plan_id = selected_plan_id()
        buckets = graph().list_plan_buckets(plan_id)
        PlannerConfiguration.objects.update_or_create(
            plan_id=plan_id,
            defaults={"buckets": buckets, "buckets_checked_at": timezone.now()},
        )
        messages.success(request, "Buckets consultados. Selecione o bucket padrão e os mapeamentos opcionais.")
    except PlannerError:
        messages.error(request, "Consulta indisponível. Verifique a autorização Microsoft e a configuração do plano.")
    return redirect("integrations")


@require_POST
@administrator
def save_mapping(request):
    with transaction.atomic():
        config = PlannerConfiguration.objects.select_for_update().filter(plan_id=selected_plan_id()).first()
        form = MappingForm(request.POST, config=config)
        if action_availability(config)['can_save_mapping'] and form.is_valid():
            config.bucket_mapping = {field: form.cleaned_data[field] for field in BUCKET_FIELDS}
            config.save(update_fields=["bucket_mapping"])
            AccountAudit.objects.create(actor=request.user, action="PLANNER_BUCKET_MAPPING")
            messages.success(request, "Mapeamento salvo. As flags de integração não foram alteradas.")
        else:
            messages.error(request, "Mapeamento inválido. Escolha o bucket padrão e use buckets distintos nos mapeamentos opcionais.")
    return redirect("integrations")


@require_POST
@administrator
def test_task(request):
    # Consume the nonce before any remote attempt. An ambiguous POST is never
    # repeated by refreshing/resubmitting this form. No employee data is used.
    nonce = request.POST.get("nonce", "")
    expected = request.session.get("planner_test_nonce", "")
    if not action_availability(None)['can_test_task']:
        messages.error(request, "Teste real desabilitado.")
        return redirect("integrations")
    if request.POST.get("confirm") != "CRIAR TAREFA DE TESTE" or not expected or not secrets.compare_digest(nonce, expected):
        messages.error(request, "Confirmação inválida ou já utilizada.")
        return redirect("integrations")
    try:
        client = graph()
        entry = bucket_id("PLANNER_INTAKE_BUCKET_ID")
        if not entry:
            raise PlannerError("BUCKET_REQUIRED", "Bucket ausente.")
    except PlannerError:
        messages.error(request, "Teste indisponível. Verifique conexão e mapeamento.")
        return redirect("integrations")
    # Deterministic UUID and unique PK enforce one attempt even for concurrent
    # requests carrying the same session nonce.
    attempt, created = PlannerTestAttempt.objects.get_or_create(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"planner-test:{request.user.pk}:{nonce}"),
        defaults={"actor": request.user},
    )
    if not created:
        messages.warning(request, "Essa tentativa já foi registrada. Confira o resultado antes de outro teste.")
        return redirect("integrations")
    request.session.pop("planner_test_nonce", None)
    try:
        task = client.create_task(plan_id=selected_plan_id(), bucket_id=entry,
                                  title=f"[TESTE C+ SERVICE DESK] {attempt.pk}")
        if not isinstance(task, dict) or not isinstance(task.get("id"), str) or not task["id"] or task.get("planId") != selected_plan_id():
            raise PlannerError("INVALID_PAYLOAD", "Resposta inválida.")
        attempt.task_id, attempt.state = task["id"], "CREATED"
        attempt.save(update_fields=["task_id", "state"])
        messages.success(request, "Tarefa de teste criada. Nenhum dado de colaborador foi enviado.")
    except PlannerError:
        attempt.state = "VERIFY"
        attempt.save(update_fields=["state"])
        messages.error(request, "Resultado não confirmado. Confira o Planner antes de criar outro teste.")
    AccountAudit.objects.create(actor=request.user, action="PLANNER_CONTROLLED_TEST")
    return redirect("integrations")


def _remote_allowed(request):
    if not action_availability(None)['can_query_buckets']:
        messages.error(request, 'Conexão indisponível. Confira a configuração inicial e reconecte a conta Microsoft.')
        return False
    return True


@require_POST
@administrator
def refresh_plans(request):
    if _remote_allowed(request):
        try:
            plans = graph().list_my_plans()
            runtime, _ = PlannerRuntime.objects.get_or_create(pk=1)
            runtime.plans = plans
            runtime.save(update_fields=['plans'])
            messages.success(request, 'Planos consultados. Selecione o plano de atendimento.')
        except PlannerError:
            messages.error(request, 'Não foi possível consultar os planos. Reconecte Microsoft e confira o acesso da conta ao plano.')
    return redirect('integrations')


@require_POST
@administrator
def select_plan(request):
    from apps.tickets.models import Ticket

    if not _remote_allowed(request):
        return redirect('integrations')
    chosen = request.POST.get('plan_id', '')
    try:
        with transaction.atomic():
            runtime, _ = PlannerRuntime.objects.select_for_update().get_or_create(pk=1)
            if chosen not in {p['id'] for p in runtime.plans}:
                raise PlannerError('INVALID_PLAN', 'Plano inválido.')
            if runtime.lease_until and runtime.lease_until > timezone.now():
                raise PlannerError('BUSY', 'Sincronização em andamento.')
            if chosen != selected_plan_id() and (
                Ticket.objects.exclude(planner_task_id__isnull=True).exclude(planner_task_id='').exists()
                or PlannerTaskProvisioning.objects.filter(state='RECONCILIATION').exists()
            ):
                messages.error(request, 'O plano não pode ser trocado enquanto houver tarefas vinculadas ou criações em conferência. Os vínculos existentes foram preservados.')
                return redirect('integrations')
            buckets = graph().list_plan_buckets(chosen)
            config, _ = PlannerConfiguration.objects.update_or_create(plan_id=chosen, defaults={
                'buckets': buckets, 'buckets_checked_at': timezone.now(),
            })
            runtime.configuration = config
            runtime.automation_enabled = False
            runtime.connection_error = ''
            runtime.connection_checked_at = timezone.now()
            runtime.save(update_fields=['configuration', 'automation_enabled', 'connection_error', 'connection_checked_at'])
            AccountAudit.objects.create(actor=request.user, action='PLANNER_PLAN_SELECTED')
        messages.success(request, 'Plano selecionado. Escolha o bucket padrão e ative a automação quando estiver pronto.')
    except PlannerError:
        messages.error(request, 'Não foi possível selecionar o plano. Atualize a lista e verifique a conexão ou aguarde a sincronização atual.')
    return redirect('integrations')


@require_POST
@administrator
def toggle_automation(request):
    enable = request.POST.get('enabled') == 'on'
    if not settings.MICROSOFT_GRAPH_APPROVED:
        messages.error(request, 'A integração aguarda aprovação inicial do ambiente.')
        return redirect('integrations')
    if enable and (not _remote_allowed(request) or not selected_plan_id() or not bucket_id('PLANNER_INTAKE_BUCKET_ID')):
        messages.error(request, 'Conecte Microsoft, selecione o plano e salve o bucket padrão antes de ativar.')
        return redirect('integrations')
    with transaction.atomic():
        runtime, _ = PlannerRuntime.objects.select_for_update().get_or_create(pk=1)
        runtime.automation_enabled = enable
        runtime.save(update_fields=['automation_enabled'])
        AccountAudit.objects.create(actor=request.user, action='PLANNER_AUTOMATION_CHANGED', changes={'enabled': enable})
    messages.success(request, 'Automação ativada. Novos chamados e a fila pendente serão processados automaticamente.' if enable else 'Automação pausada. Os chamados e vínculos foram preservados.')
    return redirect('integrations')


@require_POST
@administrator
def test_connection(request):
    if not _remote_allowed(request):
        return redirect('integrations')
    runtime, _ = PlannerRuntime.objects.get_or_create(pk=1)
    try:
        if not selected_plan_id():
            graph().list_my_plans()
        else:
            graph().list_plan_buckets(selected_plan_id())
        runtime.connection_error = ''
        messages.success(request, 'Conexão validada. Nenhuma tarefa foi criada ou alterada.')
    except PlannerError as exc:
        runtime.connection_error = exc.code if exc.code in {'AUTH_REQUIRED', 'FORBIDDEN', 'THROTTLED'} else 'GRAPH_UNAVAILABLE'
        messages.error(request, 'Não foi possível validar a conexão. Reconecte Microsoft, confira o acesso ao plano ou tente novamente em instantes.')
    runtime.connection_checked_at = timezone.now()
    runtime.save(update_fields=['connection_error', 'connection_checked_at'])
    return redirect('integrations')


@require_POST
@administrator
def synchronize_now(request):
    from kombu.exceptions import OperationalError

    from .tasks import run_requested_sync

    if not settings.MICROSOFT_GRAPH_APPROVED or not (automation_enabled() or automation_enabled(synchronize=True)):
        messages.error(request, 'Ative a automação antes de solicitar uma sincronização.')
        return redirect('integrations')
    with transaction.atomic():
        runtime, _ = PlannerRuntime.objects.select_for_update().get_or_create(pk=1)
        already_requested = runtime.sync_requested
        runtime.sync_requested = True
        runtime.save(update_fields=['sync_requested'])
        AccountAudit.objects.create(actor=request.user, action='PLANNER_SYNC_REQUESTED')
    try:
        if not already_requested:
            run_requested_sync.delay()
        messages.success(request, 'Sincronização solicitada. A fila será processada em segundo plano; atualize esta página para acompanhar.')
    except (OperationalError, OSError):
        messages.warning(request, 'Pedido salvo. A fila está temporariamente indisponível; a sincronização será retomada automaticamente quando o serviço voltar.')
    return redirect('integrations')


@require_POST
@administrator
def review_sends(request):
    if _remote_allowed(request):
        try:
            plan_id = selected_plan_id()
            tasks = graph().list_plan_tasks(plan_id)
            search = request.POST.get('search', '').strip().casefold()[:255]
            choices = [{'id': task['id'], 'title': task['title']} for task in tasks
                       if isinstance(task, dict) and isinstance(task.get('id'), str)
                       and isinstance(task.get('title'), str)
                       and (not search or search in task['title'].casefold() or search == task['id'].casefold())]
            request.session['planner_recovery'] = {
                'plan_id': plan_id,
                'tasks': choices[:200],
            }
            if len(choices) > 200:
                messages.warning(request, 'Há muitas tarefas. Use a busca pelo protocolo ou título para encontrar a tarefa correspondente.')
            elif not choices:
                messages.warning(request, 'Nenhuma tarefa encontrada. Confira o texto da busca ou aguarde a conferência automática.')
            messages.success(request, 'Tarefas consultadas. Confira o protocolo no Planner antes de vincular uma tarefa existente.')
        except PlannerError:
            messages.error(request, 'Não foi possível conferir os envios. Teste a conexão e tente novamente.')
    return redirect('integrations')


@require_POST
@administrator
def resolve_send(request):
    from django.db import IntegrityError

    from .jobs import integration_job
    from .services import _persist_link

    if not _remote_allowed(request):
        return redirect('integrations')
    task_id = request.POST.get('task_id', '')
    choices = request.session.get('planner_recovery', {})
    if choices.get('plan_id') != selected_plan_id() or task_id not in {t['id'] for t in choices.get('tasks', [])}:
        messages.error(request, 'Consulte as tarefas e selecione uma tarefa existente da lista.')
        return redirect('integrations')
    try:
        provisioning_id = int(request.POST.get('provisioning_id', ''))
        with integration_job() as acquired:
            if not acquired:
                raise PlannerError('BUSY', 'Aguarde o processamento atual.')
            row = PlannerTaskProvisioning.objects.select_related('ticket').filter(
                pk=provisioning_id, state__in=['RECONCILIATION', 'FAILED'],
                ticket__is_sensitive=False, ticket__archived_at__isnull=True,
                ticket__planner_deleted_at__isnull=True,
            ).first()
            if row is None or row.ticket.planner_task_id:
                raise PlannerError('INVALID_TASK', 'Envio já resolvido ou indisponível.')
            task = graph().get_task(task_id)
            if not isinstance(task, dict) or task.get('id') != task_id or task.get('planId') != selected_plan_id():
                raise PlannerError('INVALID_TASK', 'Tarefa inválida.')
            _persist_link(row, task)
            PlannerTaskProvisioning.objects.filter(pk=row.pk).exclude(state='CANCELLED').update(available_at=timezone.now())
            AccountAudit.objects.create(actor=request.user, action='PLANNER_SEND_RESOLVED', changes={'ticket_id': str(row.ticket_id)})
        messages.success(request, 'Tarefa existente vinculada. A descrição pendente será concluída pela fila; nenhuma nova tarefa foi criada.')
    except (PlannerError, IntegrityError, ValueError):
        messages.error(request, 'Vínculo não realizado. Confira se a tarefa pertence ao plano, se já está vinculada ou se há sincronização em andamento.')
    return redirect('integrations')
