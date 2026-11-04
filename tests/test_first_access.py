import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client

from apps.accounts.imports import import_employees
from apps.accounts.models import LocalAccount

pytestmark = pytest.mark.django_db


@pytest.fixture
def isolated(settings):
    settings.LOCAL_AUTH_ENABLED = True
    settings.AUTHENTICATION_BACKENDS = ["apps.accounts.backends.LocalBackend"]
    settings.ISOLATED_HOMOLOGATION_IMPORT_ENABLED = True
    settings.PORTAL_BASE_URL = "http://localhost:8010"
    settings.DEBUG = True
    settings.LDAP_ENABLED = False
    settings.MICROSOFT_GRAPH_APPROVED = False
    settings.PLANNER_ENABLED = False
    settings.EMAIL_ENABLED = False


def test_isolated_import_accepts_authorized_single_name_preserves_existing(isolated, django_user_model):
    untouched = django_user_model.objects.create_user("colaborador.teste", password="unchanged")
    before = untouched.password
    rows = [{"full_name": "Bruna", "email": "bruna@example.test", "username": "bruna"}]
    options = dict(actor=None, rows=rows, initial_password="weak-test", single_name_usernames={"bruna"})
    assert import_employees(**options)["ready"] == 1
    assert django_user_model.objects.count() == 1
    result = import_employees(**options, apply=True)
    assert len(result["created"]) == 1
    user = django_user_model.objects.get(username="bruna")
    assert user.first_name == "Bruna" and user.last_name == ""
    assert user.check_password("weak-test") and user.local_account.must_change_password
    assert not user.is_staff and not user.is_superuser and not user.user_permissions.exists()
    assert set(user.groups.values_list("name", flat=True)) == {"COLABORADOR"}
    assert not import_employees(**options, apply=True)["created"]
    untouched.refresh_from_db()
    assert untouched.password == before


@pytest.mark.parametrize("setting,value", [
    ("ISOLATED_HOMOLOGATION_IMPORT_ENABLED", False), ("DEBUG", False),
    ("PORTAL_BASE_URL", "https://production.example"), ("EMAIL_ENABLED", True),
    ("PLANNER_ENABLED", True), ("MICROSOFT_GRAPH_APPROVED", True), ("LDAP_ENABLED", True),
])
def test_shared_initial_password_is_restricted_to_isolated_environment(isolated, settings, setting, value):
    setattr(settings, setting, value)
    with pytest.raises(PermissionDenied):
        import_employees(actor=None, rows=[], initial_password="weak-test", apply=True)


def test_single_name_requires_explicit_allowlist(isolated):
    result = import_employees(actor=None, initial_password="weak-test", rows=[
        {"full_name": "Bruna", "email": "bruna@example.test", "username": "bruna"},
    ], apply=True)
    assert result["errors"] and not result["created"]


@pytest.fixture
def first_user(isolated, django_user_model):
    user = django_user_model.objects.create_user("ana.silva", email="ana@example.test", password="weak-test")
    LocalAccount.objects.create(user=user)
    return user


def test_first_access_modal_and_backend_gate(client, first_user):
    assert client.login(username=first_user.username, password="weak-test")
    response = client.get("/conta/senha/")
    html = response.content.decode()
    assert "Bem-vindo ao C+ Service Desk!" in html
    assert 'id="first-access-dialog"' in html and 'name="old_password"' not in html
    assert 'minlength="8"' in html and "data-password-toggle" in html
    for path in ("/", "/chamados/", "/chamados/novo/", "/admin/", "/integracoes/"):
        assert client.get(path).url == "/conta/senha/"
        assert client.post(path).url == "/conta/senha/"
    assert client.get("/api/private/").status_code == 403
    assert client.get("/chamados/", HTTP_HX_REQUEST="true").status_code == 403
    # A resource required by the modal must load even without WhiteNoise/JS.
    assert client.get("/conta/senha/").status_code == 200
    import os
    from pathlib import Path

    if directory := os.environ.get("FIRST_ACCESS_UI_CAPTURE_DIR"):
        Path(directory).mkdir(parents=True, exist_ok=True)
        (Path(directory) / "welcome.html").write_text(html, encoding="utf-8")


@pytest.mark.parametrize("password,confirmation", [
    ("weak-test", "weak-test"), ("tiny-29", "tiny-29"),
    ("123456789012345", "123456789012345"),
    ("averylongpassword", "different-long-password"),
    ("ana.silva1234", "ana.silva1234"),
])
def test_invalid_password_keeps_first_access_locked(client, first_user, password, confirmation):
    client.force_login(first_user)
    response = client.post("/conta/senha/", {"new_password1": password, "new_password2": confirmation})
    assert response.status_code == 200 and response.context["form"].errors
    first_user.refresh_from_db()
    assert first_user.check_password("weak-test")
    assert first_user.local_account.must_change_password
    assert client.get("/chamados/").url == "/conta/senha/"


def test_success_rotates_current_session_and_invalidates_other_sessions(client, first_user):
    other = Client()
    client.force_login(first_user)
    other.force_login(first_user)
    old_session = client.session.session_key
    password = "Lago!Horizonte-8437"
    response = client.post("/conta/senha/", {"new_password1": password, "new_password2": password})
    assert response.status_code == 302 and response.url == "/"
    first_user.refresh_from_db()
    assert first_user.check_password(password)
    assert not first_user.local_account.must_change_password
    assert client.session.session_key != old_session
    landing = client.get("/")
    assert landing.wsgi_request.user.is_authenticated
    assert "Senha atualizada com sucesso" in landing.content.decode()
    assert not other.get("/").wsgi_request.user.is_authenticated
    assert not Client().login(username=first_user.username, password="weak-test")


def test_password_change_requires_csrf(first_user):
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(first_user)
    assert strict.post("/conta/senha/", {"new_password1": "Lago!Horizonte-8437"}).status_code == 403


def test_existing_account_retains_regular_password_change(client, isolated, django_user_model):
    user = django_user_model.objects.create_user("existing.synthetic", password="Synthetic-Example-4872!")
    LocalAccount.objects.create(user=user, must_change_password=False)
    client.force_login(user)
    html = client.get("/conta/senha/").content.decode()
    assert 'name="old_password"' in html
    assert 'id="first-access-dialog"' not in html
    assert client.get("/").status_code == 200


def test_password_recovery_cannot_bypass_first_access_policy(first_user):
    from apps.accounts.local_views import CompletePasswordForm

    form = CompletePasswordForm(first_user, data={"new_password1": "tiny-29", "new_password2": "tiny-29"})
    assert not form.is_valid()
    assert first_user.local_account.must_change_password


@pytest.mark.parametrize("form_name", ["FirstAccessPasswordForm", "CompletePasswordForm"])
@pytest.mark.parametrize("password,valid", [("Z!q8R@v2", True), ("Z!q8R@v", False)])
def test_eight_character_minimum_in_first_access_and_recovery(first_user, form_name, password, valid):
    from apps.accounts import local_views

    form = getattr(local_views, form_name)(first_user, data={"new_password1": password, "new_password2": password})
    assert form.is_valid() is valid


def test_first_access_keeps_configured_django_validators(client, first_user, settings):
    settings.AUTH_PASSWORD_VALIDATORS = [{
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 24},
    }]
    client.force_login(first_user)
    response = client.post("/conta/senha/", {"new_password1": "Lago!Horizonte-8437", "new_password2": "Lago!Horizonte-8437"})
    assert response.status_code == 200 and response.context["form"].errors
    assert first_user.local_account.must_change_password


@pytest.mark.parametrize("case", ["wrong_hash", "excluded_number", "missing_row"])
def test_import_command_rejects_invalid_roster_before_prompt(tmp_path, monkeypatch, case):
    import csv
    import hashlib

    from django.core.management import call_command
    from django.core.management.base import CommandError

    from apps.accounts.management.commands.import_homologation_employees import EXCLUDED

    rows = [{"number": number, "full_name": "Pessoa Exemplo", "email": f"p{number}@example.test", "username": f"p{number}.exemplo"}
            for number in range(1, 100) if number not in EXCLUDED]
    if case == "excluded_number":
        rows[0]["number"] = 30
    if case == "missing_row":
        rows.pop()
    source = tmp_path / "roster.csv"
    with source.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    digest = "wrong" if case == "wrong_hash" else hashlib.sha256(source.read_bytes()).hexdigest()

    def forbidden(*args):
        raise AssertionError("Não solicitar senha para um lote inválido")

    monkeypatch.setattr("getpass.getpass", forbidden)
    with pytest.raises(CommandError):
        call_command("import_homologation_employees", str(source), sha256=digest, apply=True, confirm_isolated_8010=True)
