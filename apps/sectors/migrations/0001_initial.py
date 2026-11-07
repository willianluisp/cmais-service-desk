import django.db.models.deletion
from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    initial = True
    dependencies = [("tickets", "0005_ticketdeletionaudit_privatefiledeletion")]
    operations = [
        migrations.CreateModel(
            name="Sector",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150, unique=True, verbose_name="Nome")),
                ("is_active", models.BooleanField(default=True, verbose_name="Ativo")),
                ("display_order", models.PositiveIntegerField(default=0, verbose_name="Ordem de exibição")),
                ("revision", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["display_order", "name", "pk"], "verbose_name": "Setor", "verbose_name_plural": "Setores",
                     "constraints": [models.UniqueConstraint(Lower("name"), name="sectors_unique_name_ci")]},
        ),
        migrations.CreateModel(
            name="TicketIntakeContext",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sector_name_snapshot", models.CharField(max_length=150)),
                ("service_location", models.CharField(max_length=255)),
                ("sector", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ticket_contexts", to="sectors.sector")),
                ("ticket", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="intake_context", to="tickets.ticket")),
            ],
        ),
    ]
