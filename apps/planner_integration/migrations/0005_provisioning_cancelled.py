from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("planner_integration", "0004_attachmentpublication")]
    operations = [
        migrations.AlterField(
            model_name="plannertaskprovisioning", name="state",
            field=models.CharField(max_length=20, default="PENDING", choices=[
                ("PENDING", "Pendente"), ("LINKED", "Vinculado"),
                ("RECONCILIATION", "Requer conferência"), ("FAILED", "Falhou"),
                ("CANCELLED", "Cancelado; registro arquivado"),
            ]),
        ),
    ]
