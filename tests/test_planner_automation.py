from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from apps.planner_integration.client import GraphClient, PlannerError
from apps.planner_integration.models import PlannerTaskProvisioning
from apps.tickets.services import create_ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def administrator(settings, django_user_model):
    settings.MICROSOFT_GRAPH_APPROVED = True
    settings.GRAPH_AUTH_STRATEGY = 'client_credentials'
    settings.GRAPH_TENANT_ID = 'synthetic-tenant'
    settings.GRAPH_CLIENT_ID = 'synthetic-client'
    settings.GRAPH_CLIENT_SECRET = 'synthetic-secret'
    settings.PLANNER_PLAN_ID = 'legacy-plan'
    settings.PLANNER_ENABLED = False
    settings.PLANNER_SYNC_ENABLED = False
    cache.clear()
    user = django_user_model.objects.create_superuser('automation-admin', password='test')
    client = Client()
    client.force_login(user)
    return client


def test_plan_list_is_paginated_and_validated():
    graph = GraphClient(token_provider=lambda: 'synthetic')
    graph._request_json = Mock(side_effect=[
        {'value': [{'id': 'plan-a', 'title': 'Suporte'}],
         '@odata.nextLink': 'https://graph.microsoft.com/v1.0/next'},
        {'value': [{'id': 'plan-b', 'title': 'Infra'}]},
    ])
    assert [p['id'] for p in graph.list_my_plans()] == ['plan-a', 'plan-b']
    graph._request_json = Mock(return_value={'value': [{'id': 'bad'}]})
    with pytest.raises(PlannerError):
        graph.list_my_plans()


def test_select_plan_and_explicitly_enable_without_changing_approvals(administrator, monkeypatch, settings):
    from apps.planner_integration.configuration import automation_enabled, selected_plan_id

    graph = Mock()
    graph.list_my_plans.return_value = [{'id': 'chosen-plan', 'title': 'Suporte'}]
    graph.list_plan_buckets.return_value = [{'id': 'entry', 'name': 'Entrada', 'planId': 'chosen-plan'}]
    monkeypatch.setattr('apps.planner_integration.admin_panel.graph', lambda: graph)
    administrator.post('/integracoes/microsoft/planos/')
    response = administrator.post('/integracoes/microsoft/plano/', {'plan_id': 'chosen-plan'})
    assert response.status_code == 302
    assert selected_plan_id() == 'chosen-plan'
    assert not automation_enabled()
    administrator.post('/integracoes/microsoft/mapeamento/', {'PLANNER_INTAKE_BUCKET_ID': 'entry'})
    administrator.post('/integracoes/microsoft/automacao/', {'enabled': 'on'})
    assert automation_enabled()
    assert not settings.PLANNER_ENABLED and not settings.PLANNER_SYNC_ENABLED
    settings.MICROSOFT_GRAPH_APPROVED = False
    assert not automation_enabled()


def test_invalid_or_unsafe_plan_switch_preserves_existing_links(administrator, monkeypatch, django_user_model):
    from apps.planner_integration.configuration import selected_plan_id

    graph = Mock()
    graph.list_my_plans.return_value = [{'id': 'new-plan', 'title': 'Novo'}]
    graph.list_plan_buckets.return_value = []
    monkeypatch.setattr('apps.planner_integration.admin_panel.graph', lambda: graph)
    administrator.post('/integracoes/microsoft/planos/')
    administrator.post('/integracoes/microsoft/plano/', {'plan_id': 'injected'})
    assert selected_plan_id() == 'legacy-plan'
    ticket = create_ticket(actor=django_user_model.objects.create_user('owner'), title='Falha', description='Detalhes', priority='NORMAL')
    ticket.planner_task_id, ticket.planner_plan_id = 'existing', 'legacy-plan'
    ticket.save()
    administrator.post('/integracoes/microsoft/plano/', {'plan_id': 'new-plan'})
    assert selected_plan_id() == 'legacy-plan'
    ticket.refresh_from_db()
    assert ticket.planner_task_id == 'existing'


def test_connection_test_reads_only_and_redacts_errors(administrator, monkeypatch):
    graph = Mock()
    graph.list_plan_buckets.return_value = []
    monkeypatch.setattr('apps.planner_integration.admin_panel.graph', lambda: graph)
    response = administrator.post('/integracoes/microsoft/testar-conexao/', follow=True)
    assert 'Conexão validada' in response.content.decode()
    graph.create_task.assert_not_called()
    graph.list_plan_buckets.side_effect = PlannerError('AUTH_REQUIRED', 'SECRET TOKEN')
    response = administrator.post('/integracoes/microsoft/testar-conexao/', follow=True)
    assert b'SECRET TOKEN' not in response.content
    assert 'Reconecte' in response.content.decode()


@pytest.mark.parametrize('action', ['planos', 'plano', 'automacao', 'testar-conexao', 'sincronizar', 'conferir-envios', 'vincular-envio'])
def test_new_actions_enforce_role_post_and_csrf(administrator, django_user_model, action):
    path = f'/integracoes/microsoft/{action}/'
    assert administrator.get(path).status_code == 405
    csrf = Client(enforce_csrf_checks=True)
    csrf.cookies = administrator.cookies
    assert csrf.post(path).status_code == 403
    client = Client()
    client.force_login(django_user_model.objects.create_user(f'ordinary-{action}', is_staff=True))
    assert client.post(path).status_code == 403


def test_failure_before_post_is_retried_without_ambiguous_state(settings, django_user_model):
    from apps.planner_integration.services import process_pending_provisioning

    settings.PLANNER_PLAN_ID = 'plan'
    ticket = create_ticket(actor=django_user_model.objects.create_user('preflight'), title='Falha', description='Dados', priority='NORMAL')
    graph = Mock()
    graph.list_plan_tasks.side_effect = PlannerError('GRAPH_UNAVAILABLE', 'temporário')
    process_pending_provisioning(graph_client=graph)
    row = PlannerTaskProvisioning.objects.get(ticket=ticket)
    assert row.state == 'PENDING'
    assert row.available_at > timezone.now()
    graph.create_task.assert_not_called()


def test_disconnected_admin_actions_cannot_bypass_explicit_approval(administrator, settings, monkeypatch):
    settings.MICROSOFT_GRAPH_APPROVED = False
    monkeypatch.setattr('apps.planner_integration.admin_panel.graph', lambda: pytest.fail('network'))
    for action in ('planos', 'testar-conexao', 'sincronizar', 'automacao', 'conferir-envios', 'vincular-envio'):
        assert administrator.post(f'/integracoes/microsoft/{action}/', {'enabled': 'on'}).status_code == 302


def test_sync_request_is_durable_when_broker_is_unavailable(administrator, monkeypatch, settings):
    from kombu.exceptions import OperationalError

    from apps.planner_integration.models import PlannerRuntime

    settings.PLANNER_ENABLED = settings.PLANNER_SYNC_ENABLED = True
    monkeypatch.setattr('apps.planner_integration.tasks.run_requested_sync.delay', Mock(side_effect=OperationalError('private redis address')))
    response = administrator.post('/integracoes/microsoft/sincronizar/', follow=True)
    assert PlannerRuntime.objects.get(pk=1).sync_requested
    assert b'private redis address' not in response.content


def test_worker_obeys_shared_backoff_and_recovers_durable_request(administrator, monkeypatch, settings):
    from apps.planner_integration.models import PlannerRuntime
    from apps.planner_integration.tasks import run_requested_sync

    settings.PLANNER_ENABLED = settings.PLANNER_SYNC_ENABLED = True
    runtime = PlannerRuntime.objects.create(sync_requested=True, throttle_until=timezone.now() + timedelta(minutes=5))
    provision = Mock(return_value=0)
    sync = Mock(return_value=0)
    monkeypatch.setattr('apps.planner_integration.tasks.process_pending_provisioning', provision)
    monkeypatch.setattr('apps.planner_integration.tasks._synchronize_linked_tasks', sync)
    run_requested_sync()
    provision.assert_not_called()
    runtime.refresh_from_db()
    assert runtime.sync_requested
    runtime.throttle_until = timezone.now() - timedelta(seconds=1)
    runtime.save()
    run_requested_sync()
    runtime.refresh_from_db()
    assert not runtime.sync_requested and runtime.last_finished_at
    assert provision.called and sync.called


def test_process_crash_keeps_uncertain_post_durable(settings, django_user_model):
    from apps.planner_integration.services import process_pending_provisioning

    settings.PLANNER_PLAN_ID = 'plan'
    ticket = create_ticket(actor=django_user_model.objects.create_user('crash'), title='Falha', description='Dados', priority='NORMAL')
    graph = Mock()
    graph.list_plan_tasks.return_value = []
    graph.create_task.side_effect = RuntimeError('worker interrupted after sending POST')
    with pytest.raises(RuntimeError):
        process_pending_provisioning(graph_client=graph)
    row = PlannerTaskProvisioning.objects.get(ticket=ticket)
    assert row.state == 'RECONCILIATION'
    assert row.attempts == 1
    row.available_at = timezone.now()
    row.save()
    process_pending_provisioning(graph_client=graph)
    assert graph.create_task.call_count == 1


def test_lease_blocks_overlapping_workers_and_expired_lease_is_recovered(administrator):
    from apps.planner_integration.jobs import integration_job
    from apps.planner_integration.models import PlannerRuntime

    with integration_job() as acquired:
        assert acquired
        with integration_job() as duplicate:
            assert not duplicate
    runtime = PlannerRuntime.objects.get()
    assert runtime.last_finished_at and runtime.lease_until is None
    runtime.lease_until = timezone.now() - timedelta(seconds=1)
    runtime.save()
    with integration_job() as recovered:
        assert recovered


def test_planner_token_throttle_is_not_reclassified_as_auth_failure():
    def throttled():
        raise PlannerError('AUTH_THROTTLED', 'aguarde', status=429, retry_after=300)

    graph = GraphClient(token_provider=throttled)
    with pytest.raises(PlannerError) as exc:
        graph.get_task('task')
    assert exc.value.status == 429 and exc.value.retry_after == 300


def test_failed_ticket_does_not_starve_other_tickets(administrator, monkeypatch, settings, django_user_model):
    from apps.planner_integration.tasks import synchronize_linked_tasks

    settings.PLANNER_SYNC_ENABLED = True
    user = django_user_model.objects.create_user('fairness')
    first = create_ticket(actor=user, title='Primeiro', description='Dados', priority='NORMAL')
    second = create_ticket(actor=user, title='Segundo', description='Dados', priority='NORMAL')
    for i, ticket in enumerate((first, second)):
        ticket.planner_task_id = f'task-{i}'
        ticket.save()
    sync = Mock(side_effect=PlannerError('GRAPH_UNAVAILABLE', 'temporário'))
    monkeypatch.setattr('apps.planner_integration.tasks.sync_ticket', sync)
    synchronize_linked_tasks(limit=1)
    synchronize_linked_tasks(limit=1)
    assert {call.kwargs['ticket_id'] for call in sync.call_args_list} == {first.pk, second.pk}


def test_details_remain_pending_if_worker_stops_after_link(settings, django_user_model, monkeypatch):
    from apps.planner_integration.services import process_pending_provisioning

    settings.PLANNER_PLAN_ID = 'plan'
    ticket = create_ticket(actor=django_user_model.objects.create_user('details-crash'), title='Falha', description='Dados', priority='NORMAL')
    graph = Mock()
    graph.list_plan_tasks.return_value = []
    graph.create_task.return_value = {'id': 'created', 'planId': 'plan', 'bucketId': 'entry'}
    graph.update_task_details.side_effect = RuntimeError('worker stops before PATCH')
    with pytest.raises(RuntimeError):
        process_pending_provisioning(graph_client=graph)
    row = PlannerTaskProvisioning.objects.get(ticket=ticket)
    ticket.refresh_from_db()
    assert ticket.planner_task_id == 'created'
    assert row.state in ('PENDING', 'RECONCILIATION')
    row.available_at = timezone.now()
    row.save()
    graph.update_task_details.side_effect = None
    process_pending_provisioning(graph_client=graph)
    assert graph.create_task.call_count == 1
    row.refresh_from_db()
    assert row.state == 'LINKED'


def test_bucket_refresh_cannot_write_old_buckets_into_new_plan(administrator, monkeypatch):
    from apps.planner_integration.models import PlannerConfiguration, PlannerRuntime

    new = PlannerConfiguration.objects.create(plan_id='new-plan')
    runtime = PlannerRuntime.objects.create()
    graph = Mock()

    def switch_during_query(plan):
        assert plan == 'legacy-plan'
        runtime.configuration = new
        runtime.save()
        return [{'id': 'old-entry', 'name': 'Antigo', 'planId': 'legacy-plan'}]

    graph.list_plan_buckets.side_effect = switch_during_query
    monkeypatch.setattr('apps.planner_integration.admin_panel.graph', lambda: graph)
    administrator.post('/integracoes/microsoft/buckets/')
    new.refresh_from_db()
    assert new.buckets == []


def test_admin_can_resolve_uncertain_creation_using_existing_task(administrator, monkeypatch, django_user_model):
    graph = Mock()
    graph.list_plan_tasks.return_value = [{'id': 'existing', 'title': 'Título alterado no Planner'}]
    graph.get_task.return_value = {'id': 'existing', 'planId': 'legacy-plan', 'bucketId': 'entry', 'percentComplete': 0}
    monkeypatch.setattr('apps.planner_integration.admin_panel.graph', lambda: graph)
    ticket = create_ticket(actor=django_user_model.objects.create_user('recovery'), title='Original', description='Dados', priority='NORMAL')
    row = ticket.planner_provisioning
    row.state = 'RECONCILIATION'
    row.save()
    administrator.post('/integracoes/microsoft/conferir-envios/')
    response = administrator.post('/integracoes/microsoft/vincular-envio/', {'provisioning_id': row.pk, 'task_id': 'existing'})
    assert response.status_code == 302
    ticket.refresh_from_db()
    row.refresh_from_db()
    assert ticket.planner_task_id == 'existing' and row.state == 'PENDING'
    graph.create_task.assert_not_called()


def test_migration_definitions_match_models_without_executing_them(settings):
    from django.apps import apps
    from django.db.migrations.autodetector import MigrationAutodetector
    from django.db.migrations.loader import MigrationLoader
    from django.db.migrations.state import ProjectState

    settings.MIGRATION_MODULES = {}
    loader = MigrationLoader(None)
    changes = MigrationAutodetector(loader.project_state(), ProjectState.from_apps(apps)).changes(graph=loader.graph)
    assert not ({'planner_integration', 'tickets'} & changes.keys())


def test_one_plan_task_list_per_provisioning_batch(settings, django_user_model):
    from apps.planner_integration.services import process_pending_provisioning

    settings.PLANNER_PLAN_ID = 'plan'
    owner = django_user_model.objects.create_user('batch-owner')
    for title in ('Primeiro', 'Segundo'):
        create_ticket(actor=owner, title=title, description='Dados', priority='NORMAL')
    graph = Mock()
    graph.list_plan_tasks.return_value = []
    graph.create_task.side_effect = [{'id': f'created-{i}', 'planId': 'plan', 'bucketId': 'entry'} for i in range(2)]
    assert process_pending_provisioning(graph_client=graph) == 2
    assert graph.list_plan_tasks.call_count == 1


def test_oauth_token_throttle_preserves_retry_after():
    from io import BytesIO
    from urllib.error import HTTPError

    from apps.planner_integration.delegated_oauth import _post_form

    opener = Mock()
    opener.open.side_effect = HTTPError('https://login.microsoftonline.com/synthetic/token', 429,
        'throttled', {'Retry-After': '300'}, BytesIO(b'{"error":"temporarily_unavailable"}'))
    with pytest.raises(PlannerError) as exc:
        _post_form('https://login.microsoftonline.com/synthetic/token', {}, opener=opener)
    assert exc.value.status == 429 and exc.value.retry_after == 300


def test_recovery_search_reaches_tasks_beyond_first_page(administrator, monkeypatch):
    graph = Mock()
    graph.list_plan_tasks.return_value = [{'id': str(i), 'title': f'Tarefa {i}'} for i in range(250)]
    monkeypatch.setattr('apps.planner_integration.admin_panel.graph', lambda: graph)
    administrator.post('/integracoes/microsoft/conferir-envios/', {'search': 'Tarefa 249'})
    choices = administrator.session['planner_recovery']['tasks']
    assert choices == [{'id': '249', 'title': 'Tarefa 249'}]
