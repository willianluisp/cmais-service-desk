from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AdminPasswordChangeForm

from .permissions import USER_MANAGER_LOGIN, is_user_management_admin


class ManagedPasswordChangeForm(AdminPasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Password resets must always provide a validated replacement password.
        self.fields.pop('usable_password', None)


class ManagedUserForm(forms.ModelForm):
    admin_portal = forms.BooleanField(label='Administrar chamados e integrações (ADMIN_PORTAL)', required=False)

    class Meta:
        model = get_user_model()
        fields = ('username', 'first_name', 'last_name', 'is_active')

    def __init__(self, *args, actor=None, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)
        self.initial['admin_portal'] = self.instance.groups.filter(name='ADMIN_PORTAL').exists()

    def clean_username(self):
        value = self.cleaned_data['username']
        if get_user_model().objects.filter(username__iexact=value).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Já existe um usuário com este login.')
        return value

    def clean(self):
        data = super().clean()
        if self.actor is None or not is_user_management_admin(self.actor):
            raise forms.ValidationError('Acesso não autorizado.')
        original = get_user_model().objects.get(pk=self.instance.pk)
        if not self.actor.is_superuser and (original.is_staff or original.is_superuser):
            raise forms.ValidationError('Esta conta exige recuperação administrativa autorizada.')
        if original.username == USER_MANAGER_LOGIN and not self.actor.is_superuser:
            if (data.get('username') != USER_MANAGER_LOGIN or not data.get('is_active')
                    or not data.get('admin_portal')):
                raise forms.ValidationError('A conta protegida deve manter login, acesso ativo e ADMIN_PORTAL.')
        return data
