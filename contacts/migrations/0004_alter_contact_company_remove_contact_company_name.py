# Generated manually to enforce non-nullable constraint after data migration

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0003_contact_company'),
        ('companies', '0002_migrate_legacy_companies'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='contact',
            name='company_name',
        ),
        migrations.AlterField(
            model_name='contact',
            name='company',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='contacts',
                to='companies.company'
            ),
        ),
    ]
