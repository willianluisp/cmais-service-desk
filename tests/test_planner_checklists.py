import copy
from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.custom_forms.forms import DefinitionForm
from apps.custom_forms.services import publish_form, save_definition, submit_request
from apps.planner_integration.client import GraphClient, PlannerError
from apps.planner_integration.models import PlannerTaskProvisioning
from apps.planner_integration.services import process_pending_provisioning
from apps.tickets.services import create_ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(django_user_model):
    admin = django_user_model.objects.create_superuser('checklist-admin')
    owner = django_user_model.objects.create_user('checklist-owner')
    tech = django_user_model.objects.create_user('checklist-tech')
    tech.groups.add(Group.objects.get_or_create(name='TECNICO_TI')[0])
    return admin, owner, tech


def data(**changes):
    return dict(title='Instalação', description='', icon='support', display_order=0,
                revision=0, fields='[]', checklist_enabled='on',
                checklist_items='Backup\nInstalar Windows', **changes)


def save(admin, definition=None, text='Backup\nInstalar Windows', publish=True):
    payload = data()
    payload['checklist_items'] = text
    payload['revision'] = definition.revision if definition else 0
    form = DefinitionForm(payload, instance=definition)
    assert form.is_valid(), form.errors
    return save_definition(actor=admin, form_id=definition.pk if definition else None,
                           cleaned=form.cleaned_data, publish=publish)


def test_configure_edit_remove_reorder_publish_and_disable(people):
    admin = people[0]
    definition = save(admin)
    assert definition.checklist_items == ['Backup', 'Instalar Windows']
    assert definition.published_checklist == ['Backup', 'Instalar Windows']
    assert 'checklist' not in str(definition.published_snapshot).lower()
    definition = save(admin, definition, 'Instalar Windows\nValidar', publish=False)
    assert definition.checklist_items == ['Instalar Windows', 'Validar']
    assert definition.published_checklist == ['Backup', 'Instalar Windows']
    publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    definition.refresh_from_db()
    assert definition.published_checklist == ['Instalar Windows', 'Validar']
    payload = data()
    payload.pop('checklist_enabled')
    payload['revision'] = definition.revision
    form = DefinitionForm(payload, instance=definition)
    assert form.is_valid()
    definition = save_definition(actor=admin, form_id=definition.pk, cleaned=form.cleaned_data, publish=True)
    assert definition.published_checklist == []


@pytest.mark.parametrize('text', ['x' * 101, '\n'.join(str(i) for i in range(21)), 'Backup\n backup', ''])
def test_backend_validation(text):
    payload = data()
    payload['checklist_items'] = text
    assert not DefinitionForm(payload).is_valid()


def test_only_admin_can_configure(people):
    form = DefinitionForm(data())
    assert form.is_valid()
    for user in people[1:]:
        with pytest.raises(PermissionDenied):
            save_definition(actor=user, form_id=None, cleaned=form.cleaned_data)


def test_snapshot_is_per_ticket_and_never_public(people, intake_data, client):
    from apps.sectors.models import Company, Sector

    admin, owner, _ = people
    definition = save(admin)
    cleaned = dict(form_version=definition.published_version,
                   company=Company.objects.get(pk=intake_data['company']),
                   sector=Sector.objects.get(pk=intake_data['sector']))
    ticket = submit_request(actor=owner, form_id=definition.pk, cleaned=cleaned)
    original = copy.deepcopy(ticket.planner_provisioning.checklist_snapshot)
    assert [item['title'] for item in original] == ['Backup', 'Instalar Windows']
    definition = save(admin, definition, 'Outro item')
    cleaned['form_version'] = definition.published_version
    other = submit_request(actor=owner, form_id=definition.pk, cleaned=cleaned)
    assert other.planner_provisioning.checklist_snapshot != original
    ticket.planner_provisioning.refresh_from_db()
    assert ticket.planner_provisioning.checklist_snapshot == original
    assert 'Backup' not in str(ticket.form_submission.schema_snapshot)
    client.force_login(owner)
    for path in ['/chamados/novo/', f'/chamados/novo/formulario/{definition.pk}/']:
        response = client.get(path)
        assert response.status_code == 200
        assert b'Outro item' not in response.content


@pytest.fixture
def provision(people, settings):
    settings.PLANNER_PLAN_ID = 'plan'
    ticket = create_ticket(actor=people[1], title='Falha', description='Dados', priority='NORMAL')
    row = ticket.planner_provisioning
    row.checklist_snapshot = [{'id': '11111111-1111-4111-8111-111111111111', 'title': 'Backup'},
                              {'id': '22222222-2222-4222-8222-222222222222', 'title': 'Validar'}]
    row.save()
    graph = Mock(spec=GraphClient)
    graph.list_plan_tasks.return_value = []
    graph.create_task.return_value = {'id': 'task', 'planId': 'plan', 'bucketId': 'entry'}
    graph.get_task_details.return_value = {'@odata.etag': 'etag1', 'checklist': {}}
    return row, graph


def retry(row):
    PlannerTaskProvisioning.objects.filter(pk=row.pk).update(available_at=timezone.now() - timedelta(seconds=1))


def test_native_creation_and_no_duplicate_task(provision):
    row, graph = provision
    process_pending_provisioning(graph_client=graph)
    graph.patch_task_checklist.assert_called_once()
    patch = graph.patch_task_checklist.call_args.kwargs
    assert patch['etag'] == 'etag1'
    assert [v['isChecked'] for v in patch['checklist'].values()] == [False, False]
    row.refresh_from_db()
    assert row.state == 'LINKED' and row.checklist_completed_at
    process_pending_provisioning(graph_client=graph)
    assert graph.create_task.call_count == 1


@pytest.mark.parametrize('code,status', [('THROTTLED', 429), ('AUTH_REQUIRED', 401), ('FORBIDDEN', 403), ('GRAPH_UNAVAILABLE', 503)])
def test_failure_keeps_task_and_recovers(provision, code, status):
    row, graph = provision
    graph.patch_task_checklist.side_effect = PlannerError(code, 'temporário', status=status, retry_after=2)
    process_pending_provisioning(graph_client=graph)
    row.refresh_from_db()
    assert row.ticket.planner_task_id == 'task'
    assert row.state in {'PENDING', 'RECONCILIATION'} and row.last_error_code == code
    graph.patch_task_checklist.side_effect = None
    retry(row)
    process_pending_provisioning(graph_client=graph)
    row.refresh_from_db()
    assert row.state == 'LINKED'
    assert graph.create_task.call_count == 1


def test_retry_preserves_completed_edited_and_manual_items(provision):
    row, graph = provision
    first, second = row.checklist_snapshot
    graph.patch_task_checklist.side_effect = PlannerError('GRAPH_UNAVAILABLE', 'timeout')
    process_pending_provisioning(graph_client=graph)
    graph.patch_task_checklist.side_effect = None
    graph.get_task_details.return_value = {'@odata.etag': 'etag2', 'checklist': {
        first['id']: {'title': 'Backup editado', 'isChecked': True},
        second['id']: {'title': 'Validar', 'isChecked': False},
        'manual': {'title': 'Manual', 'isChecked': True}}}
    retry(row)
    process_pending_provisioning(graph_client=graph)
    assert graph.patch_task_checklist.call_count == 1
    row.refresh_from_db()
    assert row.checklist_completed_at and row.state == 'LINKED'


def test_conflict_reloads_details_and_only_adds_missing(provision):
    row, graph = provision
    first = row.checklist_snapshot[0]
    graph.get_task_details.side_effect = [
        {'@odata.etag': 'old', 'checklist': {}},
        {'@odata.etag': 'new', 'checklist': {first['id']: {'title': 'Editado', 'isChecked': True}}}]
    graph.patch_task_checklist.side_effect = [PlannerError('CONFLICT', 'conflito', status=412), {}]
    process_pending_provisioning(graph_client=graph)
    patch = graph.patch_task_checklist.call_args.kwargs
    assert patch['etag'] == 'new' and first['id'] not in patch['checklist']


def test_ambiguous_removal_is_not_recreated(provision):
    row, graph = provision
    graph.patch_task_checklist.side_effect = PlannerError('GRAPH_UNAVAILABLE', 'timeout')
    process_pending_provisioning(graph_client=graph)
    graph.patch_task_checklist.side_effect = None
    graph.get_task_details.return_value = {'@odata.etag': 'changed', 'checklist': {}}
    retry(row)
    process_pending_provisioning(graph_client=graph)
    row.refresh_from_db()
    assert row.last_error_code == 'CHECKLIST_RECONCILIATION'
    assert graph.patch_task_checklist.call_count == 1


def test_legacy_or_disabled_checklist_does_not_patch(people, settings):
    settings.PLANNER_PLAN_ID = 'plan'
    ticket = create_ticket(actor=people[1], title='Antigo', description='Dados', priority='NORMAL')
    graph = Mock(spec=GraphClient)
    graph.list_plan_tasks.return_value = []
    graph.create_task.return_value = {'id': 'legacy', 'planId': 'plan', 'bucketId': 'entry'}
    process_pending_provisioning(graph_client=graph)
    graph.patch_task_checklist.assert_not_called()
    assert PlannerTaskProvisioning.objects.get(ticket=ticket).state == 'LINKED'


def test_checklist_privacy_and_existing_ticket_access(people, client):
    admin, owner, tech = people
    ticket = create_ticket(actor=owner, title='Privado', description='Dados', priority='NORMAL')
    ticket.planner_checklist = [{'id': 'one', 'title': 'INTERNO-SEGREDO', 'is_checked': True}]
    ticket.planner_checklist_total = 1
    ticket.planner_task_id = 'task'
    ticket.save()
    path = f'/chamados/{ticket.pk}/'
    client.force_login(owner)
    response = client.get(path)
    assert b'INTERNO-SEGREDO' not in response.content
    assert response.context['ticket'].planner_checklist == []
    client.force_login(tech)
    assert client.get(path).status_code == 404
    client.force_login(admin)
    assert b'INTERNO-SEGREDO' in client.get(path).content
    owner.groups.add(Group.objects.get(name='TECNICO_TI'))
    client.force_login(owner)
    response = client.get(path)
    assert b'INTERNO-SEGREDO' in response.content
    assert b'planner.cloud.microsoft' in response.content


def test_graph_patch_uses_supplied_details_etag():
    graph = GraphClient(token_provider=lambda: 'synthetic')
    graph._request_json = Mock(return_value={})
    graph.patch_task_checklist('task', checklist={'id': {'title': 'Backup'}}, etag='details-etag')
    call = graph._request_json.call_args
    assert call.kwargs['extra_headers'] == {'If-Match': 'details-etag'}
    assert call.kwargs['payload'] == {'checklist': {'id': {'title': 'Backup'}}}
    with pytest.raises(PlannerError):
        graph.patch_task_checklist('task', checklist={}, etag='')


def test_remote_limit_missing_etag_and_repeated_conflicts(provision):
    row, graph = provision
    graph.get_task_details.return_value = {'@odata.etag': 'etag', 'checklist': {
        str(i): {'title': f'Manual {i}'} for i in range(19)}}
    process_pending_provisioning(graph_client=graph)
    row.refresh_from_db()
    assert row.last_error_code == 'CHECKLIST_LIMIT'
    graph.patch_task_checklist.assert_not_called()
    graph.get_task_details.return_value = {'checklist': {}}
    retry(row)
    process_pending_provisioning(graph_client=graph)
    row.refresh_from_db()
    assert row.last_error_code == 'INVALID_PAYLOAD'
    graph.get_task_details.return_value = {'@odata.etag': 'etag', 'checklist': {}}
    graph.patch_task_checklist.side_effect = PlannerError('CONFLICT', 'conflict', status=409)
    retry(row)
    process_pending_provisioning(graph_client=graph)
    assert graph.patch_task_checklist.call_count == 3
    row.refresh_from_db()
    assert row.last_error_code == 'CONFLICT' and row.state == 'PENDING'


def test_removed_acknowledged_item_is_not_recreated(provision):
    row, graph = provision
    first, second = row.checklist_snapshot
    row.checklist_acknowledged_ids = [first['id']]
    row.save()
    process_pending_provisioning(graph_client=graph)
    assert list(graph.patch_task_checklist.call_args.kwargs['checklist']) == [second['id']]


def test_crash_after_patch_is_reconciled(provision):
    row, graph = provision
    graph.patch_task_checklist.side_effect = RuntimeError('worker stopped after HTTP')
    with pytest.raises(RuntimeError):
        process_pending_provisioning(graph_client=graph)
    row.refresh_from_db()
    assert row.state == 'PENDING' and row.checklist_inflight_ids
    graph.get_task_details.return_value = {'@odata.etag': 'new', 'checklist': {
        item['id']: {'title': 'Editado', 'isChecked': True} for item in row.checklist_snapshot}}
    retry(row)
    process_pending_provisioning(graph_client=graph)
    row.refresh_from_db()
    assert row.state == 'LINKED' and row.checklist_completed_at
    assert graph.create_task.call_count == graph.patch_task_checklist.call_count == 1


def test_accept_remote_after_ambiguous_deletion_is_authorized_and_non_destructive(provision, people, client, monkeypatch):
    row, graph = provision
    graph.patch_task_checklist.side_effect = PlannerError('GRAPH_UNAVAILABLE', 'timeout')
    process_pending_provisioning(graph_client=graph)
    graph.get_task_details.return_value = {'@odata.etag': 'new', 'checklist': {}}
    retry(row)
    process_pending_provisioning(graph_client=graph)
    path = f'/chamados/{row.ticket_id}/checklist/aceitar-remoto/'
    monkeypatch.setattr('apps.planner_integration.client.configured_read_client', lambda: graph)
    for user in people[1:]:
        client.force_login(user)
        assert client.post(path, {'confirm': 'yes'}).status_code == 403
    client.force_login(people[0])
    assert client.get(path).status_code == 405
    from django.test import Client

    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.cookies = client.cookies
    assert csrf_client.post(path, {'confirm': 'yes'}).status_code == 403
    assert client.post(path).status_code == 400
    assert client.post(path, {'confirm': 'yes'}).status_code == 302
    row.refresh_from_db()
    assert row.checklist_completed_at and row.state == 'PENDING'
    process_pending_provisioning(graph_client=graph)
    row.refresh_from_db()
    assert row.state == 'LINKED'
    assert graph.patch_task_checklist.call_count == graph.create_task.call_count == 1


def test_projection_tracks_native_personalization_and_does_not_leak_in_json(provision, people, client, monkeypatch):
    from apps.planner_integration.services import sync_ticket

    row, graph = provision
    process_pending_provisioning(graph_client=graph)
    graph.get_task.return_value = {'id': 'task', 'planId': 'plan', 'bucketId': 'entry', 'percentComplete': 0}
    graph.get_task_details.return_value = {'@odata.etag': 'new', 'checklist': {
        'extra': {'title': 'INTERNO-ADICIONAL', 'isChecked': False, 'orderHint': 'z'},
        'original': {'title': 'INTERNO-CONCLUIDO', 'isChecked': True, 'orderHint': 'a'}}}
    result = sync_ticket(actor=people[1], ticket_id=row.ticket_id, graph_client=graph)
    row.ticket.refresh_from_db()
    assert [item['title'] for item in row.ticket.planner_checklist] == ['INTERNO-CONCLUIDO', 'INTERNO-ADICIONAL']
    assert row.ticket.planner_checklist_completed == 1
    assert 'INTERNO' not in str(result)
    assert row.checklist_snapshot[0]['title'] == 'Backup'
    monkeypatch.setattr('apps.planner_integration.services.configured_read_client', lambda: graph)
    client.force_login(people[1])
    response = client.post(f'/chamados/{row.ticket_id}/sincronizar/')
    assert response.status_code == 200
    assert 'INTERNO' not in str(response.json()) and 'checklist' not in str(response.json())


def test_duplicate_retains_internal_template_only_in_draft(people):
    from apps.custom_forms.services import perform_action

    definition = save(people[0])
    clone = perform_action(actor=people[0], form_id=definition.pk, revision=definition.revision, action='duplicate')
    assert clone.checklist_items == definition.checklist_items
    assert clone.checklist_enabled and not clone.published_checklist


def test_sensitive_form_keeps_existing_portal_only_policy(people, intake_data):
    from apps.sectors.models import Company, Sector

    group = Group.objects.get_or_create(name='RH_CHECKLIST')[0]
    people[1].groups.add(group)
    definition = save(people[0])
    definition.is_sensitive = True
    definition.draft_audience = [group.pk]
    definition.save()
    definition = publish_form(actor=people[0], form_id=definition.pk, revision=definition.revision)
    ticket = submit_request(actor=people[1], form_id=definition.pk, cleaned={
        'form_version': definition.published_version,
        'company': Company.objects.get(pk=intake_data['company']),
        'sector': Sector.objects.get(pk=intake_data['sector'])})
    assert ticket.is_sensitive and not PlannerTaskProvisioning.objects.filter(ticket=ticket).exists()
