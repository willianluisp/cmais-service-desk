"""Directory boundary: validate attributes, and revalidate sessions without user passwords."""

from dataclasses import dataclass
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email

from config.ldap import SECURITY_GROUP_FILTER, USER_ATTRIBUTES


class DirectoryUnavailable(Exception):
    pass


@dataclass(frozen=True)
class DirectoryIdentity:
    object_guid: UUID
    sam_account_name: str
    user_principal_name: str
    display_name: str
    department: str
    distinguished_name: str
    first_name: str
    last_name: str
    email: str
    roles: frozenset[str]


def identity_from_attributes(attributes, distinguished_name, group_dns):
    attrs = {key.casefold(): value for key, value in (attributes or {}).items()}

    def value(name, default=""):
        values = attrs.get(name.casefold(), [])
        if not values:
            return default
        if len(values) != 1:
            raise PermissionDenied("Directory identity rejected.")
        return values[0]

    def text(name, limit=256):
        raw = value(name)
        return (raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))[:limit]

    try:
        raw_guid = value("objectGUID")
        if isinstance(raw_guid, str):
            guid = UUID(raw_guid) if len(raw_guid) == 36 else UUID(bytes_le=raw_guid.encode("utf-8"))
        else:
            guid = UUID(bytes_le=raw_guid)
        flags = int(value("userAccountControl"))
        if flags < 0 or flags & 2:
            raise ValueError
        groups = {dn.casefold() for dn in group_dns}
        roles = frozenset(
            role for role, dn in settings.LDAP_ROLE_GROUPS.items() if dn.casefold() in groups
        )
        sam_name = text("sAMAccountName")
        if not roles or not sam_name or not distinguished_name or guid.int == 0:
            raise ValueError
        email = text("mail", 254)
        if email:
            try:
                validate_email(email)
            except ValidationError:
                email = ""
        return DirectoryIdentity(
            object_guid=guid, sam_account_name=sam_name,
            user_principal_name=text("userPrincipalName"), display_name=text("displayName"),
            department=text("department"), distinguished_name=distinguished_name,
            first_name=text("givenName", 150), last_name=text("sn", 150), email=email,
            roles=roles,
        )
    except (ValueError, TypeError, UnicodeError, AttributeError):
        raise PermissionDenied("Directory identity rejected.") from None


def lookup_guid(object_guid):
    """Search by binary GUID, so renamed/recreated accounts cannot inherit a session."""
    import ldap
    from ldap.filter import escape_filter_chars

    connection = None
    try:
        connection = ldap.initialize(settings.AUTH_LDAP_SERVER_URI)
        for option, value in settings.AUTH_LDAP_CONNECTION_OPTIONS.items():
            connection.set_option(option, value)
        if settings.AUTH_LDAP_START_TLS:
            connection.start_tls_s()
        connection.simple_bind_s(settings.AUTH_LDAP_BIND_DN, settings.AUTH_LDAP_BIND_PASSWORD)
        guid_filter = "".join(f"\\{byte:02x}" for byte in object_guid.bytes_le)
        results = connection.search_s(
            settings.AUTH_LDAP_USER_SEARCH_BASE, ldap.SCOPE_SUBTREE,
            f"(&(objectClass=user)(objectGUID={guid_filter}))", USER_ATTRIBUTES,
        )
        results = [(dn, attrs) for dn, attrs in results if dn]
        if len(results) != 1:
            raise PermissionDenied("Directory identity rejected.")
        dn, attrs = results[0]
        groups = connection.search_s(
            settings.AUTH_LDAP_GROUP_SEARCH_BASE, ldap.SCOPE_SUBTREE,
            f"(&{SECURITY_GROUP_FILTER}(member:1.2.840.113556.1.4.1941:={escape_filter_chars(dn)}))",
            ["distinguishedName"],
        )
        identity = identity_from_attributes(attrs, dn, {group_dn for group_dn, _ in groups if group_dn})
        if identity.object_guid != object_guid:
            raise PermissionDenied("Directory identity rejected.")
        return identity
    except ldap.LDAPError:
        raise DirectoryUnavailable("Directory temporarily unavailable.") from None
    finally:
        if connection is not None:
            try:
                connection.unbind_s()
            except ldap.LDAPError:
                pass
