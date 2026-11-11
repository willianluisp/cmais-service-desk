"""Real browser/DOM, mocked message API, disposable pytest database only."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.environ.get('RUN_OBSERVATIONS_BROWSER') != '1', reason='Opt-in isolated Edge UI test')
@pytest.mark.django_db(transaction=True)
def test_observations_browser(live_server, client, django_user_model, settings):
    from apps.tickets.models import Category, Ticket

    settings.PLANNER_OBSERVATIONS_ENABLED = True
    settings.PORTAL_BASE_URL = 'http://localhost:8010'
    settings.MICROSOFT_GRAPH_APPROVED = True
    settings.GRAPH_AUTH_STRATEGY = 'delegated'
    settings.GRAPH_DELEGATED_OAUTH_ENABLED = True
    owner = django_user_model.objects.create_user('observations-browser-synthetic')
    ticket = Ticket.objects.create(number='SD-OBS-UI', title='Solicitação fictícia para testar observações',
        description='Dados exclusivos do banco descartável pytest.', requester=owner,
        category=Category.objects.create(name='Teste'), planner_task_id='task', planner_plan_id='plan')
    client.force_login(owner)
    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, 'OBS_UI_URL': live_server.url,
        'OBS_UI_COOKIE_NAME': settings.SESSION_COOKIE_NAME, 'OBS_UI_TICKET': str(ticket.pk),
        'OBS_UI_SESSION': client.cookies[settings.SESSION_COOKIE_NAME].value}
    result = subprocess.run([shutil.which('node'), str(root / 'scripts/validate-observations-ui.mjs')],
        cwd=root, env=environment, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
