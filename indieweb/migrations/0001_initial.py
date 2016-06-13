# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import model_utils.fields
import django.utils.timezone
import indieweb.models
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Auth',
            fields=[
                ('id', models.AutoField(verbose_name='ID', auto_created=True, serialize=False, primary_key=True)),
                ('created', model_utils.fields.AutoCreatedField(verbose_name='created', editable=False, default=django.utils.timezone.now)),
                ('modified', model_utils.fields.AutoLastModifiedField(verbose_name='modified', editable=False, default=django.utils.timezone.now)),
                ('state', models.IntegerField()),
                ('client_id', models.CharField(max_length=512)),
                ('redirect_uri', models.CharField(max_length=1024)),
                ('scope', models.CharField(max_length=256)),
                ('me', models.CharField(max_length=512)),
                ('key', models.CharField(max_length=32)),
                ('owner', models.ForeignKey(to=settings.AUTH_USER_MODEL, related_name='indieweb_auth')),
            ],
            bases=(indieweb.models.GenKeyMixin, models.Model),
        ),
        migrations.CreateModel(
            name='Token',
            fields=[
                ('id', models.AutoField(verbose_name='ID', auto_created=True, serialize=False, primary_key=True)),
                ('created', model_utils.fields.AutoCreatedField(verbose_name='created', editable=False, default=django.utils.timezone.now)),
                ('modified', model_utils.fields.AutoLastModifiedField(verbose_name='modified', editable=False, default=django.utils.timezone.now)),
                ('key', models.CharField(max_length=32)),
                ('client_id', models.CharField(max_length=512)),
                ('me', models.CharField(max_length=512, unique=True)),
                ('scope', models.CharField(max_length=256)),
                ('owner', models.ForeignKey(to=settings.AUTH_USER_MODEL, related_name='indieweb_token')),
            ],
            bases=(indieweb.models.GenKeyMixin, models.Model),
        ),
        migrations.AlterUniqueTogether(
            name='token',
            unique_together=set([('me', 'client_id', 'scope', 'owner')]),
        ),
        migrations.AlterUniqueTogether(
            name='auth',
            unique_together=set([('me', 'client_id', 'scope', 'owner')]),
        ),
    ]
