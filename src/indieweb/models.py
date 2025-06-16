from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.utils.crypto import get_random_string
from model_utils.models import TimeStampedModel


class GenKeyMixin(models.Model):
    """Mixin that automatically generates a random key on save if not provided."""

    key: models.CharField[str, str]

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.key:
            self.key = get_random_string(length=32)
        super().save(*args, **kwargs)


class Auth(GenKeyMixin, TimeStampedModel):
    """
    Model for storing IndieAuth authorization codes.

    Used during the IndieAuth flow to temporarily store authorization details
    before exchanging the auth code for an access token.
    """

    key = models.CharField(max_length=32)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="indieweb_auth", on_delete=models.CASCADE)
    state = models.CharField(max_length=32)
    client_id = models.CharField(max_length=512)
    redirect_uri = models.CharField(max_length=1024)
    scope = models.CharField(max_length=256, null=True, blank=True)  # noqa
    me = models.CharField(max_length=512)

    class Meta:
        unique_together = ("me", "client_id", "scope", "owner")

    def __str__(self) -> str:
        return f"{self.client_id} {self.me} {self.scope} {self.owner.username}"


class Token(GenKeyMixin, TimeStampedModel):
    """
    Model for storing IndieAuth/Micropub access tokens.

    Represents long-lived access tokens that clients can use to authenticate
    requests to the Micropub endpoint and other IndieWeb services.
    """

    key = models.CharField(max_length=32, db_index=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="indieweb_token",
        on_delete=models.CASCADE,
    )
    client_id = models.CharField(max_length=512)
    me = models.CharField(max_length=512, unique=True)
    scope = models.CharField(max_length=256, null=True, blank=True)  # noqa

    class Meta:
        unique_together = ("me", "client_id", "scope", "owner")

    def __str__(self) -> str:
        return f"{self.client_id} {self.me} {self.scope} {self.owner.username}"
