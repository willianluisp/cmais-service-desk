import pytest
from django.apps import apps
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client, override_settings
from django.utils.datastructures import MultiValueDict

from apps.tickets.models import Category, Ticket, TicketEvent, TicketSequence

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(django_user_model):
    owner = django_user_model.objects.create_user(username="owner")
    stranger = django_user_model.objects.create_user(username="stranger", is_staff=True)
    technician = django_user_model.objects.create_user(username="technician")
    technician.groups.add(Group.objects.get_or_create(name="TECNICO_TI")[0])
    manager = django_user_model.objects.create_user(username="manager")
    manager.groups.add(Group.objects.get_or_create(name="SUPERVISOR_TI")[0])
    return owner, stranger, technician, manager


@pytest.fixture
def ticket(people):
    from apps.tickets.services import create_ticket

    return create_ticket(
        actor=people[0], title="Acesso ao sistema", description="Preciso de acesso.",
        category=Category.objects.create(name="Acesso"), priority=Ticket.Priority.NORMAL,
    )


def test_ticket_model_is_registered():
    assert any(model.__name__ == "Ticket" for model in apps.get_models())


def test_legacy_ticket_access_does_not_expand_portal_visibility(ticket, people):
    from apps.tickets.models import TicketAccess
    from apps.tickets.permissions import visible_tickets

    technician = people[2]
    assert not visible_tickets(technician, Ticket.objects.all()).filter(pk=ticket.pk).exists()
    TicketAccess.objects.create(ticket=ticket, user=technician)
    assert not visible_tickets(technician, Ticket.objects.all()).filter(pk=ticket.pk).exists()


@pytest.mark.parametrize("responsible", ["none", "username", "full_name"])
def test_list_handles_optional_assignee(client, ticket, people, responsible):
    if responsible != "none":
        assignee = people[2]
        if responsible == "full_name":
            assignee.first_name, assignee.last_name = "Técnico", "Autorizado"
            assignee.save(update_fields=["first_name", "last_name"])
        ticket.assignee = assignee
        ticket.save(update_fields=["assignee"])
    client.force_login(people[0])
    response = client.get("/chamados/")
    assert response.status_code == 200
    expected = {"none": "Aguardando atribuição", "username": "technician", "full_name": "Técnico Autorizado"}
    assert expected[responsible] in response.content.decode()
    assert ticket.number in response.content.decode()
    assert client.get(f"/chamados/{ticket.pk}/").status_code == 200


def test_list_and_details_remain_owner_only_despite_legacy_grants(client, ticket, people):
    from apps.tickets.models import TicketAccess

    for user in (people[1], people[2], people[3]):
        client.force_login(user)
        response = client.get("/chamados/")
        assert response.status_code == 200
        assert ticket.number not in response.content.decode()
        assert client.get(f"/chamados/{ticket.pk}/").status_code == 404
        grant = TicketAccess.objects.create(ticket=ticket, user=user)
        response = client.get("/chamados/")
        assert response.status_code == 200
        assert ticket.number not in response.content.decode()
        assert client.get(f"/chamados/{ticket.pk}/").status_code == 404
        grant.delete()
        assert ticket.number not in client.get("/chamados/").content.decode()
        assert client.get(f"/chamados/{ticket.pk}/").status_code == 404


def test_opening_assigns_unique_protocol_and_atomic_event(ticket, people):
    from apps.tickets.services import create_ticket

    second = create_ticket(actor=people[0], title="Outro", description="Descrição",
                           category=ticket.category, priority="ALTA")
    assert ticket.number.endswith("-000001")
    assert second.number.endswith("-000002")
    assert ticket.id != second.id
    assert ticket.events.get().event_type == "CREATED"
    assert ticket.sync_state == "PENDING"
    assert ticket.planner_provisioning.state == "PENDING"
    assert TicketSequence.objects.get().value == 2


def test_ticket_and_counter_rollback_with_event_failure(people):
    from apps.tickets.services import create_ticket

    category = Category.objects.create(name="Rede")
    with pytest.raises(RuntimeError), transaction.atomic():
        create_ticket(actor=people[0], title="Rede", description="Falha", category=category,
                      priority="NORMAL")
        raise RuntimeError("rollback")
    assert not Ticket.objects.exists()
    assert not TicketEvent.objects.exists()
    assert not TicketSequence.objects.exists()


@override_settings(ROOT_URLCONF="tests.urls_tickets")
def test_idor_filters_list_and_portal_has_no_ti_management_routes(client, ticket, people):
    owner, stranger, technician, _ = people
    client.force_login(stranger)
    assert ticket.number not in client.get("/chamados/").content.decode()
    assert client.get(f"/chamados/{ticket.pk}/").status_code == 404
    assert client.post(f"/chamados/{ticket.pk}/comentarios/", {"body": "IDOR"}).status_code == 404
    assert client.get("/ti/fila/").status_code == 404
    client.force_login(technician)
    assert client.get("/ti/fila/").status_code == 404
    assert client.post(f"/chamados/{ticket.pk}/atribuir/", {}).status_code == 404
    assert client.post(f"/chamados/{ticket.pk}/status/", {}).status_code == 404


@override_settings(ROOT_URLCONF="tests.urls_tickets")
def test_planner_management_routes_are_not_exposed(ticket, people):
    client = Client(enforce_csrf_checks=True)
    client.force_login(people[0])
    assert client.get(f"/chamados/{ticket.pk}/fechar/").status_code == 404
    assert client.post(f"/chamados/{ticket.pk}/comentarios/", {"body": "CSRF"}).status_code == 404


@override_settings(ROOT_URLCONF="tests.urls_tickets")
def test_create_ignores_forged_owner_and_status(client, ticket, people):
    client.force_login(people[1])
    response = client.post("/chamados/novo/", {
        "title": "Forjado", "description": "<script>alert(1)</script>",
        "category": ticket.category_id, "priority": "NORMAL", "requester": people[0].pk,
        "status": "FECHADO",
    })
    assert response.status_code == 302
    created = Ticket.objects.get(title="Forjado")
    assert created.requester == people[1]
    assert created.status == "ABERTO"
    assert b"<script>alert(1)</script>" not in client.get(response.url).content


def test_upload_rejects_forged_mime_oversize_and_filename():
    from apps.tickets.uploads import validate_upload

    for upload in [
        SimpleUploadedFile("shell.pdf", b"<script>bad</script>", "application/pdf"),
        SimpleUploadedFile("image.png", b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024), "image/png"),
        SimpleUploadedFile("image.svg", b"<svg></svg>", "image/svg+xml"),
        SimpleUploadedFile("document.pdf", b"%PDF-1.4\n%%EOF", "text/html"),
    ]:
        with pytest.raises(ValidationError):
            validate_upload(upload)


@override_settings(ROOT_URLCONF="tests.urls_tickets")
def test_private_attachment_acl_and_download_headers(client, ticket, people, settings, tmp_path):
    from apps.tickets.uploads import save_attachment

    settings.PRIVATE_ATTACHMENT_ROOT = tmp_path
    upload = SimpleUploadedFile("../documento.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")
    attachment = save_attachment(ticket=ticket, actor=people[0], upload=upload)
    url = f"/chamados/{ticket.pk}/anexos/{attachment.pk}/"
    client.force_login(people[1])
    assert client.get(url).status_code == 404
    preview_url = f"{url}visualizar/"
    assert client.get(preview_url).status_code == 404
    client.force_login(people[0])
    response = client.get(url)
    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment;")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert b"".join(response.streaming_content) == b"%PDF-1.4\n%%EOF"
    assert ".." not in attachment.original_name
    assert "documento" not in attachment.storage_key
    assert len(attachment.sha256) == 64
    preview = client.get(preview_url)
    assert preview.status_code == 200
    assert preview["Content-Disposition"].startswith("inline;")
    assert preview["Content-Security-Policy"] == (
        "default-src 'none'; script-src 'none'; style-src 'none'; object-src 'none'; "
        "frame-ancestors 'self'; sandbox"
    )
    assert preview["X-Content-Type-Options"] == "nosniff"
    assert b"".join(preview.streaming_content) == b"%PDF-1.4\n%%EOF"


def test_admin_portal_can_read_ticket_and_attachments_but_other_roles_cannot(
    client, ticket, people, settings, tmp_path, django_user_model
):
    from apps.tickets.uploads import save_attachment

    settings.PRIVATE_ATTACHMENT_ROOT = tmp_path
    attachment = save_attachment(
        ticket=ticket,
        actor=people[0],
        upload=SimpleUploadedFile(
            "print.png", b"\x89PNG\r\n\x1a\nimage-data", "image/png"
        ),
    )
    detail_url = f"/chamados/{ticket.pk}/"
    preview_url = f"/chamados/{ticket.pk}/anexos/{attachment.pk}/visualizar/"
    download_url = f"/chamados/{ticket.pk}/anexos/{attachment.pk}/"
    admin = django_user_model.objects.create_user("portal.admin")
    admin.groups.add(Group.objects.get_or_create(name="ADMIN_PORTAL")[0])
    client.force_login(admin)
    detail = client.get(detail_url)
    assert detail.status_code == 200
    assert ticket.number in detail.content.decode()
    assert preview_url.encode() in detail.content
    assert b'class="attachment-image-preview"' in detail.content
    assert b'alt="Pr\xc3\xa9-visualiza\xc3\xa7\xc3\xa3o de print.png"' in detail.content
    preview = client.get(preview_url)
    assert preview.status_code == 200
    download = client.get(download_url)
    assert download.status_code == 200
    for denied in (people[1], people[2], people[3]):
        client.force_login(denied)
        assert client.get(detail_url).status_code == 404
        assert client.get(preview_url).status_code == 404
        assert client.get(download_url).status_code == 404
    preview.close()
    download.close()


def test_ticket_form_rejects_more_than_five_attachments(ticket):
    from apps.tickets.forms import TicketForm

    uploads = [
        SimpleUploadedFile(f"arquivo-{index}.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")
        for index in range(6)
    ]
    form = TicketForm(
        data={
            "title": "Muitos anexos",
            "description": "Teste de limite",
            "category": ticket.category_id,
            "priority": "NORMAL",
        },
        files=MultiValueDict({"attachments": uploads}),
    )
    assert not form.is_valid()
    assert "no máximo cinco" in form.errors["attachments"][0]


@pytest.mark.parametrize("person_index", [2, 3])
def test_ti_attachment_access_is_denied_even_with_legacy_grant(
    client, ticket, people, settings, tmp_path, person_index,
):
    from apps.tickets.models import TicketAccess
    from apps.tickets.uploads import save_attachment

    settings.PRIVATE_ATTACHMENT_ROOT = tmp_path
    attachment = save_attachment(ticket=ticket, actor=people[0], upload=SimpleUploadedFile(
        "teste.pdf", b"%PDF-1.4\n%%EOF", "application/pdf",
    ))
    client.force_login(people[person_index])
    url = f"/chamados/{ticket.pk}/anexos/{attachment.pk}/"
    assert client.get(url).status_code == 404
    grant = TicketAccess.objects.create(ticket=ticket, user=people[person_index])
    response = client.get(url)
    assert response.status_code == 404
    grant.delete()
    assert client.get(url).status_code == 404


def test_zz_urlconf_is_restored_after_ticket_route_overrides(settings):
    assert settings.ROOT_URLCONF == "config.urls"


@pytest.mark.parametrize("role", ["COLABORADOR", "TECNICO_TI", "SUPERVISOR_TI", "ADMIN_PORTAL"])
def test_portal_navigation_and_counts_are_requester_only(client, ticket, people, role):
    user = people[1]
    user.groups.add(Group.objects.get_or_create(name=role)[0])
    client.force_login(user)
    response = client.get("/chamados/", {"q": ticket.number})
    assert response.status_code == 200
    can_administer = role == "ADMIN_PORTAL"
    detail_link = f'href="/chamados/{ticket.pk}/"'
    assert (detail_link in response.content.decode()) == can_administer
    assert client.get(f"/chamados/{ticket.pk}/").status_code == (200 if can_administer else 404)
    home = client.get("/")
    assert (ticket.number in home.content.decode()) == can_administer
    for body in (response.content.decode(), home.content.decode()):
        assert "Fila da TI" not in body
        assert "Atribuídos a mim" not in body
        assert ("Administração de usuários" in body) == (role == "ADMIN_PORTAL")
    assert client.post(f"/chamados/{ticket.pk}/status/", {}).status_code == 404
