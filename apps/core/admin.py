from functools import wraps

from django.contrib.admin import AdminSite
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from apps.accounts.permissions import is_portal_admin


class PortalAdminSite(AdminSite):
    site_header = "C+ Service Desk"
    site_title = "Administração C+"
    index_title = "Administração do portal"

    def has_permission(self, request):
        return is_portal_admin(request.user)

    def login(self, request, extra_context=None):
        return redirect("login")

    def admin_view(self, view, cacheable=False):
        protected_view = super().admin_view(view, cacheable)

        @wraps(view)
        @login_required
        def authorized_view(request, *args, **kwargs):
            if not is_portal_admin(request.user):
                raise PermissionDenied
            return protected_view(request, *args, **kwargs)

        return authorized_view


portal_admin = PortalAdminSite(name="admin")
