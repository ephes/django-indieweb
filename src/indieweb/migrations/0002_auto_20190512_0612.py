# Generated by Django 2.2.1 on 2019-05-12 11:12

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("indieweb", "0001_initial")]

    operations = [migrations.AlterField(model_name="auth", name="state", field=models.CharField(max_length=32))]
