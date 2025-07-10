from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.utils.crypto import get_random_string


class GenKeyMixin(models.Model):
    """Mixin that automatically generates a random key on save if not provided."""

    key: models.CharField[str, str]

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.key:
            self.key = get_random_string(length=32)
        super().save(*args, **kwargs)


class Auth(GenKeyMixin):
    """Stores authorization grants during the IndieAuth flow."""

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
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


class Token(GenKeyMixin):
    """Stores access tokens for authenticated API access."""

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
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
    me = models.CharField(max_length=512)
    scope = models.CharField(max_length=256, null=True, blank=True)  # noqa

    class Meta:
        unique_together = ("me", "client_id", "scope", "owner")

    def __str__(self) -> str:
        return f"{self.client_id} {self.me} {self.scope} {self.owner.username}"


class Webmention(models.Model):
    """
    Model for storing webmentions.

    Webmentions are a W3C recommendation for notifying when one site
    mentions another, enabling cross-site conversations.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("verified", "Verified"),
        ("failed", "Failed"),
        ("spam", "Spam"),
    ]

    MENTION_TYPE_CHOICES = [
        ("mention", "Mention"),
        ("like", "Like"),
        ("reply", "Reply"),
        ("repost", "Repost"),
    ]

    # Core webmention fields
    source_url = models.URLField(max_length=500, db_index=True)
    target_url = models.URLField(max_length=500, db_index=True)

    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    # Parsed content from microformats2
    author_name = models.CharField(max_length=200, blank=True)
    author_url = models.URLField(blank=True)
    author_photo = models.URLField(blank=True)

    content = models.TextField(blank=True)
    content_html = models.TextField(blank=True)
    published = models.DateTimeField(null=True, blank=True)

    # Webmention type
    mention_type = models.CharField(max_length=20, choices=MENTION_TYPE_CHOICES, default="mention")

    # Tracking
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    # Optional spam check result
    spam_check_result = models.JSONField(null=True, blank=True)

    class Meta:
        unique_together = ["source_url", "target_url"]
        indexes = [
            models.Index(fields=["target_url", "status"]),
            models.Index(fields=["created"]),
        ]

    def __str__(self) -> str:
        return f"{self.mention_type}: {self.source_url} -> {self.target_url}"
