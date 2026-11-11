import os
import shutil
import subprocess
from pathlib import Path

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.test import Client
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


@pytest.mark.skipif(os.environ.get('RUN_SECURITY_UI_BROWSER') != '1', reason='Opt-in local Edge password/priority test')
@pytest.mark.django_db(transaction=True)
def test_password_and_priority_browser(live_server, django_user_model, settings):
    import django

    from apps.accounts.models import LocalAccount
    from apps.custom_forms.models import FormDefinition

    settings.LOCAL_AUTH_ENABLED = True
    settings.LDAP_ENABLED = False
    settings.AUTHENTICATION_BACKENDS = ['apps.accounts.backends.LocalBackend']
    settings.MICROSOFT_GRAPH_APPROVED = settings.PLANNER_ENABLED = settings.EMAIL_ENABLED = False
    admin = django_user_model.objects.create_superuser('security.synthetic')
    first = django_user_model.objects.create_user('security.first')
    LocalAccount.objects.create(user=first, must_change_password=True)
    admin_client, first_client = Client(), Client()
    admin_client.force_login(admin)
    first_client.force_login(first)
    reset = django_user_model.objects.create_user('security.reset')
    reset_path = f'/conta/redefinir/{urlsafe_base64_encode(force_bytes(reset.pk))}/{default_token_generator.make_token(reset)}/'
    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, 'SEC_UI_URL': live_server.url,
        'SEC_UI_COOKIE_NAME': settings.SESSION_COOKIE_NAME,
        'SEC_UI_SESSION': admin_client.cookies[settings.SESSION_COOKIE_NAME].value,
        'SEC_UI_FIRST_SESSION': first_client.cookies[settings.SESSION_COOKIE_NAME].value,
        'SEC_UI_DJANGO_STATIC': str(Path(django.__file__).parent / 'contrib' / 'admin' / 'static'),
        'SEC_UI_RESET_PATH': reset_path, 'SEC_UI_ADMIN_ID': str(admin.pk)}
    result = subprocess.run([shutil.which('node'), str(root / 'scripts/validate-priority-password-ui.mjs')],
        cwd=root, env=environment, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    definition = FormDefinition.objects.get(title='Prioridade administrativa fictícia')
    assert definition.default_priority == 'CRITICA'
    assert definition.published_snapshot['default_priority'] == 'CRITICA'
