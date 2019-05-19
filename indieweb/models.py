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
        settings.AUTH_USER_MODEL, related_name="indieweb_auth", on_delete=models.CASCADE
    )
    state = models.CharField(max_length=32)
    client_id = models.CharField(max_length=512)
    redirect_uri = models.CharField(max_length=1024)
    scope = models.CharField(max_length=256, null=True, blank=True)
    me = models.CharField(max_length=512)
    key = models.CharField(max_length=32)

    class Meta:
        unique_together = ("me", "client_id", "scope", "owner")

    def __str__(self):
        return f"{self.client_id} {self.me} {self.scope} {self.owner.username}"


class Token(GenKeyMixin, TimeStampedModel):
    key = models.CharField(max_length=32, db_index=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="indieweb_token",
        on_delete=models.CASCADE,
    )
    client_id = models.CharField(max_length=512)
    me = models.CharField(max_length=512, unique=True)
    scope = models.CharField(max_length=256, null=True, blank=True)

    class Meta:
        unique_together = ("me", "client_id", "scope", "owner")
