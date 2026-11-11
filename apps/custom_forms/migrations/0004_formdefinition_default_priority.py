from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('custom_forms', '0003_forms_evolution')]

    operations = [
        migrations.AddField(
            model_name='formdefinition', name='default_priority',
            field=models.CharField(choices=[('BAIXA', 'Baixa'), ('NORMAL', 'Normal'), ('ALTA', 'Alta'), ('CRITICA', 'Crítica')],
                                   default='NORMAL', max_length=10),
        ),
    ]
