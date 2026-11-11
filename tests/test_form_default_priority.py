import copy
import uuid
from unittest.mock import Mock

import pytest
from django.contrib.auth.models import Group

from apps.custom_forms.forms import DefinitionForm, RequestForm
from apps.custom_forms.models import FormDefinition, FormSubmission
from apps.custom_forms.services import perform_action, publish_form, save_definition, submit_request
from apps.planner_integration.client import GraphClient, PlannerError
from apps.planner_integration.services import process_pending_provisioning
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


def question(kind='priority', label='Prioridade'):
    return dict(id=str(uuid.uuid4()), type=kind, label=label, required=True, options=['Baixa', 'Alta'] if kind == 'select' else [], default='', help_text='', placeholder='')


@pytest.fixture
def people(django_user_model):
    return (django_user_model.objects.create_superuser('priority-admin'),
            django_user_model.objects.create_user('priority-employee'))


def submit(definition, user, intake, **extra):
    form = RequestForm(definition.published_snapshot, {**intake, 'form_version': definition.published_version, **extra})
    assert form.is_valid(), form.errors
    return submit_request(actor=user, form_id=definition.pk, cleaned=form.cleaned_data)


@pytest.mark.parametrize('kind,label', [('priority', 'Escolha'), ('select', 'Prioridade'), ('short_text', 'Nível de prioridade'), ('select', 'Qual é a urgência do chamado?')])
def test_legacy_priority_questions_not_visible_or_authoritative(people, intake_data, kind, label):
    admin, employee = people
    legacy, other = question(kind, label), question('short_text', 'Descrição')
    definition = FormDefinition.objects.create(title='Prioridade do TI', fields=[legacy, other], default_priority='ALTA')
    definition = publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    form = RequestForm(definition.published_snapshot)
    assert f"cf_{legacy['id']}" not in form.fields and f"cf_{other['id']}" in form.fields
    ticket = submit(definition, employee, intake_data, **{f"cf_{other['id']}": 'Pedido', f"cf_{legacy['id']}": 'CRITICA', 'priority': 'CRITICA', 'default_priority': 'CRITICA'})
    assert ticket.priority == 'ALTA'
    definition.refresh_from_db()
    assert definition.fields == [legacy, other]


def test_configuration_position_permissions_and_choices(people, client):
    admin, employee = people
    client.force_login(admin)
    response = client.get('/administracao/formularios/novo/')
    html = response.content.decode()
    assert html.index('id="id_audience"') < html.index('id="id_default_priority"') < html.index('class="form-builder-layout"')
    assert 'A prioridade selecionada será aplicada automaticamente às novas solicitações deste formulário.' in html
    assert 'data-add-field="priority"' not in html
    assert [choice[0] for choice in response.context['form'].fields['default_priority'].choices] == Ticket.Priority.values
    client.force_login(employee)
    assert client.post('/administracao/formularios/novo/', {'default_priority': 'CRITICA'}).status_code == 403
    employee.groups.add(Group.objects.get_or_create(name='TECNICO_TI')[0])
    assert client.post('/administracao/formularios/novo/', {'default_priority': 'ALTA'}).status_code == 403


def test_draft_publish_copy_history_and_distinct_defaults(people, intake_data):
    admin, employee = people
    definition = FormDefinition.objects.create(title='Alta', default_priority='ALTA')
    definition = publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    old = submit(definition, employee, intake_data)
    previous = copy.deepcopy(FormSubmission.objects.get(ticket=old).schema_snapshot)
    definition = save_definition(actor=admin, form_id=definition.pk, cleaned=dict(revision=definition.revision,
        title='Alta', description='', icon='support', display_order=0, fields=[], audience=[], default_priority='BAIXA'))
    assert submit(definition, employee, intake_data).priority == 'ALTA'
    definition = publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    assert submit(definition, employee, intake_data).priority == 'BAIXA'
    old.refresh_from_db()
    assert old.priority == 'ALTA' and FormSubmission.objects.get(ticket=old).schema_snapshot == previous
    clone = perform_action(actor=admin, form_id=definition.pk, revision=definition.revision, action='duplicate')
    assert clone.default_priority == 'BAIXA'
    clone = publish_form(actor=admin, form_id=clone.pk, revision=clone.revision)
    assert submit(clone, employee, intake_data).priority == 'BAIXA'


def test_old_snapshot_uses_normal_and_legacy_schema_survives_admin_save(people, intake_data):
    admin, employee = people
    legacy = question()
    definition = FormDefinition.objects.create(title='Antigo', fields=[legacy])
    definition = publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    definition.published_snapshot.pop('default_priority', None)
    definition.save(update_fields=['published_snapshot'])
    assert submit(definition, employee, intake_data, priority='CRITICA').priority == 'NORMAL'
    definition = save_definition(actor=admin, form_id=definition.pk, cleaned=dict(revision=definition.revision,
        title='Antigo', description='', icon='support', display_order=0, fields=[], audience=[], default_priority='ALTA'))
    assert definition.fields == [legacy]


def test_invalid_admin_priority_rejected_and_omission_preserves_existing():
    data = dict(title='Exemplo', icon='support', display_order=0, revision=0, fields='[]', default_priority='FORGED')
    form = DefinitionForm(data)
    assert not form.is_valid() and 'default_priority' in form.errors
    instance = FormDefinition(title='Antigo', default_priority='ALTA')
    form = DefinitionForm({k: v for k, v in data.items() if k != 'default_priority'}, instance=instance)
    assert form.is_valid(), form.errors
    assert form.cleaned_data['default_priority'] == 'ALTA'


@pytest.mark.parametrize('priority,mapped', [('BAIXA', 9), ('NORMAL', 5), ('ALTA', 3), ('CRITICA', 1)])
def test_planner_creation_mapped_once(people, intake_data, settings, priority, mapped):
    admin, employee = people
    settings.PLANNER_PLAN_ID, settings.PLANNER_INTAKE_BUCKET_ID = 'plan', 'entry'
    definition = FormDefinition.objects.create(title='Planner', default_priority=priority)
    definition = publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    ticket = submit(definition, employee, intake_data)
    graph = Mock()
    graph.list_plan_tasks.return_value = []
    graph.create_task.return_value = {'id': 'task', 'planId': 'plan'}
    assert process_pending_provisioning(graph_client=graph) == 1
    assert graph.create_task.call_args.kwargs['priority'] == mapped
    ticket.refresh_from_db()
    assert ticket.priority == priority
    graph.reset_mock()
    process_pending_provisioning(graph_client=graph)
    graph.create_task.assert_not_called()


def test_graph_priority_rejection_falls_back_only_after_explicit_bad_request():
    graph = GraphClient(token_provider=lambda: 'mock')
    graph._request_json = Mock(side_effect=[PlannerError('INVALID_REQUEST', 'Rejected', status=400), {'id': 'task'}])
    assert graph.create_task(plan_id='plan', bucket_id='bucket', title='Teste', priority=3) == {'id': 'task'}
    calls = graph._request_json.call_args_list
    assert calls[0].kwargs['payload']['priority'] == 3
    assert 'priority' not in calls[1].kwargs['payload']


@pytest.mark.parametrize('status', [401, 403, 429, 503])
def test_uncertain_creation_or_other_failures_never_retried(status):
    graph = GraphClient(token_provider=lambda: 'mock')
    graph._request_json = Mock(side_effect=PlannerError('GRAPH_UNAVAILABLE', 'private', status=status))
    with pytest.raises(PlannerError):
        graph.create_task(plan_id='plan', bucket_id='bucket', title='Teste', priority=3)
    assert graph._request_json.call_count == 1


@pytest.mark.django_db(transaction=True)
def test_additive_migration_preserves_old_schema_answers_and_ticket_priority(django_user_model):
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    from apps.tickets.models import Category

    user = django_user_model.objects.create_user('priority-migration-synthetic')
    ticket = Ticket.objects.create(number='MIGRATION-PRIORITY', title='Histórico', description='Preservar',
        requester=user, category=Category.objects.create(name='Teste'), priority='CRITICA')
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    old = [('custom_forms', '0003_forms_evolution')]
    legacy = question()
    snapshot = {'title': 'Antigo', 'version': 1, 'fields': [legacy]}
    try:
        executor.migrate(old)
        models = executor.loader.project_state(old).apps
        definition = models.get_model('custom_forms', 'FormDefinition').objects.create(title='Antigo', fields=[legacy], published_snapshot=snapshot)
        submission = models.get_model('custom_forms', 'FormSubmission').objects.create(ticket_id=ticket.pk,
            definition_id=definition.pk, schema_snapshot=snapshot, answers={legacy['id']: 'Alta antiga'})
        MigrationExecutor(connection).migrate(targets)
        restored = FormDefinition.objects.get(pk=definition.pk)
        assert restored.default_priority == 'NORMAL'
        assert restored.fields == [legacy] and restored.published_snapshot == snapshot
        assert FormSubmission.objects.get(pk=submission.pk).answers == {legacy['id']: 'Alta antiga'}
        ticket.refresh_from_db()
        assert ticket.priority == 'CRITICA'
    finally:
        MigrationExecutor(connection).migrate(targets)
