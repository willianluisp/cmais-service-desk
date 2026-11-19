"""Loaded only with the optional django-auth-ldap/python-ldap dependencies installed."""

from django.conf import settings
from django_auth_ldap.backend import LDAPBackend

from .backends import ActiveDirectoryBackend, PortalRolesDirectoryBackend
from .directory import identity_from_attributes


class DirectoryLDAPBackend(LDAPBackend):
    def get_or_build_user(self, username, ldap_user):
        identity = identity_from_attributes(ldap_user.attrs, ldap_user.dn, ldap_user.group_dns)
        return ActiveDirectoryBackend().provision(identity), False


class PortalLinkLDAPBackend(LDAPBackend):
    """Valida a senha no AD (bind do próprio usuário) e devolve a conta já existente no portal."""

    def get_or_build_user(self, username, ldap_user):
        # Grupos só são consultados quando há um grupo de acesso configurado;
        # o AUTH_LDAP_REQUIRE_GROUP já foi conferido antes desta chamada.
        group_dns = ldap_user.group_dns if settings.LDAP_ACCESS_GROUP_DN else ()
        identity = identity_from_attributes(
            ldap_user.attrs, ldap_user.dn, group_dns, require_roles=False,
        )
        return PortalRolesDirectoryBackend().link(identity), False
