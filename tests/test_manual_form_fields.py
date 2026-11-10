import uuid

import pytest
from django.contrib.auth.models import Group

from apps.custom_forms.forms import RequestForm
from apps.custom_forms.models import FormDefinition, FormSubmission
from apps.custom_forms.services import publish_form, submit_request
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


def question(label):
    return {"id": str(uuid.uuid4()), "type": "short_text", "label": label,
            "required": True, "default": "", "options": [], "help_text": "", "placeholder": ""}


def test_company_sector_subject_and_priority_are_automatic(intake_data):
    form = RequestForm({"version": 1, "fields": []})
    assert [field.name for field in form.visible_fields()] == ["company", "sector", "title", "priority"]


def test_manual_location_is_a_normal_question(django_user_model, intake_data):
    actor = django_user_model.objects.create_superuser("manual-admin", password="test")
    fields = [question("Onde o atendimento deverá ser realizado?"), question("Detalhes adicionais")]
    definition = FormDefinition.objects.create(title="Pedido manual", fields=fields)
    definition = publish_form(actor=actor, form_id=definition.pk, revision=definition.revision)
    form = RequestForm(definition.published_snapshot, {
        "company": intake_data["company"], "sector": intake_data["sector"], "form_version": 1,
        f"cf_{fields[0]['id']}": "Sala 7", f"cf_{fields[1]['id']}": "Meu pedido",
        "title": "Título do pedido", "priority": "ALTA", "service_location": "Ignorar",
    })
    assert form.is_valid(), form.errors
    ticket = submit_request(actor=actor, form_id=definition.pk, cleaned=form.cleaned_data)
    assert ticket.title == "Título do pedido"
    assert ticket.priority == Ticket.Priority.ALTA
    assert ticket.intake_context.service_location == ""
    assert FormSubmission.objects.get(ticket=ticket).answers[fields[0]["id"]] == "Sala 7"


def test_subject_and_priority_remain_required_and_validated(intake_data):
    data = {"company": intake_data["company"], "sector": intake_data["sector"], "form_version": 1}
    form = RequestForm({"version": 1, "fields": []}, data)
    assert not form.is_valid()
    assert set(form.errors) == {"title", "priority"}
    form = RequestForm({"version": 1, "fields": []}, {**data, "title": "Teste", "priority": "forged"})
    assert not form.is_valid()
    assert set(form.errors) == {"priority"}


def test_can_publish_and_submit_without_manual_questions(django_user_model, intake_data):
    actor = django_user_model.objects.create_superuser("empty-admin", password="test")
    definition = FormDefinition.objects.create(title="Sem perguntas extras", fields=[])
    definition = publish_form(actor=actor, form_id=definition.pk, revision=definition.revision)
    form = RequestForm(definition.published_snapshot, {
        "company": intake_data["company"], "sector": intake_data["sector"], "form_version": 1,
        "title": "Pedido sem perguntas extras", "priority": "NORMAL",
    })
    assert form.is_valid(), form.errors
    ticket = submit_request(actor=actor, form_id=definition.pk, cleaned=form.cleaned_data)
    assert ticket.company_id == intake_data["company"]
    assert ticket.intake_context.sector_id == intake_data["sector"]


def test_support_has_only_globals_before_manual_configuration(client, django_user_model, intake_data):
    actor = django_user_model.objects.create_user("manual-employee")
    client.force_login(actor)
    page = client.get("/chamados/novo/suporte/", intake_data)
    assert [field.name for field in page.context["form"].visible_fields()] == ["company", "sector", "title", "priority"]
    response = client.post("/chamados/novo/suporte/", {
        "company": intake_data["company"], "sector": intake_data["sector"],
        "title": "Ajuda com acesso", "priority": "NORMAL",
    })
    assert response.status_code == 302
    assert Ticket.objects.get().title == "Ajuda com acesso"


def test_support_editor_can_be_created_only_by_admin(client, django_user_model):
    actor = django_user_model.objects.create_user("support-editor")
    client.force_login(actor)
    url = "/administracao/formularios/suporte/"
    assert client.post(url).status_code == 403
    actor.groups.add(Group.objects.get_or_create(name="ADMIN_PORTAL")[0])
    response = client.post(url)
    assert response.status_code == 302
    definition = FormDefinition.objects.get(provision_key="support")
    assert definition.fields == []
    client.post(url)
    assert FormDefinition.objects.filter(provision_key="support").count() == 1
    page = client.get(response.url)
    assert page.status_code == 200
    assert "Onde o atendimento deverá ser realizado?" not in page.content.decode()
