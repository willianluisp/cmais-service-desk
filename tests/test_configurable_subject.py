import copy
import uuid
from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError

from apps.custom_forms.forms import RequestForm
from apps.custom_forms.models import FormDefinition, FormSubmission
from apps.custom_forms.schema import validate_fields
from apps.custom_forms.services import publish_form, save_definition, submit_request
from apps.planner_integration.services import _card_title, process_pending_provisioning
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


def field(kind='subject', required=False, **changes):
    return dict(id=str(uuid.uuid4()), type=kind, label='Assunto' if kind == 'subject' else 'Prioridade',
                required=required, help_text='', placeholder='', default='', options=[], **changes)


@pytest.fixture
def actor(django_user_model):
    return django_user_model.objects.create_superuser('subject-admin')


def published(actor, fields):
    definition = FormDefinition.objects.create(title='Solicitação de acesso', fields=fields)
    return publish_form(actor=actor, form_id=definition.pk, revision=definition.revision)


def submit(actor, definition, data):
    form = RequestForm(definition.published_snapshot, {**data, 'form_version': definition.published_version})
    assert form.is_valid(), form.errors
    return submit_request(actor=actor, form_id=definition.pk, cleaned=form.cleaned_data)


def test_no_automatic_subject_or_priority_and_fallback(actor, intake_data):
    definition = published(actor, [])
    form = RequestForm(definition.published_snapshot)
    assert [f.name for f in form.visible_fields()] == ['company', 'sector']
    ticket = submit(actor, definition, {**intake_data, 'title': 'Ignored unconfigured input', 'priority': 'CRITICA'})
    assert ticket.title == definition.title and ticket.priority == Ticket.Priority.NORMAL
    assert _card_title(ticket) == definition.title


@pytest.mark.parametrize('required,value,valid,title', [
    (False, '', True, 'Solicitação de acesso'), (False, 'Pedido específico', True, 'Pedido específico'),
    (True, '', False, None), (True, 'Pedido obrigatório', True, 'Pedido obrigatório'),
])
def test_optional_and_required_subject(actor, intake_data, required, value, valid, title):
    subject = field(required=required)
    definition = published(actor, [subject])
    data = {**intake_data, 'form_version': 1, f"cf_{subject['id']}": value}
    form = RequestForm(definition.published_snapshot, data)
    assert form.is_valid() == valid
    if valid:
        ticket = submit_request(actor=actor, form_id=definition.pk, cleaned=form.cleaned_data)
        assert ticket.title == title and _card_title(ticket) == title
        assert FormSubmission.objects.get(ticket=ticket).answers[subject['id']] == value
    else:
        assert f"cf_{subject['id']}" in form.errors
        assert not Ticket.objects.exists()


def test_subject_can_be_removed_without_rewriting_existing_answers(actor, intake_data):
    subject = field(required=True)
    definition = published(actor, [subject])
    old = submit(actor, definition, {**intake_data, f"cf_{subject['id']}": 'Histórico preservado'})
    before = copy.deepcopy(FormSubmission.objects.get(ticket=old).schema_snapshot)
    definition = save_definition(actor=actor, form_id=definition.pk, publish=True, cleaned={
        'revision': definition.revision, 'title': definition.title, 'description': '', 'icon': 'access',
        'display_order': 0, 'fields': [], 'audience': []})
    new = submit(actor, definition, intake_data)
    old.refresh_from_db()
    assert old.title == 'Histórico preservado' and _card_title(old) == old.title
    assert FormSubmission.objects.get(ticket=old).schema_snapshot == before
    assert new.title == definition.title


def test_legacy_manual_short_text_subject_is_recognized(actor, intake_data):
    item = field(kind='short_text')
    item['label'] = 'Assunto'
    definition = published(actor, [item])
    ticket = submit(actor, definition, {**intake_data, f"cf_{item['id']}": 'Assunto já cadastrado'})
    assert ticket.title == 'Assunto já cadastrado' and _card_title(ticket) == ticket.title


@pytest.mark.parametrize('value,expected', [('Novo assunto', 'Novo assunto'), ('', 'Solicitação de acesso')])
def test_explicit_subject_takes_precedence_over_legacy_question(actor, intake_data, value, expected):
    legacy, explicit = field('short_text'), field()
    legacy['label'] = 'Assunto'
    definition = published(actor, [legacy, explicit])
    ticket = submit(actor, definition, {**intake_data, f"cf_{legacy['id']}": 'Pergunta antiga', f"cf_{explicit['id']}": value})
    assert ticket.title == expected and _card_title(ticket) == expected
    assert FormSubmission.objects.get(ticket=ticket).answers[legacy['id']] == 'Pergunta antiga'


def test_legacy_priority_question_is_ignored_by_employee_intake(actor, intake_data):
    item = field('priority')
    definition = published(actor, [item])
    assert submit(actor, definition, intake_data).priority == Ticket.Priority.NORMAL
    assert submit(actor, definition, {**intake_data, f"cf_{item['id']}": 'ALTA'}).priority == Ticket.Priority.NORMAL
    form = RequestForm(definition.published_snapshot, {**intake_data, 'form_version': 1, f"cf_{item['id']}": 'FORGED'})
    assert form.is_valid()
    assert f"cf_{item['id']}" not in form.fields


def test_subject_schema_rejects_duplicates_and_oversized_default():
    with pytest.raises(ValidationError):
        validate_fields([field(), field()])
    item = field()
    item['default'] = 'a' * 161
    with pytest.raises(ValidationError):
        validate_fields([item])


@pytest.mark.parametrize('with_subject', [False, True])
def test_planner_creation_uses_resolved_title(actor, intake_data, settings, with_subject):
    settings.PLANNER_PLAN_ID = 'plan'
    settings.PLANNER_INTAKE_BUCKET_ID = 'entry'
    subject = field()
    definition = published(actor, [subject] if with_subject else [])
    submit(actor, definition, {**intake_data, f"cf_{subject['id']}": 'Assunto do Planner'})
    graph = Mock()
    graph.list_plan_tasks.return_value = []
    graph.create_task.return_value = {'id': 'task', 'planId': 'plan'}
    graph.get_task_details.return_value = {'@odata.etag': 'etag'}
    assert process_pending_provisioning(graph_client=graph) == 1
    assert graph.create_task.call_args.kwargs['title'] == ('Assunto do Planner' if with_subject else definition.title)


def test_legacy_support_without_subject_still_creates_ticket(actor, client, intake_data):
    client.force_login(actor)
    response = client.get('/chamados/novo/suporte/', intake_data)
    assert [f.name for f in response.context['form'].visible_fields()] == ['company', 'sector']
    result = client.post('/chamados/novo/suporte/', intake_data)
    assert result.status_code == 302
    assert Ticket.objects.get().title == 'Suporte técnico'


def test_editor_offers_subject_without_inserting_it(actor, client):
    client.force_login(actor)
    response = client.get('/administracao/formularios/novo/')
    html = response.content.decode()
    assert 'data-add-field="subject"' in html
    assert '"subject"' in html
    assert not FormDefinition.objects.exists()


def test_selection_pages_advance_with_native_submit_options(actor, client, intake_data):
    client.force_login(actor)
    for params, name in [({}, 'company'), ({'company': intake_data['company']}, 'sector')]:
        page = client.get('/chamados/novo/', params).content.decode()
        assert f'type="submit" name="{name}"' in page
        assert 'Continuar' not in page


def test_return_to_company_remembers_choices_without_skipping_sector(actor, client, intake_data):
    client.force_login(actor)
    response = client.get('/chamados/novo/', {**intake_data, 'change': 'company'})
    assert response.context['choosing_company']
    assert f'name="company" value="{intake_data["company"]}" aria-pressed="true"' in response.content.decode()
    response = client.get('/chamados/novo/', {'company': intake_data['company'], 'previous_sector': intake_data['sector']})
    assert response.context['selected_sector'].pk == intake_data['sector']
    assert 'type="submit" name="sector"' in response.content.decode()
    assert 'request-cards' not in response.content.decode()
