"""Opt-in AD settings. Importing this module never opens a directory connection."""

from functools import reduce
from operator import or_
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

ROLES = ("COLABORADOR", "TECNICO_TI", "SUPERVISOR_TI", "ADMIN_PORTAL")
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
    required = (
        "AUTH_LDAP_SERVER_URI", "AUTH_LDAP_BIND_DN", "AUTH_LDAP_BIND_PASSWORD",
        "AUTH_LDAP_USER_SEARCH_BASE", "AUTH_LDAP_GROUP_SEARCH_BASE", "LDAP_CA_CERT_PATH",
    )
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
    groups = {
        role: environment.get(f"LDAP_GROUP_{role}_DN", "").strip()
        for role in ROLES if environment.get(f"LDAP_GROUP_{role}_DN", "").strip()
    }
    if not groups or len({dn.casefold() for dn in groups.values()}) != len(groups):
        raise ImproperlyConfigured("Configure grupos AD distintos para os papéis autorizados.")
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
    return {
        "LDAP_ENABLED": True,
        "LDAP_ROLE_GROUPS": groups,
        "LDAP_REVALIDATE_SECONDS": ttl,
        "AUTHENTICATION_BACKENDS": ["apps.accounts.backends.ActiveDirectoryBackend"],
        "AUTH_LDAP_SERVER_URI": uri,
        "AUTH_LDAP_BIND_DN": environment["AUTH_LDAP_BIND_DN"],
        "AUTH_LDAP_BIND_PASSWORD": environment["AUTH_LDAP_BIND_PASSWORD"],
        "AUTH_LDAP_USER_SEARCH_BASE": environment["AUTH_LDAP_USER_SEARCH_BASE"],
        "AUTH_LDAP_GROUP_SEARCH_BASE": environment["AUTH_LDAP_GROUP_SEARCH_BASE"],
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
        "AUTH_LDAP_GROUP_SEARCH": config.LDAPSearch(
            environment["AUTH_LDAP_GROUP_SEARCH_BASE"], ldap.SCOPE_SUBTREE, SECURITY_GROUP_FILTER,
        ),
        "AUTH_LDAP_GROUP_TYPE": config.NestedActiveDirectoryGroupType(),
        "AUTH_LDAP_REQUIRE_GROUP": reduce(or_, (config.LDAPGroupQuery(dn) for dn in groups.values())),
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
