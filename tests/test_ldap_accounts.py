from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.accounts.backends import ActiveDirectoryBackend
from apps.accounts.directory import identity_from_attributes
from apps.accounts.models import UserProfile

GUID = UUID("5affd692-952d-4c4b-8cfa-ff99232ddf90")
ROLE_DN = "CN=Portal,DC=example,DC=invalid"


@pytest.fixture(autouse=True)
def ldap_settings(settings):
    settings.LDAP_ENABLED = True
    settings.LDAP_ROLE_GROUPS = {"COLABORADOR": ROLE_DN, "TECNICO_TI": "CN=TI,DC=example,DC=invalid"}
    settings.LDAP_REVALIDATE_SECONDS = 300


@pytest.fixture
def attributes():
    return {
        "objectGUID": [GUID.bytes_le], "userAccountControl": ["512"],
        "sAMAccountName": ["ana"], "givenName": ["Ana"], "sn": ["Silva"],
        "displayName": ["Ana Silva"], "mail": [], "department": ["Fiscal"],
        "userPrincipalName": ["ana@example.invalid"],
    }


@pytest.fixture
def identity(attributes):
    return identity_from_attributes(attributes, "CN=Ana,DC=example,DC=invalid", {ROLE_DN.lower()})


def test_identity_extracts_binary_guid_and_allows_missing_email(identity):
    assert identity.object_guid == GUID
    assert identity.roles == frozenset({"COLABORADOR"})
    assert identity.email == ""
    assert identity.display_name == "Ana Silva"


@pytest.mark.parametrize("change", [
    {"objectGUID": []}, {"objectGUID": [b"bad"]},
    {"userAccountControl": ["514"]}, {"userAccountControl": []},
    {"userAccountControl": ["bad"]}, {"sAMAccountName": []},
])
def test_untrustworthy_or_disabled_identity_is_denied(attributes, change):
    attributes.update(change)
    with pytest.raises(PermissionDenied):
        identity_from_attributes(attributes, "CN=Ana,DC=example,DC=invalid", {ROLE_DN})


def test_identity_outside_allowlist_is_denied(attributes):
    with pytest.raises(PermissionDenied):
        identity_from_attributes(attributes, "CN=Ana,DC=example,DC=invalid", set())


@pytest.mark.django_db
def test_guid_preserves_user_and_tickets_identity_on_login_rename(identity):
    first = ActiveDirectoryBackend().provision(identity)
    renamed = replace(identity, sam_account_name="ana.renamed", user_principal_name="new@example.invalid")
    second = ActiveDirectoryBackend().provision(renamed)
    assert first.pk == second.pk
    assert second.ad_profile.object_guid == GUID
    assert second.ad_profile.sam_account_name == "ana.renamed"
    assert not second.has_usable_password()
    assert not second.is_superuser
    assert not second.is_staff


@pytest.mark.django_db
def test_same_mutable_login_with_different_guid_gets_distinct_identity(identity):
    first = ActiveDirectoryBackend().provision(identity)
    other = ActiveDirectoryBackend().provision(replace(identity, object_guid=UUID(int=1)))
    assert first.pk != other.pk


@pytest.mark.django_db
def test_admin_portal_does_not_become_superuser(identity):
    admin = ActiveDirectoryBackend().provision(replace(identity, roles=frozenset({"ADMIN_PORTAL"})))
    assert not admin.is_superuser
    assert not admin.is_staff
    assert list(admin.groups.values_list("name", flat=True)) == ["ADMIN_PORTAL"]


@pytest.mark.django_db
def test_role_removal_revokes_old_group_and_local_extra_permissions(identity):
    backend = ActiveDirectoryBackend()
    user = backend.provision(replace(identity, roles=frozenset({"TECNICO_TI"})))
    user.groups.add(Group.objects.create(name="LOCAL_PRIVILEGE"))
    user = backend.provision(identity)
    assert list(user.groups.values_list("name", flat=True)) == ["COLABORADOR"]


@pytest.mark.django_db
def test_disabled_backend_never_restores_local_session(identity, settings):
    user = ActiveDirectoryBackend().provision(identity)
    settings.LDAP_ENABLED = False
    assert ActiveDirectoryBackend().get_user(user.pk) is None


@pytest.mark.django_db
def test_get_user_revalidates_stale_identity_by_guid_and_applies_roles(identity, monkeypatch):
    backend = ActiveDirectoryBackend()
    user = backend.provision(replace(identity, roles=frozenset({"TECNICO_TI"})))
    UserProfile.objects.filter(user=user).update(last_verified_at=timezone.now() - timedelta(seconds=301))
    lookups = []

    def lookup(guid):
        lookups.append(guid)
        return identity

    monkeypatch.setattr("apps.accounts.backends.lookup_guid", lookup)
    restored = backend.get_user(user.pk)
    assert restored.pk == user.pk
    assert lookups == [GUID]
    assert list(restored.groups.values_list("name", flat=True)) == ["COLABORADOR"]


@pytest.mark.django_db
@pytest.mark.parametrize("failure", [PermissionDenied, OSError])
def test_get_user_denies_and_deactivates_when_revalidation_fails(identity, monkeypatch, failure):
    backend = ActiveDirectoryBackend()
    user = backend.provision(identity)
    UserProfile.objects.filter(user=user).update(last_verified_at=timezone.now() - timedelta(seconds=301))

    def lookup(_guid):
        raise failure("must never leak directory details")

    monkeypatch.setattr("apps.accounts.backends.lookup_guid", lookup)
    assert backend.get_user(user.pk) is None
    user.refresh_from_db()
    assert not user.is_active
    assert not user.groups.exists()


@pytest.mark.django_db
def test_local_user_without_guid_cannot_restore_session(django_user_model):
    user = django_user_model.objects.create_user("local", password="test-only")
    assert ActiveDirectoryBackend().get_user(user.pk) is None


def test_empty_password_or_disabled_integration_never_calls_ldap(settings, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("empty password must not reach LDAP")

    monkeypatch.setattr(ActiveDirectoryBackend, "_authenticate_directory", unexpected)
    assert ActiveDirectoryBackend().authenticate(None, username="ana", password="") is None
    settings.LDAP_ENABLED = False
    assert ActiveDirectoryBackend().authenticate(None, username="ana", password="test-only") is None


@pytest.mark.django_db
def test_entra_and_planner_identity_link_requires_explicit_immutable_ids(identity):
    from apps.accounts.identity_links import link_entra_identity

    user = ActiveDirectoryBackend().provision(identity)
    profile = link_entra_identity(
        user=user,
        entra_object_id=UUID("3f9a17da-1d70-4883-85ec-aac3f3fef790"),
        planner_user_id="3f9a17da-1d70-4883-85ec-aac3f3fef790",
    )
    assert profile.object_guid == GUID
    assert str(profile.entra_object_id) == "3f9a17da-1d70-4883-85ec-aac3f3fef790"
    assert profile.planner_user_id == "3f9a17da-1d70-4883-85ec-aac3f3fef790"


@pytest.mark.django_db
def test_entra_identity_cannot_be_reassigned_to_another_ad_user(identity):
    from apps.accounts.identity_links import link_entra_identity

    first = ActiveDirectoryBackend().provision(identity)
    second = ActiveDirectoryBackend().provision(replace(identity, object_guid=UUID(int=2)))
    identifier = UUID("3f9a17da-1d70-4883-85ec-aac3f3fef790")
    link_entra_identity(user=first, entra_object_id=identifier, planner_user_id=str(identifier))
    with pytest.raises(PermissionDenied):
        link_entra_identity(user=second, entra_object_id=identifier, planner_user_id=str(identifier))
