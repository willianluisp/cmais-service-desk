import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('planner_integration', '0006_microsoftoauthconfiguration')]

    operations = [migrations.CreateModel(
        name='PlannerRuntime',
        fields=[
            ('id', models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
            ('plans', models.JSONField(default=list)),
            ('automation_enabled', models.BooleanField(default=None, null=True)),
            ('sync_requested', models.BooleanField(default=False)),
            ('connection_checked_at', models.DateTimeField(null=True)),
            ('connection_error', models.CharField(blank=True, max_length=50)),
            ('last_started_at', models.DateTimeField(null=True)),
            ('last_finished_at', models.DateTimeField(null=True)),
            ('lease_id', models.UUIDField(null=True)),
            ('lease_until', models.DateTimeField(null=True)),
            ('throttle_until', models.DateTimeField(null=True)),
            ('configuration', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to='planner_integration.plannerconfiguration')),
        ],
    )]
