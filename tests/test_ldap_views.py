from unittest.mock import Mock

import pytest
from django.core.cache import cache
from django.test import RequestFactory

from apps.accounts.views import login_view, logout_view


class FormRequestFactory(RequestFactory):
    def post(self, *args, **kwargs):
        request = super().post(*args, **kwargs)
        request._dont_enforce_csrf_checks = True
        return request


@pytest.fixture(autouse=True)
def clean_login_cache(settings):
    cache.clear()
    settings.LOCAL_AUTH_ENABLED = False
    settings.LDAP_ENABLED = True
    yield
    cache.clear()


def test_disabled_login_has_no_credentials_form(settings):
    settings.LDAP_ENABLED = False
    response = login_view(RequestFactory().get("/login/"))
    assert response.context_data["ldap_enabled"] is False
    assert response.context_data["form"] is None


def test_login_throttles_before_reaching_directory(monkeypatch):
    authenticate = Mock(return_value=None)
    monkeypatch.setattr("apps.accounts.forms.authenticate", authenticate)
    factory = FormRequestFactory()
    responses = [login_view(factory.post("/login/", {"username": "ana", "password": "wrong"})) for _ in range(11)]
    assert responses[-1].status_code == 429
    assert authenticate.call_count == 10


def test_limiter_blocks_varying_usernames_for_one_source_ip(monkeypatch):
    monkeypatch.setattr("apps.accounts.forms.authenticate", Mock(return_value=None))
    factory = FormRequestFactory()
    for index in range(10):
        assert login_view(factory.post("/login/", {"username": f"user{index}", "password": "wrong"})).status_code == 200
    assert login_view(factory.post("/login/", {"username": "next", "password": "wrong"})).status_code == 429


def test_cache_outage_denies_login_without_ldap_attempt(monkeypatch):
    monkeypatch.setattr("apps.accounts.views.cache.add", Mock(side_effect=OSError("private")))
    authenticate = Mock(return_value=None)
    monkeypatch.setattr("apps.accounts.forms.authenticate", authenticate)
    response = login_view(FormRequestFactory().post("/login/", {"username": "ana", "password": "wrong"}))
    assert response.status_code == 503
    assert not authenticate.called
    assert "private" not in response.context_data["login_error"]


@pytest.mark.django_db
def test_successful_login_rejects_external_next_and_rotates_session(client, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user("ad_test")
    user.backend = "apps.accounts.backends.ActiveDirectoryBackend"
    monkeypatch.setattr("apps.accounts.forms.authenticate", Mock(return_value=user))
    old_session = client.session.session_key
    response = client.post("/login/?next=https://attacker.invalid/", {"username": "ana", "password": "test-only"})
    assert response.status_code == 302
    assert response.url == "/"
    assert client.session.session_key != old_session
    assert client.session["_auth_user_id"] == str(user.pk)


def test_logout_requires_post():
    assert logout_view(RequestFactory().get("/logout/")).status_code == 405


def test_login_and_logout_enforce_csrf(client):
    from django.test import Client

    strict_client = Client(enforce_csrf_checks=True)
    assert strict_client.post("/login/", {"username": "ana", "password": "wrong"}).status_code == 403
    assert strict_client.post("/logout/").status_code == 403
