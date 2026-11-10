"""Contracts for navigation, progressive intake and safe, comprehensible errors."""
from html.parser import HTMLParser

import pytest
from django.urls import reverse


class IDs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        self.ids.extend(value for name, value in attrs if name == "id")


@pytest.mark.django_db
def test_navigation_and_account_respect_roles(client, django_user_model):
    user = django_user_model.objects.create_user("redesign.employee")
    client.force_login(user)
    body = client.get("/").content.decode()
    assert 'aria-controls="portal-navigation"' in body
    assert reverse("password_change") in body
    assert "Abrir solicitação" in body
    assert reverse("companies:manage") not in body
    assert reverse("integrations") not in body


@pytest.mark.django_db
def test_administrator_document_titles_never_contain_actions(client, django_user_model):
    from django.contrib.auth.models import Group

    from apps.tickets.services import create_ticket

    user = django_user_model.objects.create_user("redesign.admin")
    user.groups.add(Group.objects.get_or_create(name="ADMIN_PORTAL")[0])
    ticket = create_ticket(actor=user, title="Chamado de teste", description="Descrição de teste", priority="NORMAL")
    client.force_login(user)
    for url in [reverse("tickets:list"), reverse("tickets:detail", args=[ticket.pk])]:
        body = client.get(url).content.decode()
        title = body.split("<title>", 1)[1].split("</title>", 1)[0]
        assert "<" not in title
        assert body.count('<summary>Administração deste chamado</summary>') <= 1


@pytest.mark.django_db
def test_intake_progress_and_context_survive_form_selection(client, django_user_model, intake_data):
    client.force_login(django_user_model.objects.create_user("redesign.intake"))
    first = client.get(reverse("tickets:create")).content.decode()
    assert 'aria-label="Etapas da solicitação"' in first
    assert 'aria-current="step"' in first
    choice = client.get(reverse("tickets:create"), intake_data).content.decode()
    assert "Alterar empresa ou departamento" in choice
    assert f'company={intake_data["company"]}' in choice
    form = client.get(reverse("tickets:standard-create"), intake_data).content.decode()
    assert "data-request-review" in form
    assert "Revisar solicitação" in form
    assert "data-review-content" in form
    parser = IDs()
    parser.feed(form)
    assert len(parser.ids) == len(set(parser.ids))


@pytest.mark.django_db
def test_invalid_form_keeps_errors_and_server_validation(client, django_user_model):
    from apps.tickets.models import Ticket

    client.force_login(django_user_model.objects.create_user("redesign.invalid"))
    response = client.post(reverse("tickets:create"), {})
    assert response.status_code == 200
    assert 'aria-invalid="true"' in response.content.decode()
    assert 'data-request-review' in response.content.decode()
    assert not Ticket.objects.exists()


@pytest.mark.django_db
def test_error_pages_explain_next_step_without_leaking_details(client, django_user_model):
    client.force_login(django_user_model.objects.create_user("redesign.denied"))
    response = client.get(reverse("companies:manage"))
    assert response.status_code == 403
    assert "Você não tem acesso a esta página" in response.content.decode()
    response = client.get("/pagina-inexistente-redesign/")
    assert response.status_code == 404
    assert "Não encontramos esta página" in response.content.decode()
    assert 'href="/"' in response.content.decode()


@pytest.mark.django_db
def test_change_selection_keeps_company_and_offers_department(client, django_user_model, intake_data):
    client.force_login(django_user_model.objects.create_user("redesign.change"))
    response = client.get(reverse("tickets:create"), {**intake_data, "change": "1"})
    assert response.status_code == 200
    assert response.context["company"].pk == intake_data["company"]
    assert response.context["selected_sector"].pk == intake_data["sector"]
    assert 'name="sector"' in response.content.decode()
    assert "Alterar empresa" in response.content.decode()


@pytest.mark.django_db
def test_account_only_shows_current_user_and_is_authenticated(client, django_user_model):
    user = django_user_model.objects.create_user("my.account", email="mine@example.invalid", first_name="Minha")
    django_user_model.objects.create_user("another.account", email="private@example.invalid")
    assert client.get("/conta/").status_code == 302
    client.force_login(user)
    response = client.get("/conta/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "mine@example.invalid" in body
    assert "private@example.invalid" not in body
    assert 'value="admin"' not in body


@pytest.mark.django_db
def test_personal_admin_filter_keeps_authorization(client, django_user_model):
    import re

    from django.contrib.auth.models import Group

    from apps.tickets.services import create_ticket

    admin = django_user_model.objects.create_user("admin.queue")
    admin.groups.add(Group.objects.get_or_create(name="ADMIN_PORTAL")[0])
    other = django_user_model.objects.create_user("other.queue")
    own = create_ticket(actor=admin, title="Meu pedido", description="Teste", priority="NORMAL")
    theirs = create_ticket(actor=other, title="Outro pedido", description="Teste", priority="NORMAL")
    client.force_login(admin)
    response = client.get(reverse("tickets:list"), {"view": "mine"})
    assert own.number in response.content.decode()
    assert theirs.number not in response.content.decode()
    filters = re.search(r'<form[^>]*aria-label="Filtrar meus chamados".*?</form>', response.content.decode(), re.S).group(0)
    assert 'name="view" value="mine"' in filters
    cleared = client.get(reverse("tickets:list"), {"view": "mine", "q": "inexistente"}).content.decode()
    assert '?view=mine">Limpar filtros' in cleared
    client.force_login(other)
    assert own.number not in client.get(reverse("tickets:list"), {"view": "all"}).content.decode()


@pytest.mark.django_db
def test_detail_preserves_public_comments_and_hides_internal_notes(client, django_user_model):
    from apps.tickets.models import TicketComment
    from apps.tickets.services import create_ticket

    user = django_user_model.objects.create_user("comments.owner")
    other = django_user_model.objects.create_user("comments.other")
    ticket = create_ticket(actor=user, title="Comentário de teste", description="Teste", priority="NORMAL")
    TicketComment.objects.create(ticket=ticket, author=user, body="Mensagem pública registrada")
    TicketComment.objects.create(ticket=ticket, author=user, body="Nota interna confidencial", is_internal=True)
    client.force_login(user)
    body = client.get(reverse("tickets:detail", args=[ticket.pk])).content.decode()
    assert "Mensagem pública registrada" in body
    assert "Nota interna confidencial" not in body
    client.force_login(other)
    assert client.get(reverse("tickets:detail", args=[ticket.pk])).status_code == 404


@pytest.mark.django_db
def test_dynamic_request_has_review_and_private_attachment_preview(client, django_user_model, intake_data):
    import uuid

    from django.contrib.auth.models import Group

    from apps.custom_forms.models import FormDefinition
    from apps.custom_forms.services import publish_form

    user = django_user_model.objects.create_user("redesign.dynamic")
    user.groups.add(Group.objects.get_or_create(name="ADMIN_PORTAL")[0])
    definition = FormDefinition.objects.create(title="Solicitar acesso", fields=[{
        "id": str(uuid.uuid4()), "type": "attachment", "label": "Evidência", "required": False,
        "help_text": "Anexe o comprovante.", "placeholder": "", "default": "", "options": [],
    }])
    publish_form(actor=user, form_id=definition.pk, revision=definition.revision)
    client.force_login(user)
    response = client.get(reverse("custom_forms:request", args=[definition.pk]), intake_data)
    assert response.status_code == 200
    body = response.content.decode()
    assert "data-request-review" in body
    assert "attachments.js" in body
    assert 'id="attachment-dialog"' in body
    assert "data-review-edit" in body


@pytest.mark.django_db
def test_capture_redesign_screens(client, django_user_model, settings, tmp_path):
    """Optional synthetic HTML fixtures; never reads a running portal/database."""
    import json
    import os
    import uuid
    from pathlib import Path

    from django.contrib.auth.models import Group
    from django.template.loader import render_to_string
    from django.utils import timezone

    from apps.accounts.models import LocalAccount
    from apps.custom_forms.models import FormDefinition
    from apps.custom_forms.services import publish_form
    from apps.sectors.models import Company, Sector
    from apps.tickets.models import Ticket
    from apps.tickets.services import create_ticket

    target = os.environ.get("REDESIGN_CAPTURE_DIR")
    if not target:
        return
    output = Path(target)
    output.mkdir(parents=True, exist_ok=True)
    settings.PRIVATE_ATTACHMENT_ROOT = tmp_path
    settings.LOCAL_AUTH_ENABLED = True
    settings.MICROSOFT_GRAPH_APPROVED = False
    settings.PLANNER_ENABLED = False
    settings.PLANNER_SYNC_ENABLED = False
    admin = django_user_model.objects.create_superuser("admin.preview", "admin@example.invalid", "Test-preview-only-486!")
    admin.groups.add(Group.objects.get_or_create(name="ADMIN_PORTAL")[0])
    employee = django_user_model.objects.create_user("colaborador.preview", first_name="Marina", last_name="Demonstração")
    company = Company.objects.create(name="C+ • Empresa de demonstração", display_order=1)
    Company.objects.create(name="Empresa de demonstração inativa", is_active=False)
    sector = Sector.objects.create(name="Departamento de demonstração")
    Sector.objects.create(name="Departamento inativo", is_active=False)
    fields = [{"id": str(uuid.uuid4()), "type": kind, "label": label, "required": required,
               "help_text": help_text, "placeholder": "", "default": "", "options": options}
              for kind, label, required, help_text, options in [
                  ("short_text", "Qual sistema você precisa acessar?", True, "Exemplo: sistema contábil.", []),
                  ("long_text", "Conte o que precisa", False, "Não inclua senhas.", []),
                  ("multiple", "Quais recursos?", True, "Escolha pelo menos uma opção.", ["Consulta", "Relatórios"]),
                  ("date", "Quando precisa do acesso?", False, "", []),
                  ("attachment", "Comprovante", False, "Arquivo privado.", []),
                  ("attachment", "Outra evidência", False, "Opcional.", []),
              ]]
    definition = FormDefinition.objects.create(title="Acesso a sistemas", description="Peça os acessos necessários para seu trabalho.", fields=fields)
    publish_form(actor=admin, form_id=definition.pk, revision=definition.revision)
    definition.refresh_from_db()
    FormDefinition.objects.create(title="Novo equipamento — rascunho", description="Solicitação em preparação.")
    trash = FormDefinition.objects.create(title="Formulário na lixeira", trashed_at=timezone.now(), trashed_by=admin)
    intake = {"company": company.pk, "sector": sector.pk}
    query = f"?company={company.pk}&sector={sector.pk}"
    pages = []

    def capture(name, url, data=None, status=200):
        response = client.get(url, data or {})
        assert response.status_code == status, (name, response.status_code)
        (output / f"{name}.html").write_bytes(response.content)
        pages.append(name)

    capture("guest", "/")
    capture("login", "/login/")
    capture("recover", "/conta/recuperar/")
    capture("recover-done", "/conta/recuperar/enviado/")
    client.force_login(employee)
    capture("dashboard-empty", "/")
    capture("account", "/conta/")
    capture("list-empty", "/chamados/")
    capture("company-selection", "/chamados/novo/")
    capture("department-selection", "/chamados/novo/", {"company": company.pk})
    capture("choose", "/chamados/novo/", intake)
    capture("create", "/chamados/novo/suporte/", intake)
    capture("request", reverse("custom_forms:request", args=[definition.pk]) + query)
    response = client.post("/chamados/novo/suporte/", {})
    assert response.status_code == 200
    (output / "create-errors.html").write_bytes(response.content)
    pages.append("create-errors")
    for index in range(7):
        ticket = create_ticket(actor=employee, title=("Não consigo acessar o sistema de trabalho" if index == 0 else f"Solicitação de demonstração {index + 1}"),
            description="O sistema apresentou uma mensagem de erro ao iniciar. Preciso de ajuda para continuar minhas atividades.",
            priority="NORMAL", company=company, sector=sector, service_location="2º andar, sala de demonstração")
    ticket.status = Ticket.Status.EM_ATENDIMENTO
    ticket.save(update_fields=["status"])
    capture("dashboard", "/")
    capture("list", "/chamados/")
    capture("detail", reverse("tickets:detail", args=[ticket.pk]))
    # Stress cases: long, unbroken values and enough rows for pagination.
    for _index in range(22):
        create_ticket(actor=employee, title=("Assunto " + "W" * 150)[:160],
            description="Texto longo de demonstração. " * 30, priority="NORMAL", company=company,
            sector=sector, service_location="Localização " + "A" * 180)
    capture("list-many-long", "/chamados/")
    capture("filtered-empty", "/chamados/?q=inexistente")
    capture("403", "/integracoes/", status=403)
    capture("404", "/nao-existe/", status=404)
    LocalAccount.objects.create(user=employee, must_change_password=True)
    capture("first-access", "/conta/senha/")
    client.force_login(admin)
    capture("admin-home", "/admin/")
    capture("admin-users", "/admin/auth/user/")
    capture("admin-add", "/admin/auth/user/add/")
    capture("admin-edit", reverse("admin:auth_user_change", args=[employee.pk]))
    capture("admin-groups", "/admin/auth/group/")
    capture("admin-group-add", "/admin/auth/group/add/")
    capture("companies", "/administracao/empresas/")
    capture("company-form", reverse("companies:create"))
    capture("company-edit", reverse("companies:edit", args=[company.pk]))
    capture("company-delete", reverse("companies:delete", args=[company.pk]))
    capture("sectors", "/administracao/setores/")
    capture("sector-form", "/administracao/setores/novo/")
    capture("sector-delete", reverse("sectors:delete", args=[sector.pk]))
    capture("forms", reverse("custom_forms:manage"))
    capture("editor", reverse("custom_forms:edit", args=[definition.pk]))
    capture("ordering", reverse("custom_forms:ordering"))
    capture("trash", reverse("custom_forms:trash"))
    capture("form-permanent-delete", reverse("custom_forms:permanent-delete", args=[trash.pk]))
    capture("integrations", "/integracoes/")
    from apps.planner_integration.models import PlannerConfiguration, PlannerRuntime

    config = PlannerConfiguration.objects.create(plan_id="synthetic-plan",
        buckets=[{"id": "synthetic-bucket", "name": "Entrada de demonstração"}],
        buckets_checked_at=timezone.now(), bucket_mapping={"PLANNER_INTAKE_BUCKET_ID": "synthetic-bucket"})
    PlannerRuntime.objects.create(configuration=config, plans=[{"id": config.pk, "title": "Plano de atendimento de demonstração"}], connection_error="DEMONSTRATION")
    ticket.planner_provisioning.state = "RECONCILIATION"
    ticket.planner_provisioning.save(update_fields=["state"])
    capture("integrations-recovery", "/integracoes/")
    capture("soft-delete", reverse("tickets:delete", args=[ticket.pk]))
    ticket.archived_at = timezone.now()
    ticket.save(update_fields=["archived_at"])
    capture("archived", reverse("tickets:archived"))
    capture("permanent-delete", reverse("tickets:permanent-delete", args=[ticket.pk]))
    (output / "admin-jsi18n.js").write_bytes(client.get("/admin/jsi18n/").content)
    for code in [400, 500]:
        (output / f"{code}.html").write_text(render_to_string(f"{code}.html"), encoding="utf-8")
        pages.append(str(code))
    (output / "screens.json").write_text(json.dumps(pages), encoding="utf-8")
