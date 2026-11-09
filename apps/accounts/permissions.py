"""Portal administration is a role, independent of Django staff/superuser flags."""


def is_portal_admin(user):
    return bool(user.is_authenticated and user.is_active and (
        user.is_superuser or user.groups.filter(name="ADMIN_PORTAL").exists()
    ))


USER_MANAGER_LOGIN = 'willian.pedroso'


def is_user_management_admin(user):
    return bool(user.is_authenticated and user.is_active and (
        user.is_superuser or user.username == USER_MANAGER_LOGIN
    ))


def portal_access(request):
    return {'is_portal_administrator': is_portal_admin(request.user),
            'can_manage_ticket_lifecycle': bool(request.user.is_authenticated and request.user.is_active
                and request.user.groups.filter(name='ADMIN_PORTAL').exists()),
            'can_manage_users': is_user_management_admin(request.user)}
