from django import forms
from django.contrib import messages
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html

from apps.core.admin import portal_admin

from .admin_forms import ManagedPasswordChangeForm, ManagedUserCreationForm, ManagedUserForm
from .models import AccountAudit, LocalAccount
from .permissions import USER_MANAGER_LOGIN, is_user_management_admin


class ManagedGroupForm(forms.ModelForm):
    users = forms.ModelMultipleChoiceField(
        queryset=get_user_model().objects.order_by('username'), required=False,
        label='Pessoas deste grupo',
        help_text='Selecione as pessoas que terão os acessos deste grupo. Remover alguém do grupo não exclui a conta.',
        widget=FilteredSelectMultiple('usuários', is_stacked=False),
    )

    class Meta:
        model = Group
        fields = ('name',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['users'].initial = self.instance.user_set.all()
        if self.instance.name == 'ADMIN_PORTAL':
            self.fields['users'].disabled = True
            self.fields['users'].help_text = 'Para conceder ou retirar administração, edite a pessoa em Usuários. As proteções da conta serão verificadas lá.'

    def clean_name(self):
        name = self.cleaned_data['name']
        if self.instance.pk and self.instance.name == 'ADMIN_PORTAL' and name != 'ADMIN_PORTAL':
            raise forms.ValidationError('O grupo administrativo do portal não pode ser renomeado.')
        return name


class ManagedGroupAdmin(GroupAdmin):
    form = ManagedGroupForm
    change_form_template = 'admin/auth/group/managed_form.html'
    add_form_template = 'admin/auth/group/managed_form.html'
    fieldsets = ((None, {'fields': ('name', 'users', 'access_summary')}),)
    readonly_fields = ('access_summary',)
    actions = None

    def access_summary(self, obj):
        if not obj or not obj.pk:
            return 'Salve o grupo e escolha os formulários em Gerenciar formulários.'
        from apps.custom_forms.models import FormDefinition

        names = FormDefinition.objects.filter(allowed_groups=obj, trashed_at__isnull=True).values_list('title', flat=True)
        forms_text = ', '.join(names) or 'Nenhum formulário com acesso específico para este grupo.'
        permissions = ', '.join(str(p) for p in obj.permissions.all()) or 'Nenhuma permissão adicional.'
        role = ('Administra chamados, formulários e integrações.' if obj.name == 'ADMIN_PORTAL'
                else 'Não concede administração do portal por si só.')
        return f'{role} Formulários: {forms_text} Permissões adicionais: {permissions}'

    access_summary.short_description = 'Acessos do grupo'

    def has_module_permission(self, request):
        return is_user_management_admin(request.user)

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request) and (obj is None or obj.name != 'ADMIN_PORTAL')

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.user_set.set(form.cleaned_data['users'])


class EmployeeAdmin(UserAdmin):
    change_password_form = ManagedPasswordChangeForm
    form = ManagedUserForm
    add_form = ManagedUserCreationForm
    add_form_template = 'admin/auth/user/managed_form.html'
    change_form_template = 'admin/auth/user/managed_form.html'
    delete_confirmation_template = 'admin/auth/user/managed_delete.html'
    add_fieldsets = ((None, {'fields': ('first_name', 'last_name', 'username', 'is_active', 'admin_portal', 'temporary_password')}),)
    fieldsets = ((None, {'fields': ('username', 'first_name', 'last_name', 'is_active', 'admin_portal', 'reset_password')}),)
    readonly_fields = ('reset_password',)
    list_display = ('username', 'first_name', 'last_name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('username', 'first_name', 'last_name')
    filter_horizontal = ()
    actions = None

    class Media:
        js = ('js/managed-users.js',)

    def has_module_permission(self, request):
        return is_user_management_admin(request.user)

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request) and (
            obj is None or request.user.is_superuser or not (obj.is_staff or obj.is_superuser)
        )

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj) and (
            obj is None or (obj.username != USER_MANAGER_LOGIN and obj.pk != request.user.pk)
        )

    def _deletion_blockers(self, obj):
        # Even SET_NULL/CASCADE relationships carry identity or historical data.
        return [str(relation.related_model._meta.verbose_name_plural)
                for relation in obj._meta.related_objects
                if not relation.many_to_many and relation.get_accessor_name() != 'local_account'
                and relation.related_model._default_manager.filter(**{relation.field.name: obj}).exists()]

    def get_deleted_objects(self, objs, request):
        deleted, counts, perms, protected = super().get_deleted_objects(objs, request)
        for obj in objs:
            protected.extend(self._deletion_blockers(obj))
        return deleted, counts, perms, protected

    def delete_view(self, request, object_id, extra_context=None):
        if request.method == 'POST' and request.POST.get('post') != 'yes':
            raise PermissionDenied
        return super().delete_view(request, object_id, extra_context)

    @transaction.atomic
    def delete_model(self, request, obj):
        target = get_user_model().objects.select_for_update().get(pk=obj.pk)
        if not self.has_delete_permission(request, target) or self._deletion_blockers(target):
            raise PermissionDenied
        AccountAudit.objects.create(actor=request.user, action='USER_DELETED',
                                    changes={'user_id': target.pk, 'username': target.username})
        target.delete()

    def get_form(self, request, obj=None, **kwargs):
        base = super().get_form(request, obj, **kwargs)

        class ActorForm(base):
            def __init__(self, *args, **kw):
                super().__init__(*args, actor=request.user, **kw)

        return ActorForm

    def reset_password(self, obj):
        return format_html('<a href="{}">Redefinir senha</a>', reverse('admin:auth_user_password_change', args=[obj.pk]))

    reset_password.short_description = 'Senha'

    @transaction.atomic
    def user_change_password(self, request, id, form_url=''):
        target = self.get_object(request, id)
        if not self.has_change_permission(request, target):
            raise PermissionDenied
        get_user_model().objects.select_for_update().filter(pk=id).first()
        response = super().user_change_password(request, id, form_url)
        if request.method == 'POST' and response.status_code == 302:
            LocalAccount.objects.update_or_create(user_id=id, defaults={'must_change_password': True})
            AccountAudit.objects.create(actor=request.user, target_id=id, action='ADMIN_PASSWORD_RESET')
        return response

    def save_model(self, request, obj, form, change):
        if not change:
            if not self.has_add_permission(request):
                raise PermissionDenied
            obj.is_staff = obj.is_superuser = False
            obj.save()
            LocalAccount.objects.create(user=obj, must_change_password=True)
            enabled = bool(form.cleaned_data['admin_portal'])
            if enabled:
                obj.groups.add(Group.objects.get_or_create(name='ADMIN_PORTAL')[0])
            AccountAudit.objects.create(actor=request.user, target=obj, action='USER_CREATED')
            return
        if not self.has_change_permission(request, obj):
            raise PermissionDenied
        before = get_user_model().objects.select_for_update().get(pk=obj.pk)
        enabled = bool(form.cleaned_data['admin_portal'])
        if before.username == USER_MANAGER_LOGIN and not request.user.is_superuser:
            if obj.username != USER_MANAGER_LOGIN or not obj.is_active or not enabled:
                raise PermissionDenied
        fields = ('username', 'first_name', 'last_name', 'is_active')
        changes = {name: {'before': getattr(before, name), 'after': getattr(obj, name)}
                   for name in fields if getattr(before, name) != getattr(obj, name)}
        old_role = before.groups.filter(name='ADMIN_PORTAL').exists()
        if old_role != enabled:
            changes['ADMIN_PORTAL'] = {'before': old_role, 'after': enabled}
        request._user_before_relations = {
            'groups': set(before.groups.values_list('pk', flat=True)),
            'user_permissions': set(before.user_permissions.values_list('pk', flat=True)),
        }
        request._user_changes = changes
        if any(field in changes for field in fields):
            obj.save(update_fields=fields)
        if old_role != enabled:
            group, _ = Group.objects.get_or_create(name='ADMIN_PORTAL')
            if enabled:
                obj.groups.add(group)
            else:
                obj.groups.remove(group)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if change:
            changes = request._user_changes
            for field, before in request._user_before_relations.items():
                after = set(getattr(form.instance, field).values_list('pk', flat=True))
                if before != after:
                    changes[field] = {'before': sorted(before), 'after': sorted(after)}
            if changes:
                AccountAudit.objects.create(actor=request.user, target=form.instance,
                                            action='USER_CHANGED', changes=changes)

    def log_change(self, request, obj, message):
        if getattr(request, '_user_changes', None):
            super().log_change(request, obj, message)

    def response_change(self, request, obj):
        if getattr(request, '_user_changes', None):
            self.message_user(request, 'Usuário salvo com sucesso.', messages.SUCCESS)
        return redirect('admin:auth_user_change', obj.pk)

    def response_add(self, request, obj, post_url_continue=None):
        self.message_user(request, 'Usuário criado com sucesso.', messages.SUCCESS)
        return redirect('admin:auth_user_change', obj.pk)


portal_admin.register(get_user_model(), EmployeeAdmin)
portal_admin.register(Group, ManagedGroupAdmin)
