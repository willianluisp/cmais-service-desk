import uuid

from django import forms

from .models import Ticket


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else ([data] if data else [])
        return [super(MultipleFileField, self).clean(item, initial) for item in files]


class TicketForm(forms.ModelForm):
    submission_key = forms.UUIDField(required=False, widget=forms.HiddenInput, initial=uuid.uuid4)

    class Meta:
        model = Ticket
        fields = ["title", "priority"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.sectors.intake import add_global_fields

        add_global_fields(self)
        self.fields["title"].label = "Assunto"
        self.fields["title"].help_text = "Resuma o que você precisa, por exemplo: Não consigo acessar o sistema."
        self.fields["priority"].help_text = "Escolha a prioridade de acordo com o impacto no seu trabalho."
