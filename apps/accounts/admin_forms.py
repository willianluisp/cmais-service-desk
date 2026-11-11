import secrets

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AdminPasswordChangeForm
from django.contrib.auth.password_validation import validate_password

from .permissions import USER_MANAGER_LOGIN, is_user_management_admin


class ManagedPasswordChangeForm(AdminPasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Password resets must always provide a validated replacement password.
        self.fields.pop('usable_password', None)


class ManagedUserForm(forms.ModelForm):
    admin_portal = forms.BooleanField(label='Permitir administrar o portal', required=False,
        help_text='Permite gerenciar chamados, formulários e integrações. Não libera chamados restritos a outros grupos.')

    class Meta:
        model = get_user_model()
        fields = ('username', 'first_name', 'last_name', 'is_active')

    def __init__(self, *args, actor=None, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)
        self.initial['admin_portal'] = bool(self.instance.pk and self.instance.groups.filter(name='ADMIN_PORTAL').exists())

    def clean_username(self):
        value = self.cleaned_data['username']
        if get_user_model().objects.filter(username__iexact=value).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Já existe um usuário com este login.')
        return value

    def clean(self):
        data = super().clean()
        if self.actor is None or not is_user_management_admin(self.actor):
            raise forms.ValidationError('Acesso não autorizado.')
        if not self.instance.pk:
            return data
        original = get_user_model().objects.get(pk=self.instance.pk)
        if not self.actor.is_superuser and (original.is_staff or original.is_superuser):
            raise forms.ValidationError('Esta conta exige recuperação administrativa autorizada.')
        if original.username == USER_MANAGER_LOGIN and not self.actor.is_superuser:
            if (data.get('username') != USER_MANAGER_LOGIN or not data.get('is_active')
                    or not data.get('admin_portal')):
                raise forms.ValidationError('A conta protegida deve manter login, acesso ativo e ADMIN_PORTAL.')
        return data


class ManagedUserCreationForm(ManagedUserForm):
    temporary_password = forms.CharField(
        label='Senha temporária gerada', min_length=24, strip=False,
        widget=forms.PasswordInput(render_value=True, attrs={'readonly': True, 'autocomplete': 'off'}),
        help_text='Copie e entregue por um canal seguro. A troca será obrigatória no primeiro acesso. '
                  'Esta senha não poderá ser consultada depois de salvar.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial['temporary_password'] = secrets.token_urlsafe(24) + '!aA7'

    def clean_temporary_password(self):
        password = self.cleaned_data['temporary_password']
        validate_password(password, self.instance)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['temporary_password'])
        if commit:
            user.save()
            self.save_m2m()
        return user
