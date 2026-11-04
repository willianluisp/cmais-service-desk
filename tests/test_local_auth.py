import pytest
from django.test import override_settings


@pytest.mark.django_db
@override_settings(AUTHENTICATION_BACKENDS=["django.contrib.auth.backends.ModelBackend"])
def test_temporary_password_blocks_ticket_access(client, django_user_model):
    from apps.accounts.models import LocalAccount

    user = django_user_model.objects.create_user("ana.silva", password="temporary-test-password")
    LocalAccount.objects.create(user=user, must_change_password=True)
    client.force_login(user)
    response = client.get("/chamados/")
    assert response.status_code == 302
    assert response.url == "/conta/senha/"


@pytest.mark.django_db
def test_import_preflight_and_idempotence(django_user_model):
    from apps.accounts.imports import import_employees

    admin = django_user_model.objects.create_superuser("admin", "admin@example.test", "test-only-password")
    rows = [{"full_name": "Ana Souza", "email": "ana@example.test"}]
    assert not import_employees(actor=admin, rows=rows)["created"]
    result = import_employees(actor=admin, rows=rows, apply=True)
    user = django_user_model.objects.get(username="ana.souza")
    assert user.check_password(result["created"][0]["temporary_password"])
    assert user.local_account.must_change_password
    assert not import_employees(actor=admin, rows=rows, apply=True)["created"]
    conflicts = rows + [{"full_name": "Ana Souza", "email": "other@example.test"}]
    assert import_employees(actor=admin, rows=conflicts, apply=True)["errors"]
    assert django_user_model.objects.count() == 2


@pytest.mark.django_db
def test_local_login_and_mandatory_password_change(client, django_user_model, settings):
    from apps.accounts.models import LocalAccount

    settings.LOCAL_AUTH_ENABLED = True
    settings.AUTHENTICATION_BACKENDS = ["apps.accounts.backends.LocalBackend"]
    user = django_user_model.objects.create_user("ana.silva", password="Temporary-pass-92")
    response = client.post("/login/", {"username": user.username, "password": "Temporary-pass-92"})
    assert response.url == "/conta/senha/"
    assert client.post("/api/protected/").status_code == 403
    response = client.post("/conta/senha/", {"old_password": "Temporary-pass-92", "new_password1": "Different-pass-349", "new_password2": "Different-pass-349"})
    assert response.status_code == 302
    assert not LocalAccount.objects.get(user=user).must_change_password
    user.refresh_from_db()
    assert user.check_password("Different-pass-349")
    assert client.get("/").status_code == 200


@pytest.mark.django_db
def test_import_rejects_missing_names_and_nonadmin(django_user_model):
    from django.core.exceptions import PermissionDenied

    from apps.accounts.imports import import_employees

    employee = django_user_model.objects.create_user("employee")
    with pytest.raises(PermissionDenied):
        import_employees(actor=employee, rows=[], apply=True)
    admin = django_user_model.objects.create_superuser("admin", "admin@example.test", "test-only-password")
    assert import_employees(actor=admin, rows=[{"email": "only@example.test"}], apply=True)["errors"]


@pytest.mark.django_db
def test_reset_is_queued_private_and_token_is_single_use(client, django_user_model, settings):
    import re

    from django.core.cache import cache

    from apps.accounts.models import LocalAccount
    from apps.notifications.models import NotificationOutbox
    from apps.notifications.services import ProviderDisabled, deliver_local

    cache.clear()
    settings.PORTAL_BASE_URL = "http://127.0.0.1:8010"
    user = django_user_model.objects.create_user("ana.silva", email="ana@example.test", password="Temporary-pass-92")
    LocalAccount.objects.create(user=user)
    response = client.post("/conta/recuperar/", {"email": user.email})
    assert response.status_code == 302
    notice = NotificationOutbox.objects.get(template_key="password-reset")
    assert "redefinir" not in response.content.decode()
    settings.NOTIFICATIONS_PROVIDER = "console"
    with pytest.raises(ProviderDisabled):
        deliver_local(notice)
    url = re.search(r"http://127.0.0.1:8010([^\s]+)", notice.body_text).group(1)
    landing = client.get(url)
    changed = client.post(landing.url, {"new_password1": "Different-pass-349", "new_password2": "Different-pass-349"})
    assert changed.status_code == 302
    user.refresh_from_db()
    assert user.check_password("Different-pass-349")
    assert not user.local_account.must_change_password
    assert "inválido" in client.get(url).content.decode()


def test_planner_details_uses_own_etag_and_accepts_empty_204():
    import json
    from io import BytesIO

    from apps.planner_integration.client import GraphClient

    calls = []

    def opener(request, timeout):
        calls.append(request.method)
        if request.method == "GET":
            response = BytesIO(json.dumps({"@odata.etag": "details-etag"}).encode())
            response.status = 200
        else:
            assert request.get_header("If-match") == "details-etag"
            response = BytesIO(b"")
            response.status = 204
        return response

    graph = GraphClient(token_provider=lambda: "test-token", opener=opener)
    assert graph.update_task_details("task", description="Protocol", etag="wrong-task-etag") == {}
    assert calls == ["GET", "PATCH"]


@pytest.mark.django_db
def test_graph_mail_uses_approved_mailbox_and_accepts_202(settings, monkeypatch):
    import json
    from io import BytesIO

    from apps.notifications.models import NotificationOutbox
    from apps.notifications.services import deliver_graph

    settings.EMAIL_ENABLED = True
    settings.MICROSOFT_GRAPH_APPROVED = True
    settings.GRAPH_MAILBOX_ID = "service@example.test"
    monkeypatch.setattr("apps.notifications.services.configured_token_provider", lambda: lambda: "test-token")
    notice = NotificationOutbox.objects.create(idempotency_key="test-mail", recipient="recipient@example.test", subject="Homologação", body_text="Teste")

    class Transport:
        def open(self, request, timeout):
            assert request.full_url == "https://graph.microsoft.com/v1.0/users/service%40example.test/sendMail"
            assert request.method == "POST"
            assert json.loads(request.data)["message"]["toRecipients"][0]["emailAddress"]["address"] == notice.recipient
            response = BytesIO(b"")
            response.status = 202
            return response

    deliver_graph(notice, opener=Transport())


@pytest.mark.django_db
def test_local_login_denies_inactive_and_csrf(client, django_user_model, settings):
    from django.core.cache import cache
    from django.test import Client

    cache.clear()
    settings.LOCAL_AUTH_ENABLED = True
    settings.AUTHENTICATION_BACKENDS = ["apps.accounts.backends.LocalBackend"]
    user = django_user_model.objects.create_user("inactive", password="Temporary-pass-92", is_active=False)
    assert not client.login(username=user.username, password="Temporary-pass-92")
    strict = Client(enforce_csrf_checks=True)
    assert strict.post("/login/", {"username": user.username, "password": "Temporary-pass-92"}).status_code == 403
    assert strict.post("/conta/recuperar/", {"email": "someone@example.test"}).status_code == 403
