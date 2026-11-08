import uuid

from django.db import models
from django.utils import timezone

DEMANDAS_PLAN_ID = "OYsA-pTkhUm5MuVZj6PxK2UAHdk5"


class AttachmentPublication(models.Model):
    attachment = models.OneToOneField("tickets.Attachment", on_delete=models.PROTECT, related_name="publication")
    state = models.CharField(max_length=20, default="PENDING")
    drive_id = models.CharField(max_length=255, blank=True)
    folder_id = models.CharField(max_length=255, blank=True)
    remote_item_id = models.CharField(max_length=255, blank=True)
    remote_web_url = models.URLField(max_length=2048, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now)
    last_error_code = models.CharField(max_length=50, blank=True)
    published_at = models.DateTimeField(null=True)


class PlannerConfiguration(models.Model):
    plan_id = models.CharField(max_length=255, primary_key=True, default=DEMANDAS_PLAN_ID)
    buckets = models.JSONField(default=list)
    bucket_mapping = models.JSONField(default=dict)
    buckets_checked_at = models.DateTimeField(null=True)


class PlannerRuntime(models.Model):
    """Singleton, explicit portal choices and durable background coordination."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    configuration = models.ForeignKey(PlannerConfiguration, null=True, on_delete=models.PROTECT)
    plans = models.JSONField(default=list)
    automation_enabled = models.BooleanField(null=True, default=None)
    sync_requested = models.BooleanField(default=False)
    connection_checked_at = models.DateTimeField(null=True)
    connection_error = models.CharField(max_length=50, blank=True)
    last_started_at = models.DateTimeField(null=True)
    last_finished_at = models.DateTimeField(null=True)
    lease_id = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    throttle_until = models.DateTimeField(null=True)


class PlannerTestAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey("auth.User", on_delete=models.PROTECT)
    state = models.CharField(max_length=20, default="SUBMITTING")
    task_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class PlannerTaskProvisioning(models.Model):
    """Durable outbox for exactly one requested Planner card per ticket.

    A network timeout is deliberately not retried blindly: reconciliation looks
    for the immutable protocol embedded in the title before another POST.
    """

    class State(models.TextChoices):
        PENDING = "PENDING", "Pendente"
        LINKED = "LINKED", "Vinculado"
        RECONCILIATION = "RECONCILIATION", "Requer conferência"
        FAILED = "FAILED", "Falhou"
        CANCELLED = "CANCELLED", "Cancelado; registro arquivado"

    ticket = models.OneToOneField("tickets.Ticket", on_delete=models.PROTECT, related_name="planner_provisioning")
    correlation_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    state = models.CharField(max_length=20, choices=State, default=State.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now)
    last_error_code = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["state", "available_at"], name="planner_prov_ready_idx")]


class MicrosoftOAuthConfiguration(models.Model):
    """Local confidential-client credential; never an approval or feature flag."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    tenant_id = models.CharField(max_length=64)
    client_id = models.CharField(max_length=255)
    client_secret_encrypted = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)


class MicrosoftGraphConnection(models.Model):
    """One explicitly selected delegated Microsoft account for Planner work.

    Ciphertexts use ``GRAPH_TOKEN_ENCRYPTION_KEY``.  The Django user remains
    the local portal identity; it is not replaced by a Microsoft session.
    """

    user = models.OneToOneField(
        "auth.User", on_delete=models.PROTECT, related_name="graph_connection"
    )
    tenant_id = models.CharField(max_length=64)
    microsoft_user_id = models.CharField(max_length=255, unique=True)
    microsoft_user_principal_name = models.CharField(max_length=320)
    scopes = models.TextField()
    access_token_encrypted = models.TextField()
    refresh_token_encrypted = models.TextField()
    access_token_expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="planner_one_active_delegated_connection",
            ),
        ]
