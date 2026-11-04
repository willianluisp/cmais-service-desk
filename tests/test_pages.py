import pytest
from django.test import Client


@pytest.fixture(autouse=True)
def disabled_authentication_mode(settings):
    # These tests specifically cover the preserved disabled-auth deployment.
    settings.LOCAL_AUTH_ENABLED = False
    settings.LDAP_ENABLED = False


def test_home_explains_portal_state_without_invented_tickets(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "C+ Service Desk" in response.content.decode()
    assert "Sua central de suporte C+" in response.content.decode()
    assert "Suas solicitações em um só lugar" in response.content.decode()
    assert "Content-Security-Policy" in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_login_does_not_collect_domain_password_until_ldap_is_available(client):
    response = client.get("/login/")
    assert response.status_code == 200
    assert "Acesso corporativo em preparação" in response.content.decode()
    assert 'type="password"' not in response.content.decode()


def test_login_post_without_csrf_is_rejected():
    response = Client(enforce_csrf_checks=True).post(
        "/login/",
        {"username": "colaborador", "password": "fake-password"},
    )
    assert response.status_code == 403
    assert "fake-password" not in response.content.decode()


def test_login_post_with_csrf_remains_unavailable(settings):
    client = Client(enforce_csrf_checks=True)
    client.get("/login/")
    csrf = client.cookies[settings.CSRF_COOKIE_NAME].value
    response = client.post(
        "/login/",
        {"username": "colaborador", "password": "fake-password"},
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 503
    assert "fake-password" not in response.content.decode()


@pytest.mark.parametrize("path", ["/integracoes/", "/admin/"])
def test_anonymous_visitors_are_sent_to_corporate_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_employee_cannot_view_integration_diagnostics(client, django_user_model):
    user = django_user_model.objects.create_user(username="employee")
    client.force_login(user)
    assert client.get("/integracoes/").status_code == 403


@pytest.mark.django_db
def test_admin_sees_disabled_integrations_without_configuration_secrets(
    client,
    django_user_model,
    settings,
):
    settings.GRAPH_TENANT_ID = "sensitive-config-sentinel"
    staff = django_user_model.objects.create_user(username="support", is_staff=True, is_superuser=True)
    client.force_login(staff)
    response = client.get("/integracoes/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Integração Microsoft" in body
    assert "Demandas Infra TI" in body
    assert "desabilitado" in body
    assert "sensitive-config-sentinel" not in body
    assert response.headers["Cache-Control"] == "no-store"


def test_admin_login_cannot_offer_local_password_fallback(client):
    response = client.get("/admin/login/")
    assert response.status_code == 302
    assert response.url == "/login/"


def test_logout_is_post_only(client):
    assert client.get("/logout/").status_code == 405


@pytest.mark.django_db
def test_logout_clears_authenticated_session(client, django_user_model):
    client.force_login(django_user_model.objects.create_user(username="session-user"))
    assert "_auth_user_id" in client.session
    response = client.post("/logout/")
    assert response.status_code == 302
    assert "_auth_user_id" not in client.session


def test_private_media_is_not_served_directly(client):
    assert client.get("/media/private-attachment.pdf").status_code == 404
