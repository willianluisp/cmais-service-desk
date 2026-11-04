from django.db import models
from django.utils import timezone


class NotificationOutbox(models.Model):
    class State(models.TextChoices):
        PENDING = "PENDING", "Pendente"
        SENT = "SENT", "Enviado ao provedor"
        FAILED = "FAILED", "Falhou"

    event = models.ForeignKey(
        "tickets.TicketEvent", null=True, blank=True, on_delete=models.PROTECT
    )
    ticket = models.ForeignKey("tickets.Ticket", null=True, blank=True, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=200, unique=True)
    recipient = models.EmailField()
    channel = models.CharField(max_length=20, default="email")
    template_key = models.CharField(max_length=50, default="ticket-event-v1")
    subject = models.CharField(max_length=255)
    body_text = models.TextField()
    body_html = models.TextField(blank=True)
    state = models.CharField(max_length=10, choices=State, default=State.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["state", "available_at"], name="outbox_ready_idx")]
