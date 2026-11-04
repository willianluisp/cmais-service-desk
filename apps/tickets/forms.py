import uuid

from django import forms

from .models import Category, Ticket


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else ([data] if data else [])
        return [super(MultipleFileField, self).clean(item, initial) for item in files]


class TicketForm(forms.ModelForm):
    submission_key = forms.UUIDField(required=False, widget=forms.HiddenInput, initial=uuid.uuid4)
    attachments = MultipleFileField(
        label="Anexos (PDF, PNG ou JPEG, até 2 MB cada)", required=False,
        widget=MultipleFileInput(attrs={"multiple": True, "accept": ".pdf,.png,.jpg,.jpeg"}),
    )

    class Meta:
        model = Ticket
        fields = ["title", "category", "priority", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 7})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(is_active=True)
        self.fields["category"].empty_label = "Selecione uma categoria"
        self.fields["title"].label = "Assunto"
        self.fields["title"].help_text = "Resuma o que você precisa, por exemplo: Não consigo acessar o sistema."
        self.fields["description"].label = "Descrição da solicitação"
        self.fields["description"].help_text = "Informe o que aconteceu, quando começou e como isso afeta seu trabalho."
        self.fields["priority"].help_text = "Escolha a prioridade de acordo com o impacto no seu trabalho."
        self.fields["attachments"].help_text = "Opcional: até cinco arquivos PDF, PNG ou JPEG, com no máximo 2 MB cada."

    def clean_attachments(self):
        uploads = self.cleaned_data.get("attachments", [])
        if len(uploads) > 5:
            raise forms.ValidationError("Envie no máximo cinco anexos por chamado.")
        for upload in uploads:
            from .uploads import validate_upload

            validate_upload(upload)
        return uploads
