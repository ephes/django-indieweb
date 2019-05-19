# Generated by Django 2.2.1 on 2019-05-11 14:38

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import indieweb.models
import model_utils.fields


class Migration(migrations.Migration):

    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="Token",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("key", models.CharField(db_index=True, max_length=32)),
                ("client_id", models.CharField(max_length=512)),
                ("me", models.CharField(max_length=512, unique=True)),
                ("scope", models.CharField(max_length=256)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="indieweb_token",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"unique_together": {("me", "client_id", "scope", "owner")}},
            bases=(indieweb.models.GenKeyMixin, models.Model),
        ),
        migrations.CreateModel(
            name="Auth",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("state", models.IntegerField()),
                ("client_id", models.CharField(max_length=512)),
                ("redirect_uri", models.CharField(max_length=1024)),
                ("scope", models.CharField(max_length=256)),
                ("me", models.CharField(max_length=512)),
                ("key", models.CharField(max_length=32)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="indieweb_auth",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"unique_together": {("me", "client_id", "scope", "owner")}},
            bases=(indieweb.models.GenKeyMixin, models.Model),
        ),
    ]
