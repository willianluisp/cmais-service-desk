from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.urls import reverse
from django.utils.html import format_html

from apps.core.admin import portal_admin

from .admin_forms import ManagedPasswordChangeForm, ManagedUserForm
from .models import AccountAudit, LocalAccount
from .permissions import USER_MANAGER_LOGIN, is_user_management_admin


class EmployeeAdmin(UserAdmin):
    change_password_form = ManagedPasswordChangeForm
    form = ManagedUserForm
    fieldsets = ((None, {'fields': ('username', 'first_name', 'last_name', 'is_active', 'admin_portal', 'reset_password')}),)
    readonly_fields = ('reset_password',)
    list_display = ('username', 'first_name', 'last_name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('username', 'first_name', 'last_name')
    filter_horizontal = ()
    actions = None

    def has_module_permission(self, request):
        return is_user_management_admin(request.user)

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request) and (
            obj is None or request.user.is_superuser or not (obj.is_staff or obj.is_superuser)
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

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
        if not change or not self.has_change_permission(request, obj):
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
        obj.save(update_fields=fields)
        group, _ = Group.objects.get_or_create(name='ADMIN_PORTAL')
        if enabled:
            obj.groups.add(group)
        else:
            obj.groups.remove(group)
        if changes:
            AccountAudit.objects.create(actor=request.user, target=obj, action='USER_CHANGED', changes=changes)


portal_admin.register(get_user_model(), EmployeeAdmin)
