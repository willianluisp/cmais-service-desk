import copy
import uuid

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError

from apps.accounts.models import AccountAudit
from apps.custom_forms.models import FormDefinition
from apps.custom_forms.services import publish_form
from apps.tickets.models import Ticket
from apps.tickets.services import create_ticket

pytestmark = pytest.mark.django_db


def question(kind="short_text", label="Pergunta fictícia", **changes):
    return {"id": str(uuid.uuid4()), "type": kind, "label": label, "required": True,
            "default": "", "options": [], "help_text": "", "placeholder": "", **changes}


@pytest.fixture
def people(django_user_model):
    admin = django_user_model.objects.create_user("evo-admin", password="synthetic-password")
    admin.groups.add(Group.objects.get_or_create(name="ADMIN_PORTAL")[0])
    employee = django_user_model.objects.create_user("evo-employee", email="employee@example.test", password="synthetic-password")
    approver = django_user_model.objects.create_user("evo-approver", password="synthetic-password")
    audience = Group.objects.create(name="Solicitantes fictícios autorizados")
    approvers = Group.objects.create(name="Aprovadores fictícios designados")
    employee.groups.add(audience)
    approver.groups.add(approvers)
    return admin, employee, approver, audience, approvers


def test_sensitive_publication_requires_only_explicit_access_groups(people):
    admin, _, _, audience, approvers = people
    definition = FormDefinition.objects.create(title="Desligamento fictício", provision_key="offboarding",
        is_sensitive=True, fields=[question()])
    with pytest.raises(ValidationError):
        publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    definition.draft_audience = [audience.pk]
    definition.save()
    publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    definition.refresh_from_db()
    assert definition.status == "PUBLISHED"


def test_sensitive_ticket_is_hidden_even_from_generic_portal_admin_and_never_queued(people, client, settings):
    from apps.notifications.models import NotificationOutbox
    from apps.planner_integration.models import PlannerTaskProvisioning

    admin, employee, approver, audience, approvers = people
    ticket = create_ticket(actor=employee, title="Solicitação sensível fictícia", description="Dados fictícios", priority="NORMAL",
        is_sensitive=True, restricted_group_ids=[audience.pk], approver_group_ids=[approvers.pk])
    assert ticket.is_sensitive
    assert not PlannerTaskProvisioning.objects.filter(ticket=ticket).exists()
    assert not NotificationOutbox.objects.filter(ticket=ticket).exists()
    for user, expected in ((admin, 404), (employee, 200), (approver, 200)):
        client.force_login(user)
        assert client.get(f"/chamados/{ticket.pk}/").status_code == expected
        body = client.get("/chamados/").content.decode()
        assert (ticket.title in body) == (expected == 200)


def test_sensitive_ticket_has_no_approval_endpoint_or_interface(people, client):
    from apps.tickets.models import SensitiveTicketApproval

    admin, employee, approver, audience, approvers = people
    ticket = create_ticket(actor=employee, title="Desligamento fictício", description="Teste", priority="NORMAL",
        is_sensitive=True, restricted_group_ids=[audience.pk], approver_group_ids=[approvers.pk])
    url = f"/chamados/{ticket.pk}/aprovacao/"
    for user in (admin, employee, approver):
        client.force_login(user)
        assert client.post(url, {"reference": "Aprovação fictícia", "confirm": "on"}).status_code == 404
    client.force_login(employee)
    body = client.get(f"/chamados/{ticket.pk}/").content.decode()
    assert "Registrar aprovação" not in body and "Aguardando aprovação" not in body
    assert not SensitiveTicketApproval.objects.exists()


def test_order_places_standard_exactly_and_rejects_stale_missing_or_duplicate_rows(people):
    from apps.custom_forms.ordering import order_state, save_order

    admin = people[0]
    first = FormDefinition.objects.create(title="Primeiro fictício", fields=[question()])
    second = FormDefinition.objects.create(title="Segundo fictício", fields=[question()])
    state, rows = order_state()
    assert {row["key"] for row in rows} == {"standard", str(first.pk), str(second.pk)}
    old_revision = state.revision
    desired = [str(second.pk), "standard", str(first.pk)]
    save_order(actor=admin, revision=old_revision, items=desired)
    state, rows = order_state()
    assert [row["key"] for row in rows] == desired
    with pytest.raises(ValidationError):
        save_order(actor=admin, revision=old_revision, items=list(reversed(desired)))
    for bad in (["standard"], ["standard", str(first.pk), str(first.pk)]):
        with pytest.raises(ValidationError):
            save_order(actor=admin, revision=state.revision, items=bad)


def test_card_order_is_immediate_without_republishing_and_no_duplicate_support(people, client, intake_data):
    from apps.custom_forms.ordering import order_state, save_order

    admin, employee, _, _, _ = people
    support = FormDefinition.objects.create(title="Suporte de TI fictício", provision_key="support", fields=[question()])
    other = FormDefinition.objects.create(title="Outro fictício", fields=[question()])
    for definition in (support, other):
        publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    client.force_login(employee)
    state, _ = order_state()
    save_order(actor=admin, revision=state.revision, items=[str(other.pk), "standard"])
    page = client.get("/chamados/novo/", intake_data)
    html = page.content.decode()
    assert html.count('class="request-card') >= 2
    assert html.index("Outro fictício") < html.index("Suporte de TI fictício")
    assert html.count("Suporte de TI fictício") == 1
    assert "Suporte técnico</h2>" not in html
    support.refresh_from_db()
    assert support.published_version == 1


def test_new_schema_types_validate_positive_integer_official_sector_and_datetime(intake_data):
    from apps.custom_forms.forms import RequestForm
    from apps.sectors.models import Sector

    sector = Sector.objects.create(name="Setor fictício de testes")
    fields = [question("integer"), question("sector", "Setor do colaborador desligado"), question("datetime")]
    snapshot = {"version": 1, "fields": fields}
    payload = {**intake_data, "title": "Teste fictício", "priority": "NORMAL", "form_version": 1,
        "sector": sector.pk, "service_location": "Local fictício",
        f"cf_{fields[0]['id']}": "2", f"cf_{fields[1]['id']}": sector.pk,
        f"cf_{fields[2]['id']}": "2026-11-06T15:30"}
    assert RequestForm(snapshot, payload).is_valid()
    for bad in ("0", "-1", "1.5"):
        data = {**payload, f"cf_{fields[0]['id']}": bad}
        assert not RequestForm(snapshot, data).is_valid()


def test_equivalent_global_questions_are_not_duplicated_and_values_are_snapshotted(people, client, intake_data):
    from apps.custom_forms.models import FormSubmission
    from apps.sectors.models import Sector

    admin, employee, _, _, _ = people
    sector = Sector.objects.create(name="Setor fictício oficial")
    fields = [question("select", "Em qual setor você trabalha?", options=["Antigo"]),
        question("short_text", "Onde o atendimento deverá ser realizado?"), question()]
    definition = FormDefinition.objects.create(title="Globais fictícios", fields=copy.deepcopy(fields))
    publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    client.force_login(employee)
    page = client.get(f"/chamados/novo/formulario/{definition.pk}/", {**intake_data, "sector": sector.pk})
    assert page.content.decode().count("Em qual setor você trabalha?") == 1
    assert page.content.decode().count("Onde o atendimento deverá ser realizado?") == 1
    response = client.post(f"/chamados/novo/formulario/{definition.pk}/", {**intake_data, "title": "Globais fictícios", "priority": "NORMAL",
        "form_version": 1, "sector": sector.pk, f"cf_{fields[1]['id']}": "Sala fictícia", f"cf_{fields[2]['id']}": "Resposta fictícia"})
    assert response.status_code == 302
    ticket = Ticket.objects.get()
    assert ticket.intake_context.sector_name_snapshot == "Setor fictício oficial"
    assert ticket.intake_context.service_location == ""
    assert FormSubmission.objects.get(ticket=ticket).answers[fields[1]["id"]] == "Sala fictícia"
    assert FormSubmission.objects.get(ticket=ticket).answers[fields[0]["id"]] == {"id": sector.pk, "name": "Setor fictício oficial"}
    sector.name = "Nome alterado"
    sector.save()
    detail = client.get(f"/chamados/{ticket.pk}/").content.decode()
    assert "Setor fictício oficial" in detail and "Sala fictícia" in detail


@pytest.mark.parametrize("kind", ["standard", "custom"])
def test_every_public_intake_requires_both_globals_first(people, client, kind, intake_data):
    from apps.sectors.models import Sector

    Sector.objects.create(name="Setor fictício para obrigatoriedade")
    admin, employee, _, _, _ = people
    definition = FormDefinition.objects.create(title="Formulário obrigatório fictício", fields=[question()])
    publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    client.force_login(employee)
    url = "/chamados/novo/suporte/" if kind == "standard" else f"/chamados/novo/formulario/{definition.pk}/"
    page = client.get(url, intake_data)
    assert list(page.context["form"].fields)[:2] == ["company", "sector"]
    response = client.post(url, {"title": "Teste fictício", "description": "Teste", "priority": "NORMAL",
        "form_version": 1, f"cf_{definition.fields[0]['id']}": "Texto fictício"})
    assert response.context["form"].errors.keys() >= {"company", "sector"}
    assert not Ticket.objects.exists()


def test_old_ticket_has_no_backfilled_context_and_remains_readable(people, client):
    from apps.sectors.models import TicketIntakeContext

    ticket = create_ticket(actor=people[1], title="Chamado anterior fictício", description="Sem contexto antigo", priority="NORMAL")
    client.force_login(people[1])
    assert client.get(f"/chamados/{ticket.pk}/").status_code == 200
    assert not TicketIntakeContext.objects.exists()
    ticket.refresh_from_db()
    assert ticket.description == "Sem contexto antigo"


def test_published_support_replaces_builtin_intake_without_duplicate_card(people, client, intake_data):
    from apps.custom_forms.models import FormSubmission

    definition = FormDefinition.objects.create(title="Suporte de TI", provision_key="support", fields=[question()])
    publish_form(actor=people[0], form_id=definition.pk, revision=definition.revision)
    client.force_login(people[1])
    page = client.get("/chamados/novo/", intake_data)
    assert page.content.decode().count('class="request-card request-card-standard"') == 1
    response = client.post("/chamados/novo/suporte/", {**intake_data, "title": "Teste de suporte fictício",
        "priority": "NORMAL", "form_version": 1, f"cf_{definition.fields[0]['id']}": "Equipamento fictício"})
    assert response.status_code == 302
    assert FormSubmission.objects.get().definition == definition


def test_offboarding_cannot_be_downgraded_or_forged_by_editor(people, client):
    import json

    admin, _, _, audience, approvers = people
    definition = FormDefinition.objects.create(title="Desligamento fictício", provision_key="offboarding", is_sensitive=True,
        fields=[question()], draft_audience=[audience.pk], draft_approver_groups=[approvers.pk])
    client.force_login(admin)
    page = client.get(f'/administracao/formularios/{definition.pk}/').content.decode()
    assert 'Proteção de acesso' not in page
    assert 'name="is_sensitive"' not in page
    assert 'name="approvers"' not in page
    response = client.post(f"/administracao/formularios/{definition.pk}/", {"title": "Nome editado",
        "description": "Texto fictício", "icon": "request", "display_order": 0, "revision": definition.revision,
        "fields": json.dumps(definition.fields), "action": "publish", "audience": [audience.pk], "approvers": [approvers.pk]})
    assert response.status_code == 302
    definition.refresh_from_db()
    assert definition.is_sensitive and definition.published_snapshot["is_sensitive"]


def test_historical_approval_groups_keep_access_without_approval(people, client):
    from apps.tickets.models import SensitiveTicketApproval

    admin, employee, former_approver, audience, group = people
    ticket = create_ticket(actor=employee, title='Histórico fictício', description='Teste', priority='NORMAL',
        is_sensitive=True, restricted_group_ids=[audience.pk])
    ticket.approver_groups.add(group)
    approval = SensitiveTicketApproval.objects.create(ticket=ticket, approved_by=former_approver,
        approver_name_snapshot='Nome histórico', reference='Referência preservada')
    client.force_login(former_approver)
    response = client.get(f'/chamados/{ticket.pk}/')
    assert response.status_code == 200
    assert 'Registrar aprovação' not in response.content.decode()
    approval.refresh_from_db()
    assert approval.reference == 'Referência preservada'
    client.force_login(admin)
    assert client.get(f'/chamados/{ticket.pk}/').status_code == 404


def test_sensitive_custom_submission_stores_explicit_groups_and_authenticated_requester(people, client, intake_data):
    admin, employee, _, audience, approvers = people
    definition = FormDefinition.objects.create(title="Solicitação sensível fictícia", is_sensitive=True, fields=[question()],
        draft_audience=[audience.pk], draft_approver_groups=[approvers.pk])
    publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    client.force_login(employee)
    response = client.post(f"/chamados/novo/formulario/{definition.pk}/", {**intake_data, "title": "Solicitação restrita fictícia",
        "priority": "NORMAL", "form_version": 1, f"cf_{definition.fields[0]['id']}": "Dados fictícios", "approved_by": admin.pk})
    assert response.status_code == 302
    ticket = Ticket.objects.get()
    assert ticket.is_sensitive and ticket.requester == employee
    assert set(ticket.restricted_groups.values_list("pk", flat=True)) == {audience.pk, approvers.pk}
    assert not ticket.approver_groups.exists()
    assert not hasattr(ticket, "sensitive_approval")


def test_sensitive_attachments_archive_and_external_consumers_fail_closed(people, client, settings, tmp_path):
    from unittest.mock import Mock

    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.http import Http404

    from apps.notifications.models import NotificationOutbox
    from apps.notifications.services import ProviderDisabled, deliver_graph, process_pending
    from apps.planner_integration.attachments import process_publications
    from apps.planner_integration.client import PlannerError
    from apps.planner_integration.models import AttachmentPublication, PlannerTaskProvisioning
    from apps.planner_integration.services import process_pending_provisioning, sync_ticket
    from apps.tickets.lifecycle import archive_ticket
    from apps.tickets.uploads import save_attachment

    settings.PRIVATE_ATTACHMENT_ROOT = tmp_path
    for flag in ("MICROSOFT_GRAPH_APPROVED", "PLANNER_ENABLED", "PLANNER_ATTACHMENTS_ENABLED", "GRAPH_ATTACHMENTS_STORAGE_APPROVED", "EMAIL_ENABLED"):
        setattr(settings, flag, True)
    settings.GRAPH_ATTACHMENTS_DRIVE_ID = "synthetic-drive"
    settings.GRAPH_ATTACHMENTS_FOLDER_ID = "synthetic-folder"
    settings.GRAPH_ATTACHMENTS_HOST = "synthetic.sharepoint.com"
    settings.GRAPH_AUTH_STRATEGY = "delegated"
    admin, employee, _, audience, approvers = people
    ticket = create_ticket(actor=employee, title="Sensível fictício", description="Teste", priority="NORMAL",
        is_sensitive=True, restricted_group_ids=[audience.pk], approver_group_ids=[approvers.pk])
    attachment = save_attachment(ticket=ticket, actor=employee,
        upload=SimpleUploadedFile("ficticio.pdf", b"%PDF-1.4\ntest\n%%EOF", content_type="application/pdf"))
    client.force_login(admin)
    assert client.get(f"/chamados/{ticket.pk}/anexos/{attachment.pk}/").status_code == 404
    with pytest.raises(Http404):
        archive_ticket(actor=admin, ticket_id=ticket.pk)
    fake = Mock()
    PlannerTaskProvisioning.objects.create(ticket=ticket)
    assert process_pending_provisioning(graph_client=fake) == 0
    with pytest.raises(PlannerError, match="sensível"):
        sync_ticket(actor=employee, ticket_id=ticket.pk, graph_client=fake)
    ticket.planner_task_id = "artificial-task"
    ticket.save(update_fields=["planner_task_id"])
    AttachmentPublication.objects.create(attachment=attachment)
    assert process_publications(graph_client=fake) == 0
    fake.assert_not_called()
    assert not fake.method_calls
    notice = NotificationOutbox.objects.create(idempotency_key="sensitive-artificial", ticket=ticket,
        recipient=employee.email, subject="Fictício", body_text="Fictício")
    with pytest.raises(ProviderDisabled):
        deliver_graph(notice)
    assert process_pending(provider=fake) == 0
    fake.assert_not_called()
    admin.groups.add(audience)
    archive_ticket(actor=admin, ticket_id=ticket.pk)
    admin.groups.remove(audience)
    assert ticket.title not in client.get("/chamados/arquivados/").content.decode()
    assert client.get(f"/chamados/{ticket.pk}/excluir-permanentemente/").status_code == 404


def test_order_endpoint_permissions_csrf_and_valid_payload(people, client):
    import json

    from django.test import Client

    admin, employee, _, _, _ = people
    client.force_login(employee)
    assert client.get("/administracao/formularios/ordenar/").status_code == 403
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(admin)
    assert strict.post("/administracao/formularios/ordenar/", {}).status_code == 403
    client.force_login(admin)
    page = client.get("/administracao/formularios/ordenar/")
    revision = page.context["state"].revision
    assert client.post("/administracao/formularios/ordenar/", {"revision": revision, "items": json.dumps(["standard"])}).status_code == 302
    assert AccountAudit.objects.filter(action="FORM_CARDS_REORDERED").exists()


def test_archived_form_can_resume_editing_as_draft_with_history_intact(people):
    from apps.custom_forms.services import perform_action

    admin = people[0]
    definition = FormDefinition.objects.create(title="Formulário arquivado fictício", fields=[question()])
    publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    definition.refresh_from_db()
    original = copy.deepcopy(definition.published_snapshot)
    perform_action(actor=admin, form_id=definition.pk, revision=definition.revision, action="archive")
    definition.refresh_from_db()
    perform_action(actor=admin, form_id=definition.pk, revision=definition.revision, action="unarchive")
    definition.refresh_from_db()
    assert definition.status == "DRAFT" and definition.published_snapshot == original
    assert AccountAudit.objects.filter(action="FORM_UNARCHIVED").exists()


def test_restricted_published_support_has_no_legacy_fallback(people, client, intake_data):
    admin, employee, outsider, audience, _ = people
    support = FormDefinition.objects.create(title="Suporte restrito fictício", provision_key="support",
        fields=[question()], draft_audience=[audience.pk])
    publish_form(actor=admin, form_id=support.pk, revision=support.revision)
    client.force_login(outsider)  # No administrative role and not a member of this audience.
    html = client.get("/chamados/novo/").content.decode()
    assert 'request-card-standard' not in html
    assert client.get("/chamados/novo/suporte/").status_code == 404
    assert client.post("/chamados/novo/", {**intake_data, "title": "Bypass fictício", "description": "Teste", "priority": "NORMAL"}).status_code == 404
    assert not Ticket.objects.exists()
    client.force_login(employee)
    assert client.get("/chamados/novo/suporte/").status_code == 200


@pytest.mark.parametrize("action", ["unpublish", "archive", "trash"])
def test_support_deactivation_does_not_reopen_legacy_intake(people, client, action):
    from apps.custom_forms.services import perform_action

    admin, employee, _, _, _ = people
    support = FormDefinition.objects.create(title="Suporte de TI fictício", provision_key="support", fields=[question()])
    client.force_login(employee)
    assert client.get("/chamados/novo/suporte/").status_code == 200  # Draft-only initial transition.
    publish_form(actor=admin, form_id=support.pk, revision=support.revision)
    support.refresh_from_db()
    perform_action(actor=admin, form_id=support.pk, revision=support.revision, action=action)
    assert client.get("/chamados/novo/suporte/").status_code == 404
    assert 'request-card-standard' not in client.get("/chamados/novo/").content.decode()


def test_sensitive_access_is_revoked_when_requester_leaves_authorized_group(people, client):
    _, employee, _, audience, approvers = people
    ticket = create_ticket(actor=employee, title="Histórico sensível fictício", description="Teste", priority="NORMAL",
        is_sensitive=True, restricted_group_ids=[audience.pk], approver_group_ids=[approvers.pk])
    client.force_login(employee)
    assert client.get(f"/chamados/{ticket.pk}/").status_code == 200
    employee.groups.remove(audience)
    assert client.get(f"/chamados/{ticket.pk}/").status_code == 404
    assert ticket.title not in client.get("/chamados/").content.decode()


@pytest.mark.django_db(transaction=True)
def test_concurrent_card_ordering_rejects_one_stale_writer(people):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections, connection

    from apps.custom_forms.ordering import order_state, save_order

    if connection.vendor != "postgresql":
        pytest.skip("Concurrent ordering requires disposable PostgreSQL")
    definition = FormDefinition.objects.create(title="Ordem concorrente fictícia", fields=[question()])
    state, _ = order_state()
    barrier = Barrier(2)

    def save(items):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            try:
                save_order(actor=people[0], revision=state.revision, items=items)
                return "saved"
            except ValidationError:
                return "stale"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [["standard", str(definition.pk)], [str(definition.pk), "standard"]]))
    assert sorted(results) == ["saved", "stale"]


@pytest.mark.django_db(transaction=True)
def test_evolution_migrations_preserve_existing_forms_and_tickets_without_seeding_sectors():
    from django.contrib.auth import get_user_model
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    from apps.sectors.models import Sector, TicketIntakeContext
    from apps.tickets.models import Category

    user = get_user_model().objects.create_user("evolution-migration.synthetic")
    category = Category.objects.create(name="Categoria fictícia migration")
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    old_targets = [("custom_forms", "0002_form_trash"), ("tickets", "0005_ticketdeletionaudit_privatefiledeletion")]
    try:
        executor.migrate([*old_targets, ("sectors", None)])
        old_apps = executor.loader.project_state(old_targets).apps
        old_ticket = old_apps.get_model("tickets", "Ticket").objects.create(number="FAKE-OLD-EVO", title="Chamado antigo fictício",
            description="Texto histórico intacto", requester_id=user.pk, category_id=category.pk)
        old_definition = old_apps.get_model("custom_forms", "FormDefinition").objects.create(title="Formulário antigo fictício",
            fields=[{"label": "Histórico"}], published_snapshot={"version": 3, "title": "Snapshot histórico"})
        MigrationExecutor(connection).migrate(targets)
        ticket = Ticket.objects.get(pk=old_ticket.pk)
        definition = FormDefinition.objects.get(pk=old_definition.pk)
        assert ticket.description == "Texto histórico intacto" and not ticket.is_sensitive
        assert not ticket.restricted_groups.exists() and not ticket.approver_groups.exists()
        assert definition.published_snapshot == {"version": 3, "title": "Snapshot histórico"}
        assert not definition.is_sensitive and definition.provision_key is None
        assert not Sector.objects.exists() and not TicketIntakeContext.objects.exists()
    finally:
        MigrationExecutor(connection).migrate(targets)
