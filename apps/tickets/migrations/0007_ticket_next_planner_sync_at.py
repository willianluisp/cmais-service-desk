import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('tickets', '0006_sensitive_tickets')]

    operations = [migrations.AddField(
        model_name='ticket', name='next_planner_sync_at',
        field=models.DateTimeField(db_index=True, default=django.utils.timezone.now),
    )]
