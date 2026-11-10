import os
from pathlib import Path

import environ

from config.ldap import build_ldap_settings

BASE_DIR = Path(__file__).resolve().parents[2]
env = environ.Env()

SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
PORTAL_BASE_URL = env("PORTAL_BASE_URL", default="")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.accounts",
    "apps.tickets",
    "apps.custom_forms",
    "apps.sectors",
    "apps.planner_integration",
    "apps.notifications",
    "apps.audit",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.RequirePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.PortalSecurityHeadersMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.accounts.permissions.portal_access",
            ],
        },
    },
]

DATABASE_URL = env("DATABASE_URL", default="")
DATABASES = {
    "default": (
        environ.Env.db_url_config(DATABASE_URL)
        if DATABASE_URL
        else {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
    )
}
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    DATABASES["default"].setdefault("OPTIONS", {})["connect_timeout"] = 3
DATABASES["default"]["CONN_MAX_AGE"] = 60
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.UnavailableBackend"]
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_ROOT = BASE_DIR / "media"
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_NAME = env("SESSION_COOKIE_NAME", default="sessionid")
CSRF_COOKIE_NAME = env("CSRF_COOKIE_NAME", default="csrftoken")
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 3600
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

REDIS_URL = env("REDIS_URL", default="redis://127.0.0.1:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "cmais-portal",
        "OPTIONS": {"socket_connect_timeout": 2, "socket_timeout": 2},
    }
}
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = None
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_TASK_IGNORE_RESULT = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_TRANSPORT_OPTIONS = {"socket_connect_timeout": 3, "socket_timeout": 3}
CELERY_BEAT_SCHEDULE = {}
EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
DEFAULT_FROM_EMAIL = "nao-responda@example.invalid"

# A Fase 1 nÃ£o carrega configuraÃ§Ãµes de integraÃ§Ã£o ou backends externos.
LDAP_ENABLED = False
# A single approval is required in addition to each narrow integration flag.
# This keeps a copied environment from silently reaching Microsoft 365.
MICROSOFT_GRAPH_APPROVED = env.bool("MICROSOFT_GRAPH_APPROVED", default=False)
PLANNER_ENABLED = env.bool("PLANNER_ENABLED", default=False) and MICROSOFT_GRAPH_APPROVED
PLANNER_SYNC_ENABLED = env.bool("PLANNER_SYNC_ENABLED", default=False) and MICROSOFT_GRAPH_APPROVED
EMAIL_ENABLED = env.bool("EMAIL_ENABLED", default=False) and MICROSOFT_GRAPH_APPROVED
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}

# AD requires a second, explicit approval flag. This prevents an accidental
# ``LDAP_ENABLED=true`` in a deployment environment from loading a password
# authentication backend before the CA and group policy are approved.
LDAP_APPROVED = env.bool("LDAP_APPROVED", default=False)
ldap_environment = dict(os.environ)
if not LDAP_APPROVED:
    ldap_environment["LDAP_ENABLED"] = "false"
LOCAL_AUTH_ENABLED = env.bool("LOCAL_AUTH_ENABLED", default=True)
if LOCAL_AUTH_ENABLED:
    ldap_environment["LDAP_ENABLED"] = "false"
globals().update(build_ldap_settings(ldap_environment))
if LOCAL_AUTH_ENABLED:
    AUTHENTICATION_BACKENDS = ["apps.accounts.backends.LocalBackend"]
PLANNER_PLAN_ID = env("GRAPH_PLAN_ID", default="")
PLANNER_INTAKE_BUCKET_ID = env("PLANNER_BUCKET_ENTRADA_ID", default="")
PLANNER_COMPLETED_BUCKET_ID = env("PLANNER_BUCKET_CONCLUIDO_ID", default="")
PLANNER_IN_PROGRESS_BUCKET_ID = env("PLANNER_BUCKET_EM_ANDAMENTO_ID", default="")
PLANNER_BUCKET_STATUS_MAP = {}
PLANNER_SYNC_MIN_INTERVAL = env.int("PLANNER_SYNC_MIN_INTERVAL", default=15)
GRAPH_TENANT_ID = env("GRAPH_TENANT_ID", default="")
GRAPH_CLIENT_ID = env("GRAPH_CLIENT_ID", default="")
GRAPH_CLIENT_SECRET = env("GRAPH_CLIENT_SECRET", default="")
GRAPH_AUTH_STRATEGY = env("GRAPH_AUTH_STRATEGY", default="client_credentials")
PLANNER_OBSERVATIONS_ENABLED = env.bool("PLANNER_OBSERVATIONS_ENABLED", default=False)
GRAPH_DELEGATED_OAUTH_ENABLED = env.bool("GRAPH_DELEGATED_OAUTH_ENABLED", default=False)
PLANNER_TEST_ENABLED = env.bool("PLANNER_TEST_ENABLED", default=False)
PLANNER_ATTACHMENTS_ENABLED = env.bool("PLANNER_ATTACHMENTS_ENABLED", default=False)
GRAPH_ATTACHMENTS_STORAGE_APPROVED = env.bool("GRAPH_ATTACHMENTS_STORAGE_APPROVED", default=False)
GRAPH_ATTACHMENT_SCOPE_ENABLED = env.bool("GRAPH_ATTACHMENT_SCOPE_ENABLED", default=False)
GRAPH_ATTACHMENTS_DRIVE_ID = env("GRAPH_ATTACHMENTS_DRIVE_ID", default="")
GRAPH_ATTACHMENTS_FOLDER_ID = env("GRAPH_ATTACHMENTS_FOLDER_ID", default="")
GRAPH_ATTACHMENTS_HOST = env("GRAPH_ATTACHMENTS_HOST", default="")
GRAPH_TOKEN_ENCRYPTION_KEY = env("GRAPH_TOKEN_ENCRYPTION_KEY", default="")
GRAPH_MAILBOX_ID = env("GRAPH_MAILBOX_ID", default="")
NOTIFICATIONS_PROVIDER = env("NOTIFICATIONS_PROVIDER", default="console")
NOTIFICATIONS_MAX_ATTEMPTS = 5
NOTIFICATIONS_TI_RECIPIENTS = env.list("NOTIFICATIONS_TI_RECIPIENTS", default=[])

CELERY_BEAT_SCHEDULE = {
    'cleanup-deleted-ticket-files': {
        'task': 'apps.planner_integration.tasks.cleanup_deleted_ticket_files',
        'schedule': 300.0,
    },
    "sync-linked-planner-tasks": {
        "task": "apps.planner_integration.tasks.synchronize_linked_tasks",
        "schedule": 30.0,
        "kwargs": {"limit": 25},
    },
    "provision-planner-tasks": {
        "task": "apps.planner_integration.tasks.provision_pending_tasks",
        "schedule": 5.0,
        "kwargs": {"limit": 25},
    },
    "process-notification-outbox": {
        "task": "apps.notifications.tasks.process_outbox",
        "schedule": 30.0,
        "kwargs": {"limit": 50},
    }
}

