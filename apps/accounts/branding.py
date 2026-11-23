"""Logo do portal por empresa: quem atende a C+ Soluções vê a logo da Soluções; os demais, a da C+.

A marca é decidida no login pelo grupo do AD em EMAIL_SOLUCOES_GROUP_DN (o mesmo dos e-mails,
contando subgrupos) e fica guardada na sessão. Antes do login, e se o AD não responder, vale a C+.
"""

import logging

logger = logging.getLogger(__name__)

SESSAO = "portal_marca"
MARCAS = {
    "cmais": {"codigo": "cmais", "logo": "brand/cmais-logo.svg", "alt": "C+ Contabilidade", "largura": 340, "altura": 69},
    "solucoes": {"codigo": "solucoes", "logo": "brand/csolucoes-logo.svg", "alt": "C+ Soluções Contábeis",
                 "largura": 253, "altura": 69},
}


def ao_entrar(sender, request, user, **kwargs):
    from apps.notifications.recipients import marca

    try:
        codigo = marca(user)
    except Exception:  # o login nunca falha por causa da logo
        logger.exception("Falha ao decidir a marca do portal de %s", getattr(user, "username", "?"))
        codigo = "cmais"
    if request is not None and hasattr(request, "session"):
        request.session[SESSAO] = codigo if codigo in MARCAS else "cmais"


def contexto(request):
    user = getattr(request, "user", None)
    codigo = request.session.get(SESSAO, "cmais") if user is not None and user.is_authenticated else "cmais"
    return {"portal_marca": MARCAS.get(codigo, MARCAS["cmais"])}
