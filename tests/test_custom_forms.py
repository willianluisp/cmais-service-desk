import json
import uuid

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import AccountAudit
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


def schema(*fields):
    return [{"id": str(uuid.uuid4()), "type": kind, "label": label, "required": required,
             "help_text": "", "placeholder": "", "default": default, "options": options}
            for kind, label, required, default, options in fields]


@pytest.fixture
def actors(django_user_model):
    admin = django_user_model.objects.create_user("forms-admin", password="test-password")
    admin.groups.add(Group.objects.get_or_create(name="ADMIN_PORTAL")[0])
    employee = django_user_model.objects.create_user("forms-employee", password="test-password")
    stranger = django_user_model.objects.create_user("forms-stranger", password="test-password")
    return admin, employee, stranger


@pytest.fixture
def definition(actors):
    from apps.custom_forms.models import FormDefinition

    return FormDefinition.objects.create(title="Acesso a sistemas", description="Solicite um acesso corporativo.",
        fields=schema(("short_text", "Sistema", True, "", []), ("select", "Perfil", True, "", ["Consulta", "Edição"])))


def editor_data(definition, **changes):
    data = {"title": definition.title, "description": definition.description, "icon": "access",
            "display_order": 10, "revision": definition.revision, "fields": json.dumps(definition.fields),
            "action": "save"}
    data.update(changes)
    return data


def publish(definition, admin):
    from apps.custom_forms.services import publish_form

    publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    definition.refresh_from_db()


def test_editor_permissions_menu_and_real_field_builder(client, actors):
    admin, employee, _ = actors
    client.force_login(employee)
    assert client.get("/administracao/formularios/").status_code == 403
    assert client.post("/administracao/formularios/novo/", {}).status_code == 403
    client.force_login(admin)
    page = client.get("/administracao/formularios/novo/")
    assert page.status_code == 200
    body = page.content.decode()
    assert "Gerenciar formulários" in body
    assert "data-form-builder" in body
    assert "form-builder.js" in body


def test_create_edit_publish_duplicate_unpublish_and_delete(client, actors):
    from apps.custom_forms.models import FormDefinition

    admin = actors[0]
    client.force_login(admin)
    fields = schema(("short_text", "Seu equipamento", True, "", []))
    response = client.post("/administracao/formularios/novo/", {
        "title": "Equipamentos", "description": "Suporte aos equipamentos", "icon": "support",
        "display_order": 1, "revision": 0, "fields": json.dumps(fields), "action": "save"})
    assert response.status_code == 302
    definition = FormDefinition.objects.get(title="Equipamentos")
    assert definition.status == "DRAFT"
    client.post(f"/administracao/formularios/{definition.pk}/", editor_data(definition, action="publish"))
    definition.refresh_from_db()
    assert definition.status == "PUBLISHED" and definition.published_version == 1
    client.post(f"/administracao/formularios/{definition.pk}/acao/", {"action": "duplicate", "revision": definition.revision})
    clone = FormDefinition.objects.exclude(pk=definition.pk).get()
    assert clone.status == "DRAFT" and clone.published_version == 0
    client.post(f"/administracao/formularios/{clone.pk}/acao/", {"action": "delete", "revision": clone.revision})
    clone.refresh_from_db()
    assert clone.trashed_at
    client.post(f"/administracao/formularios/{clone.pk}/excluir-definitivamente/", {
        "revision": clone.revision, "confirmation_name": clone.title, "confirm": "on"})
    assert not FormDefinition.objects.filter(pk=clone.pk).exists()
    client.post(f"/administracao/formularios/{definition.pk}/acao/", {"action": "unpublish", "revision": definition.revision})
    definition.refresh_from_db()
    assert definition.status == "DRAFT"
    assert set(AccountAudit.objects.filter(actor=admin).values_list("action", flat=True)) >= {
        "FORM_CREATED", "FORM_PUBLISHED", "FORM_DUPLICATED", "FORM_TRASHED", "FORM_PERMANENTLY_DELETED", "FORM_UNPUBLISHED"}


def test_cards_preserve_standard_support_and_enforce_group_availability(client, actors, definition):
    from apps.custom_forms.models import FormDefinition

    admin, employee, stranger = actors
    group = Group.objects.create(name="Formulários RH")
    employee.groups.add(group)
    definition.draft_audience = [group.pk]
    definition.save()
    publish(definition, admin)
    FormDefinition.objects.create(title="Não publicado")
    client.force_login(employee)
    page = client.get("/chamados/novo/")
    assert "Acesso a sistemas" in page.content.decode()
    assert "Suporte técnico" in page.content.decode()
    assert "Não publicado" not in page.content.decode()
    client.force_login(stranger)
    assert "Acesso a sistemas" not in client.get("/chamados/novo/").content.decode()
    assert client.get(f"/chamados/novo/formulario/{definition.pk}/").status_code == 404


def test_submission_is_structured_snapshotted_and_uses_existing_ticket_pipeline(client, actors, definition, intake_data):
    from apps.custom_forms.models import FormSubmission
    from apps.planner_integration.models import PlannerTaskProvisioning

    admin, employee, stranger = actors
    publish(definition, admin)
    client.force_login(employee)
    key = str(uuid.uuid4())
    payload = {**intake_data, "title": "Preciso consultar o sistema", "priority": "NORMAL", "submission_key": key,
               "form_version": 1, f"cf_{definition.fields[0]['id']}": "Sistema fictício",
               f"cf_{definition.fields[1]['id']}": "Consulta", "status": "FECHADO", "requester": stranger.pk}
    response = client.post(f"/chamados/novo/formulario/{definition.pk}/", payload)
    assert response.status_code == 302
    ticket = Ticket.objects.get()
    assert ticket.requester == employee and ticket.status == "ABERTO"
    assert PlannerTaskProvisioning.objects.filter(ticket=ticket, state="PENDING").exists()
    submission = FormSubmission.objects.get(ticket=ticket)
    assert submission.answers[definition.fields[0]["id"]] == "Sistema fictício"
    assert submission.schema_snapshot["title"] == "Acesso a sistemas"
    assert client.post(f"/chamados/novo/formulario/{definition.pk}/", payload).status_code == 302
    assert Ticket.objects.count() == FormSubmission.objects.count() == 1
    definition.fields[0]["label"] = "Novo rótulo"
    definition.title = "Título alterado"
    definition.save()
    publish(definition, admin)
    submission.refresh_from_db()
    assert submission.schema_snapshot["fields"][0]["label"] == "Sistema"
    detail = client.get(f"/chamados/{ticket.pk}/")
    assert "Sistema fictício" in detail.content.decode()
    client.force_login(stranger)
    assert client.get(f"/chamados/{ticket.pk}/").status_code == 404


@pytest.mark.parametrize("value", ["", "Administrador"])
def test_invalid_required_or_unknown_choice_creates_nothing(client, actors, definition, value, intake_data):
    publish(definition, actors[0])
    client.force_login(actors[1])
    response = client.post(f"/chamados/novo/formulario/{definition.pk}/", {**intake_data, "title": "Teste fictício", "priority": "NORMAL", "form_version": 1,
        f"cf_{definition.fields[0]['id']}": "Sistema", f"cf_{definition.fields[1]['id']}": value})
    assert response.status_code == 200
    assert response.context["form"].errors
    assert not Ticket.objects.exists()


def test_draft_changes_stay_private_and_old_version_submission_is_rejected(client, actors, definition, intake_data):
    publish(definition, actors[0])
    client.force_login(actors[0])
    client.post(f"/administracao/formularios/{definition.pk}/", editor_data(definition, title="Título em rascunho"))
    definition.refresh_from_db()
    client.force_login(actors[1])
    cards = client.get("/chamados/novo/").content.decode()
    assert "Acesso a sistemas" in cards and "Título em rascunho" not in cards
    publish(definition, actors[0])
    response = client.post(f"/chamados/novo/formulario/{definition.pk}/", {**intake_data, "title": "Teste fictício", "priority": "NORMAL", "form_version": 1,
        f"cf_{definition.fields[0]['id']}": "Sistema", f"cf_{definition.fields[1]['id']}": "Consulta"})
    assert response.status_code == 200
    assert not Ticket.objects.exists()


def test_private_attachment_answer_reuses_validation_and_private_download(client, actors, definition, settings, tmp_path, intake_data):
    from apps.custom_forms.models import FormSubmission

    settings.PRIVATE_ATTACHMENT_ROOT = tmp_path
    definition.fields = schema(("attachment", "Comprovante", True, "", []))
    definition.save()
    publish(definition, actors[0])
    client.force_login(actors[1])
    payload = {**intake_data, "title": "Documento fictício", "priority": "NORMAL", "form_version": 1}
    url = f"/chamados/novo/formulario/{definition.pk}/"
    field = f"cf_{definition.fields[0]['id']}"
    response = client.post(url, {**payload, field: SimpleUploadedFile("fake.pdf", b"not-pdf", content_type="application/pdf")})
    assert response.status_code == 200 and not Ticket.objects.exists()
    response = client.post(url, {**payload, field: SimpleUploadedFile("ficticio.pdf", b"%PDF-1.4\nfake\n%%EOF", content_type="application/pdf")})
    assert response.status_code == 302
    ticket = Ticket.objects.get()
    attachment = ticket.attachments.get()
    assert FormSubmission.objects.get(ticket=ticket).answers[definition.fields[0]["id"]] == str(attachment.pk)
    download = f"/chamados/{ticket.pk}/anexos/{attachment.pk}/"
    response = client.get(download)
    assert response.status_code == 200
    assert b"".join(response.streaming_content).startswith(b"%PDF-")
    client.force_login(actors[2])
    assert client.get(download).status_code == 404


@pytest.mark.parametrize("kind,default,options,valid,invalid", [
    ("short_text", "Padrão", [], "Texto", "x" * 256),
    ("long_text", "", [], "Texto longo", "x" * 10001),
    ("number", "12.5", [], "0", "NaN"),
    ("date", "2026-11-06", [], "2026-12-31", "2026-02-31"),
    ("select", "A", ["A", "B"], "B", "C"),
    ("multiple", ["A"], ["A", "B"], ["A", "B"], ["C"]),
    ("checkbox", False, [], True, False),
])
def test_dynamic_types_validate_and_render_defaults(kind, default, options, valid, invalid, intake_data):
    from apps.custom_forms.forms import RequestForm

    fields = schema((kind, "Pergunta fictícia", True, default, options))
    snapshot = {"version": 1, "fields": fields}
    key = f"cf_{fields[0]['id']}"
    unbound = RequestForm(snapshot)
    assert unbound[key].value() == default
    data = {**intake_data, "title": "Teste fictício", "priority": "NORMAL", "form_version": 1, key: valid}
    form = RequestForm(snapshot, data)
    assert form.is_valid(), form.errors
    data[key] = invalid
    assert not RequestForm(snapshot, data).is_valid()


@pytest.mark.parametrize("changes", [
    {"id": "status"}, {"type": "__class__"}, {"required": "true"}, {"label": ""},
    {"options": ["Indevido"]}, {"default": {"executable": "no"}},
    {"type": "number", "default": "Infinity"}, {"type": "date", "default": "invalid"},
    {"type": "select", "options": []}, {"type": "select", "options": ["A", "A"]},
    {"type": "select", "options": ["A"], "default": "B"},
    {"type": "multiple", "options": ["A"], "default": ["B"]},
    {"type": "checkbox", "default": "yes"}, {"type": "attachment", "default": "/private/file"},
])
def test_schema_rejects_unsafe_or_invalid_configuration(changes):
    from django.core.exceptions import ValidationError

    from apps.custom_forms.schema import validate_fields

    fields = schema(("short_text", "Teste", False, "", []))
    fields[0].update(changes)
    with pytest.raises(ValidationError):
        validate_fields(fields)


def test_schema_bounds_and_unique_ids():
    from django.core.exceptions import ValidationError

    from apps.custom_forms.schema import validate_fields

    fields = schema(("short_text", "Teste", False, "", []))
    for invalid in ([fields[0], fields[0]], fields * 41,
                    schema(*[("attachment", "Arquivo", False, "", [])] * 6)):
        with pytest.raises(ValidationError):
            validate_fields(invalid)


def test_stale_editor_cannot_overwrite_published_form(client, actors, definition):
    client.force_login(actors[0])
    payload = editor_data(definition, title="Edição válida")
    assert client.post(f"/administracao/formularios/{definition.pk}/", payload).status_code == 302
    response = client.post(f"/administracao/formularios/{definition.pk}/", {**payload, "title": "Edição obsoleta"})
    assert response.status_code == 200
    assert "outra sessão" in response.content.decode()
    definition.refresh_from_db()
    assert definition.title == "Edição válida"


def test_preview_uses_unsaved_schema_without_persisting(client, actors, definition):
    from apps.custom_forms.models import FormDefinition

    client.force_login(actors[0])
    fields = schema(("date", "Data para o acesso", True, "2026-11-06", []))
    response = client.post("/administracao/formularios/previa/", editor_data(definition,
        title="Somente na prévia", fields=json.dumps(fields)))
    assert response.status_code == 200
    assert "Somente na prévia" in response.content.decode()
    assert 'type="date"' in response.content.decode()
    assert not FormDefinition.objects.filter(title="Somente na prévia").exists()
    assert not Ticket.objects.exists()


def test_archiving_used_form_preserves_snapshot(client, actors, definition, intake_data):
    from apps.custom_forms.models import FormSubmission

    publish(definition, actors[0])
    client.force_login(actors[1])
    client.post(f"/chamados/novo/formulario/{definition.pk}/", {**intake_data, "title": "Solicitação fictícia", "priority": "NORMAL", "form_version": 1,
        f"cf_{definition.fields[0]['id']}": "ERP fictício", f"cf_{definition.fields[1]['id']}": "Consulta"})
    client.force_login(actors[0])
    url = f"/administracao/formularios/{definition.pk}/acao/"
    client.post(url, {"action": "unpublish", "revision": definition.revision})
    definition.refresh_from_db()
    client.post(url, {"action": "archive", "revision": definition.revision})
    definition.refresh_from_db()
    assert definition.status == "ARCHIVED"
    assert FormSubmission.objects.get().schema_snapshot["title"] == "Acesso a sistemas"
    assert AccountAudit.objects.filter(action="FORM_ARCHIVED").exists()
    client.force_login(actors[1])
    assert client.get(f"/chamados/novo/formulario/{definition.pk}/").status_code == 404
    assert client.get(f"/chamados/{Ticket.objects.get().pk}/").status_code == 200


def test_endpoints_enforce_role_revocation_and_csrf(client, actors, definition):
    from django.test import Client

    admin, employee, _ = actors
    paths = ["/administracao/formularios/novo/", f"/administracao/formularios/{definition.pk}/",
             f"/administracao/formularios/{definition.pk}/acao/", "/administracao/formularios/previa/"]
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(admin)
    for path in paths:
        assert strict.post(path, {}).status_code == 403
    client.force_login(admin)
    admin.groups.clear()
    for path in paths:
        assert client.post(path, {}).status_code == 403
    assert not employee.is_staff


def test_ticket_permanent_deletion_removes_answers_in_existing_safe_workflow(client, actors, definition, intake_data):
    from apps.custom_forms.models import FormDefinition, FormSubmission
    from apps.tickets.lifecycle import archive_ticket, permanently_delete_ticket

    publish(definition, actors[0])
    client.force_login(actors[1])
    client.post(f"/chamados/novo/formulario/{definition.pk}/", {**intake_data, "title": "Solicitação fictícia", "priority": "NORMAL", "form_version": 1,
        f"cf_{definition.fields[0]['id']}": "Sistema fictício", f"cf_{definition.fields[1]['id']}": "Consulta"})
    ticket = Ticket.objects.get()
    archive_ticket(actor=actors[0], ticket_id=ticket.pk)
    permanently_delete_ticket(actor=actors[0], ticket_id=ticket.pk, number=ticket.number,
        irreversible=True, password="test-password")
    assert not Ticket.objects.exists() and not FormSubmission.objects.exists()
    assert FormDefinition.objects.filter(pk=definition.pk).exists()


def test_failed_response_write_rolls_back_ticket_outboxes_and_private_files(client, actors, definition, settings, tmp_path, monkeypatch, intake_data):
    from apps.custom_forms.forms import RequestForm
    from apps.custom_forms.services import submit_request
    from apps.planner_integration.models import PlannerTaskProvisioning

    settings.PRIVATE_ATTACHMENT_ROOT = tmp_path
    definition.fields = schema(("attachment", "Arquivo fictício", True, "", []))
    definition.save()
    publish(definition, actors[0])
    upload = SimpleUploadedFile("ficticio.pdf", b"%PDF-1.4\nfake\n%%EOF", content_type="application/pdf")
    form = RequestForm(definition.published_snapshot, {**intake_data, "title": "Teste fictício", "priority": "NORMAL", "form_version": 1},
        {f"cf_{definition.fields[0]['id']}": upload})
    assert form.is_valid(), form.errors

    def fail(**kwargs):
        raise RuntimeError("synthetic database failure")

    monkeypatch.setattr("apps.custom_forms.services.FormSubmission.objects.create", fail)
    with pytest.raises(RuntimeError):
        submit_request(actor=actors[1], form_id=definition.pk, cleaned=form.cleaned_data)
    assert not Ticket.objects.exists() and not PlannerTaskProvisioning.objects.exists()
    assert not list(tmp_path.rglob("*.pdf"))


def test_untrusted_labels_options_and_answers_are_escaped(client, actors, definition, intake_data):
    attack = '<script>alert("ficticio")</script>'
    definition.title = attack
    definition.fields = schema(("select", attack, True, "", [attack, "Seguro"]))
    definition.save()
    publish(definition, actors[0])
    client.force_login(actors[1])
    response = client.get(f"/chamados/novo/formulario/{definition.pk}/")
    assert attack not in response.content.decode()
    assert "&lt;script&gt;" in response.content.decode()
    client.post(f"/chamados/novo/formulario/{definition.pk}/", {**intake_data, "title": "Teste fictício", "priority": "NORMAL", "form_version": 1,
        f"cf_{definition.fields[0]['id']}": attack})
    detail = client.get(f"/chamados/{Ticket.objects.get().pk}/")
    assert attack not in detail.content.decode()
    assert "&lt;script&gt;" in detail.content.decode()


@pytest.mark.parametrize("role", ["TECNICO_TI", "SUPERVISOR_TI", "COLABORADOR"])
def test_other_roles_do_not_gain_form_administration(client, actors, role):
    employee = actors[1]
    employee.groups.add(Group.objects.get_or_create(name=role)[0])
    client.force_login(employee)
    assert client.get("/administracao/formularios/").status_code == 403
    assert "Gerenciar formulários" not in client.get("/chamados/novo/").content.decode()


def test_deleted_audience_group_does_not_make_restricted_form_public(client, actors, definition):
    group = Group.objects.create(name="Grupo restrito fictício")
    definition.draft_audience = [group.pk]
    definition.save()
    publish(definition, actors[0])
    group.delete()
    client.force_login(actors[1])
    assert definition.title not in client.get("/chamados/novo/").content.decode()
    url = f"/chamados/novo/formulario/{definition.pk}/"
    assert client.get(url).status_code == 404
    assert client.post(url, {"form_version": 1}).status_code == 404


@pytest.mark.django_db(transaction=True)
def test_concurrent_edit_cannot_silently_overwrite_a_saved_revision(actors, definition):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.core.exceptions import ValidationError
    from django.db import close_old_connections, connection

    from apps.custom_forms.services import save_definition

    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency requires disposable PostgreSQL")
    barrier = Barrier(2)
    data = {"revision": definition.revision, "title": "Edição concorrente fictícia", "description": "Teste",
            "icon": "request", "display_order": 1, "fields": definition.fields, "audience": []}

    def edit():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            try:
                save_definition(actor=actors[0], form_id=definition.pk, cleaned=data)
            except ValidationError:
                return "stale"
            return "saved"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: edit(), range(2)))
    assert sorted(results) == ["saved", "stale"]
    definition.refresh_from_db()
    assert definition.revision == 2
