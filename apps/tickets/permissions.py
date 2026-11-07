from django.db.models import Q

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
    queryset = queryset.filter(archived_at__isnull=True).filter(
        Q(planner_deleted_at__isnull=True) | Q(archive_reason='RESTORED_PLANNER_DELETED')
    )
    return authorized_tickets(user, queryset)


def authorized_tickets(user, queryset):
    """Row-level policy also used by archive/maintenance routes."""
    if not user.is_authenticated or not user.is_active:
        return queryset.none()
    # Portal administrators have read-only visibility through the same detail,
    # history and attachment endpoints. Other roles remain requester-only.
    ordinary = Q(is_sensitive=False)
    if not is_portal_admin(user):
        ordinary &= Q(requester=user)
    # Legacy approval groups retain access only; approval is no longer a workflow.
    sensitive = Q(is_sensitive=True) & (Q(restricted_groups__in=user.groups.all())
                                      | Q(approver_groups__in=user.groups.all()))
    allowed_ids = queryset.model.objects.filter(ordinary | sensitive).values("pk")
    return queryset.filter(pk__in=allowed_ids)
