from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group, Permission
from django.contrib.messages import get_messages
from django.utils import timezone

from apps.accounts.models import AccountAudit, LocalAccount
from apps.planner_integration.models import DEMANDAS_PLAN_ID, MicrosoftGraphConnection
from apps.tickets.models import Category, Ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager(client, django_user_model):
    user = django_user_model.objects.create_user('willian.pedroso')
    user.groups.add(Group.objects.get_or_create(name='ADMIN_PORTAL')[0])
    client.force_login(user)
    return user


def user_data(user, **changes):
    data = dict(username=user.username, first_name=user.first_name, last_name=user.last_name,
                is_active='on' if user.is_active else '',
                admin_portal='on' if user.groups.filter(name='ADMIN_PORTAL').exists() else '',
                _save='Salvar')
    data.update(changes)
    return data


@pytest.mark.parametrize('submit_action', ['_save', '_continue'])
def test_unchanged_save_has_no_audits_or_success_message(client, manager, django_user_model, submit_action):
    user = django_user_model.objects.create_user('unchanged', first_name='Mesmo')
    user.groups.add(Group.objects.create(name='Preservado'))
    user.user_permissions.add(Permission.objects.first())
    groups = set(user.groups.values_list('pk', flat=True))
    perms = set(user.user_permissions.values_list('pk', flat=True))
    url = f'/admin/auth/user/{user.pk}/change/'
    data = user_data(user)
    data.pop('_save')
    data[submit_action] = 'Salvar'
    response = client.post(url, data)
    assert response.status_code == 302
    assert response.url == url
    assert not AccountAudit.objects.exists()
    assert not LogEntry.objects.exists()
    assert not list(get_messages(response.wsgi_request))
    assert set(user.groups.values_list('pk', flat=True)) == groups
    assert set(user.user_permissions.values_list('pk', flat=True)) == perms


def test_role_only_change_is_audited(client, manager, django_user_model):
    user = django_user_model.objects.create_user('role.only')
    response = client.post(f'/admin/auth/user/{user.pk}/change/', user_data(user, admin_portal='on'))
    assert response.status_code == 302
    assert response.url == f'/admin/auth/user/{user.pk}/change/'
    messages = list(get_messages(response.wsgi_request))
    assert len(messages) == 1 and messages[0].tags == 'success'
    audit = AccountAudit.objects.get(target=user, action='USER_CHANGED')
    assert audit.changes['ADMIN_PORTAL'] == {'before': False, 'after': True}
    assert LogEntry.objects.filter(object_id=str(user.pk)).count() == 1


@pytest.mark.parametrize('submit_action', ['_save', '_continue'])
def test_create_user_with_generated_password_and_no_elevation(client, manager, django_user_model, submit_action):
    response = client.get('/admin/auth/user/add/')
    assert response.status_code == 200
    form = response.context['adminform'].form
    password = form.initial['temporary_password']
    assert len(password) >= 24
    data = dict(
        username='new.synthetic', first_name='Novo', last_name='Fictício', is_active='on',
        temporary_password=password, is_staff='on', is_superuser='on',
    )
    data[submit_action] = 'Salvar'
    response = client.post('/admin/auth/user/add/', data)
    user = django_user_model.objects.get(username='new.synthetic')
    assert response.status_code == 302
    assert response.url == f'/admin/auth/user/{user.pk}/change/'
    messages = list(get_messages(response.wsgi_request))
    assert len(messages) == 1 and messages[0].tags == 'success'
    assert AccountAudit.objects.filter(target=user, action='USER_CREATED').count() == 1
    assert user.check_password(password)
    assert user.local_account.must_change_password
    assert not user.is_staff and not user.is_superuser
    assert password not in str(list(AccountAudit.objects.values()))
    client.force_login(user)
    assert client.get('/chamados/').url == '/conta/senha/'


def test_create_rejects_duplicate_and_weak_password(client, manager, django_user_model):
    django_user_model.objects.create_user('existing')
    response = client.post('/admin/auth/user/add/', dict(
        username='EXISTING', temporary_password='123', is_active='on',
    ))
    assert response.status_code == 200
    assert {'username', 'temporary_password'} <= response.context['adminform'].form.errors.keys()
    assert not django_user_model.objects.filter(username='EXISTING').exists()


def test_confirmed_deletion_of_unused_user_and_protected_account(client, manager, django_user_model):
    user = django_user_model.objects.create_user('unused.synthetic')
    LocalAccount.objects.create(user=user)
    url = f'/admin/auth/user/{user.pk}/delete/'
    response = client.get(url)
    assert response.status_code == 200 and 'post' in response.content.decode()
    assert django_user_model.objects.filter(pk=user.pk).exists()
    assert client.post(url, {}).status_code == 403
    assert client.post(url, {'post': 'yes'}).status_code == 302
    assert not django_user_model.objects.filter(pk=user.pk).exists()
    assert AccountAudit.objects.get(action='USER_DELETED').changes['username'] == 'unused.synthetic'
    assert client.post(f'/admin/auth/user/{manager.pk}/delete/', {'post': 'yes'}).status_code == 403


@pytest.mark.parametrize('relation', ['audit', 'ticket', 'directory'])
def test_delete_preserves_all_history_relations(client, manager, django_user_model, relation):
    user = django_user_model.objects.create_user('linked.synthetic')
    if relation == 'audit':
        AccountAudit.objects.create(actor=manager, target=user, action='USER_CHANGED')
    elif relation == 'directory':
        import uuid

        from apps.accounts.models import UserProfile

        UserProfile.objects.create(user=user, object_guid=uuid.uuid4(), last_verified_at=timezone.now())
    else:
        Ticket.objects.create(number='LINKED', requester=user, title='Teste', description='Teste',
                              category=Category.objects.create(name='Interna'))
    response = client.post(f'/admin/auth/user/{user.pk}/delete/', {'post': 'yes'})
    assert response.status_code == 200
    assert django_user_model.objects.filter(pk=user.pk).exists()
    assert response.context['protected']


@pytest.mark.parametrize('admin', [False, True])
@pytest.mark.parametrize('filters', [{}, {'q': 'Alvo'}, {'priority': 'ALTA'},
                                    {'q': 'Alvo', 'priority': 'ALTA', 'status': 'RESOLVIDO'}])
def test_counts_match_filtered_visible_results(client, django_user_model, admin, filters):
    owner = django_user_model.objects.create_user('count.owner')
    other = django_user_model.objects.create_user('count.other')
    if admin:
        owner.groups.add(Group.objects.get_or_create(name='ADMIN_PORTAL')[0])
    category = Category.objects.create(name='Contagens')
    for i, (requester, title, priority, status, archived, deleted) in enumerate([
        (owner, 'Alvo A', 'ALTA', 'ABERTO', False, False),
        (owner, 'Alvo B', 'ALTA', 'FECHADO', False, False),
        (owner, 'Outro', 'NORMAL', 'EM_ATENDIMENTO', False, False),
        (other, 'Alvo privado', 'ALTA', 'RESOLVIDO', False, False),
        (owner, 'Alvo arquivado', 'ALTA', 'ABERTO', True, False),
        (owner, 'Alvo excluído', 'ALTA', 'ABERTO', False, True),
    ]):
        Ticket.objects.create(number=f'COUNT-{i}', requester=requester, title=title,
                              description='Fictício', category=category, priority=priority, status=status,
                              archived_at=timezone.now() if archived else None,
                              planner_deleted_at=timezone.now() if deleted else None)
    client.force_login(owner)
    response = client.get('/chamados/', filters)
    rows = list(response.context['page_obj'])
    expected_total = {0: 3 + admin, 1: 2 + admin, 2: 2 + admin, 3: 1 + admin}[len(filters)]
    assert len(rows) == expected_total
    assert sum(response.context['counts'].values()) == expected_total
    for key, count in response.context['counts'].items():
        assert count == sum(Ticket.portal_status_for(ticket.status) == key for ticket in rows)


def test_category_is_internal_and_client_cannot_override_it(client, django_user_model, intake_data):
    user = django_user_model.objects.create_user('category.synthetic')
    old = Category.objects.create(name='Homologação')
    client.force_login(user)
    assert b'name="category"' not in client.get('/chamados/novo/').content
    response = client.post('/chamados/novo/', dict(**intake_data, title='Solicitação', description='Sem categoria',
                                                priority='NORMAL', category=old.pk))
    assert response.status_code == 302
    ticket = Ticket.objects.get()
    assert ticket.category.name == 'Atendimento geral' and ticket.category.is_active
    assert 'Atendimento geral' not in client.get('/chamados/').content.decode()
    assert 'Atendimento geral' not in client.get(f'/chamados/{ticket.pk}/').content.decode()
    assert Category.objects.get(pk=old.pk).name == 'Homologação'
    assert ticket.planner_provisioning.state == 'PENDING'


def test_internal_category_is_not_reactivated_silently(client, django_user_model, intake_data):
    user = django_user_model.objects.create_user('category.inactive')
    Category.objects.create(name='Atendimento geral', is_active=False)
    client.force_login(user)
    response = client.post('/chamados/novo/', dict(**intake_data, title='Teste', description='Teste', priority='NORMAL'))
    assert response.status_code == 200 and not Ticket.objects.exists()


def test_integration_backend_blocks_despite_existing_connection(client, manager, settings, monkeypatch):
    settings.PLANNER_PLAN_ID = DEMANDAS_PLAN_ID
    settings.MICROSOFT_GRAPH_APPROVED = False
    settings.PLANNER_TEST_ENABLED = True
    MicrosoftGraphConnection.objects.create(
        user=manager, is_active=True, microsoft_user_id='synthetic',
        microsoft_user_principal_name='synthetic@example.test', tenant_id='synthetic',
        access_token_encrypted='never-decrypted', refresh_token_encrypted='never-decrypted',
        access_token_expires_at=timezone.now() + timedelta(hours=1),
    )
    graph = Mock()
    monkeypatch.setattr('apps.planner_integration.admin_panel.graph', graph)
    panel = client.get('/integracoes/')
    assert not panel.context['can_query_buckets'] and not panel.context['can_test_task']
    for path in ('buckets', 'teste'):
        client.post(f'/integracoes/microsoft/{path}/', {'confirm': 'CRIAR TAREFA DE TESTE'})
    graph.assert_not_called()


def test_oauth_endpoint_rejects_incomplete_configuration(client, manager, settings):
    settings.MICROSOFT_GRAPH_APPROVED = True
    settings.GRAPH_DELEGATED_OAUTH_ENABLED = True
    settings.GRAPH_TENANT_ID = 'synthetic'
    settings.GRAPH_CLIENT_ID = 'synthetic'
    settings.GRAPH_TOKEN_ENCRYPTION_KEY = ''
    settings.PORTAL_BASE_URL = 'http://localhost:8010'
    response = client.get('/integracoes/microsoft/conectar/')
    assert response.status_code == 503
    assert 'graph_delegated_oauth' not in client.session


def test_internal_home_and_shared_brand(client, manager):
    for path in ('/', '/login/', '/admin/', '/admin/auth/user/', '/admin/auth/user/add/'):
        response = client.get(path)
        if response.status_code == 200:
            assert b'brand/cmais-logo.svg' in response.content
    home = client.get('/')
    assert 'Abrir solicitação' in home.content.decode()
    assert 'Acompanhar meus chamados' in home.content.decode()
    assert b'institucional.avif' not in home.content
    client.logout()
    home = client.get('/')
    assert b'empresa.webp' not in home.content and b'corporate-banner' not in home.content
    assert '>Login ' in home.content.decode()


def test_admin_facets_and_edit_controls(client, manager, django_user_model):
    django_user_model.objects.create_user('inactive', is_active=False)
    response = client.get('/admin/auth/user/', {'_facets': '1', 'is_active__exact': '1'})
    assert response.status_code == 200
    assert response.context['cl'].result_count == 1
    assert response.context['cl'].add_facets
    for url in ('/admin/auth/user/add/', f'/admin/auth/user/{manager.pk}/change/'):
        form = client.get(url).content.decode()
        row = form.split('<div class="submit-row">', 1)[1].split('</div>', 1)[0]
        assert row.count('<input type="submit"') == 1
        assert 'value="Salvar"' in row and 'name="_save"' in row
        assert 'Sair sem salvar' in row and 'href="/admin/auth/user/"' in row
        assert 'name="_continue"' not in form and 'name="_addanother"' not in form
        assert 'deletelink' not in row


def test_saved_user_stays_on_edit_and_subsequent_unchanged_save_is_silent(client, manager, django_user_model):
    user = django_user_model.objects.create_user('save.synthetic', first_name='Antes')
    url = f'/admin/auth/user/{user.pk}/change/'
    response = client.post(url, user_data(user, first_name='Depois'), follow=True)
    assert response.status_code == 200 and response.redirect_chain == [(url, 302)]
    assert response.context['original'].pk == user.pk
    assert len(list(response.context['messages'])) == 1
    assert AccountAudit.objects.filter(target=user, action='USER_CHANGED').count() == 1
    assert LogEntry.objects.filter(object_id=str(user.pk)).count() == 1
    user.refresh_from_db()
    assert user.first_name == 'Depois'
    response = client.post(url, user_data(user), follow=True)
    assert response.redirect_chain == [(url, 302)]
    assert not list(response.context['messages'])
    assert AccountAudit.objects.filter(target=user, action='USER_CHANGED').count() == 1
    assert LogEntry.objects.filter(object_id=str(user.pk)).count() == 1


def test_unused_user_keeps_deletion_link_outside_save_buttons(client, manager, django_user_model):
    user = django_user_model.objects.create_user('delete.link.synthetic')
    response = client.get(f'/admin/auth/user/{user.pk}/change/')
    assert f'href="/admin/auth/user/{user.pk}/delete/"' in response.content.decode()


@pytest.mark.parametrize('strategy', ['client_credentials', 'delegated'])
@pytest.mark.parametrize('approved', [False, True])
def test_integration_capabilities_match_backend(client, manager, settings, monkeypatch, strategy, approved):
    from cryptography.fernet import Fernet

    settings.PLANNER_PLAN_ID = DEMANDAS_PLAN_ID
    settings.MICROSOFT_GRAPH_APPROVED = approved
    settings.GRAPH_AUTH_STRATEGY = strategy
    settings.GRAPH_DELEGATED_OAUTH_ENABLED = True
    settings.GRAPH_TENANT_ID = 'synthetic-tenant'
    settings.GRAPH_CLIENT_ID = 'synthetic-client'
    settings.GRAPH_CLIENT_SECRET = 'synthetic-secret'
    settings.GRAPH_TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.PORTAL_BASE_URL = 'https://synthetic.example.test'
    settings.PLANNER_TEST_ENABLED = True
    settings.PLANNER_INTAKE_BUCKET_ID = 'synthetic-entry'
    if strategy == 'delegated':
        MicrosoftGraphConnection.objects.create(
            user=manager, is_active=True, microsoft_user_id='synthetic',
            access_token_encrypted='synthetic', refresh_token_encrypted='synthetic',
            access_token_expires_at=timezone.now() - timedelta(minutes=1),
        )
    graph = Mock()
    graph.return_value.list_plan_buckets.return_value = []
    monkeypatch.setattr('apps.planner_integration.admin_panel.graph', graph)
    response = client.get('/integracoes/')
    graph.assert_not_called()
    assert response.context['can_query_buckets'] == approved
    assert response.context['can_test_task'] == approved
    assert response.context['can_connect'] == (approved and strategy == 'delegated')
    client.post('/integracoes/microsoft/buckets/')
    assert graph.called == approved


def test_capture_synthetic_ui(client, manager, django_user_model):
    import os
    from pathlib import Path

    directory = os.environ.get('PORTAL_UI_CAPTURE_DIR')
    if not directory:
        return
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'admin-jsi18n.js').write_bytes(client.get('/admin/jsi18n/').content)
    user = django_user_model.objects.create_user('edit.synthetic', first_name='Robson', last_name='Lemes')
    pages = {'admin-add': '/admin/auth/user/add/', 'admin-edit': f'/admin/auth/user/{user.pk}/change/',
             'admin-list': '/admin/auth/user/', 'admin-delete': f'/admin/auth/user/{user.pk}/delete/',
             'integrations': '/integracoes/', 'admin-home': '/'}
    for name, url in pages.items():
        response = client.get(url)
        assert response.status_code == 200
        (output / f'{name}.html').write_bytes(response.content)
    client.force_login(user)
    (output / 'employee-home.html').write_bytes(client.get('/').content)
    client.logout()
    (output / 'guest-home.html').write_bytes(client.get('/').content)
