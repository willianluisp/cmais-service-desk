import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.contrib.auth import authenticate


def production_settings(_script=None, **changes):
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "DJANGO_SETTINGS_MODULE",
            "DJANGO_SECRET_KEY",
            "DJANGO_DEBUG",
            "DATABASE_URL",
            "ALLOWED_HOSTS",
            "CSRF_TRUSTED_ORIGINS",
            "TRUST_PROXY_HEADERS",
        }
    }
    environment.update(
        DJANGO_SECRET_KEY="production-test-value-" * 4,
        DJANGO_DEBUG="false",
        DATABASE_URL="postgresql://portal:fake-password@db:5432/portal",
        ALLOWED_HOSTS="suporte.example.invalid",
        CSRF_TRUSTED_ORIGINS="https://suporte.example.invalid",
        DJANGO_SETTINGS_MODULE="config.settings.production",
    )
    for key, value in changes.items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    return subprocess.run(
        [
            sys.executable,
            "-c",
            _script
            or (
                "import json; from django.conf import settings; "
                "print(json.dumps({'secure': settings.SESSION_COOKIE_SECURE, "
                "'csrf_secure': settings.CSRF_COOKIE_SECURE, 'debug': settings.DEBUG, "
                "'proxy': settings.SECURE_PROXY_SSL_HEADER}))"
            ),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"DJANGO_SECRET_KEY": ""},
        {"DJANGO_SECRET_KEY": "change-me"},
        {"DJANGO_SECRET_KEY": "django-insecure-" + "a" * 60},
        {"DJANGO_DEBUG": "true"},
        {"DATABASE_URL": "sqlite:///db.sqlite3"},
        {"ALLOWED_HOSTS": "*"},
        {"ALLOWED_HOSTS": ""},
        {"ALLOWED_HOSTS": None},
        {"CSRF_TRUSTED_ORIGINS": "http://suporte.example.invalid"},
    ],
)
def test_production_rejects_unsafe_configuration_without_disclosing_password(changes):
    result = production_settings(**changes)
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    assert "fake-password" not in result.stderr


def test_valid_production_configuration_requires_secure_cookies_and_no_proxy_trust():
    result = production_settings()
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "secure": True,
        "csrf_secure": True,
        "debug": False,
        "proxy": None,
    }


def test_proxy_headers_are_only_trusted_when_explicitly_enabled():
    result = production_settings(TRUST_PROXY_HEADERS="true")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["proxy"] == ["HTTP_X_FORWARDED_PROTO", "https"]


@pytest.mark.django_db
def test_local_password_never_bypasses_disabled_ad(django_user_model, settings):
    settings.LOCAL_AUTH_ENABLED = False
    settings.AUTHENTICATION_BACKENDS = ["apps.accounts.backends.UnavailableBackend"]
    django_user_model.objects.create_superuser(
        username="local-admin",
        password="fake-test-password",
        email="admin@example.invalid",
    )
    assert authenticate(username="local-admin", password="fake-test-password") is None


def test_celery_uses_json_and_sao_paulo_timezone():
    from config.celery import app

    assert app.conf.accept_content == ["json"]
    assert app.conf.timezone == "America/Sao_Paulo"
    assert app.conf.enable_utc is True


def test_external_integrations_stay_disabled_even_if_environment_requests_them():
    result = production_settings(
        LDAP_ENABLED="true",
        PLANNER_ENABLED="true",
        EMAIL_ENABLED="true",
        _script=(
            "import json; from django.conf import settings; print(json.dumps("
            "[settings.LDAP_ENABLED, settings.PLANNER_ENABLED, settings.EMAIL_ENABLED]))"
        ),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [False, False, False]


def test_postgres_tls_options_survive_database_url_parsing():
    result = production_settings(
        DATABASE_URL=(
            "postgresql://portal:fake-password@db:5432/portal"
            "?sslmode=verify-full&sslrootcert=/certs/corporate-ca.pem"
        ),
        _script=(
            "import json; from django.conf import settings; "
            "print(json.dumps(settings.DATABASES['default']['OPTIONS']))"
        ),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "sslmode": "verify-full",
        "sslrootcert": "/certs/corporate-ca.pem",
        "connect_timeout": 3,
    }


def test_default_development_database_preserves_special_characters_in_workspace_path():
    environment = dict(os.environ)
    environment.pop("DATABASE_URL", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; from config.settings.development import DATABASES; "
                "print(json.dumps(str(DATABASES['default']['NAME'])))"
            ),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert Path(json.loads(result.stdout)) == Path(__file__).resolve().parents[1] / "db.sqlite3"


def test_sharepoint_attachment_publication_is_not_scheduled(settings):
    tasks = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
    assert "apps.planner_integration.tasks.publish_pending_attachments" not in tasks


def test_planner_sync_and_provisioning_are_scheduled_every_five_seconds(settings):
    schedule = settings.CELERY_BEAT_SCHEDULE
    assert schedule["sync-linked-planner-tasks"]["schedule"] == 5.0
    assert schedule["provision-planner-tasks"]["schedule"] == 5.0
    assert schedule["sync-linked-planner-tasks"]["kwargs"] == {"limit": 25}
