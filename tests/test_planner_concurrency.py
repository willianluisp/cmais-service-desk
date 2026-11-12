from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.utils import timezone

from apps.planner_integration.client import PlannerError
from apps.planner_integration.models import PlannerTaskProvisioning
from apps.planner_integration.services import process_pending_provisioning
from apps.tickets.lifecycle import archive_ticket
from apps.tickets.models import Ticket
from apps.tickets.services import create_ticket

pytestmark = pytest.mark.django_db(transaction=True)
pytest_plugins = ['tests.test_planner_attachments']


@pytest.fixture
def scenario(django_user_model, settings):
    if connection.vendor != 'postgresql':
        pytest.skip('Session locks/concurrency require disposable PostgreSQL')
    settings.PLANNER_PLAN_ID = 'plan'
    settings.PLANNER_INTAKE_BUCKET_ID = 'entry'
    admin = django_user_model.objects.create_user('concurrency-admin')
    admin.groups.add(Group.objects.get_or_create(name='ADMIN_PORTAL')[0])
    owner = django_user_model.objects.create_user('concurrency-owner')
    ticket = create_ticket(actor=owner, title='Synthetic', description='Synthetic', priority='NORMAL')
    row = ticket.planner_provisioning
    row.checklist_snapshot = [{'id': '11111111-1111-4111-8111-111111111111', 'title': 'Synthetic'}]
    row.save()
    return admin, ticket, row


def threaded(call):
    close_old_connections()
    try:
        return call()
    finally:
        connections.close_all()


class PausedGraph:
    def __init__(self, ticket, stage):
        self.ticket = ticket
        self.stage = stage
        self.entered, self.release = Event(), Event()
        self.calls = []
        self.patches = 0

    def record(self, stage):
        assert not connection.in_atomic_block, 'Graph HTTP must be outside transactions'
        assert not Ticket.objects.get(pk=self.ticket.pk).archived_at
        self.calls.append(stage)
        if stage == self.stage:
            self.entered.set()
            assert self.release.wait(10)

    def create_task(self, **kwargs):
        self.record('create')
        return {'id': 'task', 'planId': 'plan', 'bucketId': 'entry'}

    def update_task_details(self, task_id, **kwargs):
        self.record('description')

    def get_task_details(self, task_id):
        self.record('retry' if self.patches else 'read')
        return {'@odata.etag': 'details-etag', 'checklist': {}}

    def patch_task_checklist(self, task_id, **kwargs):
        self.record('patch')
        self.patches += 1
        if self.stage == 'retry' and self.patches == 1:
            raise PlannerError('CONFLICT', 'Synthetic', status=412)


@pytest.mark.parametrize('stage', ['create', 'description', 'read', 'patch', 'retry'])
@pytest.mark.parametrize('soft_delete', [False, True])
def test_archive_serializes_all_graph_stages(scenario, stage, soft_delete):
    admin, ticket, row = scenario
    if stage != 'create':
        Ticket.objects.filter(pk=ticket.pk).update(planner_task_id='task', planner_plan_id='plan')
    graph = PausedGraph(ticket, stage)
    with ThreadPoolExecutor(max_workers=2) as pool:
        worker = pool.submit(threaded, lambda: process_pending_provisioning(graph_client=graph, provisioning_id=row.pk))
        try:
            assert graph.entered.wait(10)
            maintenance = pool.submit(threaded, lambda: archive_ticket(actor=admin, ticket_id=ticket.pk, soft_delete=soft_delete))
            with pytest.raises(TimeoutError):
                maintenance.result(timeout=.2)
            assert not Ticket.objects.get(pk=ticket.pk).archived_at
        finally:
            graph.release.set()
        assert worker.result(timeout=10) == 1
        maintenance.result(timeout=10)
    row.refresh_from_db()
    ticket.refresh_from_db()
    assert ticket.archived_at and row.state == 'CANCELLED'
    assert not row.graph_write_inflight
    calls = list(graph.calls)
    assert process_pending_provisioning(graph_client=graph, provisioning_id=row.pk) == 0
    assert graph.calls == calls


def test_archive_wait_is_bounded_and_next_attempt_succeeds(scenario, settings):
    admin, ticket, row = scenario
    settings.PLANNER_TICKET_LOCK_TIMEOUT = .1
    graph = PausedGraph(ticket, 'create')
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(threaded, lambda: process_pending_provisioning(graph_client=graph, provisioning_id=row.pk))
        try:
            assert graph.entered.wait(10)
            with pytest.raises(ValidationError, match='andamento'):
                archive_ticket(actor=admin, ticket_id=ticket.pk)
            assert not Ticket.objects.get(pk=ticket.pk).archived_at
        finally:
            graph.release.set()
        worker.result(timeout=10)
    archive_ticket(actor=admin, ticket_id=ticket.pk)


@pytest.mark.parametrize('crash', [False, True])
def test_uncertain_description_blocks_archive_until_retry_and_releases_lock(scenario, crash):
    admin, ticket, row = scenario
    Ticket.objects.filter(pk=ticket.pk).update(planner_task_id='task', planner_plan_id='plan')
    graph = PausedGraph(ticket, 'none')
    graph.release.set()

    def fail(*args, **kwargs):
        assert not connection.in_atomic_block
        if crash:
            raise RuntimeError('Synthetic worker crash')
        raise PlannerError('GRAPH_UNAVAILABLE', 'Synthetic timeout')

    graph.update_task_details = fail
    if crash:
        with pytest.raises(RuntimeError):
            process_pending_provisioning(graph_client=graph, provisioning_id=row.pk)
    else:
        process_pending_provisioning(graph_client=graph, provisioning_id=row.pk)
    row.refresh_from_db()
    assert row.description_write_inflight
    # A separate DB session can acquire the mutex, but durable uncertainty blocks archive.
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(threaded, lambda: archive_ticket(actor=admin, ticket_id=ticket.pk))
        with pytest.raises(ValidationError, match='conferência'):
            future.result(timeout=5)
    PlannerTaskProvisioning.objects.filter(pk=row.pk).update(available_at=timezone.now())
    graph.update_task_details = lambda *args, **kwargs: graph.record('description')
    process_pending_provisioning(graph_client=graph, provisioning_id=row.pk)
    row.refresh_from_db()
    assert row.state == 'LINKED' and not row.description_write_inflight
    archive_ticket(actor=admin, ticket_id=ticket.pk)


def test_uncertain_post_keeps_durable_intent_and_does_not_repost(scenario):
    admin, ticket, row = scenario
    graph = PausedGraph(ticket, 'none')
    graph.create_task = lambda **kwargs: (_ for _ in ()).throw(PlannerError('GRAPH_UNAVAILABLE', 'Synthetic'))
    process_pending_provisioning(graph_client=graph, provisioning_id=row.pk)
    row.refresh_from_db()
    assert row.state == 'RECONCILIATION' and row.graph_write_inflight
    with pytest.raises(ValidationError, match='conferência'):
        archive_ticket(actor=admin, ticket_id=ticket.pk)
    graph.list_plan_tasks = lambda plan: []
    graph.create_task = lambda **kwargs: pytest.fail('Must not repeat ambiguous POST')
    PlannerTaskProvisioning.objects.filter(pk=row.pk).update(available_at=timezone.now())
    process_pending_provisioning(graph_client=graph, provisioning_id=row.pk)


def test_definite_rejection_releases_mutex_and_allows_archive(scenario):
    admin, ticket, row = scenario
    graph = PausedGraph(ticket, 'none')
    graph.create_task = lambda **kwargs: (_ for _ in ()).throw(PlannerError('FORBIDDEN', 'Synthetic', status=403))
    process_pending_provisioning(graph_client=graph, provisioning_id=row.pk)
    row.refresh_from_db()
    assert not row.graph_write_inflight
    archive_ticket(actor=admin, ticket_id=ticket.pk)


def test_attachment_http_has_no_transaction_and_serializes_archive(scenario, publication, graph):
    from apps.planner_integration.attachments import process_publications

    admin = scenario[0]
    ticket = publication.attachment.ticket
    entered, release = Event(), Event()
    transactions = []

    def pause(*args):
        transactions.append(connection.in_atomic_block)
        entered.set()
        assert release.wait(10)

    graph.attach_reference.side_effect = pause
    with ThreadPoolExecutor(max_workers=2) as pool:
        worker = pool.submit(threaded, lambda: process_publications(graph_client=graph))
        try:
            assert entered.wait(10)
            maintenance = pool.submit(threaded, lambda: archive_ticket(actor=admin, ticket_id=ticket.pk))
            with pytest.raises(TimeoutError):
                maintenance.result(timeout=.2)
        finally:
            release.set()
        assert worker.result(timeout=10) == 1
        maintenance.result(timeout=10)
    assert transactions == [False]
    publication.refresh_from_db()
    assert publication.state == 'PUBLISHED' and not publication.graph_write_inflight


def test_attachment_timeout_blocks_archive_until_recovery(scenario, publication, graph):
    from apps.planner_integration.attachments import process_publications

    admin = scenario[0]
    ticket = publication.attachment.ticket
    graph.attach_reference.side_effect = PlannerError('GRAPH_UNAVAILABLE', 'Synthetic timeout')
    process_publications(graph_client=graph)
    publication.refresh_from_db()
    assert publication.state == 'UPLOADED' and publication.graph_write_inflight
    with pytest.raises(ValidationError, match='conferência'):
        archive_ticket(actor=admin, ticket_id=ticket.pk)
    graph.attach_reference.side_effect = None
    type(publication).objects.filter(pk=publication.pk).update(available_at=timezone.now())
    process_publications(graph_client=graph)
    assert graph.upload_attachment.call_count == 1
    archive_ticket(actor=admin, ticket_id=ticket.pk)


def test_permanent_deletion_uses_same_bounded_mutex(scenario, settings):
    from apps.planner_integration.ticket_locks import ticket_graph_lock
    from apps.tickets.lifecycle import permanently_delete_ticket

    admin, ticket, row = scenario
    settings.PLANNER_TICKET_LOCK_TIMEOUT = .1
    Ticket.objects.filter(pk=ticket.pk).update(archived_at=timezone.now())
    PlannerTaskProvisioning.objects.filter(pk=row.pk).update(state='CANCELLED')
    entered, release = Event(), Event()

    def hold():
        with ticket_graph_lock(ticket.pk):
            entered.set()
            assert release.wait(10)

    with ThreadPoolExecutor(max_workers=1) as pool:
        holding = pool.submit(threaded, hold)
        try:
            assert entered.wait(10)
            with pytest.raises(ValidationError, match='andamento'):
                permanently_delete_ticket(actor=admin, ticket_id=ticket.pk, number=ticket.number,
                                          irreversible=True, password='synthetic-unused')
            assert Ticket.objects.filter(pk=ticket.pk).exists()
        finally:
            release.set()
        holding.result(timeout=10)


def test_worker_skips_busy_ticket_and_other_tickets_remain_available(scenario):
    from apps.planner_integration.ticket_locks import ticket_graph_lock

    admin, ticket, row = scenario
    other = create_ticket(actor=admin, title='Other', description='Other', priority='NORMAL')
    entered, release = Event(), Event()

    def hold():
        with ticket_graph_lock(ticket.pk):
            entered.set()
            assert release.wait(10)

    with ThreadPoolExecutor(max_workers=1) as pool:
        holding = pool.submit(threaded, hold)
        try:
            assert entered.wait(10)
            graph = PausedGraph(ticket, 'none')
            assert process_pending_provisioning(graph_client=graph, provisioning_id=row.pk) == 0
            assert not graph.calls
            archive_ticket(actor=admin, ticket_id=other.pk)
        finally:
            release.set()
        holding.result(timeout=10)


def test_unlock_failure_closes_session_and_releases_postgres_lock(scenario):
    from apps.planner_integration.ticket_locks import ticket_graph_lock

    ticket = scenario[1]

    def fail_unlock(execute, sql, params, many, context):
        if 'pg_advisory_unlock' in sql:
            raise RuntimeError('Synthetic DB error during unlock')
        return execute(sql, params, many, context)

    with connection.execute_wrapper(fail_unlock), ticket_graph_lock(ticket.pk):
        pass
    assert connection.connection is None

    def acquire():
        with ticket_graph_lock(ticket.pk, timeout=0):
            return True

    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(threaded, acquire).result(timeout=5)


def test_session_loss_prevents_graph_write(scenario):
    from apps.planner_integration.ticket_locks import JournaledGraphClient, ticket_graph_lock

    _, ticket, row = scenario
    graph = PausedGraph(ticket, 'none')
    with ticket_graph_lock(ticket.pk):
        guarded = JournaledGraphClient(graph, row, ticket.pk)
        connection.close()
        # A new session cannot inherit the old session's ownership.
        connection.ensure_connection()
        with pytest.raises(ValidationError, match='sessão'):
            guarded.create_task()
        assert not graph.calls


def test_base_exception_releases_mutex_but_preserves_uncertainty(scenario):
    from apps.planner_integration.ticket_locks import ticket_graph_lock

    _, ticket, row = scenario

    class SimulatedTermination(BaseException):
        pass

    graph = PausedGraph(ticket, 'none')
    graph.create_task = lambda **kwargs: (_ for _ in ()).throw(SimulatedTermination())
    with pytest.raises(SimulatedTermination):
        process_pending_provisioning(graph_client=graph, provisioning_id=row.pk)
    row.refresh_from_db()
    assert row.state == 'RECONCILIATION' and row.graph_write_inflight

    def acquire():
        with ticket_graph_lock(ticket.pk, timeout=0):
            return True

    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(threaded, acquire).result(timeout=5)


def test_reconciled_post_without_checklist_clears_uncertainty(scenario):
    from unittest.mock import Mock

    from apps.planner_integration.client import GraphClient

    admin, ticket, row = scenario
    row.checklist_snapshot = []
    row.graph_write_inflight = True
    row.state = 'RECONCILIATION'
    row.attempts = 1
    row.save()
    graph = Mock(spec=GraphClient)
    graph.list_plan_tasks.return_value = [{'id': 'task', 'planId': 'plan', 'bucketId': 'entry',
                                          'title': f'{ticket.number} · Synthetic'}]
    graph.get_task_details.return_value = {'description': f'Correlação C+ Service Desk: {row.correlation_id}'}
    process_pending_provisioning(graph_client=graph, provisioning_id=row.pk)
    row.refresh_from_db()
    assert row.state == 'LINKED' and not row.graph_write_inflight
    graph.create_task.assert_not_called()
    archive_ticket(actor=admin, ticket_id=ticket.pk)


def test_definite_retry_rejection_does_not_erase_earlier_uncertainty(scenario):
    _, ticket, row = scenario
    Ticket.objects.filter(pk=ticket.pk).update(planner_task_id='task')
    row.description_write_inflight = True
    row.save()
    graph = PausedGraph(ticket, 'none')
    graph.update_task_details = lambda *args, **kwargs: (_ for _ in ()).throw(PlannerError('FORBIDDEN', 'Synthetic', status=403))
    process_pending_provisioning(graph_client=graph, provisioning_id=row.pk)
    row.refresh_from_db()
    assert row.description_write_inflight


def test_attachment_uncertainty_remains_retryable_after_attempt_limit(scenario, publication, graph):
    from apps.planner_integration.attachments import process_publications

    publication.attempts = 7
    publication.save()
    graph.attach_reference.side_effect = PlannerError('GRAPH_UNAVAILABLE', 'Synthetic')
    process_publications(graph_client=graph)
    publication.refresh_from_db()
    assert publication.graph_write_inflight and publication.state == 'UPLOADED'


def test_automatic_archive_preserves_uncertain_attachment(scenario, publication):
    from apps.planner_integration.services import _mark_deleted

    publication.graph_write_inflight = True
    publication.save()
    ticket = publication.attachment.ticket
    with pytest.raises(PlannerError) as error:
        _mark_deleted(actor=scenario[0], original=ticket)
    assert error.value.code == 'BUSY' and error.value.status == 409
    ticket.refresh_from_db()
    assert not ticket.archived_at


def test_automatic_archive_contention_uses_planner_error(scenario, settings):
    from apps.planner_integration.services import _mark_deleted
    from apps.planner_integration.ticket_locks import ticket_graph_lock

    admin, ticket, _ = scenario
    settings.PLANNER_TICKET_LOCK_TIMEOUT = .1
    entered, release = Event(), Event()

    def hold():
        with ticket_graph_lock(ticket.pk):
            entered.set()
            assert release.wait(10)

    with ThreadPoolExecutor(max_workers=1) as pool:
        holding = pool.submit(threaded, hold)
        try:
            assert entered.wait(10)
            with pytest.raises(PlannerError) as error:
                _mark_deleted(actor=admin, original=ticket)
            assert error.value.code == 'BUSY'
        finally:
            release.set()
        holding.result(timeout=10)
