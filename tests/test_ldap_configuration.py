from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.ldap import build_ldap_settings


@pytest.fixture
def ldap_environment(tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("test-ca-placeholder", encoding="utf-8")
    return {
        "LDAP_ENABLED": "true",
        "AUTH_LDAP_SERVER_URI": "ldaps://dc.example.invalid:636",
        "AUTH_LDAP_BIND_DN": "CN=reader,DC=example,DC=invalid",
        "AUTH_LDAP_BIND_PASSWORD": "test-secret-never-print",
        "AUTH_LDAP_USER_SEARCH_BASE": "DC=example,DC=invalid",
        "AUTH_LDAP_GROUP_SEARCH_BASE": "DC=example,DC=invalid",
        "LDAP_CA_CERT_PATH": str(ca),
        "LDAP_GROUP_COLABORADOR_DN": "CN=portal,DC=example,DC=invalid",
    }


def fake_dependencies():
    ldap = SimpleNamespace(
        SCOPE_SUBTREE=2, OPT_X_TLS_REQUIRE_CERT=1, OPT_X_TLS_DEMAND=2,
        OPT_X_TLS_CACERTFILE=3, OPT_X_TLS_NEWCTX=4, OPT_NETWORK_TIMEOUT=5,
        OPT_TIMEOUT=6, OPT_REFERRALS=7,
    )
    config = SimpleNamespace(
        LDAPSearch=lambda *args, **kwargs: (args, kwargs),
        NestedActiveDirectoryGroupType=lambda: "nested-ad",
        LDAPGroupQuery=lambda dn: frozenset([dn]),
    )
    return ldap, config


def test_disabled_configuration_does_not_import_optional_libraries():
    assert build_ldap_settings({}) == {
        "LDAP_ENABLED": False,
        "AUTHENTICATION_BACKENDS": ["apps.accounts.backends.UnavailableBackend"],
    }


@pytest.mark.parametrize("change", [
    {"AUTH_LDAP_SERVER_URI": "ldap://dc.example.invalid:389"},
    {"AUTH_LDAP_SERVER_URI": "ldaps://user:secret@dc.example.invalid"},
    {"AUTH_LDAP_SERVER_URI": "ldaps://dc.example.invalid/path"},
    {"AUTH_LDAP_SERVER_URI": "ldaps://dc.example.invalid?query"},
    {"AUTH_LDAP_SERVER_URI": "ldaps://dc.example.invalid", "AUTH_LDAP_START_TLS": "true"},
    {"LDAP_CA_CERT_PATH": "does-not-exist.pem"},
    {"AUTH_LDAP_BIND_PASSWORD": ""},
    {"LDAP_GROUP_COLABORADOR_DN": ""},
    {"LDAP_REVALIDATE_SECONDS": "3601"},
    {"LDAP_ENABLED": "treu"},
])
def test_unsafe_or_incomplete_configuration_fails_without_disclosing_secrets(
    ldap_environment, change,
):
    ldap_environment.update(change)
    with pytest.raises(ImproperlyConfigured) as error:
        build_ldap_settings(ldap_environment, dependencies=fake_dependencies())
    assert "test-secret-never-print" not in str(error.value)


@pytest.mark.parametrize("uri,start_tls", [
    ("ldaps://dc.example.invalid:636", False),
    ("ldap://dc.example.invalid:389", True),
])
def test_enabled_configuration_enforces_tls_and_group_allowlist(
    ldap_environment, uri, start_tls,
):
    ldap_environment.update(AUTH_LDAP_SERVER_URI=uri, AUTH_LDAP_START_TLS=str(start_tls))
    result = build_ldap_settings(ldap_environment, dependencies=fake_dependencies())
    assert result["AUTHENTICATION_BACKENDS"] == ["apps.accounts.backends.ActiveDirectoryBackend"]
    assert result["AUTH_LDAP_CONNECTION_OPTIONS"][1] == 2
    assert result["AUTH_LDAP_CONNECTION_OPTIONS"][3] == ldap_environment["LDAP_CA_CERT_PATH"]
    assert result["AUTH_LDAP_CONNECTION_OPTIONS"][7] == 0
    assert result["AUTH_LDAP_REQUIRE_GROUP"] == frozenset(["CN=portal,DC=example,DC=invalid"])
    assert result["AUTH_LDAP_START_TLS"] is start_tls
    assert "userAccountControl:1.2.840.113556.1.4.803:=2" in result["AUTH_LDAP_USER_SEARCH"][0][2]
    assert result["AUTH_LDAP_CACHE_TIMEOUT"] == 0
