import copy
import uuid

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import Client

from apps.accounts.models import AccountAudit
from apps.custom_forms.models import FormDefinition, FormSubmission
from apps.custom_forms.services import perform_action, publish_form
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


@pytest.fixture
def trash_setup(client, django_user_model):
    admin = django_user_model.objects.create_user("trash-admin", password="synthetic-password")
    admin.groups.add(Group.objects.get_or_create(name="ADMIN_PORTAL")[0])
    employee = django_user_model.objects.create_user("trash-employee", password="synthetic-password")
    definition = FormDefinition.objects.create(title="Formulário fictício para lixeira", description="Teste de lixeira",
        icon="equipment", display_order=12, fields=[{"id": str(uuid.uuid4()), "type": "short_text",
            "label": "Equipamento fictício", "required": True, "options": [], "default": "", "help_text": "Ajuda", "placeholder": "Nome"}])
    publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    definition.refresh_from_db()
    client.force_login(admin)
    return admin, employee, definition


def act(client, definition, action):
    response = client.post(f"/administracao/formularios/{definition.pk}/acao/", {
        "action": action, "revision": definition.revision})
    definition.refresh_from_db()
    return response


def test_move_hides_form_from_main_and_new_ticket_immediately(client, trash_setup):
    admin, employee, definition = trash_setup
    response = act(client, definition, "trash")
    assert response.status_code == 302
    assert definition.trashed_at and definition.trashed_by == admin
    assert definition.title not in client.get("/administracao/formularios/").content.decode()
    assert definition.title not in client.get("/administracao/formularios/", {"status": "PUBLISHED"}).content.decode()
    page = client.get("/administracao/formularios/lixeira/")
    assert page.status_code == 200
    assert definition.title in page.content.decode() and admin.username in page.content.decode()
    assert page.context["definitions"][0].trashed_at
    assert client.get(f"/administracao/formularios/{definition.pk}/").status_code == 404
    client.force_login(employee)
    assert definition.title not in client.get("/chamados/novo/").content.decode()
    assert client.get(f"/chamados/novo/formulario/{definition.pk}/").status_code == 404
    assert client.post(f"/chamados/novo/formulario/{definition.pk}/", {}).status_code == 404
    assert not Ticket.objects.exists()


def test_restore_preserves_every_setting_but_always_returns_as_draft(client, trash_setup):
    admin, employee, definition = trash_setup
    group = Group.objects.create(name="Audiência fictícia")
    definition.draft_audience = [group.pk]
    definition.save()
    publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    definition.refresh_from_db()
    expected = copy.deepcopy({key: getattr(definition, key) for key in
        ("title", "description", "icon", "display_order", "fields", "draft_audience", "published_snapshot", "published_version", "audience_restricted")})
    act(client, definition, "trash")
    act(client, definition, "restore")
    assert definition.status == "DRAFT"
    assert definition.trashed_at is None and definition.trashed_by is None
    assert {key: getattr(definition, key) for key in expected} == expected
    assert list(definition.allowed_groups.values_list("pk", flat=True)) == [group.pk]
    assert definition.title in client.get("/administracao/formularios/").content.decode()
    client.force_login(employee)
    assert definition.title not in client.get("/chamados/novo/").content.decode()
    assert AccountAudit.objects.filter(action="FORM_TRASHED").count() == 1
    assert AccountAudit.objects.filter(action="FORM_RESTORED").count() == 1


@pytest.mark.parametrize("action", ["publish", "duplicate", "archive", "unpublish", "delete"])
def test_trashed_form_cannot_be_changed_through_old_actions(client, trash_setup, action):
    admin, _, definition = trash_setup
    act(client, definition, "trash")
    with pytest.raises(ValidationError):
        if action == "publish":
            publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
        else:
            perform_action(actor=admin, form_id=definition.pk, revision=definition.revision, action=action)
    assert FormDefinition.objects.count() == 1


def test_legacy_delete_only_moves_to_trash(client, trash_setup):
    _, _, definition = trash_setup
    act(client, definition, "delete")
    assert definition.trashed_at
    assert FormDefinition.objects.filter(pk=definition.pk).exists()


@pytest.mark.parametrize("payload", [{}, {"confirmation_name": "errado", "confirm": "on"},
    {"confirmation_name": "Formulário fictício para lixeira"}])
def test_permanent_delete_rejects_missing_or_wrong_confirmation(client, trash_setup, payload):
    _, _, definition = trash_setup
    act(client, definition, "trash")
    url = f"/administracao/formularios/{definition.pk}/excluir-definitivamente/"
    page = client.get(url)
    assert page.status_code == 200
    assert FormDefinition.objects.filter(pk=definition.pk).exists()
    response = client.post(url, {"revision": definition.revision, **payload})
    assert response.status_code == 200
    assert response.context["form"].errors
    assert FormDefinition.objects.filter(pk=definition.pk).exists()
    assert not AccountAudit.objects.filter(action="FORM_PERMANENTLY_DELETED").exists()


def test_permanent_delete_requires_trash_and_preserves_audit_after_removal(client, trash_setup):
    admin, _, definition = trash_setup
    url = f"/administracao/formularios/{definition.pk}/excluir-definitivamente/"
    assert client.get(url).status_code == 404
    act(client, definition, "trash")
    pk = definition.pk
    response = client.post(url, {"revision": definition.revision, "confirmation_name": definition.title, "confirm": "on"})
    assert response.status_code == 302
    assert not FormDefinition.objects.filter(pk=pk).exists()
    event = AccountAudit.objects.get(action="FORM_PERMANENTLY_DELETED")
    assert event.actor == admin and event.changes["form_id"] == str(pk)
    assert AccountAudit.objects.filter(action="FORM_TRASHED").exists()


def test_used_form_keeps_responses_snapshots_and_private_files_and_cannot_be_purged(client, trash_setup, settings, tmp_path, intake_data):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.tickets.uploads import private_storage, save_attachment

    _, employee, definition = trash_setup
    settings.PRIVATE_ATTACHMENT_ROOT = tmp_path
    client.force_login(employee)
    client.post(f"/chamados/novo/formulario/{definition.pk}/", {**intake_data, "title": "Chamado fictício preservado",
        "priority": "NORMAL", "form_version": definition.published_version,
        f"cf_{definition.fields[0]['id']}": "Equipamento fictício"})
    ticket = Ticket.objects.get()
    submission = FormSubmission.objects.get(ticket=ticket)
    before = copy.deepcopy(submission.schema_snapshot)
    attachment = save_attachment(ticket=ticket, actor=employee,
        upload=SimpleUploadedFile("ficticio.pdf", b"%PDF-1.4\ntest\n%%EOF", content_type="application/pdf"))
    client.force_login(trash_setup[0])
    act(client, definition, "trash")
    url = f"/administracao/formularios/{definition.pk}/excluir-definitivamente/"
    response = client.post(url, {"revision": definition.revision, "confirmation_name": definition.title, "confirm": "on"})
    assert response.status_code == 200
    assert response.context["form"].non_field_errors()
    assert FormDefinition.objects.filter(pk=definition.pk).exists()
    submission.refresh_from_db()
    assert submission.schema_snapshot == before
    assert submission.answers[definition.fields[0]["id"]] == "Equipamento fictício"
    assert private_storage().exists(attachment.storage_key)
    client.force_login(employee)
    assert client.get(f"/chamados/{ticket.pk}/").status_code == 200


@pytest.mark.parametrize("role", [None, "TECNICO_TI", "SUPERVISOR_TI"])
def test_non_admins_cannot_read_or_operate_trash(client, trash_setup, role):
    _, employee, definition = trash_setup
    act(client, definition, "trash")
    if role:
        employee.groups.add(Group.objects.get_or_create(name=role)[0])
    client.force_login(employee)
    for url in ("/administracao/formularios/lixeira/", f"/administracao/formularios/{definition.pk}/excluir-definitivamente/"):
        assert client.get(url).status_code == 403
    for action in ("trash", "restore", "purge"):
        assert client.post(f"/administracao/formularios/{definition.pk}/acao/", {"action": action, "revision": definition.revision}).status_code == 403
    assert client.post(f"/administracao/formularios/{definition.pk}/excluir-definitivamente/", {}).status_code == 403


def test_csrf_stale_confirmation_and_restore_of_active_form_are_rejected(client, trash_setup):
    admin, _, definition = trash_setup
    with pytest.raises(ValidationError):
        perform_action(actor=admin, form_id=definition.pk, revision=definition.revision, action="restore")
    act(client, definition, "trash")
    stale_revision = definition.revision
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(admin)
    url = f"/administracao/formularios/{definition.pk}/excluir-definitivamente/"
    assert strict.post(url, {}).status_code == 403
    assert strict.post(f"/administracao/formularios/{definition.pk}/acao/", {"action": "restore"}).status_code == 403
    act(client, definition, "restore")
    act(client, definition, "trash")
    response = client.post(url, {"revision": stale_revision, "confirmation_name": definition.title, "confirm": "on"})
    assert response.status_code == 200 and response.context["form"].non_field_errors()
    assert FormDefinition.objects.filter(pk=definition.pk).exists()


def test_archived_form_can_be_trashed_and_restored_without_publishing(client, trash_setup):
    _, _, definition = trash_setup
    act(client, definition, "archive")
    act(client, definition, "trash")
    act(client, definition, "restore")
    assert definition.status == "DRAFT" and definition.trashed_at is None


def test_actor_label_survives_user_removal_and_role_revocation_blocks_trash(client, trash_setup, django_user_model):
    admin, _, definition = trash_setup
    act(client, definition, "trash")
    admin.groups.clear()
    assert client.get("/administracao/formularios/lixeira/").status_code == 403
    admin.delete()
    reviewer = django_user_model.objects.create_superuser("trash-reviewer", password="synthetic-password")
    client.force_login(reviewer)
    definition.refresh_from_db()
    assert definition.trashed_by is None
    assert definition.trashed_by_label == "trash-admin"
    assert "trash-admin" in client.get("/administracao/formularios/lixeira/").content.decode()


def test_collector_dependency_failure_rolls_back_permanent_delete_audit(client, trash_setup, monkeypatch):
    from django.db.models.deletion import ProtectedError

    _, _, definition = trash_setup
    act(client, definition, "trash")

    def protected(*args, **kwargs):
        raise ProtectedError("synthetic dependency", {definition})

    monkeypatch.setattr(FormDefinition, "delete", protected)
    response = client.post(f"/administracao/formularios/{definition.pk}/excluir-definitivamente/", {
        "revision": definition.revision, "confirmation_name": definition.title, "confirm": "on"})
    assert response.status_code == 200 and response.context["form"].non_field_errors()
    assert FormDefinition.objects.filter(pk=definition.pk).exists()
    assert not AccountAudit.objects.filter(action="FORM_PERMANENTLY_DELETED").exists()


@pytest.mark.django_db(transaction=True)
def test_hidden_cascade_dependency_cannot_be_erased_by_form_deletion(client, trash_setup):
    from django.apps import apps
    from django.db import connection, models

    class HiddenFormDependency(models.Model):
        form = models.ForeignKey(FormDefinition, on_delete=models.CASCADE, related_name="+")

        class Meta:
            app_label = "custom_forms"
            db_table = "test_trash_hidden_dependency"

    with connection.schema_editor() as editor:
        editor.create_model(HiddenFormDependency)
    try:
        _, _, definition = trash_setup
        HiddenFormDependency.objects.create(form=definition)
        act(client, definition, "trash")
        response = client.post(f"/administracao/formularios/{definition.pk}/excluir-definitivamente/", {
            "revision": definition.revision, "confirmation_name": definition.title, "confirm": "on"})
        assert response.status_code == 200 and response.context["form"].non_field_errors()
        assert HiddenFormDependency.objects.count() == 1
        assert FormDefinition.objects.filter(pk=definition.pk).exists()
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(HiddenFormDependency)
        apps.all_models["custom_forms"].pop("hiddenformdependency")
        apps.clear_cache()


@pytest.mark.django_db(transaction=True)
def test_additive_trash_migration_preserves_existing_form_and_submission():
    from django.contrib.auth import get_user_model
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    from apps.tickets.services import create_ticket

    user = get_user_model().objects.create_user("migration.synthetic")
    ticket = create_ticket(actor=user, title="Chamado fictício pré-migration", description="Teste", priority="NORMAL")
    executor = MigrationExecutor(connection)
    final_targets = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("custom_forms", "0001_initial")])
        old_apps = executor.loader.project_state([("custom_forms", "0001_initial")]).apps
        old_form = old_apps.get_model("custom_forms", "FormDefinition").objects.create(
            title="Formulário anterior à lixeira", status="PUBLISHED", fields=[{"label": "Histórico fictício"}],
            published_version=2, published_snapshot={"title": "Snapshot antigo", "version": 2, "fields": []})
        old_apps.get_model("custom_forms", "FormSubmission").objects.create(ticket_id=ticket.pk,
            definition_id=old_form.pk, schema_snapshot={"version": 1, "title": "Original"}, answers={"answer": "Preservada"})
        executor = MigrationExecutor(connection)
        executor.migrate(final_targets)
        restored = FormDefinition.objects.get(pk=old_form.pk)
        assert restored.title == "Formulário anterior à lixeira" and restored.status == "PUBLISHED"
        assert restored.fields == [{"label": "Histórico fictício"}]
        assert restored.published_snapshot["title"] == "Snapshot antigo"
        assert restored.trashed_at is None and restored.trashed_by is None and restored.trashed_by_label == ""
        response = FormSubmission.objects.get(ticket=ticket)
        assert response.schema_snapshot == {"version": 1, "title": "Original"}
        assert response.answers == {"answer": "Preservada"}
    finally:
        MigrationExecutor(connection).migrate(final_targets)
