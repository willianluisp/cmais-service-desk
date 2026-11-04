from django.core.exceptions import ImproperlyConfigured

from .base import *

if (
    len(SECRET_KEY) < 50
    or SECRET_KEY.startswith("django-insecure-")
    or "replace-with" in SECRET_KEY.lower()
):
    raise ImproperlyConfigured("Configure DJANGO_SECRET_KEY com um segredo aleatório forte.")
if env.bool("DJANGO_DEBUG", default=False):
    raise ImproperlyConfigured("DJANGO_DEBUG deve ser false em produção.")
if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise ImproperlyConfigured("Produção exige DATABASE_URL para PostgreSQL.")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
if not ALLOWED_HOSTS or any("*" in host for host in ALLOWED_HOSTS):
    raise ImproperlyConfigured("Defina ALLOWED_HOSTS explicitamente, sem curingas.")
if any(not origin.startswith("https://") for origin in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured("CSRF_TRUSTED_ORIGINS exige origens HTTPS.")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^health/(live|ready)/$"]
if env.bool("TRUST_PROXY_HEADERS", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
