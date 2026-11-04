"""Disposable PostgreSQL homologation; never uses the portal's live database.

pytest-django creates/drops TEST.NAME. The deliberately nonexistent base NAME
also makes accidental use outside the test runner fail rather than touch data.
"""

from .test import *

if not DATABASE_URL:
    raise ValueError("DATABASE_URL PostgreSQL necessária no container isolado.")
DATABASES = {"default": environ.Env.db_url_config(DATABASE_URL)}
if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise ValueError("Homologação exige PostgreSQL.")
DATABASES["default"]["NAME"] = "cmais_homologation_unavailable_base"
DATABASES["default"]["TEST"] = {"NAME": "test_cmais_homologation"}
