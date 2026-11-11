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
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.sectors.intake import add_global_fields

        add_global_fields(self)

    def clean(self):
        cleaned = super().clean()
        cleaned['title'] = 'Suporte técnico'
        cleaned['priority'] = Ticket.Priority.NORMAL
        return cleaned
