import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.permissions import is_portal_admin
from apps.tickets.models import Ticket
from apps.tickets.permissions import visible_tickets

from .client import PlannerError
from .delegated_oauth import (
    authorization_url,
    consume_state,
    exchange_authorization_code,
    microsoft_identity,
    store_connection,
)
from .services import enforce_rate_limit, sync_ticket

logger = logging.getLogger(__name__)

OAUTH_STAGE_LABELS = {
    "token_exchange": "troca do código pelo token",
    "identity_lookup": "identificação da conta Microsoft",
    "token_storage": "armazenamento criptografado da conexão",
}
OAUTH_CATEGORY_LABELS = {
    "OAUTH_INVALID_CLIENT": "credencial da aplicação rejeitada",
    "OAUTH_INVALID_GRANT": "código de autorização inválido ou expirado",
    "OAUTH_INVALID_REQUEST": "solicitação de token rejeitada",
    "OAUTH_UNAUTHORIZED_CLIENT": "aplicação não autorizada para este fluxo",
    "OAUTH_INTERACTION_REQUIRED": "interação adicional exigida pela Microsoft",
    "OAUTH_PROVIDER_UNAVAILABLE": "serviço Microsoft temporariamente indisponível",
    "OAUTH_TOKEN_REJECTED": "solicitação de token rejeitada pela Microsoft",
    "OAUTH_INVALID_RESPONSE": "resposta Microsoft inválida",
    "OAUTH_IDENTITY_DENIED": "consulta da identidade rejeitada pela Microsoft",
    "OAUTH_IDENTITY_UNAVAILABLE": "consulta da identidade temporariamente indisponível",
    "OAUTH_STORAGE_UNAVAILABLE": "armazenamento temporariamente indisponível",
    "AUTH_REQUIRED": "autorização Microsoft incompleta",
    "OAUTH_CONFIGURATION": "configuração OAuth incompleta",
}


def _oauth_failure(stage, exc):
    category = exc.code if exc.code in OAUTH_CATEGORY_LABELS else "OAUTH_FAILURE"
    logger.warning("Microsoft OAuth callback failed stage=%s category=%s", stage, category)
    stage_label = OAUTH_STAGE_LABELS.get(stage, "processamento da autorização")
    category_label = OAUTH_CATEGORY_LABELS.get(category, "falha de autorização")
    return HttpResponseBadRequest(
        f"Não foi possível concluir a autorização Microsoft. "
        f"Etapa: {stage_label}. Categoria: {category_label}."
    )


@require_POST
@login_required
@never_cache
def synchronize(request, ticket_id):
    get_object_or_404(visible_tickets(request.user, Ticket.objects.all()), pk=ticket_id)
    try:
        enforce_rate_limit(request.user, ticket_id)
        result = sync_ticket(actor=request.user, ticket_id=ticket_id)
        if result.get("deleted"):
            messages.info(request, "Exclusão confirmada no Planner. Chamado arquivado para auditoria e removido das listas.")
            if request.headers.get("HX-Request") == "true":
                response = render(request, "tickets/_planner_feedback.html", result)
                response["HX-Redirect"] = "/chamados/"
                return response
            return JsonResponse(result)
        if request.headers.get("HX-Request") == "true":
            response = render(request, "tickets/_planner_feedback.html", result)
            if result.get("changed"):
                messages.success(request, "Chamado atualizado com os dados atuais do Planner.")
                response["HX-Refresh"] = "true"
            return response
        return JsonResponse(result)
    except PlannerError as exc:
        response = JsonResponse(
            {"changed": False, "code": exc.code, "error": str(exc)}, status=exc.status
        )
        if exc.retry_after:
            response["Retry-After"] = str(exc.retry_after)
        if request.headers.get("HX-Request") == "true":
            response = render(request, "tickets/_planner_feedback.html", {"error": str(exc)}, status=exc.status)
            response["X-Planner-Feedback"] = "error"
            return response
        return response


def _oauth_available(request):
    return (
        is_portal_admin(request.user)
        and settings.MICROSOFT_GRAPH_APPROVED
        and settings.GRAPH_DELEGATED_OAUTH_ENABLED
    )


@require_GET
@login_required
def connect_microsoft(request):
    """Start delegated OAuth through a same-origin navigation and HTTP redirect."""
    if not _oauth_available(request):
        return JsonResponse({"detail": "Integração Microsoft não está aprovada."}, status=403)
    from .admin_panel import action_availability

    if not action_availability(None)['can_connect']:
        return JsonResponse({"detail": "Configuração OAuth Microsoft indisponível."}, status=503)
    try:
        return redirect(authorization_url(request))
    except PlannerError:
        return JsonResponse({"detail": "Configuração OAuth Microsoft indisponível."}, status=503)


@require_GET
@login_required
def microsoft_callback(request):
    if not _oauth_available(request):
        return JsonResponse({"detail": "Integração Microsoft não está aprovada."}, status=403)
    verifier = consume_state(request, request.GET.get("state"))
    code = request.GET.get("code")
    if not verifier or not isinstance(code, str) or not code or request.GET.get("error"):
        return HttpResponseBadRequest("Autorização Microsoft não foi concluída.")
    try:
        token_data = exchange_authorization_code(code=code, code_verifier=verifier)
    except PlannerError as exc:
        return _oauth_failure("token_exchange", exc)
    try:
        identity = microsoft_identity(token_data["access_token"])
    except PlannerError as exc:
        return _oauth_failure("identity_lookup", exc)
    try:
        store_connection(
            user=request.user,
            tenant_id=settings.GRAPH_TENANT_ID,
            microsoft_user_id=identity["id"],
            microsoft_user_principal_name=identity["userPrincipalName"],
            token_data=token_data,
        )
    except PlannerError as exc:
        return _oauth_failure("token_storage", exc)
    except DatabaseError:
        return _oauth_failure(
            "token_storage",
            PlannerError("OAUTH_STORAGE_UNAVAILABLE", "Armazenamento indisponível."),
        )
    return redirect("integrations")
