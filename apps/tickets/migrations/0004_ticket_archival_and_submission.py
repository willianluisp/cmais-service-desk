from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tickets", "0003_ticket_planner_deleted_at")]
    operations = [
        migrations.AddField(model_name="ticket", name="archived_at", field=models.DateTimeField(blank=True, db_index=True, null=True)),
        migrations.AddField(model_name="ticket", name="archive_reason", field=models.CharField(blank=True, max_length=40)),
        migrations.AddField(model_name="ticket", name="submission_key", field=models.UUIDField(blank=True, editable=False, null=True, unique=True)),
    ]
