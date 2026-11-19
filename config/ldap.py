"""Opt-in AD settings. Importing this module never opens a directory connection."""

from functools import reduce
from operator import or_
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

ROLES = ("COLABORADOR", "TECNICO_TI", "SUPERVISOR_TI", "ADMIN_PORTAL")
# "ad": papéis vêm dos grupos do AD (modo original).
# "portal": o AD só valida a senha; papéis, ativação e grupos ficam no portal.
ROLE_SOURCES = ("ad", "portal")
USER_ATTRIBUTES = [
    "objectGUID", "sAMAccountName", "userAccountControl", "givenName", "sn",
    "displayName", "mail", "department", "userPrincipalName",
]
USER_FILTER = (
    "(&(objectClass=user)(|(sAMAccountName=%(user)s)(userPrincipalName=%(user)s))"
    "(!(userAccountControl:1.2.840.113556.1.4.803:=2)))"
)
SECURITY_GROUP_FILTER = "(&(objectClass=group)(groupType:1.2.840.113556.1.4.803:=2147483648))"


def _boolean(environment, key, default="false"):
    value = environment.get(key, default).strip().lower()
    if value not in {"true", "false", "1", "0"}:
        raise ImproperlyConfigured(f"{key} deve ser true ou false.")
    return value in {"true", "1"}


def build_ldap_settings(environment, *, dependencies=None):
    if not _boolean(environment, "LDAP_ENABLED"):
        return {
            "LDAP_ENABLED": False,
            "AUTHENTICATION_BACKENDS": ["apps.accounts.backends.UnavailableBackend"],
        }
    role_source = environment.get("LDAP_ROLE_SOURCE", "ad").strip().lower() or "ad"
    if role_source not in ROLE_SOURCES:
        raise ImproperlyConfigured("LDAP_ROLE_SOURCE deve ser ad ou portal.")
    portal_roles = role_source == "portal"
    access_group = environment.get("LDAP_ACCESS_GROUP_DN", "").strip() if portal_roles else ""
    group_base = environment.get("AUTH_LDAP_GROUP_SEARCH_BASE", "").strip()
    required = [
        "AUTH_LDAP_SERVER_URI", "AUTH_LDAP_BIND_DN", "AUTH_LDAP_BIND_PASSWORD",
        "AUTH_LDAP_USER_SEARCH_BASE", "LDAP_CA_CERT_PATH",
    ]
    if not portal_roles or access_group:
        required.append("AUTH_LDAP_GROUP_SEARCH_BASE")
    if any(not environment.get(key, "").strip() for key in required):
        raise ImproperlyConfigured("AD habilitado exige URI, bind, bases e CA corporativa.")
    uri = environment["AUTH_LDAP_SERVER_URI"].strip()
    start_tls = _boolean(environment, "AUTH_LDAP_START_TLS")
    try:
        parsed = urlsplit(uri)
        valid = (
            parsed.scheme in {"ldaps", "ldap"} and parsed.hostname and not parsed.username
            and not parsed.password and not parsed.path and not parsed.query
            and not parsed.fragment and not any(char.isspace() for char in uri)
            and (parsed.port is None or 1 <= parsed.port <= 65535)
            and ((parsed.scheme == "ldaps" and not start_tls)
                 or (parsed.scheme == "ldap" and start_tls))
        )
    except ValueError:
        valid = False
    if not valid:
        raise ImproperlyConfigured("AD exige LDAPS ou LDAP com StartTLS, sem credenciais na URI.")
    ca_path = Path(environment["LDAP_CA_CERT_PATH"])
    try:
        with ca_path.open("rb") as ca_file:
            if not ca_file.read(1):
                raise OSError
    except OSError:
        raise ImproperlyConfigured("LDAP_CA_CERT_PATH deve apontar para uma CA legível.") from None
    if portal_roles:
        # Papéis não são lidos do AD; um grupo de acesso opcional limita quem entra.
        groups = {}
        local_fallback = _boolean(environment, "LDAP_LOCAL_SUPERUSER_FALLBACK", "true")
    else:
        groups = {
            role: environment.get(f"LDAP_GROUP_{role}_DN", "").strip()
            for role in ROLES if environment.get(f"LDAP_GROUP_{role}_DN", "").strip()
        }
        if not groups or len({dn.casefold() for dn in groups.values()}) != len(groups):
            raise ImproperlyConfigured("Configure grupos AD distintos para os papéis autorizados.")
        local_fallback = False
    try:
        ttl = int(environment.get("LDAP_REVALIDATE_SECONDS", "300"))
        if not 1 <= ttl <= 3600:
            raise ValueError
    except ValueError:
        raise ImproperlyConfigured("LDAP_REVALIDATE_SECONDS deve estar entre 1 e 3600.") from None
    if dependencies is None:
        try:
            import ldap
            from django_auth_ldap import config
        except ImportError:
            raise ImproperlyConfigured("AD habilitado requer as dependências LDAP opcionais.") from None
    else:
        ldap, config = dependencies
    tls_options = {
        ldap.OPT_X_TLS_REQUIRE_CERT: ldap.OPT_X_TLS_DEMAND,
        ldap.OPT_X_TLS_CACERTFILE: str(ca_path),
    }
    if portal_roles:
        backends = ["apps.accounts.backends.PortalRolesDirectoryBackend"]
        if local_fallback:
            backends.append("apps.accounts.backends.LocalSuperuserBackend")
        group_search = (
            config.LDAPSearch(group_base, ldap.SCOPE_SUBTREE, SECURITY_GROUP_FILTER)
            if group_base else None
        )
        group_type = config.NestedActiveDirectoryGroupType() if group_base else None
        require_group = config.LDAPGroupQuery(access_group) if access_group else None
    else:
        backends = ["apps.accounts.backends.ActiveDirectoryBackend"]
        group_search = config.LDAPSearch(group_base, ldap.SCOPE_SUBTREE, SECURITY_GROUP_FILTER)
        group_type = config.NestedActiveDirectoryGroupType()
        require_group = reduce(or_, (config.LDAPGroupQuery(dn) for dn in groups.values()))
    return {
        "LDAP_ENABLED": True,
        "LDAP_ROLE_SOURCE": role_source,
        "LDAP_ACCESS_GROUP_DN": access_group,
        "LDAP_LOCAL_SUPERUSER_FALLBACK": local_fallback,
        "LDAP_ROLE_GROUPS": groups,
        "LDAP_REVALIDATE_SECONDS": ttl,
        "AUTHENTICATION_BACKENDS": backends,
        "AUTH_LDAP_SERVER_URI": uri,
        "AUTH_LDAP_BIND_DN": environment["AUTH_LDAP_BIND_DN"],
        "AUTH_LDAP_BIND_PASSWORD": environment["AUTH_LDAP_BIND_PASSWORD"],
        "AUTH_LDAP_USER_SEARCH_BASE": environment["AUTH_LDAP_USER_SEARCH_BASE"],
        "AUTH_LDAP_GROUP_SEARCH_BASE": group_base,
        "AUTH_LDAP_START_TLS": start_tls,
        "AUTH_LDAP_GLOBAL_OPTIONS": tls_options,
        "AUTH_LDAP_CONNECTION_OPTIONS": {
            **tls_options, ldap.OPT_X_TLS_NEWCTX: 0,
            ldap.OPT_NETWORK_TIMEOUT: 3, ldap.OPT_TIMEOUT: 3, ldap.OPT_REFERRALS: 0,
        },
        "AUTH_LDAP_USER_SEARCH": config.LDAPSearch(
            environment["AUTH_LDAP_USER_SEARCH_BASE"], ldap.SCOPE_SUBTREE,
            USER_FILTER, attrlist=USER_ATTRIBUTES,
        ),
        "AUTH_LDAP_GROUP_SEARCH": group_search,
        "AUTH_LDAP_GROUP_TYPE": group_type,
        "AUTH_LDAP_REQUIRE_GROUP": require_group,
        "AUTH_LDAP_USER_ATTRLIST": USER_ATTRIBUTES,
        "AUTH_LDAP_USER_ATTR_MAP": {},
        "AUTH_LDAP_USER_FLAGS_BY_GROUP": {},
        "AUTH_LDAP_ALWAYS_UPDATE_USER": True,
        "AUTH_LDAP_CACHE_TIMEOUT": 0,
        "AUTH_LDAP_PERMIT_EMPTY_PASSWORD": False,
        "AUTH_LDAP_FIND_GROUP_PERMS": False,
        "AUTH_LDAP_MIRROR_GROUPS": False,
        "AUTH_LDAP_BIND_AS_AUTHENTICATING_USER": False,
    }
