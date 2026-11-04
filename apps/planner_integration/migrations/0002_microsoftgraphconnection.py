from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("planner_integration", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="MicrosoftGraphConnection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant_id", models.CharField(max_length=64)),
                ("microsoft_user_id", models.CharField(max_length=255, unique=True)),
                ("microsoft_user_principal_name", models.CharField(max_length=320)),
                ("scopes", models.TextField()),
                ("access_token_encrypted", models.TextField()),
                ("refresh_token_encrypted", models.TextField()),
                ("access_token_expires_at", models.DateTimeField()),
                ("is_active", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="graph_connection", to="auth.user")),
            ],
        ),
        migrations.AddConstraint(
            model_name="microsoftgraphconnection",
            constraint=models.UniqueConstraint(condition=models.Q(is_active=True), fields=("is_active",), name="planner_one_active_delegated_connection"),
        ),
    ]
