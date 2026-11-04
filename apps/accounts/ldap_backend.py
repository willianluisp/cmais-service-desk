"""Loaded only with the optional django-auth-ldap/python-ldap dependencies installed."""

from django_auth_ldap.backend import LDAPBackend

from .backends import ActiveDirectoryBackend
from .directory import identity_from_attributes


class DirectoryLDAPBackend(LDAPBackend):
    def get_or_build_user(self, username, ldap_user):
        identity = identity_from_attributes(ldap_user.attrs, ldap_user.dn, ldap_user.group_dns)
        return ActiveDirectoryBackend().provision(identity), False
