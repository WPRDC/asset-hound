# Generated by Django 3.0.4 on 2020-03-16 16:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('assets', '0008_auto_20200311_1641'),
    ]

    operations = [
        migrations.AddField(
            model_name='assettype',
            name='title',
            field=models.CharField(default='', max_length=255),
            preserve_default=False,
        ),
    ]