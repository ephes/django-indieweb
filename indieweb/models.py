# -*- coding: utf-8 -*-

from django.db import models
from django.conf import settings
from django.utils.crypto import get_random_string

from model_utils.models import TimeStampedModel


class GenKeyMixin:
    def save(self, *args, **kwargs):
        if not self.key:
            self.key = get_random_string(length=32)
        return super().save(*args, **kwargs)


class Auth(GenKeyMixin, TimeStampedModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name='indieweb_auth')
    state = models.IntegerField()
    client_id = models.CharField(max_length=512)
    redirect_uri = models.CharField(max_length=1024)
    scope = models.CharField(max_length=256)
    me = models.CharField(max_length=512)
    key = models.CharField(max_length=32)

    class Meta:
        unique_together = (('me', 'client_id', 'scope', 'owner'))


class Token(GenKeyMixin, TimeStampedModel):
    key = models.CharField(max_length=32)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name='indieweb_token')
    client_id = models.CharField(max_length=512)
    me = models.CharField(max_length=512, unique=True)
    scope = models.CharField(max_length=256)

    class Meta:
        unique_together = (('me', 'client_id', 'scope', 'owner'))
