"""Explicit links between on-premises AD and Microsoft cloud identities."""

from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q

from .models import UserProfile


@transaction.atomic
def link_entra_identity(*, user, entra_object_id, planner_user_id):
    """Persist administrator-verified immutable identifiers for one user."""
    if not isinstance(entra_object_id, UUID) or not isinstance(planner_user_id, str):
        raise ValidationError("Identificadores de identidade inválidos.")
    planner_user_id = planner_user_id.strip()
    if not planner_user_id or len(planner_user_id) > 255:
        raise ValidationError("Identificador Planner inválido.")
    profile = UserProfile.objects.select_for_update().filter(user=user).first()
    if profile is None or not user.is_active:
        raise PermissionDenied("Usuário corporativo não autorizado.")
    if profile.entra_object_id not in (None, entra_object_id):
        raise PermissionDenied("Identidade Entra já vinculada a outro registro.")
    if profile.planner_user_id not in ("", planner_user_id):
        raise PermissionDenied("Identidade Planner já vinculada a outro registro.")
    if UserProfile.objects.filter(
        Q(entra_object_id=entra_object_id) | Q(planner_user_id=planner_user_id)
    ).exclude(pk=profile.pk).exists():
        raise PermissionDenied("Identidade Microsoft já vinculada a outro registro.")
    profile.entra_object_id = entra_object_id
    profile.planner_user_id = planner_user_id
    profile.save(update_fields=["entra_object_id", "planner_user_id"])
    return profile
