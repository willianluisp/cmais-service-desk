import os
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.tickets.models import Category, Ticket

pytestmark = pytest.mark.django_db


def capture(name, response):
    directory = os.environ.get("PORTAL_UI_CAPTURE_DIR")
    if directory:
        output = Path(directory)
        output.mkdir(parents=True, exist_ok=True)
        (output / f"{name}.html").write_bytes(response.content)


@pytest.fixture
def employee(client, django_user_model, settings, tmp_path):
    settings.PRIVATE_ATTACHMENT_ROOT = tmp_path
    user = django_user_model.objects.create_user("visual.employee", first_name="Colaborador", last_name="Demonstração")
    client.force_login(user)
    return client, user, Category.objects.create(name="Acesso a sistemas")


def test_empty_form_has_instructions_and_only_standard_fields(employee, intake_data):
    client, _, _ = employee
    response = client.get("/chamados/novo/suporte/", intake_data)
    assert response.status_code == 200
    assert b'id="id_company_helptext"' in response.content
    assert b'aria-describedby="id_company_helptext"' in response.content
    assert b'name="title"' not in response.content
    assert b'id="attachment-dialog"' in response.content
    assert b'data-submit-feedback' in response.content
    assert 'name="attachments"' not in response.content.decode()
    assert 'name="description"' not in response.content.decode()
    capture("create", response)


def test_empty_post_shows_errors_without_creating_ticket(employee):
    client, _, _ = employee
    response = client.post("/chamados/novo/", {})
    assert response.status_code == 200
    assert b'class="error-summary"' in response.content
    assert b'aria-invalid="true"' in response.content
    assert b'href="#id_company"' in response.content
    assert not Ticket.objects.exists()
    capture("create-errors", response)


def test_success_shows_protocol_and_preserves_attachment_and_history(employee, intake_data, manual_support):
    client, owner, category = employee
    response = client.post("/chamados/novo/", {
        **intake_data,
        "title": "Não consigo acessar o sistema de trabalho", "description": "O acesso apresentou uma mensagem de erro nesta manhã.",
        "category": category.pk, "priority": "NORMAL",
        "form_version": manual_support.published_version,
        f"cf_{manual_support.fields[0]['id']}": "O acesso apresentou uma mensagem de erro nesta manhã.",
        f"cf_{manual_support.fields[1]['id']}": SimpleUploadedFile("evidencia.pdf", b"%PDF-1.4\n%%EOF", "application/pdf"),
    }, follow=True)
    ticket = Ticket.objects.get(requester=owner)
    assert response.status_code == 200
    assert f"Chamado {ticket.number} registrado com sucesso" in response.content.decode()
    assert b'role="status"' in response.content
    assert b'evidencia.pdf' in response.content
    assert b'Visualizar PDF' in response.content
    assert b'class="attachment-file-type"' in response.content
    assert b'<time datetime=' in response.content
    assert "Chamado aberto pelo solicitante" in response.content.decode()
    assert ticket.planner_provisioning.state == "PENDING"
    capture("detail-success", response)
    listed = client.get("/chamados/")
    assert ticket.category.name == 'Atendimento geral'
    assert b'<th scope="col">Categoria</th>' not in listed.content
    assert b'Ver detalhes' in listed.content
    capture("list", listed)
    capture("dashboard", client.get("/"))


def test_empty_states_and_clear_filters_are_actionable(employee):
    client, _, _ = employee
    response = client.get("/chamados/")
    assert "Abrir primeiro chamado" in response.content.decode()
    capture("list-empty", response)
    filtered = client.get("/chamados/?q=sem-resultados")
    assert "Limpar filtros" in filtered.content.decode()
    capture("list-filtered", filtered)
    capture("dashboard-empty", client.get("/"))


def test_preview_csp_is_image_only(employee):
    client, _, _ = employee
    response = client.get("/chamados/novo/")
    csp = response.headers["Content-Security-Policy"]
    assert "img-src 'self' blob:" in csp
    assert "script-src 'self';" in csp
    assert "object-src 'none'" in csp


def test_login_visual_identity_is_preserved(client):
    response = client.get("/login/")
    assert response.status_code == 200
    assert b'brand/cmais-logo.svg' in response.content
    capture("login", response)
