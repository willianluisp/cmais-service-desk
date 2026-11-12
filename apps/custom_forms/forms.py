import uuid

from django import forms
from django.contrib.auth.models import Group

from apps.tickets.models import Ticket
from apps.tickets.uploads import validate_upload

from .globals import global_kind, is_priority_question
from .models import FormDefinition
from .schema import ICONS, validate_fields


class DefinitionForm(forms.ModelForm):
    checklist_enabled = forms.BooleanField(label='Habilitar checklist automático', required=False)
    checklist_items = forms.CharField(label='Itens do checklist', required=False, max_length=5000,
        widget=forms.Textarea(attrs={'rows': 5}),
        help_text='Um item por linha. Até 20 itens de 100 caracteres. Visível somente ao TI; alterações entram em vigor ao publicar.')
    default_priority = forms.ChoiceField(label='Prioridade padrão do chamado', choices=Ticket.Priority.choices,
        initial=Ticket.Priority.NORMAL, required=False,
        help_text='A prioridade selecionada será aplicada automaticamente às novas solicitações deste formulário.')
    revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    fields = forms.JSONField(widget=forms.HiddenInput, required=False)
    audience = forms.ModelMultipleChoiceField(
        label="Quem pode abrir este formulário?", queryset=Group.objects.order_by("name"), required=False,
        help_text="Selecione um ou vários grupos; basta pertencer a um deles. Sem seleção: todos os colaboradores autenticados, exceto solicitações sensíveis. A alteração entra em vigor ao publicar.",
    )

    class Meta:
        model = FormDefinition
        fields = ["title", "description", "icon", "display_order", "default_priority"]
        labels = {"title": "Nome do formulário", "description": "Descrição", "icon": "Ícone", "display_order": "Ordem de exibição"}
        widgets = {"description": forms.Textarea(attrs={"rows": 3}), "icon": forms.Select(choices=[
            ("support", "◈ Suporte"), ("access", "⌘ Acessos"), ("people", "♧ Pessoas"),
            ("document", "▤ Documentos"), ("equipment", "▣ Equipamentos"), ("request", "＋ Solicitações")])}

    def clean_fields(self):
        return validate_fields(self.cleaned_data.get("fields") or [])

    def clean_checklist_items(self):
        from apps.planner_integration.checklists import validate_titles

        items = validate_titles([line.strip() for line in self.cleaned_data.get('checklist_items', '').splitlines() if line.strip()])
        if self.cleaned_data.get('checklist_enabled') and not items:
            raise forms.ValidationError('Adicione pelo menos um item ou desabilite o checklist.')
        return items

    def clean_default_priority(self):
        return self.cleaned_data.get('default_priority') or self.instance.default_priority or Ticket.Priority.NORMAL

    def clean_icon(self):
        value = self.cleaned_data["icon"]
        if value not in ICONS:
            raise forms.ValidationError("Selecione um ícone da lista.")
        return value


class PrivateAttachmentField(forms.FileField):
    def clean(self, data, initial=None):
        upload = super().clean(data, initial)
        if upload:
            validate_upload(upload)
        return upload


class PermanentDeleteForm(forms.Form):
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    confirmation_name = forms.CharField(label="Digite o nome exato do formulário", max_length=120, strip=False,
        widget=forms.TextInput(attrs={"autocomplete": "off"}))
    confirm = forms.BooleanField(label="Confirmo a exclusão definitiva e entendo que não será possível restaurar este formulário.")


class RequestForm(forms.Form):
    submission_key = forms.UUIDField(required=False, widget=forms.HiddenInput, initial=uuid.uuid4)
    form_version = forms.IntegerField(widget=forms.HiddenInput, min_value=1)

    def __init__(self, snapshot, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.snapshot = snapshot
        self.fields["form_version"].initial = snapshot.get("version", 1)
        for item in validate_fields(snapshot["fields"]):
            if global_kind(item) or is_priority_question(item):
                continue
            kwargs = {"label": item["label"], "required": item["required"], "help_text": item["help_text"], "initial": item["default"]}
            kind = item["type"]
            attrs = {"placeholder": item["placeholder"]} if item["placeholder"] else {}
            if kind in ("subject", "short_text", "long_text"):
                widget = forms.Textarea(attrs={**attrs, "rows": 4}) if kind == "long_text" else forms.TextInput(attrs=attrs)
                field = forms.CharField(max_length=10000 if kind == "long_text" else 160 if kind == "subject" else 255, widget=widget, **kwargs)
            elif kind == "number":
                field = forms.DecimalField(max_digits=18, decimal_places=4, widget=forms.NumberInput(attrs={**attrs, "step": "0.0001"}), **kwargs)
            elif kind == "date":
                field = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), input_formats=["%Y-%m-%d"], **kwargs)
            elif kind == "datetime":
                field = forms.DateTimeField(widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
                    input_formats=["%Y-%m-%dT%H:%M"], **kwargs)
            elif kind == "integer":
                field = forms.IntegerField(min_value=1, max_value=2147483647, widget=forms.NumberInput(attrs={**attrs, "step": "1"}), **kwargs)
            elif kind == "sector":
                from apps.sectors.models import Sector

                field = forms.ModelChoiceField(queryset=Sector.objects.filter(is_active=True), empty_label="Selecione seu setor", **kwargs)
            elif kind in ("select", "multiple"):
                choices = [(option, option) for option in item["options"]]
                field = (forms.ChoiceField(choices=[("", "Selecione uma opção"), *choices], **kwargs) if kind == "select"
                         else forms.MultipleChoiceField(choices=choices, widget=forms.CheckboxSelectMultiple, **kwargs))
            elif kind == "checkbox":
                field = forms.BooleanField(**kwargs)
            else:
                field = PrivateAttachmentField(widget=forms.FileInput(attrs={"accept": ".pdf,.png,.jpg,.jpeg"}), **kwargs)
                field.help_text = (field.help_text + " PDF, PNG ou JPEG válido, até 2 MB.").strip()
            self.fields[f"cf_{item['id']}"] = field
        from apps.sectors.intake import add_global_fields

        add_global_fields(self)
