import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.accounts.models import AccountAudit, LocalAccount

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager(client, django_user_model):
    user = django_user_model.objects.create_user('willian.pedroso', password='Initial-Only-478!')
    user.groups.add(Group.objects.get_or_create(name='ADMIN_PORTAL')[0])
    LocalAccount.objects.create(user=user, must_change_password=False)
    client.force_login(user)
    return user


def payload(user, **changes):
    data = dict(username=user.username, first_name='Updated', last_name='Person',
                is_active='on', admin_portal='on' if user.groups.filter(name='ADMIN_PORTAL').exists() else '', _save='Save')
    data.update(changes)
    return data


@pytest.mark.parametrize('privilege', ['group', 'staff'])
def test_other_admin_denied_all_user_routes(client, django_user_model, privilege):
    user = django_user_model.objects.create_user('other', is_staff=privilege == 'staff')
    user.groups.add(Group.objects.get_or_create(name='ADMIN_PORTAL')[0])
    client.force_login(user)
    for path in ['/admin/auth/user/', '/admin/auth/user/add/', f'/admin/auth/user/{user.pk}/change/',
                 f'/admin/auth/user/{user.pk}/password/', f'/admin/auth/user/{user.pk}/history/', f'/admin/auth/user/{user.pk}/delete/']:
        assert client.get(path).status_code == 403
        assert client.post(path, {}).status_code == 403
    assert client.get('/integracoes/').status_code == 200


def test_edit_group_audit_and_no_escalation(client, manager, django_user_model):
    user = django_user_model.objects.create_user('employee', password='Keep-Secret-473!')
    other_group = Group.objects.create(name='COLABORADOR')
    user.groups.add(other_group)
    before = user.password
    response = client.post(f'/admin/auth/user/{user.pk}/change/', payload(user, username='employee.changed', admin_portal='on',
        is_staff='on', is_superuser='on', groups=[other_group.pk], user_permissions=[1], password='raw-secret'))
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.username == 'employee.changed' and user.first_name == 'Updated'
    assert user.password == before and not user.is_staff and not user.is_superuser
    assert set(user.groups.values_list('name', flat=True)) == {'COLABORADOR', 'ADMIN_PORTAL'}
    audit = AccountAudit.objects.get(action='USER_CHANGED', target=user)
    assert audit.actor == manager and audit.created_at
    assert audit.changes['username'] == {'before': 'employee', 'after': 'employee.changed'}
    assert 'password' not in audit.changes and 'raw-secret' not in str(audit.changes)
    assert client.post(f'/admin/auth/user/{user.pk}/change/', payload(user, admin_portal='', is_active='')).status_code == 302
    user.refresh_from_db()
    assert not user.is_active and not user.groups.filter(name='ADMIN_PORTAL').exists()


@pytest.mark.parametrize('changes', [dict(username='renamed'), dict(is_active=''), dict(admin_portal='')])
def test_protected_account_rejects_loss_of_access(client, manager, changes):
    response = client.post(f'/admin/auth/user/{manager.pk}/change/', payload(manager, **changes))
    assert response.status_code == 200 and response.context['adminform'].form.errors
    manager.refresh_from_db()
    assert manager.username == 'willian.pedroso' and manager.is_active
    assert manager.groups.filter(name='ADMIN_PORTAL').exists()


def test_duplicate_username_and_search(client, manager, django_user_model):
    other = django_user_model.objects.create_user('existing')
    response = client.post(f'/admin/auth/user/{other.pk}/change/', payload(other, username=manager.username.upper()))
    assert response.status_code == 200 and response.context['adminform'].form.errors
    assert client.get('/admin/auth/user/?q=existing').status_code == 200


def test_password_reset_requires_change_and_invalidates_sessions(client, manager, django_user_model):
    user = django_user_model.objects.create_user('employee', password='Old-Secret-478!')
    LocalAccount.objects.create(user=user, must_change_password=False)
    session = Client()
    session.force_login(user)
    url = f'/admin/auth/user/{user.pk}/password/'
    assert client.post(url, dict(password1='tiny', password2='tiny')).status_code == 200
    password = 'New!Synthetic-Lake-847'
    response = client.post(url, dict(password1=password, password2=password))
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.check_password(password) and user.password != password
    assert user.local_account.must_change_password
    assert not session.get('/').wsgi_request.user.is_authenticated
    session.force_login(user)
    assert session.get('/chamados/').url == '/conta/senha/'
    audit = AccountAudit.objects.get(action='ADMIN_PASSWORD_RESET', target=user)
    assert audit.actor == manager and password not in str(audit.changes)
    assert user.password not in client.get(f'/admin/auth/user/{user.pk}/change/').content.decode()


def test_csrf_and_no_add_delete(client, manager):
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(manager)
    assert strict.post(f'/admin/auth/user/{manager.pk}/change/', {}).status_code == 403
    assert client.get('/admin/auth/user/add/').status_code == 403
    assert client.post(f'/admin/auth/user/{manager.pk}/delete/', {}).status_code == 403


def test_cannot_disable_password_authentication(client, manager):
    response = client.post(f'/admin/auth/user/{manager.pk}/password/',
                           {'usable_password': 'false', 'unset-password': 'on'})
    manager.refresh_from_db()
    assert response.status_code == 200
    assert manager.has_usable_password()


def test_recovery_superuser(client, django_user_model):
    root = django_user_model.objects.create_superuser('recovery', 'root@example.test', 'Recovery-478!')
    client.force_login(root)
    assert client.get('/admin/auth/user/').status_code == 200
    protected = django_user_model.objects.create_user('willian.pedroso')
    assert client.post(f'/admin/auth/user/{protected.pk}/change/', payload(protected, is_active='', username='recovered')).status_code == 302
    protected.refresh_from_db()
    assert protected.username == 'recovered' and not protected.is_active


def test_manager_cannot_take_over_superuser(client, manager, django_user_model):
    root = django_user_model.objects.create_superuser('root', 'root@example.test', 'Secret-478!')
    before = root.password
    assert client.post(f'/admin/auth/user/{root.pk}/password/', dict(password1='Another-Secret-478!', password2='Another-Secret-478!')).status_code == 403
    assert client.post(f'/admin/auth/user/{root.pk}/change/', payload(root)).status_code == 403
    root.refresh_from_db()
    assert root.password == before


def test_management_permission_does_not_grant_ticket_visibility(manager, django_user_model):
    from apps.tickets.models import Category, Ticket
    from apps.tickets.permissions import visible_tickets

    manager.groups.clear()
    owner = django_user_model.objects.create_user('private.owner')
    ticket = Ticket.objects.create(number='PRIVATE-SYNTHETIC', requester=owner, title='Private',
                                   description='Private', category=Category.objects.create(name='Private'))
    assert not visible_tickets(manager, Ticket.objects.all()).filter(pk=ticket.pk).exists()


def test_form_rejects_unauthorized_actor(django_user_model):
    from apps.accounts.admin_forms import ManagedUserForm

    user = django_user_model.objects.create_user('ordinary')
    form = ManagedUserForm(data=payload(user), instance=user, actor=user)
    assert not form.is_valid()
