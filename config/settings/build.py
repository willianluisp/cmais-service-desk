"""Configuração exclusiva de collectstatic; não usar para servir requisições."""

from .base import *

SECRET_KEY = "build-only-unused-signing-key"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
