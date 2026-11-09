from django import forms

from .models import Company


class CompanyForm(forms.ModelForm):
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput, required=False)

    class Meta:
        model = Company
        fields = ["name", "is_active", "display_order"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["revision"].required = True
            self.initial["revision"] = self.instance.revision

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if Company.objects.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Já existe uma empresa com este nome.")
        return name


class CompanyDeleteForm(forms.Form):
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    confirm = forms.BooleanField(label="Confirmo a exclusão desta empresa")
