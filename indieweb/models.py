# -*- coding: utf-8 -*-

from django.db import models
from django.conf import settings

from model_utils.models import TimeStampedModel


class Auth(TimeStampedModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name='indieweb_auth')
    state = models.IntegerField()
    client_id = models.CharField(max_length=512)
    redirect_uri = models.CharField(max_length=1024)
    scope = models.CharField(max_length=256)
    me = models.CharField(max_length=512)
    key = models.CharField(max_length=128)


class Token(TimeStampedModel):
    pass
