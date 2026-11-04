from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied

from apps.core.admin import portal_admin

from .models import AccountAudit, LocalAccount
from .permissions import is_portal_admin


class EmployeeAdmin(UserAdmin):
    def has_module_permission(self, request):
        return is_portal_admin(request.user)

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        if not self.has_module_permission(request):
            return False
        # Portal managers manage ordinary accounts, never the permissions or
        # passwords of another administrator (including their own admin role).
        return obj is None or request.user.is_superuser or not (
            obj.is_superuser or obj.is_staff or obj.groups.filter(name="ADMIN_PORTAL").exists()
        )

    def get_fieldsets(self, request, obj=None):
        if request.user.is_superuser or obj is None:
            return super().get_fieldsets(request, obj)
        return (
            (None, {"fields": ("username", "password")}),
            ("Dados pessoais", {"fields": ("first_name", "last_name", "email")}),
            ("Acesso", {"fields": ("is_active",)}),
        )

    def user_change_password(self, request, id, form_url=""):
        target = self.get_object(request, id)
        if target is not None and not self.has_change_permission(request, target):
            raise PermissionDenied
        response = super().user_change_password(request, id, form_url)
        if request.method == "POST" and response.status_code == 302:
            LocalAccount.objects.update_or_create(user_id=id, defaults={"must_change_password": True})
            AccountAudit.objects.create(actor=request.user, target_id=id, action="ADMIN_PASSWORD_RESET")
        return response

    def save_model(self, request, obj, form, change):
        if not self.has_change_permission(request, obj if change else None):
            raise PermissionDenied
        if not request.user.is_superuser:
            obj.is_staff = False
            obj.is_superuser = False
        super().save_model(request, obj, form, change)
        LocalAccount.objects.get_or_create(user=obj)
        AccountAudit.objects.create(actor=request.user, target=obj, action="USER_CHANGED" if change else "USER_CREATED")

    def has_delete_permission(self, request, obj=None):
        return False


portal_admin.register(get_user_model(), EmployeeAdmin)
