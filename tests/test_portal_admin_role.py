import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.accounts.models import LocalAccount

pytestmark = pytest.mark.django_db


@pytest.fixture
def portal_admin(django_user_model):
    user = django_user_model.objects.create_user("portal.manager", password="synthetic-password")
    user.groups.add(Group.objects.get_or_create(name="ADMIN_PORTAL")[0])
    LocalAccount.objects.create(user=user, must_change_password=False)
    return user


def test_group_grants_admin_and_integrations_without_staff_or_superuser(client, portal_admin):
    client.force_login(portal_admin)
    assert client.get("/integracoes/").status_code == 200
    assert client.get("/admin/").status_code == 200
    assert client.get("/admin/auth/user/").status_code == 403
    html = client.get("/").content.decode()
    assert 'href="/integracoes/"' in html and 'Administração de usuários' not in html
    portal_admin.refresh_from_db()
    assert not portal_admin.is_staff and not portal_admin.is_superuser


@pytest.mark.parametrize("role", ["COLABORADOR", "TECNICO_TI", "SUPERVISOR_TI"])
def test_other_roles_remain_denied(client, django_user_model, role):
    user = django_user_model.objects.create_user("employee")
    user.groups.add(Group.objects.get_or_create(name=role)[0])
    client.force_login(user)
    for path in ("/admin/", "/admin/auth/user/", "/integracoes/"):
        assert client.get(path).status_code == 403


def test_revoke_role_removes_access_on_next_request(client, portal_admin):
    client.force_login(portal_admin)
    assert client.get("/integracoes/").status_code == 200
    portal_admin.groups.clear()
    assert client.get("/integracoes/").status_code == 403
    assert client.get("/admin/").status_code == 403


def test_group_admin_cannot_edit_privileged_accounts_or_grant_privileges(client, portal_admin, django_user_model):
    client.force_login(portal_admin)
    superuser = django_user_model.objects.create_superuser("root", "root@example.test", "unchanged-password")
    password_before = superuser.password
    assert client.post(f"/admin/auth/user/{superuser.pk}/change/", {"is_active": ""}).status_code == 403
    assert client.post(f"/admin/auth/user/{superuser.pk}/password/", {}).status_code == 403
    assert client.post(f"/admin/auth/user/{portal_admin.pk}/change/", {"is_superuser": "on"}).status_code == 403
    employee = django_user_model.objects.create_user("employee", password="keep-password")
    before = employee.password
    html = client.get(f"/admin/auth/user/{employee.pk}/change/").content.decode()
    for field in ("is_superuser", "is_staff", "groups", "user_permissions"):
        assert f'name="{field}"' not in html
    response = client.post(f"/admin/auth/user/{employee.pk}/change/", {
        "username": "employee", "first_name": "Employee", "last_name": "Example",
        "email": "employee@example.test", "is_active": "on", "_save": "Save",
        "is_superuser": "on", "is_staff": "on", "groups": [portal_admin.groups.first().pk],
    })
    assert response.status_code == 403
    employee.refresh_from_db()
    superuser.refresh_from_db()
    assert employee.first_name == "" and employee.password == before
    assert not employee.is_staff and not employee.is_superuser and not employee.groups.exists()
    assert superuser.password == password_before and superuser.is_active


def test_portal_admin_keeps_first_access_gate_and_csrf(client, portal_admin):
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(portal_admin)
    assert strict.post("/integracoes/microsoft/mapeamento/", {}).status_code == 403
    LocalAccount.objects.filter(user=portal_admin).update(must_change_password=True)
    client.force_login(portal_admin)
    assert client.get("/integracoes/").url == "/conta/senha/"
    assert client.get("/admin/").url == "/conta/senha/"


def test_oauth_eligibility_accepts_group_but_still_requires_flags(portal_admin, settings):
    from django.test import RequestFactory

    from apps.planner_integration.views import _oauth_available

    request = RequestFactory().post("/integracoes/microsoft/conectar/")
    request.user = portal_admin
    settings.MICROSOFT_GRAPH_APPROVED = False
    settings.GRAPH_DELEGATED_OAUTH_ENABLED = False
    assert not _oauth_available(request)
    settings.MICROSOFT_GRAPH_APPROVED = True
    settings.GRAPH_DELEGATED_OAUTH_ENABLED = True
    assert _oauth_available(request)


def test_group_grants_read_only_access_to_other_tickets(client, portal_admin, django_user_model):
    from apps.tickets.models import Category, Ticket
    from apps.tickets.permissions import visible_tickets

    owner = django_user_model.objects.create_user("ticket.owner")
    ticket = Ticket.objects.create(number="PRIVATE-TEST", requester=owner, title="Private",
                                   description="Private", category=Category.objects.create(name="Private"))
    assert visible_tickets(portal_admin, Ticket.objects.all()).filter(pk=ticket.pk).exists()
    client.force_login(portal_admin)
    assert client.get(f"/chamados/{ticket.pk}/").status_code == 200
    assert client.post(f"/chamados/{ticket.pk}/status/", {}).status_code == 404
