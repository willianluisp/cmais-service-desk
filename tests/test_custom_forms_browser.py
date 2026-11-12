"""Opt-in live browser test, using only a disposable pytest database."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from django.contrib.auth.models import Group


@pytest.mark.skipif(os.environ.get("RUN_FORMS_BROWSER") != "1", reason="Opt-in local Edge UI test")
@pytest.mark.django_db(transaction=True)
def test_visual_builder_browser_roundtrip(live_server, client, django_user_model, settings):
    from apps.custom_forms.models import FormDefinition, FormSubmission
    from apps.sectors.models import Company, Sector

    Sector.objects.create(name="Setor fictício da validação visual")
    Company.objects.create(name='Empresa fictícia da validação visual')
    admin = django_user_model.objects.create_user("browser.synthetic", password="synthetic-password")
    admin.groups.add(Group.objects.get_or_create(name="ADMIN_PORTAL")[0])
    client.force_login(admin)
    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "FORMS_UI_URL": live_server.url,
        "FORMS_UI_COOKIE_NAME": settings.SESSION_COOKIE_NAME,
        "FORMS_UI_SESSION": client.cookies[settings.SESSION_COOKIE_NAME].value}
    result = subprocess.run([shutil.which("node"), str(root / "scripts/validate-custom-forms-ui.mjs")],
        cwd=root, env=environment, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert FormDefinition.objects.get().status == "DRAFT"
    assert len(FormDefinition.objects.get().fields) == 7
    assert FormDefinition.objects.get().published_checklist == ['CHECKLIST INTERNO Validar', 'CHECKLIST INTERNO Backup']
    assert FormSubmission.objects.count() == 1
