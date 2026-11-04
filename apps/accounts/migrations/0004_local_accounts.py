from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_userprofile_unique_planner_identity"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name="LocalAccount", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("must_change_password", models.BooleanField(default=True)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="local_account", to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name="AccountAudit", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("action", models.CharField(max_length=50)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("actor", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="account_actions", to=settings.AUTH_USER_MODEL)),
            ("target", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="account_changes", to=settings.AUTH_USER_MODEL)),
        ]),
    ]
