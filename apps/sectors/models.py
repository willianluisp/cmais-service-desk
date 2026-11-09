from django.db import models
from django.db.models.functions import Lower


class Company(models.Model):
    name = models.CharField("Nome", max_length=150, unique=True)
    is_active = models.BooleanField("Ativa", default=True)
    display_order = models.PositiveIntegerField("Ordem de exibição", default=0)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "name", "pk"]
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"
        constraints = [models.UniqueConstraint(Lower("name"), name="companies_unique_name_ci")]

    def __str__(self):
        return self.name


class Sector(models.Model):
    name = models.CharField("Nome", max_length=150, unique=True)
    is_active = models.BooleanField("Ativo", default=True)
    display_order = models.PositiveIntegerField("Ordem de exibição", default=0)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "name", "pk"]
        verbose_name = "Setor"
        verbose_name_plural = "Setores"
        constraints = [models.UniqueConstraint(Lower("name"), name="sectors_unique_name_ci")]

    def __str__(self):
        return self.name


class TicketIntakeContext(models.Model):
    ticket = models.OneToOneField("tickets.Ticket", on_delete=models.CASCADE, related_name="intake_context")
    sector = models.ForeignKey(Sector, on_delete=models.PROTECT, related_name="ticket_contexts")
    sector_name_snapshot = models.CharField(max_length=150)
    service_location = models.CharField(max_length=255)
