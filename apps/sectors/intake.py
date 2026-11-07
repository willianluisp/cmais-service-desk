from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Sector, TicketIntakeContext


def add_global_fields(form):
    fields = {
        "sector": forms.ModelChoiceField(
            queryset=Sector.objects.filter(is_active=True),
            label="Em qual setor você trabalha?",
            help_text="Selecione seu setor para facilitar o direcionamento do atendimento.",
            empty_label="Selecione seu setor",
        ),
        "service_location": forms.CharField(
            max_length=255,
            label="Onde o atendimento deverá ser realizado?",
            help_text="Informe o andar, sala ou local relacionado à solicitação.",
            widget=forms.TextInput(attrs={"placeholder": "Ex.: 2º andar, sala do Fiscal ou recepção"}),
        ),
    }
    form.fields = {**fields, **{key: value for key, value in form.fields.items() if key not in fields}}
    return form


@transaction.atomic
def save_intake_context(*, ticket, sector, service_location):
    try:
        current = Sector.objects.select_for_update().get(pk=sector.pk, is_active=True)
    except (Sector.DoesNotExist, AttributeError, ValueError, TypeError):
        raise ValidationError({"sector": "Selecione um setor ativo."}) from None
    location = forms.CharField(max_length=255).clean(service_location)
    return TicketIntakeContext.objects.create(
        ticket=ticket, sector=current, sector_name_snapshot=current.name, service_location=location,
    )
