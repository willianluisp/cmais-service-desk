from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render

from .models import Company, Sector, TicketIntakeContext


def intake_selection(request):
    """Validate each GET step, including direct links to a request form."""
    company = Company.objects.filter(pk=request.GET.get("company")).first() if request.GET.get("company", "").isdigit() else None
    sector = Sector.objects.filter(pk=request.GET.get("sector")).first() if request.GET.get("sector", "").isdigit() else None
    company = company if company and company.is_active else None
    sector = sector if company and sector and sector.is_active else None
    if company and sector and request.GET.get("change") != "1":
        return {"company": company.pk, "sector": sector.pk}, None
    return {}, render(request, "custom_forms/intake_selection.html", {
        "companies": Company.objects.filter(is_active=True), "company": company,
        "selected_sector": sector,
        "sectors": Sector.objects.filter(is_active=True) if company else Sector.objects.none(),
        "active_page": "new_ticket",
    })


def add_global_fields(form):
    fields = {
        "company": forms.ModelChoiceField(
            queryset=Company.objects.filter(is_active=True), label="Empresa",
            empty_label="Selecione a empresa", help_text="Selecione a empresa antes do departamento.",
        ),
        "sector": forms.ModelChoiceField(
            queryset=Sector.objects.filter(is_active=True),
            label="Em qual setor você trabalha?",
            help_text="Selecione seu setor para facilitar o direcionamento do atendimento.",
            empty_label="Selecione seu setor",
        ),
    }
    form.fields = {**fields, **{key: value for key, value in form.fields.items() if key not in fields}}
    return form


@transaction.atomic
def save_intake_context(*, ticket, sector, service_location=None):
    try:
        current = Sector.objects.select_for_update().get(pk=sector.pk, is_active=True)
    except (Sector.DoesNotExist, AttributeError, ValueError, TypeError):
        raise ValidationError({"sector": "Selecione um setor ativo."}) from None
    location = forms.CharField(max_length=255, required=False).clean(service_location)
    return TicketIntakeContext.objects.create(
        ticket=ticket, sector=current, sector_name_snapshot=current.name, service_location=location,
    )
