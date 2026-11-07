"""Resolve local prerequisites without network access or granting approvals."""

from django.conf import settings
from django.views.decorators.debug import sensitive_variables

from .client import PlannerError


@sensitive_variables()
def client_secret():
    from .delegated_oauth import decrypt_token
    from .models import MicrosoftOAuthConfiguration

    config = MicrosoftOAuthConfiguration.objects.filter(
        pk=1, tenant_id=settings.GRAPH_TENANT_ID, client_id=settings.GRAPH_CLIENT_ID,
    ).first()
    return decrypt_token(config.client_secret_encrypted) if config else settings.GRAPH_CLIENT_SECRET


def readiness():
    from .delegated_oauth import _fernet, redirect_uri

    issues = []
    if not settings.MICROSOFT_GRAPH_APPROVED:
        issues.append("Falta aprovação de segurança para Microsoft Graph. Solicite ao responsável a liberação inicial do ambiente; credenciais não representam aprovação.")
    if not settings.GRAPH_DELEGATED_OAUTH_ENABLED:
        issues.append("Falta aprovação para OAuth delegado neste ambiente. Solicite ao responsável a liberação inicial da conexão pelo navegador.")
    if settings.GRAPH_AUTH_STRATEGY != "delegated":
        issues.append("A configuração inicial deve selecionar autenticação Microsoft delegada.")
    if not settings.GRAPH_TENANT_ID or not settings.GRAPH_CLIENT_ID:
        issues.append("Tenant ID e Client ID precisam ser provisionados no armazenamento protegido na configuração inicial.")
    try:
        _fernet()
        encryption_ready = True
    except PlannerError:
        encryption_ready = False
        issues.append("A chave de criptografia precisa ser provisionada no armazenamento protegido. Preserve a chave existente para manter os tokens legíveis.")
    try:
        callback = redirect_uri()
    except PlannerError:
        callback = ""
        issues.append("O endereço do portal precisa ser configurado para gerar o retorno OAuth.")
    if encryption_ready:
        try:
            secret_ready = bool(client_secret())
        except PlannerError:
            secret_ready = False
        if not secret_ready:
            issues.append("Client Secret ausente ou ilegível. Salve o valor do segredo da aplicação no formulário de configuração inicial abaixo.")
    return {"can_connect": not issues, "connection_issues": issues, "callback_uri": callback,
            "can_configure_secret": encryption_ready and bool(settings.GRAPH_TENANT_ID and settings.GRAPH_CLIENT_ID)}
