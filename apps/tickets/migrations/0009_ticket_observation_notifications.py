from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0008_ticket_company_ticket_company_name_snapshot'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='observations_seen_until',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='ticket',
            name='observations_pending',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='ticket',
            name='observation_last_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
