# Generated by Django 2.2.1 on 2019-05-18 07:07

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("indieweb", "0002_auto_20190512_0612")]

    operations = [
        migrations.AlterField(
            model_name="auth",
            name="scope",
            field=models.CharField(blank=True, max_length=256, null=True),
        ),
        migrations.AlterField(
            model_name="token",
            name="scope",
            field=models.CharField(blank=True, max_length=256, null=True),
        ),
    ]
