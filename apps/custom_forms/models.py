import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tickets.models import Ticket


class FormDefinition(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Rascunho"
        PUBLISHED = "PUBLISHED", "Publicado"
        ARCHIVED = "ARCHIVED", "Arquivado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=120)
    description = models.TextField(max_length=1000, blank=True)
    icon = models.CharField(max_length=20, default="request")
    display_order = models.PositiveIntegerField(default=0)
    default_priority = models.CharField(max_length=10, choices=Ticket.Priority.choices, default=Ticket.Priority.NORMAL)
    fields = models.JSONField(default=list)
    draft_audience = models.JSONField(default=list)
    allowed_groups = models.ManyToManyField("auth.Group", blank=True, related_name="available_forms")
    audience_restricted = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=Status, default=Status.DRAFT, db_index=True)
    revision = models.PositiveIntegerField(default=1)
    published_version = models.PositiveIntegerField(default=0)
    published_snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    trashed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    trashed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="trashed_forms")
    trashed_by_label = models.CharField(max_length=300, blank=True)
    provision_key = models.CharField(max_length=40, unique=True, null=True, blank=True)
    is_sensitive = models.BooleanField(default=False)
    draft_approver_groups = models.JSONField(default=list)
    approver_groups = models.ManyToManyField("auth.Group", blank=True, related_name="approval_forms")

    class Meta:
        ordering = ["display_order", "title", "id"]

    def __str__(self):
        return self.title


class FormSubmission(models.Model):
    ticket = models.OneToOneField("tickets.Ticket", on_delete=models.CASCADE, related_name="form_submission")
    definition = models.ForeignKey(FormDefinition, on_delete=models.PROTECT, related_name="submissions")
    schema_snapshot = models.JSONField()
    answers = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)


class FormCardOrder(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    revision = models.PositiveIntegerField(default=1)
    items = models.JSONField(default=list)
