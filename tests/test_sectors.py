import pytest
from django import forms
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from apps.accounts.models import AccountAudit, LocalAccount

pytestmark = pytest.mark.django_db


@pytest.fixture
def sector():
    from apps.sectors.models import Sector

    return Sector.objects.create(name="Fiscal", display_order=2)


@pytest.fixture
def admin_user(django_user_model):
    user = django_user_model.objects.create_user("sector-admin")
    user.groups.add(Group.objects.get_or_create(name="ADMIN_PORTAL")[0])
    LocalAccount.objects.create(user=user, must_change_password=False)
    return user


@pytest.fixture
def ticket(django_user_model):
    from apps.tickets.models import Category, Ticket

    return Ticket.objects.create(
        requester=django_user_model.objects.create_user("sector-requester"),
        category=Category.objects.create(name="Teste"),
        title="Solicitação", description="Solicitação de atendimento",
    )


def test_fields_precede_existing_fields_and_filter_active_sectors(sector):
    from apps.sectors.intake import add_global_fields
    from apps.sectors.models import Sector

    inactive = Sector.objects.create(name="Inativo", is_active=False)
    first = Sector.objects.create(name="Recepção", display_order=1)
    form = forms.Form()
    form.fields["description"] = forms.CharField()
    add_global_fields(form)
    assert list(form.fields) == ["sector", "service_location", "description"]
    assert list(form.fields["sector"].queryset) == [first, sector]
    assert form.fields["sector"].required
    assert form.fields["service_location"].required
    bound = forms.Form({"sector": inactive.pk, "service_location": "Sala 2"})
    add_global_fields(bound)
    assert not bound.is_valid()
    assert "sector" in bound.errors


def test_location_is_required_and_limited_to_255_characters(sector):
    from apps.sectors.intake import add_global_fields

    for location in ("", " " * 3, "a" * 256):
        form = forms.Form({"sector": sector.pk, "service_location": location})
        add_global_fields(form)
        assert not form.is_valid()
        assert "service_location" in form.errors


def test_empty_sector_catalog_does_not_create_implicit_options():
    from apps.sectors.intake import add_global_fields
    from apps.sectors.models import Sector

    form = add_global_fields(forms.Form({"service_location": "Sala 1"}))
    assert not form.is_valid()
    assert "sector" in form.errors
    assert not Sector.objects.exists()


def test_context_preserves_snapshot_and_protects_used_sector(ticket, sector):
    from apps.sectors.intake import save_intake_context

    context = save_intake_context(ticket=ticket, sector=sector, service_location="Sala 3")
    sector.name = "Fiscal atualizado"
    sector.save()
    context.refresh_from_db()
    assert context.sector_name_snapshot == "Fiscal"
    assert context.service_location == "Sala 3"
    assert ticket.intake_context == context
    with pytest.raises(ProtectedError):
        sector.delete()
    with transaction.atomic(), pytest.raises(IntegrityError):
        save_intake_context(ticket=ticket, sector=sector, service_location="Outro local")
    context.refresh_from_db()
    assert context.service_location == "Sala 3"


def test_context_rechecks_sector_and_location(ticket, sector):
    from apps.sectors.intake import save_intake_context
    from apps.sectors.models import Sector, TicketIntakeContext

    Sector.objects.filter(pk=sector.pk).update(is_active=False)
    with pytest.raises(ValidationError):
        save_intake_context(ticket=ticket, sector=sector, service_location="Sala 1")
    assert not TicketIntakeContext.objects.exists()
    Sector.objects.filter(pk=sector.pk).update(is_active=True)
    for location in (" ", "a" * 256):
        with pytest.raises(ValidationError):
            save_intake_context(ticket=ticket, sector=sector, service_location=location)


def test_context_uses_current_name_and_is_removed_with_ticket(ticket, sector):
    from apps.sectors.intake import save_intake_context
    from apps.sectors.models import Sector, TicketIntakeContext

    Sector.objects.filter(pk=sector.pk).update(name="Fiscal renomeado")
    context = save_intake_context(ticket=ticket, sector=sector, service_location=" Sala 2 ")
    assert context.sector_name_snapshot == "Fiscal renomeado"
    assert context.service_location == "Sala 2"
    ticket.delete()
    assert not TicketIntakeContext.objects.exists()
    assert Sector.objects.filter(pk=sector.pk).exists()


def test_administrator_can_create_edit_and_delete_with_audit(client, admin_user):
    from apps.sectors.models import Sector

    client.force_login(admin_user)
    assert client.get("/administracao/setores/").status_code == 200
    assert not Sector.objects.exists()
    response = client.post("/administracao/setores/novo/", {
        "name": "Compras", "is_active": "on", "display_order": "3",
    })
    assert response.status_code == 302
    sector = Sector.objects.get(name="Compras")
    response = client.post(f"/administracao/setores/{sector.pk}/editar/", {
        "name": "Suprimentos", "display_order": "1", "revision": sector.revision,
    })
    assert response.status_code == 302
    sector.refresh_from_db()
    assert not sector.is_active and sector.name == "Suprimentos" and sector.display_order == 1
    assert AccountAudit.objects.filter(actor=admin_user, action="SECTOR_UPDATED").exists()
    assert client.get(f"/administracao/setores/{sector.pk}/excluir/").status_code == 200
    assert Sector.objects.filter(pk=sector.pk).exists()
    assert client.post(f"/administracao/setores/{sector.pk}/excluir/", {
        "revision": sector.revision, "confirm": "on",
    }).status_code == 302
    assert not Sector.objects.exists()
    assert set(AccountAudit.objects.filter(actor=admin_user).values_list("action", flat=True)) == {
        "SECTOR_CREATED", "SECTOR_UPDATED", "SECTOR_DELETED",
    }


def test_sector_conflicts_and_used_deletion_preserve_data(client, admin_user, sector, ticket):
    from apps.sectors.intake import save_intake_context
    from apps.sectors.models import Sector

    client.force_login(admin_user)
    old_revision = sector.revision
    payload = {"name": "Outro", "is_active": "on", "display_order": 0, "revision": old_revision}
    assert client.post(f"/administracao/setores/{sector.pk}/editar/", payload).status_code == 302
    payload["name"] = "Nome sobrescrito"
    assert client.post(f"/administracao/setores/{sector.pk}/editar/", payload).status_code == 409
    sector.refresh_from_db()
    assert sector.name == "Outro"
    assert client.post("/administracao/setores/novo/", {
        "name": " outro ", "is_active": "on", "display_order": 0,
    }).status_code == 200
    assert Sector.objects.count() == 1
    save_intake_context(ticket=ticket, sector=sector, service_location="Sala 1")
    response = client.post(f"/administracao/setores/{sector.pk}/excluir/", {
        "revision": sector.revision, "confirm": "on",
    })
    assert response.status_code == 409
    assert Sector.objects.filter(pk=sector.pk).exists()


def test_delete_requires_confirmation_and_current_revision(client, admin_user, sector):
    from apps.sectors.models import Sector

    client.force_login(admin_user)
    path = f"/administracao/setores/{sector.pk}/excluir/"
    assert client.post(path, {"revision": sector.revision}).status_code == 200
    assert client.post(path, {"revision": sector.revision + 1, "confirm": "on"}).status_code == 409
    assert Sector.objects.filter(pk=sector.pk).exists()


@pytest.mark.parametrize("role", ["COLABORADOR", "TECNICO_TI", "SUPERVISOR_TI"])
def test_non_administrators_cannot_manage_sectors(client, django_user_model, role, sector):
    user = django_user_model.objects.create_user("unauthorized")
    user.groups.add(Group.objects.get_or_create(name=role)[0])
    client.force_login(user)
    for path in ("/administracao/setores/", "/administracao/setores/novo/",
                 f"/administracao/setores/{sector.pk}/editar/", f"/administracao/setores/{sector.pk}/excluir/"):
        assert client.get(path).status_code == 403
        assert client.post(path, {}).status_code == 403


def test_superuser_can_manage_sectors(client, django_user_model):
    client.force_login(django_user_model.objects.create_superuser("sector-root", password="test"))
    assert client.get("/administracao/setores/").status_code == 200


def test_anonymous_access_and_csrf_are_protected(client, admin_user):
    from django.test import Client

    assert client.get("/administracao/setores/").status_code == 302
    strict_client = Client(enforce_csrf_checks=True)
    strict_client.force_login(admin_user)
    assert strict_client.post("/administracao/setores/novo/", {
        "name": "Teste", "display_order": 0,
    }).status_code == 403
