"""Para quem vai o aviso do chamado.

Com o login pelo AD (LDAP_ROLE_SOURCE=portal), o e-mail sai para o campo "mail" da conta do AD
com o mesmo login (sAMAccountName, ex.: nome.sobrenome) de quem abriu o chamado. Se o login não
existir no AD, estiver desativado ou não tiver e-mail, o aviso vai para NOTIFICATIONS_TI_RECIPIENTS
com o motivo. Com o AD fora do ar, usa o e-mail do cadastro do portal (o aviso não se perde).
Sem o login pelo AD, vale o e-mail do cadastro do portal, como antes.
"""

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

logger = logging.getLogger(__name__)

CONTA_DESATIVADA = 2  # bit ACCOUNTDISABLE do userAccountControl


def _valido(email):
    try:
        validate_email(email)
    except ValidationError:
        return ""
    return email.casefold()


def ad_ativo():
    return bool(getattr(settings, "LDAP_ENABLED", False) and getattr(settings, "LDAP_ROLE_SOURCE", "ad") == "portal")


def destino(usuario):
    """Devolve (email, motivo). Sem e-mail, motivo diz por que não foi possível achar o destinatário."""
    cadastro = _valido(usuario.email or "")
    if not ad_ativo():
        return (cadastro, None) if cadastro else ("", "o usuário não tem e-mail válido no cadastro do portal")
    from apps.accounts.directory import DirectoryUnavailable, lookup_login

    login = usuario.username.split("\\")[-1]
    try:
        contas = lookup_login(login)
    except DirectoryUnavailable:
        logger.warning("AD indisponível ao buscar o e-mail de %s; usando o do cadastro do portal.", login)
        return (cadastro, None) if cadastro else ("", "AD indisponível e o usuário não tem e-mail no cadastro do portal")
    if not contas:
        return "", f"o login '{login}' não foi encontrado no AD"
    if len(contas) > 1:
        return "", f"o login '{login}' aparece em mais de uma conta do AD"
    _dn, atributos = contas[0]

    def valor(nome):
        lista = atributos.get(nome) or [b""]
        return lista[0].decode("utf-8", "replace") if isinstance(lista[0], bytes) else str(lista[0])

    try:
        desativada = int(valor("userAccountControl") or 0) & CONTA_DESATIVADA
    except ValueError:
        desativada = False
    if desativada:
        return "", f"a conta '{login}' está desativada no AD"
    email = _valido(valor("mail").strip())
    if not email:
        return "", f"a conta '{login}' não tem e-mail preenchido no AD"
    return email, None


def destinatarios_ti():
    return sorted({e for e in (_valido(x.strip()) for x in getattr(settings, "NOTIFICATIONS_TI_RECIPIENTS", []) or []) if e})


def marca(usuario):
    """'solucoes' quando o login de quem abriu está (direto ou por subgrupo) no grupo da Soluções no AD."""
    grupo = getattr(settings, "EMAIL_SOLUCOES_GROUP_DN", "")
    if not (grupo and ad_ativo()):
        return "cmais"
    import ldap
    from ldap.filter import escape_filter_chars

    from apps.accounts.directory import DirectoryUnavailable, directory_connection

    login = escape_filter_chars(usuario.username.split("\\")[-1])
    filtro = (f"(&(objectClass=user)(sAMAccountName={login})"
              f"(memberOf:1.2.840.113556.1.4.1941:={escape_filter_chars(grupo)}))")
    try:
        with directory_connection() as conexao:
            achados = conexao.search_s(settings.AUTH_LDAP_USER_SEARCH_BASE, ldap.SCOPE_SUBTREE, filtro, ["sAMAccountName"])
    except (DirectoryUnavailable, ldap.LDAPError):
        logger.warning("AD indisponível ao conferir o grupo da Soluções de %s; usando o layout da C+.", login)
        return "cmais"
    return "solucoes" if any(dn for dn, _ in achados) else "cmais"
