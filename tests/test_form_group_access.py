import json
import uuid

import pytest
from django.contrib.auth.models import Group

from apps.custom_forms.models import FormDefinition
from apps.custom_forms.services import available_forms, publish_form
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def group_setup(django_user_model):
    groups = [Group.objects.create(name=name) for name in ("Acesso fictício A", "Acesso fictício B", "Acesso fictício C")]
    users = {name: django_user_model.objects.create_user(name, password="synthetic-password")
             for name in ("group-admin", "group-employee", "group-manager", "group-outsider")}
    users["group-admin"].groups.add(Group.objects.get_or_create(name="ADMIN_PORTAL")[0])
    users["group-manager"].groups.add(Group.objects.get_or_create(name="SUPERVISOR_TI")[0])
    users["group-employee"].groups.add(groups[0])
    users["group-manager"].groups.add(groups[1])
    users["group-outsider"].groups.add(groups[2])
    users["root"] = django_user_model.objects.create_superuser("group-root", password="synthetic-password")
    field = {"id": str(uuid.uuid4()), "type": "short_text", "label": "Pergunta fictícia", "required": True,
             "default": "", "options": [], "help_text": "", "placeholder": ""}
    form = FormDefinition.objects.create(title="Formulário multigrupo fictício", fields=[field],
        draft_audience=[groups[0].pk, groups[1].pk])
    publish_form(actor=users["group-admin"], form_id=form.pk, revision=form.revision)
    form.refresh_from_db()
    return users, groups, form


@pytest.mark.parametrize("username", ["group-admin", "root"])
def test_admin_can_open_and_submit_common_form_of_other_groups(client, group_setup, intake_data, username):
    users, _, definition = group_setup
    client.force_login(users[username])
    assert definition.pk in available_forms(users[username]).values_list("pk", flat=True)
    assert definition.title in client.get("/chamados/novo/", intake_data).content.decode()
    url = f"/chamados/novo/formulario/{definition.pk}/"
    assert client.get(url, intake_data).status_code == 200
    response = client.post(url, {**intake_data, "title": "Abertura administrativa fictícia", "priority": "NORMAL",
        "form_version": definition.published_version, f"cf_{definition.fields[0]['id']}": "Resposta fictícia"})
    assert response.status_code == 302
    assert Ticket.objects.get().requester == users[username]


@pytest.mark.parametrize("username", ["group-employee", "group-manager"])
def test_any_one_authorized_group_can_read_and_submit_without_admin_rights(client, group_setup, intake_data, username):
    users, _, definition = group_setup
    user = users[username]
    client.force_login(user)
    assert definition.title in client.get("/chamados/novo/", intake_data).content.decode()
    url = f"/chamados/novo/formulario/{definition.pk}/"
    assert client.get(url, intake_data).status_code == 200
    assert client.post(url, {**intake_data, "title": "Abertura por grupo fictício", "priority": "NORMAL",
        "form_version": definition.published_version, f"cf_{definition.fields[0]['id']}": "Resposta fictícia"}).status_code == 302
    for path in ("/administracao/formularios/", "/administracao/formularios/ordenar/", "/administracao/formularios/lixeira/", "/administracao/setores/", "/integracoes/"):
        assert client.get(path).status_code == 403
    assert client.post(f"/administracao/formularios/{definition.pk}/acao/", {"action": "trash", "revision": definition.revision}).status_code == 403
    user.refresh_from_db()
    assert not user.is_staff and not user.is_superuser


def test_multiple_matching_memberships_do_not_duplicate_cards_and_removal_revokes_access(client, group_setup, intake_data):
    users, groups, definition = group_setup
    employee = users["group-employee"]
    employee.groups.add(groups[1])
    client.force_login(employee)
    assert available_forms(employee).filter(pk=definition.pk).count() == 1
    assert client.get("/chamados/novo/", intake_data).content.decode().count(f'/chamados/novo/formulario/{definition.pk}/') == 1
    employee.groups.remove(groups[0])
    assert client.get(f"/chamados/novo/formulario/{definition.pk}/", intake_data).status_code == 200
    employee.groups.remove(groups[1])
    assert client.get(f"/chamados/novo/formulario/{definition.pk}/", intake_data).status_code == 404


def test_unauthorized_group_cannot_bypass_cards_or_direct_post(client, group_setup, intake_data):
    users, _, definition = group_setup
    client.force_login(users["group-outsider"])
    assert definition.title not in client.get("/chamados/novo/").content.decode()
    url = f"/chamados/novo/formulario/{definition.pk}/"
    assert client.get(url).status_code == 404
    assert client.post(url, {**intake_data, "title": "Bypass fictício", "priority": "NORMAL", "form_version": 1,
        f"cf_{definition.fields[0]['id']}": "Teste"}).status_code == 404
    assert not Ticket.objects.exists()


def test_admin_editor_preserves_multiple_groups_and_only_publishes_audience_on_publish(client, group_setup):
    users, groups, definition = group_setup
    client.force_login(users["group-admin"])
    response = client.post(f"/administracao/formularios/{definition.pk}/", {"title": definition.title,
        "description": "Teste fictício", "icon": "request", "display_order": 0, "revision": definition.revision,
        "fields": json.dumps(definition.fields), "audience": [groups[1].pk, groups[2].pk], "action": "save"})
    assert response.status_code == 302
    definition.refresh_from_db()
    assert set(definition.draft_audience) == {groups[1].pk, groups[2].pk}
    assert set(definition.allowed_groups.values_list("pk", flat=True)) == {groups[0].pk, groups[1].pk}
    publish_form(actor=users["group-admin"], form_id=definition.pk, revision=definition.revision)
    assert set(definition.allowed_groups.values_list("pk", flat=True)) == {groups[1].pk, groups[2].pk}


def test_generic_admin_override_does_not_grant_sensitive_form_or_ticket(client, group_setup, intake_data):
    users, groups, _ = group_setup
    sensitive = FormDefinition.objects.create(title="Desligamento restrito fictício", is_sensitive=True,
        fields=[{"id": str(uuid.uuid4()), "type": "short_text", "label": "Referência fictícia", "required": True,
            "default": "", "options": [], "help_text": "", "placeholder": ""}],
        draft_audience=[groups[0].pk], draft_approver_groups=[groups[1].pk])
    publish_form(actor=users["group-admin"], form_id=sensitive.pk, revision=sensitive.revision)
    sensitive.refresh_from_db()
    client.force_login(users["group-employee"])
    url = f"/chamados/novo/formulario/{sensitive.pk}/"
    assert client.post(url, {**intake_data, "title": "Desligamento fictício", "priority": "NORMAL", "form_version": 1,
        f"cf_{sensitive.fields[0]['id']}": "Dados fictícios"}).status_code == 302
    ticket = Ticket.objects.get()
    for username in ("group-admin", "root"):
        client.force_login(users[username])
        assert client.get(f"/administracao/formularios/{sensitive.pk}/").status_code == 200
        assert client.get(url).status_code == 404
        assert client.get(f"/chamados/{ticket.pk}/").status_code == 404
    client.force_login(users["group-manager"])
    assert client.get(f"/chamados/{ticket.pk}/").status_code == 200


def test_admin_losing_role_loses_cross_group_access_and_unpublished_stays_hidden(client, group_setup):
    users, _, definition = group_setup
    admin = users["group-admin"]
    client.force_login(admin)
    assert client.get(f"/chamados/novo/formulario/{definition.pk}/").status_code == 200
    admin.groups.clear()
    assert client.get(f"/chamados/novo/formulario/{definition.pk}/").status_code == 404
    assert client.get("/administracao/formularios/").status_code == 403
    client.force_login(users["root"])
    definition.status = "DRAFT"
    definition.save()
    assert client.get(f"/chamados/novo/formulario/{definition.pk}/").status_code == 404


@pytest.mark.parametrize("role", ["GERENTE", "SUPERVISORA", "SUPERVISOR_TI"])
def test_management_roles_only_receive_additional_group_access_not_administration(client, group_setup, role):
    users, groups, definition = group_setup
    user = users["group-outsider"]
    user.groups.add(Group.objects.get_or_create(name=role)[0])
    client.force_login(user)
    assert client.get(f"/chamados/novo/formulario/{definition.pk}/").status_code == 404
    user.groups.add(groups[1])
    assert client.get(f"/chamados/novo/formulario/{definition.pk}/").status_code == 200
    assert client.get("/administracao/formularios/").status_code == 403
