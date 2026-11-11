"""Form editor and intake navigation, only against a disposable pytest server."""

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest


@pytest.mark.skipif(os.environ.get('RUN_REQUEST_FLOW_BROWSER') != '1', reason='Opt-in local Edge flow test')
@pytest.mark.django_db(transaction=True)
def test_request_flow_browser(live_server, client, django_user_model, settings, tmp_path):
    from apps.custom_forms.models import FormDefinition, FormSubmission
    from apps.custom_forms.services import publish_form
    from apps.sectors.models import Company, Sector
    from apps.tickets.models import Ticket

    settings.PRIVATE_ATTACHMENT_ROOT = tmp_path
    settings.PLANNER_ENABLED = settings.PLANNER_SYNC_ENABLED = settings.MICROSOFT_GRAPH_APPROVED = False
    owner = django_user_model.objects.create_superuser('flow.synthetic')
    companies = [Company.objects.create(name=f'Empresa fictícia {i}') for i in range(2)]
    sectors = [Sector.objects.create(name=f'Setor fictício {i}') for i in range(2)]
    fields = [dict(id=str(uuid.uuid4()), type=kind, label=label, required=required,
        help_text='', placeholder='', default='', options=[]) for kind, label, required in [
        ('subject', 'Assunto', False), ('long_text', 'Descrição', True), ('attachment', 'Evidência', False)]]
    definition = FormDefinition.objects.create(title='Fluxo fictício de acesso', fields=fields)
    definition = publish_form(actor=owner, form_id=definition.pk, revision=definition.revision)
    client.force_login(owner)
    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, 'FLOW_UI_URL': live_server.url,
        'FLOW_UI_COOKIE_NAME': settings.SESSION_COOKIE_NAME,
        'FLOW_UI_SESSION': client.cookies[settings.SESSION_COOKIE_NAME].value,
        'FLOW_UI_FORM': str(definition.pk), 'FLOW_UI_SUBJECT': fields[0]['id'],
        'FLOW_UI_DESCRIPTION': fields[1]['id'], 'FLOW_UI_COMPANY': str(companies[0].pk),
        'FLOW_UI_OTHER_COMPANY': str(companies[1].pk), 'FLOW_UI_SECTOR': str(sectors[0].pk),
        'FLOW_UI_OTHER_SECTOR': str(sectors[1].pk)}
    result = subprocess.run([shutil.which('node'), str(root / 'scripts/validate-request-flow-ui.mjs')],
        cwd=root, env=environment, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    tickets = list(Ticket.objects.order_by('created_at'))
    assert len(tickets) == 2 and FormSubmission.objects.count() == 2
    assert tickets[0].title == 'Assunto preenchido e preservado'
    assert tickets[0].company_id == companies[1].pk
    assert tickets[0].intake_context.sector_id == sectors[1].pk
    assert tickets[0].attachments.count() == 1
    assert tickets[1].title == definition.title
    assert FormDefinition.objects.get(title='Formulário fictício sem assunto').fields == []
