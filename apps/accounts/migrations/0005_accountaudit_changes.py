from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0004_local_accounts')]
    operations = [migrations.AddField(model_name='accountaudit', name='changes',
                                    field=models.JSONField(default=dict, blank=True))]
