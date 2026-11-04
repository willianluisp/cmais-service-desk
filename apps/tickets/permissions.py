from apps.accounts.permissions import is_portal_admin

TI_GROUPS = ("TECNICO_TI", "SUPERVISOR_TI", "ADMIN_PORTAL")
MANAGER_GROUPS = ("SUPERVISOR_TI", "ADMIN_PORTAL")


def is_ti(user):
    return user.is_authenticated and user.is_active and user.groups.filter(name__in=TI_GROUPS).exists()


def is_manager(user):
    return (
        user.is_authenticated and user.is_active
        and user.groups.filter(name__in=MANAGER_GROUPS).exists()
    )


def visible_tickets(user, queryset):
    queryset = queryset.filter(planner_deleted_at__isnull=True, archived_at__isnull=True)
    if not user.is_authenticated or not user.is_active:
        return queryset.none()
    # Portal administrators have read-only visibility through the same detail,
    # history and attachment endpoints. Other roles remain requester-only.
    if is_portal_admin(user):
        return queryset
    return queryset.filter(requester=user)
