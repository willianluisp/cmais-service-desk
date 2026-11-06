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
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import AccountAudit
from apps.accounts.permissions import is_portal_admin

from .client import GraphClient, PlannerError, configured_planner_token_provider
from .configuration import BUCKET_FIELDS, bucket_id
from .models import (
    DEMANDAS_PLAN_ID,
    MicrosoftGraphConnection,
    PlannerConfiguration,
    PlannerTaskProvisioning,
    PlannerTestAttempt,
)


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
            self.fields[field] = forms.ChoiceField(label=label, choices=choices)

    def clean(self):
        data = super().clean()
        values = [data.get(key) for key in BUCKET_FIELDS if data.get(key)]
        if len(values) != len(set(values)):
            raise forms.ValidationError("Selecione um bucket diferente para cada status.")
        return data


def graph():
    if settings.PLANNER_PLAN_ID != DEMANDAS_PLAN_ID:
        raise PlannerError("PLAN_MISMATCH", "Plano divergente.")
    return GraphClient(token_provider=configured_planner_token_provider())


def action_availability(config):
    """Local preconditions only: never refresh a token or contact Microsoft here."""
    from .delegated_oauth import _fernet, redirect_uri

    oauth_enabled = settings.MICROSOFT_GRAPH_APPROVED and settings.GRAPH_DELEGATED_OAUTH_ENABLED
    can_connect = False
    if oauth_enabled and settings.GRAPH_TENANT_ID and settings.GRAPH_CLIENT_ID:
        try:
            _fernet()
            redirect_uri()
            can_connect = True
        except PlannerError:
            pass
    remote_ready = False
    if settings.PLANNER_PLAN_ID == DEMANDAS_PLAN_ID:
        try:
            configured_planner_token_provider()
            remote_ready = settings.GRAPH_AUTH_STRATEGY != 'delegated' or can_connect
        except PlannerError:
            pass
    return {
        'can_connect': can_connect,
        'can_query_buckets': remote_ready,
        'can_save_mapping': bool(config and config.buckets_checked_at and config.buckets),
        'can_test_task': bool(remote_ready and settings.PLANNER_TEST_ENABLED
                              and bucket_id('PLANNER_INTAKE_BUCKET_ID')),
    }


@require_GET
@never_cache
@administrator
def panel(request):
    config = PlannerConfiguration.objects.filter(plan_id=DEMANDAS_PLAN_ID).first()
    connection = MicrosoftGraphConnection.objects.filter(is_active=True).only(
        "microsoft_user_principal_name", "access_token_expires_at", "updated_at"
    ).first()
    request.session.setdefault("planner_test_nonce", secrets.token_urlsafe(32))
    return render(request, "portal/integrations.html", {
        "active_page": "integrations", "connection": connection,
        "access_expired": connection and connection.access_token_expires_at <= timezone.now(),
        "oauth_enabled": settings.MICROSOFT_GRAPH_APPROVED and settings.GRAPH_DELEGATED_OAUTH_ENABLED,
        "planner_enabled": settings.PLANNER_ENABLED and settings.MICROSOFT_GRAPH_APPROVED,
        "test_enabled": settings.PLANNER_TEST_ENABLED and settings.MICROSOFT_GRAPH_APPROVED,
        "config": config, "plan_id": DEMANDAS_PLAN_ID,
        "mapping_form": MappingForm(config=config, initial=config.bucket_mapping if config else {}),
        "queue": list(PlannerTaskProvisioning.objects.values("state").annotate(total=Count("pk"))),
        "errors": PlannerTaskProvisioning.objects.exclude(state=PlannerTaskProvisioning.State.CANCELLED).exclude(last_error_code="").values_list("last_error_code", flat=True).distinct()[:10],
        "attempts": PlannerTestAttempt.objects.order_by("-created_at")[:10],
        "test_nonce": request.session["planner_test_nonce"],
        **action_availability(config),
    })


@require_POST
@administrator
def refresh_buckets(request):
    if not action_availability(None)['can_query_buckets']:
        messages.error(request, "Consulta indisponível. Verifique a autorização Microsoft e a configuração do plano.")
        return redirect('integrations')
    try:
        buckets = graph().list_plan_buckets(DEMANDAS_PLAN_ID)
        PlannerConfiguration.objects.update_or_create(
            plan_id=DEMANDAS_PLAN_ID,
            defaults={"buckets": buckets, "buckets_checked_at": timezone.now()},
        )
        messages.success(request, "Buckets consultados. Selecione e salve os três mapeamentos.")
    except PlannerError:
        messages.error(request, "Consulta indisponível. Verifique a autorização Microsoft e a configuração do plano.")
    return redirect("integrations")


@require_POST
@administrator
def save_mapping(request):
    with transaction.atomic():
        config = PlannerConfiguration.objects.select_for_update().filter(plan_id=DEMANDAS_PLAN_ID).first()
        form = MappingForm(request.POST, config=config)
        if action_availability(config)['can_save_mapping'] and form.is_valid():
            config.bucket_mapping = {field: form.cleaned_data[field] for field in BUCKET_FIELDS}
            config.save(update_fields=["bucket_mapping"])
            AccountAudit.objects.create(actor=request.user, action="PLANNER_BUCKET_MAPPING")
            messages.success(request, "Mapeamento salvo. As flags de integração não foram alteradas.")
        else:
            messages.error(request, "Mapeamento inválido. Consulte os buckets e escolha três IDs distintos da lista.")
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
        task = client.create_task(plan_id=DEMANDAS_PLAN_ID, bucket_id=entry,
                                  title=f"[TESTE C+ SERVICE DESK] {attempt.pk}")
        if not isinstance(task, dict) or not isinstance(task.get("id"), str) or not task["id"] or task.get("planId") != DEMANDAS_PLAN_ID:
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
