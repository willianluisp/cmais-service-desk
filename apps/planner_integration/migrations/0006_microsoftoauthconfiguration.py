from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("planner_integration", "0005_provisioning_cancelled")]

    operations = [
        migrations.CreateModel(
            name="MicrosoftOAuthConfiguration",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.CharField(max_length=64)),
                ("client_id", models.CharField(max_length=255)),
                ("client_secret_encrypted", models.TextField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
