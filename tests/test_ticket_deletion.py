import pytest
from django.contrib.auth.models import Group
from django.core.cache import cache

from apps.accounts.models import LocalAccount
from apps.planner_integration.models import PlannerTaskProvisioning
from apps.tickets.models import Category, Ticket

pytestmark = pytest.mark.django_db
PASSWORD = 'Synthetic!Admin-4892'


@pytest.fixture
def deletion_setup(client, django_user_model, settings, tmp_path):
    settings.AUTHENTICATION_BACKENDS = ['apps.accounts.backends.LocalBackend']
    settings.LOCAL_AUTH_ENABLED = True
    settings.PRIVATE_ATTACHMENT_ROOT = tmp_path
    cache.clear()
    admin = django_user_model.objects.create_user('other.admin', password=PASSWORD)
    admin.groups.add(Group.objects.get_or_create(name='ADMIN_PORTAL')[0])
    LocalAccount.objects.create(user=admin, must_change_password=False)
    owner = django_user_model.objects.create_user('owner')
    ticket = Ticket.objects.create(number='SYNTHETIC-001', requester=owner,
                                   category=Category.objects.create(name='Synthetic'),
                                   title='Synthetic', description='Synthetic')
    PlannerTaskProvisioning.objects.create(ticket=ticket)
    client.force_login(admin)
    return admin, owner, ticket


def url(ticket, action):
    return f'/chamados/{ticket.pk}/{action}/'


def confirmations(client, ticket, **changes):
    response = client.get(url(ticket, 'excluir-permanentemente'))
    data = dict(number=ticket.number, irreversible='on', password=PASSWORD,
                confirmation_token=response.context['confirmation_token'])
    data.update(changes)
    return data


def test_archive_restore(client, deletion_setup):
    _, _, ticket = deletion_setup
    assert client.get(url(ticket, 'arquivar')).status_code == 405
    assert client.post(url(ticket, 'arquivar')).status_code == 302
    ticket.refresh_from_db()
    assert ticket.archived_at
    assert ticket.planner_provisioning.state == 'CANCELLED'
    assert client.get(f'/chamados/{ticket.pk}/').status_code == 404
    assert ticket.number in client.get('/chamados/arquivados/').content.decode()
    assert client.post(url(ticket, 'restaurar')).status_code == 302
    ticket.refresh_from_db()
    assert ticket.archived_at is None
    assert client.get(f'/chamados/{ticket.pk}/').status_code == 200


@pytest.mark.parametrize('action', ['arquivar', 'restaurar', 'excluir-permanentemente'])
def test_owner_cannot_manage(client, deletion_setup, action):
    _, owner, ticket = deletion_setup
    client.force_login(owner)
    assert client.post(url(ticket, action), {}).status_code == 403
    assert client.get('/chamados/arquivados/').status_code == 403


@pytest.mark.parametrize('change', [dict(number='SYNTHETIC-001 '), dict(irreversible=''),
                                 dict(password='wrong'), dict(confirmation_token='forged')])
def test_invalid_confirmation_preserves_ticket(client, deletion_setup, change):
    _, _, ticket = deletion_setup
    client.post(url(ticket, 'arquivar'))
    data = confirmations(client, ticket, **change)
    assert client.post(url(ticket, 'excluir-permanentemente'), data).status_code == 200
    assert Ticket.objects.filter(pk=ticket.pk).exists()


def test_delete_requires_archived_and_opened_screen(client, deletion_setup):
    _, _, ticket = deletion_setup
    assert client.get(url(ticket, 'excluir-permanentemente')).status_code == 404
    client.post(url(ticket, 'arquivar'))
    assert client.post(url(ticket, 'excluir-permanentemente'), dict(number=ticket.number,
                       irreversible='on', password=PASSWORD)).status_code == 200
    assert Ticket.objects.filter(pk=ticket.pk).exists()


def test_permanent_delete_audit(client, deletion_setup):
    from apps.tickets.models import TicketDeletionAudit

    admin, _, ticket = deletion_setup
    client.post(url(ticket, 'arquivar'))
    response = client.post(url(ticket, 'excluir-permanentemente'), confirmations(client, ticket))
    assert response.status_code == 302
    assert not Ticket.objects.filter(pk=ticket.pk).exists()
    audit = TicketDeletionAudit.objects.get(ticket_id=ticket.pk, action='PERMANENT_DELETE')
    assert audit.actor == admin and audit.number == ticket.number and audit.created_at
    assert PASSWORD not in str(audit.details)


def test_delete_dependencies_and_files(client, deletion_setup, django_capture_on_commit_callbacks):
    from django.core.files.base import ContentFile

    from apps.notifications.models import NotificationOutbox
    from apps.planner_integration.models import AttachmentPublication
    from apps.tickets.models import (
        Attachment,
        PrivateFileDeletion,
        TicketAccess,
        TicketComment,
        TicketEvent,
    )
    from apps.tickets.uploads import private_storage

    admin, owner, ticket = deletion_setup
    event = TicketEvent.objects.create(ticket=ticket, actor=owner, event_type='SYNTHETIC', summary='Synthetic')
    NotificationOutbox.objects.create(event=event, idempotency_key='synthetic', recipient='owner@example.test', subject='Synthetic', body_text='Synthetic')
    TicketAccess.objects.create(ticket=ticket, user=admin)
    TicketComment.objects.create(ticket=ticket, author=owner, body='Synthetic')
    storage = private_storage()
    key = storage.save(f'{ticket.pk}/synthetic.pdf', ContentFile(b'Synthetic file'))
    attachment = Attachment.objects.create(ticket=ticket, uploader=owner, storage_key=key,
        original_name='synthetic.pdf', mime_type='application/pdf', size=14, sha256='a' * 64)
    AttachmentPublication.objects.create(attachment=attachment, state='UPLOADED', remote_item_id='remote-synthetic', drive_id='drive-synthetic')
    ticket.planner_task_id = 'task-synthetic'
    ticket.save()
    client.post(url(ticket, 'arquivar'))
    assert NotificationOutbox.objects.get().state == 'FAILED'
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(url(ticket, 'excluir-permanentemente'), confirmations(client, ticket)).status_code == 302
    assert not storage.exists(key)
    assert PrivateFileDeletion.objects.get().completed_at
    for model in [Attachment, AttachmentPublication, TicketEvent, TicketAccess, TicketComment, NotificationOutbox, PlannerTaskProvisioning]:
        assert not model.objects.exists()


def test_file_cleanup_failure_is_retriable(deletion_setup, monkeypatch):
    from apps.tickets.lifecycle import process_file_deletions
    from apps.tickets.models import PrivateFileDeletion, TicketDeletionAudit

    admin, _, ticket = deletion_setup
    audit = TicketDeletionAudit.objects.create(ticket_id=ticket.pk, number=ticket.number, actor=admin, action='PERMANENT_DELETE')
    row = PrivateFileDeletion.objects.create(audit=audit, storage_key='synthetic/missing.pdf')
    with monkeypatch.context() as scoped:
        scoped.setattr('django.core.files.storage.FileSystemStorage.delete', lambda *a: (_ for _ in ()).throw(OSError('synthetic failure')))
        process_file_deletions()
    row.refresh_from_db()
    assert row.completed_at is None and row.last_error_code == 'FILE_DELETE_FAILED'
    process_file_deletions()
    row.refresh_from_db()
    assert row.completed_at and row.attempts == 2


def test_stale_confirmation_and_csrf(client, deletion_setup):
    from django.test import Client

    admin, _, ticket = deletion_setup
    client.post(url(ticket, 'arquivar'))
    data = confirmations(client, ticket)
    client.post(url(ticket, 'restaurar'))
    client.post(url(ticket, 'arquivar'))
    assert client.post(url(ticket, 'excluir-permanentemente'), data).status_code == 200
    assert Ticket.objects.filter(pk=ticket.pk).exists()
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(admin)
    for action in ['arquivar', 'restaurar', 'excluir-permanentemente']:
        assert strict.post(url(ticket, action), data).status_code == 403


def test_restoring_planner_deleted_never_recreates_task(client, deletion_setup):
    from django.utils import timezone

    from apps.planner_integration.services import process_pending_provisioning

    _, _, ticket = deletion_setup
    ticket.archived_at = ticket.planner_deleted_at = timezone.now()
    ticket.archive_reason = 'PLANNER_DELETED'
    ticket.save()
    client.post(url(ticket, 'restaurar'))
    assert client.get(f'/chamados/{ticket.pk}/').status_code == 200
    class ForbiddenClient:
        def create_task(self, **kwargs):
            pytest.fail('No external creation allowed')
    assert process_pending_provisioning(graph_client=ForbiddenClient()) == 0


def test_no_batch_or_main_list_permanent_link(client, deletion_setup):
    _, _, ticket = deletion_setup
    assert 'excluir-permanentemente' not in client.get('/chamados/').content.decode()
    assert client.post('/chamados/excluir-permanentemente/', {'ids': [str(ticket.pk)]}).status_code == 404


def test_rate_limit(client, deletion_setup):
    _, _, ticket = deletion_setup
    client.post(url(ticket, 'arquivar'))
    data = confirmations(client, ticket, password='incorrect')
    for _ in range(5):
        assert client.post(url(ticket, 'excluir-permanentemente'), data).status_code == 200
    data['password'] = PASSWORD
    response = client.post(url(ticket, 'excluir-permanentemente'), data)
    assert response.status_code == 200 and 'Limite de tentativas' in response.content.decode()
    assert Ticket.objects.filter(pk=ticket.pk).exists()


def test_revoked_admin_and_expired_confirmation(client, deletion_setup):
    admin, _, ticket = deletion_setup
    client.post(url(ticket, 'arquivar'))
    data = confirmations(client, ticket)
    session = client.session
    session[f'ticket_delete:{ticket.pk}']['expires'] = 0
    session.save()
    assert client.post(url(ticket, 'excluir-permanentemente'), data).status_code == 200
    admin.groups.clear()
    assert client.post(url(ticket, 'excluir-permanentemente'), data).status_code == 403
    assert Ticket.objects.filter(pk=ticket.pk).exists()


def test_archived_queues_cannot_call_external_providers(client, deletion_setup, settings):
    from unittest.mock import Mock

    from apps.notifications.models import NotificationOutbox
    from apps.notifications.services import process_pending
    from apps.planner_integration.attachments import process_publications
    from apps.planner_integration.models import AttachmentPublication
    from apps.planner_integration.services import process_pending_provisioning
    from apps.tickets.models import Attachment

    _, owner, ticket = deletion_setup
    ticket.planner_task_id = 'synthetic-task'
    ticket.save()
    attachment = Attachment.objects.create(ticket=ticket, uploader=owner, storage_key='synthetic.pdf',
        original_name='synthetic.pdf', mime_type='application/pdf', size=1, sha256='a' * 64)
    AttachmentPublication.objects.create(attachment=attachment)
    NotificationOutbox.objects.create(ticket=ticket, idempotency_key='synthetic-notice', recipient='owner@example.test', subject='Synthetic', body_text='Synthetic')
    client.post(url(ticket, 'arquivar'))
    for flag in ['MICROSOFT_GRAPH_APPROVED', 'PLANNER_ENABLED', 'PLANNER_ATTACHMENTS_ENABLED', 'GRAPH_ATTACHMENTS_STORAGE_APPROVED']:
        setattr(settings, flag, True)
    settings.GRAPH_AUTH_STRATEGY = 'delegated'
    settings.GRAPH_ATTACHMENTS_DRIVE_ID = 'synthetic-drive'
    settings.GRAPH_ATTACHMENTS_FOLDER_ID = 'synthetic-folder'
    settings.GRAPH_ATTACHMENTS_HOST = 'synthetic.example.test'
    graph, provider = Mock(), Mock()
    assert process_pending_provisioning(graph_client=graph) == 0
    assert process_publications(graph_client=graph) == 0
    assert process_pending(provider=provider) == 0
    assert not graph.mock_calls and not provider.mock_calls


@pytest.mark.django_db(transaction=True)
def test_inflight_planner_work_finishes_before_archive(deletion_setup, settings):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event

    from django.db import close_old_connections, connection

    from apps.planner_integration.services import process_pending_provisioning
    from apps.tickets.lifecycle import archive_ticket

    if connection.vendor != 'postgresql':
        pytest.skip('Row-lock concurrency requires disposable PostgreSQL')
    admin, _, ticket = deletion_setup
    settings.PLANNER_PLAN_ID = 'synthetic-plan'
    settings.PLANNER_INTAKE_BUCKET_ID = 'synthetic-bucket'
    entered, release = Event(), Event()

    class SyntheticGraph:
        def create_task(self, **kwargs):
            entered.set()
            assert release.wait(10)
            return {'id': 'synthetic-task', 'planId': 'synthetic-plan', 'bucketId': 'synthetic-bucket'}

    def provision():
        close_old_connections()
        try:
            return process_pending_provisioning(graph_client=SyntheticGraph(), limit=1)
        finally:
            close_old_connections()

    def archive():
        close_old_connections()
        try:
            archive_ticket(actor=admin, ticket_id=ticket.pk)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        worker = pool.submit(provision)
        try:
            assert entered.wait(10)
            pending_archive = pool.submit(archive)
            with pytest.raises(TimeoutError):
                pending_archive.result(timeout=0.2)
        finally:
            release.set()
        assert worker.result(timeout=10) == 1
        pending_archive.result(timeout=10)
    ticket.refresh_from_db()
    assert ticket.archived_at and ticket.planner_provisioning.state == 'CANCELLED'
    assert process_pending_provisioning(graph_client=SyntheticGraph(), limit=1) == 0
