"""Portal administration is a role, independent of Django staff/superuser flags."""


def is_portal_admin(user):
    return bool(user.is_authenticated and user.is_active and (
        user.is_superuser or user.groups.filter(name="ADMIN_PORTAL").exists()
    ))


def portal_access(request):
    return {"is_portal_administrator": is_portal_admin(request.user)}
