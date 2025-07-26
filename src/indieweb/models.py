from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator, URLValidator
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


class Profile(models.Model):
    """User profile with h-card data stored as JSON."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="indieweb_profile")
    h_card = models.JSONField(default=dict, blank=True)

    # Common fields for quick access/querying
    name = models.CharField(max_length=200, blank=True)
    photo_url = models.URLField(blank=True)
    url = models.URLField(blank=True)

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "indieweb_profile"
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self) -> str:
        return f"Profile for {self.user.username}"

    def clean(self) -> None:
        """Validate h_card data before saving."""
        super().clean()
        if self.h_card:
            self._validate_h_card_urls()
            self._validate_h_card_emails()

    def _validate_h_card_urls(self) -> None:
        """Validate all URLs in h_card data."""
        url_validator = URLValidator()
        url_fields = ["url", "photo"]

        for field in url_fields:
            if field in self.h_card:
                for url in self.h_card[field]:
                    # Handle both string URLs and photo objects
                    if isinstance(url, dict) and "value" in url:
                        url_to_validate = url["value"]
                    elif isinstance(url, str):
                        url_to_validate = url
                    else:
                        continue

                    try:
                        url_validator(url_to_validate)
                    except ValidationError as e:
                        raise ValidationError(f"Invalid URL in h_card.{field}: {url_to_validate}") from e

        # Also validate org URLs
        if "org" in self.h_card:
            for org in self.h_card["org"]:
                if isinstance(org, dict) and "url" in org:
                    try:
                        url_validator(org["url"])
                    except ValidationError as e:
                        raise ValidationError(f"Invalid URL in h_card.org.url: {org['url']}") from e

    def _validate_h_card_emails(self) -> None:
        """Validate all emails in h_card data."""
        email_validator = EmailValidator()
        if "email" in self.h_card:
            for email in self.h_card["email"]:
                try:
                    email_validator(email)
                except ValidationError as e:
                    raise ValidationError(f"Invalid email in h_card: {email}") from e

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save profile and sync quick-access fields with h_card data."""
        # Sync fields before saving
        self._sync_fields_from_h_card()

        # Validate
        self.full_clean()

        super().save(*args, **kwargs)

    def _sync_fields_from_h_card(self) -> None:
        """Sync quick-access fields with h_card data."""
        if not self.h_card:
            return

        # Sync name
        if "name" in self.h_card and self.h_card["name"]:
            self.name = self.h_card["name"][0]

        # Sync URL
        if "url" in self.h_card and self.h_card["url"]:
            self.url = self.h_card["url"][0]

        # Sync photo URL
        if "photo" in self.h_card and self.h_card["photo"]:
            photo = self.h_card["photo"][0]
            if isinstance(photo, dict) and "value" in photo:
                self.photo_url = photo["value"]
            elif isinstance(photo, str):
                self.photo_url = photo
