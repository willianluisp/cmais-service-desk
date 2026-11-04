from django import forms
from django.contrib.auth import authenticate


class DomainAuthenticationForm(forms.Form):
    username = forms.CharField(label="Usuário", max_length=256)
    password = forms.CharField(label="Senha", strip=False, widget=forms.PasswordInput, max_length=4096)

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs["autocomplete"] = "username"
        self.fields["password"].widget.attrs["autocomplete"] = "current-password"

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("username") and cleaned.get("password"):
            self.user_cache = authenticate(
                self.request, username=cleaned["username"], password=cleaned["password"],
            )
            if self.user_cache is None or not self.user_cache.is_active:
                raise forms.ValidationError("Não foi possível entrar. Verifique o acesso ou tente novamente.")
        return cleaned

    def get_user(self):
        return self.user_cache
