from django.conf import settings
from django.db import models


class LocalAccount(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="local_account")
    must_change_password = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AccountAudit(models.Model):
    changes = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="account_actions")
    target = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="account_changes")
    action = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)


class UserProfile(models.Model):
    """AD identity; mutable names and e-mail are never account linkage keys."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ad_profile")
    object_guid = models.UUIDField(unique=True, editable=False)
    sam_account_name = models.CharField(max_length=256)
    user_principal_name = models.CharField(max_length=256, blank=True)
    display_name = models.CharField(max_length=256, blank=True)
    department = models.CharField(max_length=256, blank=True)
    distinguished_name = models.TextField()
    # These identifiers are populated only by an authorized administrator or
    # an approved directory/Graph reconciliation; display names are not keys.
    entra_object_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    planner_user_id = models.CharField(max_length=255, blank=True, db_index=True, editable=False)
    last_verified_at = models.DateTimeField()

    def __str__(self):
        return self.display_name or self.sam_account_name

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["planner_user_id"],
                condition=models.Q(planner_user_id__gt=""),
                name="accounts_unique_nonempty_planner_user_id",
            ),
        ]
