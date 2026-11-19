"""Modo LDAP_ROLE_SOURCE=portal: o AD valida a senha e os papéis continuam no portal."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.utils import timezone

from apps.accounts.backends import (
    LocalSuperuserBackend,
    PortalRolesDirectoryBackend,
    normalize_login,
    password_managed_by_directory,
)
from apps.accounts.directory import DirectoryUnavailable, identity_from_attributes
from apps.accounts.models import LocalAccount, UserProfile
from config.ldap import build_ldap_settings
from tests.test_ldap_configuration import fake_dependencies

GUID = UUID("0b6f1e3a-1c2d-4e5f-8a9b-0c1d2e3f4a5b")
ACCESS_DN = "CN=GRP_App_Chamados,OU=Grupos,OU=CMAIS,DC=example,DC=invalid"


@pytest.fixture
def portal_settings(settings):
    settings.LDAP_ENABLED = True
    settings.LDAP_ROLE_SOURCE = "portal"
    settings.LDAP_ACCESS_GROUP_DN = ""
    settings.LDAP_LOCAL_SUPERUSER_FALLBACK = True
    settings.LDAP_ROLE_GROUPS = {}
    settings.LDAP_REVALIDATE_SECONDS = 300
    settings.LOCAL_AUTH_ENABLED = False
    settings.AUTHENTICATION_BACKENDS = [
        "apps.accounts.backends.PortalRolesDirectoryBackend",
        "apps.accounts.backends.LocalSuperuserBackend",
    ]
    return settings


def ad_attributes(login="Ana.Silva", flags="512", guid=GUID):
    return {
        "objectGUID": [guid.bytes_le], "userAccountControl": [flags],
        "sAMAccountName": [login], "givenName": ["Ana"], "sn": ["Silva"],
        "displayName": ["Ana Silva (AD)"], "mail": ["ana@example.invalid"],
        "department": ["Fiscal"], "userPrincipalName": [f"{login}@example.invalid"],
    }


def identity(login="Ana.Silva", guid=GUID):
    return identity_from_attributes(
        ad_attributes(login, guid=guid), f"CN={login},DC=example,DC=invalid", (), require_roles=False,
    )


# ---------- configuração ----------

@pytest.fixture
def portal_environment(tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("test-ca-placeholder", encoding="utf-8")
    return {
        "LDAP_ENABLED": "true",
        "LDAP_ROLE_SOURCE": "portal",
        "AUTH_LDAP_SERVER_URI": "ldaps://dc.example.invalid:636",
        "AUTH_LDAP_BIND_DN": "CN=svc,DC=example,DC=invalid",
        "AUTH_LDAP_BIND_PASSWORD": "test-secret-never-print",
        "AUTH_LDAP_USER_SEARCH_BASE": "OU=Usuarios,DC=example,DC=invalid",
        "LDAP_CA_CERT_PATH": str(ca),
    }


def test_portal_mode_needs_no_role_groups_and_keeps_superuser_fallback(portal_environment):
    result = build_ldap_settings(portal_environment, dependencies=fake_dependencies())
    assert result["LDAP_ROLE_SOURCE"] == "portal"
    assert result["LDAP_ROLE_GROUPS"] == {}
    assert result["AUTH_LDAP_REQUIRE_GROUP"] is None
    assert result["AUTH_LDAP_GROUP_SEARCH"] is None
    assert result["AUTHENTICATION_BACKENDS"] == [
        "apps.accounts.backends.PortalRolesDirectoryBackend",
        "apps.accounts.backends.LocalSuperuserBackend",
    ]
    # TLS continua obrigatório com a CA corporativa.
    assert result["AUTH_LDAP_CONNECTION_OPTIONS"][1] == 2
    assert result["AUTH_LDAP_CONNECTION_OPTIONS"][3] == portal_environment["LDAP_CA_CERT_PATH"]


def test_portal_mode_can_disable_local_fallback(portal_environment):
    portal_environment["LDAP_LOCAL_SUPERUSER_FALLBACK"] = "false"
    result = build_ldap_settings(portal_environment, dependencies=fake_dependencies())
    assert result["AUTHENTICATION_BACKENDS"] == ["apps.accounts.backends.PortalRolesDirectoryBackend"]


def test_access_group_requires_group_search_base(portal_environment):
    portal_environment["LDAP_ACCESS_GROUP_DN"] = ACCESS_DN
    with pytest.raises(ImproperlyConfigured):
        build_ldap_settings(portal_environment, dependencies=fake_dependencies())
    portal_environment["AUTH_LDAP_GROUP_SEARCH_BASE"] = "OU=Grupos,DC=example,DC=invalid"
    result = build_ldap_settings(portal_environment, dependencies=fake_dependencies())
    assert result["AUTH_LDAP_REQUIRE_GROUP"] == frozenset([ACCESS_DN])
    assert result["LDAP_ACCESS_GROUP_DN"] == ACCESS_DN


@pytest.mark.parametrize("change", [
    {"LDAP_ROLE_SOURCE": "grupos"},
    {"AUTH_LDAP_SERVER_URI": "ldap://dc.example.invalid:389"},
    {"LDAP_CA_CERT_PATH": "nao-existe.pem"},
    {"LDAP_LOCAL_SUPERUSER_FALLBACK": "talvez"},
])
def test_portal_mode_still_rejects_unsafe_configuration(portal_environment, change):
    portal_environment.update(change)
    with pytest.raises(ImproperlyConfigured) as error:
        build_ldap_settings(portal_environment, dependencies=fake_dependencies())
    assert "test-secret-never-print" not in str(error.value)


def test_default_role_source_is_unchanged(portal_environment):
    portal_environment.pop("LDAP_ROLE_SOURCE")
    with pytest.raises(ImproperlyConfigured):
        # Sem LDAP_ROLE_SOURCE vale o modo original, que exige grupos de papel.
        build_ldap_settings(portal_environment, dependencies=fake_dependencies())


# ---------- identidade e login ----------

@pytest.mark.parametrize("typed,expected", [
    ("ana.silva", "ana.silva"), ("CMAIS\\ana.silva", "ana.silva"),
    ("  ana.silva  ", "ana.silva"), ("ana.silva@cmais.local", "ana.silva@cmais.local"), ("", ""),
])
def test_normalize_login_accepts_domain_prefix(typed, expected):
    assert normalize_login(typed) == expected


def test_identity_without_roles_is_accepted_only_in_portal_mode(portal_settings):
    attributes = ad_attributes()
    with pytest.raises(PermissionDenied):
        identity_from_attributes(attributes, "CN=Ana,DC=example,DC=invalid", ())
    assert identity_from_attributes(
        attributes, "CN=Ana,DC=example,DC=invalid", (), require_roles=False,
    ).roles == frozenset()


def test_disabled_ad_account_is_rejected_even_without_roles(portal_settings):
    identity_from_attributes(ad_attributes(), "CN=Ana,DC=x", (), require_roles=False)
    with pytest.raises(PermissionDenied):
        identity_from_attributes(ad_attributes(flags="514"), "CN=Ana,DC=x", (), require_roles=False)


@pytest.mark.django_db
def test_first_login_links_existing_portal_account_and_keeps_its_roles(portal_settings, django_user_model):
    user = django_user_model.objects.create_user("ana.silva", password="senha-local-antiga", is_staff=True)
    technician = Group.objects.create(name="TECNICO_TI")
    user.groups.add(technician)
    LocalAccount.objects.create(user=user, must_change_password=True)

    linked = PortalRolesDirectoryBackend().link(identity("Ana.Silva"))

    assert linked.pk == user.pk
    linked.refresh_from_db()
    assert list(linked.groups.all()) == [technician]
    assert linked.is_staff and not linked.is_superuser
    assert linked.username == "ana.silva"
    assert not linked.has_usable_password()
    assert linked.ad_profile.object_guid == GUID
    assert linked.ad_profile.display_name == "Ana Silva (AD)"
    assert not LocalAccount.objects.get(user=user).must_change_password


@pytest.mark.django_db
def test_superuser_keeps_local_password_for_emergency_access(portal_settings, django_user_model):
    admin = django_user_model.objects.create_superuser("ana.silva", password="senha-de-emergencia")
    PortalRolesDirectoryBackend().link(identity())
    admin.refresh_from_db()
    assert admin.check_password("senha-de-emergencia")


@pytest.mark.django_db
def test_later_logins_follow_guid_after_ad_rename(portal_settings, django_user_model):
    user = django_user_model.objects.create_user("ana.silva")
    PortalRolesDirectoryBackend().link(identity("ana.silva"))
    again = PortalRolesDirectoryBackend().link(identity("ana.souza"))
    assert again.pk == user.pk
    assert again.ad_profile.sam_account_name == "ana.souza"


@pytest.mark.django_db
def test_login_without_portal_account_is_denied_and_creates_nothing(portal_settings, django_user_model):
    with pytest.raises(PermissionDenied):
        PortalRolesDirectoryBackend().link(identity("pessoa.sem.cadastro"))
    assert not django_user_model.objects.exists()
    assert not UserProfile.objects.exists()


@pytest.mark.django_db
def test_inactive_portal_account_is_denied(portal_settings, django_user_model):
    django_user_model.objects.create_user("ana.silva", is_active=False)
    with pytest.raises(PermissionDenied):
        PortalRolesDirectoryBackend().link(identity())


@pytest.mark.django_db
def test_recreated_ad_account_does_not_inherit_linked_portal_account(portal_settings, django_user_model):
    django_user_model.objects.create_user("ana.silva")
    PortalRolesDirectoryBackend().link(identity())
    with pytest.raises(PermissionDenied):
        PortalRolesDirectoryBackend().link(identity(guid=UUID(int=7)))


@pytest.mark.django_db
def test_ambiguous_usernames_are_denied(portal_settings, django_user_model):
    django_user_model.objects.create_user("ana.silva")
    django_user_model.objects.create_user("Ana.Silva")
    with pytest.raises(PermissionDenied):
        PortalRolesDirectoryBackend().link(identity())


@pytest.mark.django_db
def test_authenticate_returns_none_when_directory_fails(portal_settings, monkeypatch):
    backend = PortalRolesDirectoryBackend()
    for error in (PermissionDenied(), DirectoryUnavailable()):
        monkeypatch.setattr(backend, "_authenticate_directory", Mock(side_effect=error))
        assert backend.authenticate(None, username="ana.silva", password="x") is None


@pytest.mark.django_db
def test_authenticate_strips_domain_prefix(portal_settings, monkeypatch):
    backend = PortalRolesDirectoryBackend()
    directory = Mock(return_value="user")
    monkeypatch.setattr(backend, "_authenticate_directory", directory)
    assert backend.authenticate(None, username="CMAIS\\ana.silva", password="x") == "user"
    assert directory.call_args.args[1] == "ana.silva"
    assert backend.authenticate(None, username="ana.silva", password="") is None


def test_backend_is_inert_outside_portal_mode(settings):
    settings.LDAP_ENABLED = True
    settings.LDAP_ROLE_SOURCE = "ad"
    assert PortalRolesDirectoryBackend().authenticate(None, username="ana", password="x") is None
    assert PortalRolesDirectoryBackend().get_user(1) is None


@pytest.mark.django_db
def test_ldap_backend_hook_links_through_django_auth_ldap(portal_settings, django_user_model):
    from apps.accounts.ldap_backend import PortalLinkLDAPBackend

    user = django_user_model.objects.create_user("ana.silva")
    ldap_user = SimpleNamespace(attrs=ad_attributes(), dn="CN=Ana,DC=example,DC=invalid", group_dns=set())
    linked, built = PortalLinkLDAPBackend().get_or_build_user("ana.silva", ldap_user)
    assert (linked.pk, built) == (user.pk, False)


# ---------- revalidação da sessão ----------

@pytest.mark.django_db
def test_session_revalidation_logs_out_without_touching_portal_account(portal_settings, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user("ana.silva")
    PortalRolesDirectoryBackend().link(identity())
    backend = PortalRolesDirectoryBackend()
    assert backend.get_user(user.pk).pk == user.pk  # dentro do prazo: sem consultar o AD

    UserProfile.objects.filter(user=user).update(last_verified_at=timezone.now() - timedelta(hours=1))
    monkeypatch.setattr("apps.accounts.backends.lookup_guid", Mock(side_effect=DirectoryUnavailable()))
    assert backend.get_user(user.pk) is None
    user.refresh_from_db()
    assert user.is_active


@pytest.mark.django_db
def test_session_revalidation_refreshes_profile(portal_settings, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user("ana.silva")
    PortalRolesDirectoryBackend().link(identity())
    UserProfile.objects.filter(user=user).update(last_verified_at=timezone.now() - timedelta(hours=1))
    lookup = Mock(return_value=identity())
    monkeypatch.setattr("apps.accounts.backends.lookup_guid", lookup)
    assert PortalRolesDirectoryBackend().get_user(user.pk).pk == user.pk
    assert lookup.call_args.kwargs == {"require_roles": False}
    assert timezone.now() - UserProfile.objects.get(user=user).last_verified_at < timedelta(minutes=1)


# ---------- acesso de emergência e senha ----------

@pytest.mark.django_db
def test_local_fallback_only_accepts_superusers(portal_settings, django_user_model):
    django_user_model.objects.create_superuser("admin.local", password="senha-de-emergencia")
    django_user_model.objects.create_user("ana.silva", password="senha-local-antiga")
    backend = LocalSuperuserBackend()
    assert backend.authenticate(None, username="admin.local", password="senha-de-emergencia") is not None
    assert backend.authenticate(None, username="ana.silva", password="senha-local-antiga") is None
    portal_settings.LDAP_LOCAL_SUPERUSER_FALLBACK = False
    assert backend.authenticate(None, username="admin.local", password="senha-de-emergencia") is None


@pytest.mark.django_db
def test_password_change_page_redirects_directory_accounts(portal_settings, client, django_user_model):
    user = django_user_model.objects.create_user("ana.silva")
    PortalRolesDirectoryBackend().link(identity())
    assert password_managed_by_directory(user)
    client.force_login(user, backend="apps.accounts.backends.PortalRolesDirectoryBackend")
    response = client.get("/conta/senha/")
    assert response.status_code == 302
    assert response.url == "/conta/"
    page = client.get("/conta/")
    assert "mesma do Windows" in page.content.decode()


@pytest.mark.django_db
def test_login_page_tells_users_to_use_windows_password(portal_settings, client):
    assert "mesma senha do Windows" in client.get("/login/").content.decode()
