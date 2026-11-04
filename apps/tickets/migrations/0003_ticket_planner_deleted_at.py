from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tickets", "0002_planner_read_projection")]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="planner_deleted_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
