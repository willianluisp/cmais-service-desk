import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Category(models.Model):
    name = models.CharField("Nome", max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Categoria"

    def __str__(self):
        return self.name


class TicketSequence(models.Model):
    year = models.PositiveIntegerField(primary_key=True)
    value = models.PositiveIntegerField(default=0)


class Ticket(models.Model):
    class Status(models.TextChoices):
        ABERTO = "ABERTO", "Aberto"
        EM_ATENDIMENTO = "EM_ATENDIMENTO", "Em atendimento"
        AGUARDANDO_SOLICITANTE = "AGUARDANDO_SOLICITANTE", "Aguardando solicitante"
        RESOLVIDO = "RESOLVIDO", "Resolvido"
        FECHADO = "FECHADO", "Fechado"

    class Priority(models.TextChoices):
        BAIXA = "BAIXA", "Baixa"
        NORMAL = "NORMAL", "Normal"
        ALTA = "ALTA", "Alta"
        CRITICA = "CRITICA", "Crítica"

    class SyncState(models.TextChoices):
        PENDING = "PENDING", "Pendente"
        SYNCED = "SYNCED", "Sincronizado"
        ERROR = "ERROR", "Erro"
        DISABLED = "DISABLED", "Desabilitado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=30, unique=True, editable=False)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_tickets"
    )
    title = models.CharField("Título", max_length=160)
    description = models.TextField("Descrição", max_length=10000)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, verbose_name="Categoria")
    priority = models.CharField("Prioridade", max_length=10, choices=Priority, default=Priority.NORMAL)
    status = models.CharField(max_length=30, choices=Status, default=Status.ABERTO)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="assigned_tickets",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    planner_deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    archive_reason = models.CharField(max_length=40, blank=True)
    submission_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    planner_task_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    planner_plan_id = models.CharField(max_length=255, blank=True)
    planner_bucket_id = models.CharField(max_length=255, blank=True)
    planner_percent_complete = models.PositiveSmallIntegerField(null=True, blank=True)
    planner_assignee_ids = models.JSONField(default=list, blank=True)
    planner_assignee_names = models.JSONField(default=list, blank=True)
    planner_due_at = models.DateTimeField(null=True, blank=True)
    planner_checklist = models.JSONField(default=list, blank=True)
    planner_checklist_completed = models.PositiveSmallIntegerField(default=0)
    planner_checklist_total = models.PositiveSmallIntegerField(default=0)
    planner_etag = models.CharField(max_length=255, blank=True)
    last_planner_sync_at = models.DateTimeField(null=True, blank=True)
    sync_state = models.CharField(max_length=10, choices=SyncState, default=SyncState.DISABLED)
    sync_error_code = models.CharField(max_length=80, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["requester", "status"]),
            models.Index(fields=["assignee", "status"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [models.CheckConstraint(
            condition=models.Q(planner_percent_complete__isnull=True)
            | models.Q(planner_percent_complete__gte=0, planner_percent_complete__lte=100),
            name="tickets_planner_percent_range",
        )]

    def __str__(self):
        return self.number

    PORTAL_STATUS_GROUPS = {
        "ABERTO": ("ABERTO",),
        "EM_ATENDIMENTO": ("EM_ATENDIMENTO", "AGUARDANDO_SOLICITANTE"),
        "RESOLVIDO": ("RESOLVIDO", "FECHADO"),
    }
    PORTAL_STATUS_LABELS = {
        "ABERTO": "Aberto", "EM_ATENDIMENTO": "Em andamento", "RESOLVIDO": "Finalizado",
    }

    @classmethod
    def portal_status_for(cls, status):
        return next((key for key, values in cls.PORTAL_STATUS_GROUPS.items() if status in values), None)

    @property
    def portal_status_label(self):
        return self.PORTAL_STATUS_LABELS.get(self.portal_status_for(self.status), "Estado não reconhecido")


class TicketEvent(models.Model):
    class Origin(models.TextChoices):
        PORTAL = "PORTAL", "Portal"
        PLANNER_SYNC = "PLANNER_SYNC", "Sincronização Planner"
        SYSTEM = "SYSTEM", "Sistema"

    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="events")
    event_type = models.CharField(max_length=50)
    origin = models.CharField(max_length=20, choices=Origin, default=Origin.PORTAL)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    payload = models.JSONField(default=dict)
    summary = models.TextField()
    is_internal = models.BooleanField(default=False)
    detected_at = models.DateTimeField(default=timezone.now)
    idempotency_key = models.CharField(max_length=200, null=True, unique=True)

    class Meta:
        ordering = ["detected_at", "id"]


class TicketAccess(models.Model):
    """Explicit portal-read authorization; Planner remains the workflow owner."""

    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="access_grants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="granted_ticket_accesses",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["ticket", "user"], name="ticket_access_unique")]


class TicketComment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField("Comentário", max_length=5000)
    is_internal = models.BooleanField("Visível somente à TI", default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]


class Attachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="attachments")
    uploader = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    original_name = models.CharField(max_length=160)
    storage_key = models.CharField(max_length=255, unique=True)
    mime_type = models.CharField(max_length=80)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)


class TicketDeletionAudit(models.Model):
    ticket_id = models.UUIDField(db_index=True)
    number = models.CharField(max_length=30)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=30)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)


class PrivateFileDeletion(models.Model):
    audit = models.ForeignKey(TicketDeletionAudit, on_delete=models.PROTECT)
    storage_key = models.CharField(max_length=255, unique=True)
    completed_at = models.DateTimeField(null=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error_code = models.CharField(max_length=40, blank=True)
