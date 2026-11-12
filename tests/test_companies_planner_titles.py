from unittest.mock import Mock

import pytest
from django.contrib.auth.models import Group

from apps.custom_forms.models import FormDefinition, FormSubmission
from apps.planner_integration.services import _card_title, process_pending_provisioning
from apps.sectors.models import Company
from apps.tickets.services import create_ticket

pytestmark = pytest.mark.django_db


def test_dynamic_title_uses_frozen_form_name(django_user_model):
    ticket = create_ticket(actor=django_user_model.objects.create_user('title-owner'),
                           title='Assunto diferente', description='Dados', priority='NORMAL')
    definition = FormDefinition.objects.create(title='Nome atual')
    FormSubmission.objects.create(ticket=ticket, definition=definition,
        schema_snapshot={'title': 'Desligamento de Colaborador', 'fields': []}, answers={})
    assert _card_title(ticket) == 'Desligamento de Colaborador'


def test_company_persists_snapshot_and_rejects_inactive(django_user_model):
    from django.core.exceptions import ValidationError

    user = django_user_model.objects.create_user('company-owner')
    company = Company.objects.create(name='Empresa somente de teste')
    ticket = create_ticket(actor=user, company=company, title='Falha', description='Dados', priority='NORMAL')
    company.name = 'Nome alterado'
    company.is_active = False
    company.save()
    ticket.refresh_from_db()
    assert ticket.company_id == company.pk
    assert ticket.company_name_snapshot == 'Empresa somente de teste'
    with pytest.raises(ValidationError):
        create_ticket(actor=user, company=company, title='Falha', description='Dados', priority='NORMAL')


def test_soft_delete_requires_group_and_confirmation(client, django_user_model):
    owner = django_user_model.objects.create_user('delete-owner')
    ticket = create_ticket(actor=owner, title='Falha', description='Dados', priority='NORMAL')
    path = f'/chamados/{ticket.pk}/excluir/'
    client.force_login(owner)
    assert client.post(path, {'confirm': 'on'}).status_code == 403
    admin = django_user_model.objects.create_user('delete-admin')
    admin.groups.add(Group.objects.get_or_create(name='ADMIN_PORTAL')[0])
    client.force_login(admin)
    assert client.post(path).status_code == 200
    ticket.refresh_from_db()
    assert ticket.archived_at is None

    assert client.post(path, {'confirm': 'on'}).status_code == 302
    ticket.refresh_from_db()
    assert ticket.archived_at is not None
    graph = Mock()
    assert process_pending_provisioning(graph_client=graph) == 0
    graph.create_task.assert_not_called()
    graph.delete_task.assert_not_called()
    assert client.get(f'/chamados/{ticket.pk}/').status_code == 404
    assert client.post(f'/chamados/{ticket.pk}/restaurar/').status_code == 302
    ticket.refresh_from_db()
    assert ticket.archived_at is None


def test_company_crud_audit_conflicts_and_protected_delete(client, django_user_model):
    from apps.accounts.models import AccountAudit

    admin = django_user_model.objects.create_user('company-admin')
    admin.groups.add(Group.objects.get_or_create(name='ADMIN_PORTAL')[0])
    client.force_login(admin)
    root = '/administracao/empresas/'
    assert client.get(root).status_code == 200
    assert not Company.objects.exists()
    assert client.post(root + 'novo/', {'name': 'Empresa teste', 'is_active': 'on', 'display_order': 0}).status_code == 302
    company = Company.objects.get()
    payload = {'name': 'Empresa renomeada', 'display_order': 1, 'revision': company.revision}
    assert client.post(f'{root}{company.pk}/editar/', payload).status_code == 302
    assert client.post(f'{root}{company.pk}/editar/', payload).status_code == 409
    company.refresh_from_db()
    assert not company.is_active
    payload.update(revision=company.revision, is_active='on')
    assert client.post(f'{root}{company.pk}/editar/', payload).status_code == 302
    company.refresh_from_db()
    assert company.is_active
    assert client.post(root + 'novo/', {'name': ' EMPRESA RENOMEADA ', 'display_order': 0}).status_code == 200
    ticket = create_ticket(actor=admin, company=company, title='Teste', description='Dados', priority='NORMAL')
    assert client.post(f'{root}{company.pk}/excluir/', {'confirm': 'on', 'revision': company.revision}).status_code == 409
    ticket.refresh_from_db()
    assert ticket.company_name_snapshot == 'Empresa renomeada'
    unused = Company.objects.create(name='Empresa descartável teste')
    assert client.get(f'{root}{unused.pk}/excluir/').status_code == 200
    assert client.post(f'{root}{unused.pk}/excluir/', {'revision': unused.revision}).status_code == 200
    assert client.post(f'{root}{unused.pk}/excluir/', {'confirm': 'on', 'revision': unused.revision}).status_code == 302
    assert set(AccountAudit.objects.values_list('action', flat=True)) >= {'COMPANY_CREATED', 'COMPANY_UPDATED', 'COMPANY_DELETED'}


@pytest.mark.parametrize('role', ['COLABORADOR', 'TECNICO_TI', 'SUPERVISOR_TI'])
def test_company_crud_rejects_other_roles(client, django_user_model, role):
    user = django_user_model.objects.create_user('forbidden-company', is_staff=True)
    user.groups.add(Group.objects.get_or_create(name=role)[0])
    company = Company.objects.create(name='Teste restrito')
    client.force_login(user)
    for suffix in ('', 'novo/', f'{company.pk}/editar/', f'{company.pk}/excluir/'):
        assert client.get('/administracao/empresas/' + suffix).status_code == 403
        assert client.post('/administracao/empresas/' + suffix, {}).status_code == 403


def test_company_step_then_shared_departments_then_forms(client, django_user_model):
    from apps.sectors.models import Sector

    client.force_login(django_user_model.objects.create_user('steps'))
    assert 'Nenhuma empresa ativa' in client.get('/chamados/novo/').content.decode()
    companies = [Company.objects.create(name=f'Empresa teste {i}') for i in range(3)]
    sector = Sector.objects.create(name='Departamento compartilhado teste')
    for company in companies:
        page = client.get('/chamados/novo/', {'company': company.pk})
        assert sector.name in page.content.decode()
        assert 'request-cards' not in page.content.decode()
        page = client.get('/chamados/novo/', {'company': company.pk, 'sector': sector.pk})
        assert page.context['cards']
        assert f'company={company.pk}&amp;sector={sector.pk}' in page.content.decode()
    assert Sector.objects.count() == 1
    assert not Group.objects.exists()


def test_company_required_in_both_forms_and_current_at_submission(intake_data):
    from apps.custom_forms.forms import RequestForm
    from apps.tickets.forms import TicketForm

    for company in (None, 999999, intake_data['company']):
        if company == intake_data['company']:
            Company.objects.filter(pk=company).update(is_active=False)
        payload = {**intake_data, 'company': company, 'title': 'Teste', 'description': 'Dados', 'priority': 'NORMAL', 'form_version': 1}
        for form in (TicketForm(payload), RequestForm({'version': 1, 'fields': []}, payload)):
            assert not form.is_valid()
            assert 'company' in form.errors


def test_reconcile_equal_titles_uses_correlation_and_never_reposts(settings, django_user_model):
    from django.utils import timezone

    from apps.planner_integration.services import _card_description

    settings.PLANNER_PLAN_ID = 'plan'
    owner = django_user_model.objects.create_user('same-title')
    tickets = [create_ticket(actor=owner, title='Mesmo título', description='Dados', priority='NORMAL') for _ in range(2)]
    graph = Mock()
    graph.list_plan_tasks.return_value = [{'id': str(i), 'title': 'Mesmo título', 'planId': 'plan', 'bucketId': 'entry'} for i in range(2)]
    descriptions = {str(i): {'description': _card_description(t, t.planner_provisioning.correlation_id)} for i, t in enumerate(tickets)}
    graph.get_task_details.side_effect = descriptions.__getitem__
    for ticket in tickets:
        row = ticket.planner_provisioning
        row.state = 'RECONCILIATION'
        row.available_at = timezone.now()
        row.save()
    assert process_pending_provisioning(graph_client=graph) == 2
    assert [type(t).objects.get(pk=t.pk).planner_task_id for t in tickets] == ['0', '1']
    graph.create_task.assert_not_called()
    assert process_pending_provisioning(graph_client=graph) == 0


def test_uncertain_task_without_description_does_not_match_equal_title(settings, django_user_model):
    settings.PLANNER_PLAN_ID = 'plan'
    ticket = create_ticket(actor=django_user_model.objects.create_user('uncertain'), title='Igual', description='Dados', priority='NORMAL')
    row = ticket.planner_provisioning
    row.state = 'RECONCILIATION'
    row.save()
    graph = Mock()
    graph.list_plan_tasks.return_value = [{'id': 'unknown', 'title': 'Igual'}]
    graph.get_task_details.return_value = {'description': ''}
    process_pending_provisioning(graph_client=graph)
    ticket.refresh_from_db()
    row.refresh_from_db()
    assert not ticket.planner_task_id
    assert row.state == 'RECONCILIATION'
    graph.create_task.assert_not_called()


def test_planner_description_and_existing_link_preserved(settings, django_user_model, intake_data):
    from apps.planner_integration.services import _card_description
    from apps.sectors.models import Sector

    settings.PLANNER_PLAN_ID = 'plan'
    owner = django_user_model.objects.create_user('linked-owner')
    ticket = create_ticket(actor=owner, title='Assunto', description='Dados', priority='NORMAL',
        company=Company.objects.get(pk=intake_data['company']), sector=Sector.objects.get(pk=intake_data['sector']),
        service_location=intake_data['service_location'])
    text = _card_description(ticket, ticket.planner_provisioning.correlation_id)
    assert f'Protocolo: {ticket.number}' in text
    assert ticket.company_name_snapshot in text
    assert ticket.intake_context.sector_name_snapshot in text
    assert owner.username in text
    ticket.planner_task_id = 'existing-link'
    ticket.save()
    graph = Mock()
    process_pending_provisioning(graph_client=graph)
    graph.create_task.assert_not_called()
    graph.list_plan_tasks.assert_not_called()
    assert graph.update_task_details.call_args.args == ('existing-link',)
    ticket.refresh_from_db()
    assert ticket.planner_task_id == 'existing-link'


def test_new_dynamic_tasks_with_same_name_are_created_separately(settings, django_user_model):
    settings.PLANNER_PLAN_ID = 'plan'
    owner = django_user_model.objects.create_user('dynamic-duplicates')
    definition = FormDefinition.objects.create(title='Nome do formulário')
    tickets = []
    for _ in range(2):
        ticket = create_ticket(actor=owner, title='Assunto', description='Dados', priority='NORMAL')
        FormSubmission.objects.create(ticket=ticket, definition=definition,
            schema_snapshot={'title': 'Nome do formulário', 'fields': []}, answers={})
        tickets.append(ticket)
    graph = Mock()
    graph.list_plan_tasks.return_value = [{'id': 'unrelated', 'title': 'Nome do formulário'}]
    graph.create_task.side_effect = [{'id': 'task-a', 'planId': 'plan'}, {'id': 'task-b', 'planId': 'plan'}]
    assert process_pending_provisioning(graph_client=graph) == 2
    assert [call.kwargs['title'] for call in graph.create_task.call_args_list] == ['Nome do formulário'] * 2
    assert len({type(t).objects.get(pk=t.pk).planner_task_id for t in tickets}) == 2
    graph.get_task_details.assert_not_called()


def test_soft_delete_enforces_csrf_group_and_service_authorization(client, django_user_model):
    from django.core.exceptions import PermissionDenied
    from django.test import Client

    from apps.tickets.lifecycle import archive_ticket

    root = django_user_model.objects.create_superuser('ungrouped-root', password='test')
    ticket = create_ticket(actor=root, title='Restrito', description='Dados', priority='NORMAL')
    client.force_login(root)
    for action in ('excluir', 'arquivar', 'restaurar', 'excluir-permanentemente'):
        assert client.post(f'/chamados/{ticket.pk}/{action}/', {'confirm': 'on'}).status_code == 403
    with pytest.raises(PermissionDenied):
        archive_ticket(actor=root, ticket_id=ticket.pk, soft_delete=True)
    root.groups.add(Group.objects.get_or_create(name='ADMIN_PORTAL')[0])
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(root)
    assert strict.post(f'/chamados/{ticket.pk}/excluir/', {'confirm': 'on'}).status_code == 403
    assert strict.post('/administracao/empresas/novo/', {'name': 'Forjado', 'display_order': 0}).status_code == 403


def test_archive_during_remote_creation_is_rejected_until_finished(settings, django_user_model):
    from django.core.exceptions import ValidationError

    from apps.tickets.lifecycle import archive_ticket
    from apps.tickets.models import TicketDeletionAudit

    settings.PLANNER_PLAN_ID = 'plan'
    admin = django_user_model.objects.create_user('inflight-admin')
    admin.groups.add(Group.objects.get_or_create(name='ADMIN_PORTAL')[0])
    ticket = create_ticket(actor=admin, title='Em envio', description='Dados', priority='NORMAL')
    graph = Mock()
    graph.list_plan_tasks.return_value = []

    def create(**kwargs):
        with pytest.raises(ValidationError, match='conferência'):
            archive_ticket(actor=admin, ticket_id=ticket.pk, soft_delete=True)
        return {'id': 'accepted-task', 'planId': 'plan'}

    graph.create_task.side_effect = create
    process_pending_provisioning(graph_client=graph)
    ticket.refresh_from_db()
    assert not ticket.archived_at and ticket.planner_task_id == 'accepted-task'
    assert ticket.planner_provisioning.state == 'LINKED'
    assert not TicketDeletionAudit.objects.filter(ticket_id=ticket.pk).exists()
    graph.update_task_details.assert_called_once()
    archive_ticket(actor=admin, ticket_id=ticket.pk, soft_delete=True)
    assert TicketDeletionAudit.objects.get(ticket_id=ticket.pk).action == 'SOFT_DELETE'
    graph.delete_task.assert_not_called()
    from apps.tickets.lifecycle import restore_ticket

    restore_ticket(actor=admin, ticket_id=ticket.pk)
    ticket.refresh_from_db()
    assert ticket.planner_provisioning.state == 'PENDING'
    process_pending_provisioning(graph_client=graph)
    assert graph.update_task_details.call_count == 2
    assert graph.create_task.call_count == 1


def test_company_deactivated_after_dynamic_validation_creates_nothing(django_user_model, intake_data):
    from django.core.exceptions import ValidationError

    from apps.custom_forms.forms import RequestForm
    from apps.custom_forms.services import submit_request
    from apps.tickets.models import Ticket

    definition = FormDefinition.objects.create(title='Teste dinâmico', status='PUBLISHED', published_version=1,
        published_snapshot={'title': 'Teste dinâmico', 'version': 1, 'fields': []})
    form = RequestForm(definition.published_snapshot, {**intake_data, 'title': 'Dados', 'priority': 'NORMAL', 'form_version': 1})
    assert form.is_valid(), form.errors
    Company.objects.filter(pk=intake_data['company']).update(is_active=False)
    with pytest.raises(ValidationError):
        submit_request(actor=django_user_model.objects.create_user('deactivated-company'),
                       form_id=definition.pk, cleaned=form.cleaned_data)
    assert not Ticket.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_migrations_preserve_existing_ticket_without_inventing_companies():
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    previous = [('sectors', '0001_initial'), ('tickets', '0007_ticket_next_planner_sync_at')]
    try:
        executor.migrate(previous)
        old = executor.loader.project_state(previous).apps
        owner = old.get_model('auth', 'User').objects.create(username='migration-owner')
        category = old.get_model('tickets', 'Category').objects.create(name='Legada')
        ticket = old.get_model('tickets', 'Ticket').objects.create(requester=owner, category=category,
            number='LEGACY-MIGRATION', title='Histórico', description='Preservar', planner_task_id='legacy-task')
        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        current = executor.loader.project_state(latest).apps
        saved = current.get_model('tickets', 'Ticket').objects.get(pk=ticket.pk)
        assert saved.company_id is None and saved.company_name_snapshot == ''
        assert saved.planner_task_id == 'legacy-task' and saved.description == 'Preservar'
        assert not current.get_model('sectors', 'Company').objects.exists()
    finally:
        MigrationExecutor(connection).migrate(latest)
