from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator, URLValidator
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string

TOKEN_KEY_HASH_PREFIX = "hmac-sha256$"
TOKEN_KEY_LENGTH = 32
AUTH_KEY_LENGTH = 32
AUTH_KEY_STORAGE_MAX_LENGTH = 80
WEBMENTION_STATUS_TOKEN_LENGTH = 48
WEBSUB_SECRET_ENCRYPTED_PREFIX = "fernet$"
WEBSUB_SECRET_KEY_SALT = b"django-indieweb-websub-secret-v1"
WEBSUB_SECRET_STORAGE_MAX_LENGTH = 512


def generate_webmention_status_token() -> str:
    """Return an unguessable token for public Webmention status URLs."""
    return get_random_string(length=WEBMENTION_STATUS_TOKEN_LENGTH)


def _websub_secret_fernet() -> Fernet:
    key_material = hmac.new(
        str(settings.SECRET_KEY).encode("utf-8"),
        WEBSUB_SECRET_KEY_SALT,
        hashlib.sha256,
    ).digest()
    return Fernet(base64.urlsafe_b64encode(key_material))


class WebSubSecretDecryptionError(ValueError):
    """Stored WebSub shared secret could not be decrypted."""


class GenKeyMixin(models.Model):
    """Mixin that automatically generates a random key on save if not provided."""

    key: models.CharField[str, str]

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.key:
            self.key = get_random_string(length=32)
        super().save(*args, **kwargs)


class Auth(models.Model):
    """Stores authorization grants during the IndieAuth flow."""

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    """
    Model for storing IndieAuth authorization codes.

    Used during the IndieAuth flow to temporarily store authorization details
    before exchanging the auth code for an access token.
    """

    key = models.CharField(max_length=AUTH_KEY_STORAGE_MAX_LENGTH, unique=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="indieweb_auth", on_delete=models.CASCADE)
    state = models.CharField(max_length=32)
    client_id = models.CharField(max_length=512)
    redirect_uri = models.CharField(max_length=1024)
    scope = models.CharField(max_length=256, null=True, blank=True)  # noqa
    me = models.CharField(max_length=512)
    code_challenge = models.CharField(max_length=128, null=True, blank=True)  # noqa: DJ001
    code_challenge_method = models.CharField(max_length=8, null=True, blank=True)  # noqa: DJ001

    class Meta:
        unique_together = ("me", "client_id", "scope", "owner")

    def __str__(self) -> str:
        return f"{self.client_id} {self.me} {self.scope} {self.owner.username}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        key_changed = False
        raw_key = self.raw_key
        if not self.key:
            self.set_key()
            key_changed = True
        elif not self.is_hashed_key(self.key):
            self.set_key(self.key)
            key_changed = True
        if key_changed:
            raw_key = self.raw_key
        if key_changed and kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"key"}
        super().save(*args, **kwargs)
        if raw_key is not None:
            self.key = raw_key

    @classmethod
    def make_raw_key(cls) -> str:
        """Return a new raw authorization code value for one-time issuance."""
        return get_random_string(length=AUTH_KEY_LENGTH)

    @classmethod
    def hash_key(cls, raw_key: str) -> str:
        """Return the stable at-rest HMAC digest for a raw authorization code."""
        digest = hmac.new(
            str(settings.SECRET_KEY).encode("utf-8"),
            raw_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{TOKEN_KEY_HASH_PREFIX}{digest}"

    @classmethod
    def is_hashed_key(cls, value: str) -> bool:
        """Return whether ``value`` begins with the reserved at-rest hash prefix."""
        return value.startswith(TOKEN_KEY_HASH_PREFIX)

    @classmethod
    def get_for_raw_key(cls, raw_key: str, **filters: Any) -> Auth:
        """Return the authorization row matching ``raw_key`` without storing the raw value."""
        if cls.is_hashed_key(raw_key):
            raise cls.DoesNotExist
        hashed_key = cls.hash_key(raw_key)
        try:
            auth = cls.objects.get(key=hashed_key, **filters)
        except cls.DoesNotExist:
            auth = cls.objects.get(key=raw_key, **filters)
        if not hmac.compare_digest(auth.key, hashed_key) and not hmac.compare_digest(auth.key, raw_key):
            raise cls.DoesNotExist
        return auth

    def set_key(self, raw_key: str | None = None) -> str:
        """Set a new authorization code hash and return the raw value for issuance."""
        raw_key = raw_key or self.make_raw_key()
        self.key = self.hash_key(raw_key)
        self._raw_key = raw_key
        return raw_key

    @property
    def raw_key(self) -> str | None:
        """Return the one-time raw authorization code when this instance just generated one."""
        return getattr(self, "_raw_key", None)

    def masked_key(self) -> str:
        """Return a non-secret display form for the stored authorization code hash."""
        if not self.key:
            return ""
        if self.is_hashed_key(self.key):
            return f"{TOKEN_KEY_HASH_PREFIX}..."
        return "legacy-plaintext-code-hidden"


class Token(GenKeyMixin):
    """Stores access tokens for authenticated API access."""

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    """
    Model for storing IndieAuth/Micropub access tokens.

    Represents long-lived access tokens that clients can use to authenticate
    requests to the Micropub endpoint and other IndieWeb services.
    """

    key = models.CharField(max_length=80, unique=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="indieweb_token",
        on_delete=models.CASCADE,
    )
    client_id = models.CharField(max_length=512)
    me = models.CharField(max_length=512)
    scope = models.CharField(max_length=256, null=True, blank=True)  # noqa
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        unique_together = ("me", "client_id", "scope", "owner")

    def __str__(self) -> str:
        return f"{self.client_id} {self.me} {self.scope} {self.owner.username}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        key_changed = False
        raw_key = self.raw_key
        if not self.key:
            self.set_key()
            key_changed = True
        elif not self.is_hashed_key(self.key):
            self.set_key(self.key)
            key_changed = True
        if key_changed:
            raw_key = self.raw_key
        if key_changed and kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"key"}
        super().save(*args, **kwargs)
        if raw_key is not None:
            self.key = raw_key

    @classmethod
    def make_raw_key(cls) -> str:
        """Return a new raw bearer token value for one-time display."""
        return get_random_string(length=TOKEN_KEY_LENGTH)

    @classmethod
    def hash_key(cls, raw_key: str) -> str:
        """Return the stable at-rest HMAC digest for a raw bearer token."""
        digest = hmac.new(
            str(settings.SECRET_KEY).encode("utf-8"),
            raw_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{TOKEN_KEY_HASH_PREFIX}{digest}"

    @classmethod
    def is_hashed_key(cls, value: str) -> bool:
        """Return whether ``value`` begins with the reserved at-rest hash prefix."""
        return value.startswith(TOKEN_KEY_HASH_PREFIX)

    @classmethod
    def get_for_raw_key(cls, raw_key: str) -> Token:
        """Return the token matching ``raw_key`` without storing the raw value."""
        if cls.is_hashed_key(raw_key):
            raise cls.DoesNotExist
        queryset = cls.objects.select_related("owner")
        hashed_key = cls.hash_key(raw_key)
        try:
            token = queryset.get(key=hashed_key)
        except cls.DoesNotExist:
            token = queryset.get(key=raw_key)
        # Keep the final secret comparison constant-time even though the indexed
        # lookup should already have constrained the candidate row.
        if not hmac.compare_digest(token.key, hashed_key) and not hmac.compare_digest(token.key, raw_key):
            raise cls.DoesNotExist
        return token

    def set_key(self, raw_key: str | None = None) -> str:
        """Set a new bearer token hash and return the raw value for issuance."""
        raw_key = raw_key or self.make_raw_key()
        self.key = self.hash_key(raw_key)
        self._raw_key = raw_key
        return raw_key

    @property
    def raw_key(self) -> str | None:
        """Return the one-time raw key when this instance just generated one."""
        return getattr(self, "_raw_key", None)

    def masked_key(self) -> str:
        """Return a non-secret display form for the stored token hash."""
        if not self.key:
            return ""
        if self.is_hashed_key(self.key):
            return f"{TOKEN_KEY_HASH_PREFIX}..."
        return "legacy-plaintext-token-hidden"

    def is_expired(self) -> bool:
        """Return True if the token has an expires_at in the past.

        Tokens with ``expires_at`` set to ``None`` are treated as
        non-expiring for backwards compatibility with rows created
        before expiration tracking was added.
        """
        if self.expires_at is None:
            return False
        return self.expires_at <= timezone.now()


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
    vouch_url = models.URLField(max_length=500, blank=True)

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
    vouch_verified_at = models.DateTimeField(null=True, blank=True)
    # Wall-clock time at which the most recent processing pipeline fetched
    # (or attempted to fetch) the source URL. Used as a freshness signal so
    # an older concurrent receive cannot overwrite a newer outcome that has
    # already been committed.
    last_received_at = models.DateTimeField(null=True, blank=True)

    # Optional spam check result
    spam_check_result = models.JSONField(null=True, blank=True)
    status_token = models.CharField(
        max_length=WEBMENTION_STATUS_TOKEN_LENGTH,
        unique=True,
        db_index=True,
        default=generate_webmention_status_token,
    )

    class Meta:
        unique_together = ["source_url", "target_url"]
        indexes = [
            models.Index(fields=["target_url", "status"]),
            models.Index(fields=["created"]),
        ]

    def __str__(self) -> str:
        return f"{self.mention_type}: {self.source_url} -> {self.target_url}"


class WebmentionSourceSnapshot(models.Model):
    """Latest fetched source snapshot for a submitted Webmention."""

    webmention = models.OneToOneField(
        Webmention,
        on_delete=models.CASCADE,
        related_name="source_snapshot",
    )
    raw_source_html = models.TextField()
    final_source_url = models.URLField(max_length=500)
    content_digest = models.CharField(max_length=64)
    fetched_at = models.DateTimeField()
    parsed_h_entry = models.JSONField(default=dict, blank=True)
    nested_response_identities = models.JSONField(default=list, blank=True)

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Source snapshot for {self.webmention_id}"


class WebmentionNestedResponse(models.Model):
    """Nested response discovered inside a verified parent Webmention source."""

    STATUS_CHOICES = [
        ("verified", "Verified"),
        ("missing", "Missing"),
        ("failed", "Failed"),
        ("spam", "Spam"),
    ]

    webmention = models.ForeignKey(
        Webmention,
        on_delete=models.CASCADE,
        related_name="nested_responses",
    )
    identity = models.CharField(max_length=500)
    response_url = models.URLField(max_length=500, blank=True)

    author_name = models.CharField(max_length=200, blank=True)
    author_url = models.URLField(blank=True)
    author_photo = models.URLField(blank=True)

    content = models.TextField(blank=True)
    content_html = models.TextField(blank=True)
    published = models.DateTimeField(null=True, blank=True)
    mention_type = models.CharField(max_length=20, choices=Webmention.MENTION_TYPE_CHOICES, default="mention")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="verified")
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    parsed_h_entry = models.JSONField(default=dict, blank=True)
    content_digest = models.CharField(max_length=64, blank=True)

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["webmention", "identity"], name="indieweb_nested_response_identity_uniq"),
        ]
        indexes = [
            models.Index(fields=["webmention", "status"]),
            models.Index(fields=["identity"]),
        ]

    def __str__(self) -> str:
        return f"Nested {self.mention_type}: {self.identity}"

    @property
    def is_currently_displayable(self) -> bool:
        """Return whether this child response is current under a verified parent."""
        if self.status != "verified":
            return False
        if self.__class__.webmention.is_cached(self):
            return self.webmention.status == "verified"
        return Webmention.objects.only("status").filter(pk=self.webmention_id, status="verified").exists()


class WebmentionOutboundTarget(models.Model):
    """Outbound Webmention target history for a source and target URL pair."""

    source_url = models.URLField(max_length=500, db_index=True, validators=[URLValidator(schemes=["http", "https"])])
    target_url = models.URLField(max_length=500, db_index=True, validators=[URLValidator(schemes=["http", "https"])])
    endpoint_url = models.URLField(max_length=500, blank=True, validators=[URLValidator(schemes=["http", "https"])])
    endpoint_discovered_at = models.DateTimeField(null=True, blank=True)

    first_sent_at = models.DateTimeField(null=True, blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    last_attempted_at = models.DateTimeField(null=True, blank=True)
    last_status_code = models.PositiveIntegerField(null=True, blank=True)
    last_success = models.BooleanField(default=False)
    last_error = models.TextField(blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_vouch_url = models.URLField(max_length=500, blank=True, validators=[URLValidator(schemes=["http", "https"])])
    last_seen_in_source_at = models.DateTimeField(null=True, blank=True)

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source_url", "target_url"], name="indieweb_outbound_target_uniq"),
        ]

    def __str__(self) -> str:
        return f"Outbound Webmention: {self.source_url} -> {self.target_url}"


def generate_websub_callback_token() -> str:
    """Return an unguessable token for a WebSub subscriber callback URL."""
    return get_random_string(length=64)


class WebSubSubscription(models.Model):
    """Host-level WebSub subscriber state for one hub/topic pair."""

    STATE_PENDING_SUBSCRIBE = "pending_subscribe"
    STATE_ACTIVE = "active"
    STATE_PENDING_UNSUBSCRIBE = "pending_unsubscribe"
    STATE_UNSUBSCRIBED = "unsubscribed"
    STATE_DENIED = "denied"

    STATE_CHOICES = [
        (STATE_PENDING_SUBSCRIBE, "Pending subscribe"),
        (STATE_ACTIVE, "Active"),
        (STATE_PENDING_UNSUBSCRIBE, "Pending unsubscribe"),
        (STATE_UNSUBSCRIBED, "Unsubscribed"),
        (STATE_DENIED, "Denied"),
    ]

    MODE_SUBSCRIBE = "subscribe"
    MODE_UNSUBSCRIBE = "unsubscribe"
    MODE_CHOICES = [
        (MODE_SUBSCRIBE, "Subscribe"),
        (MODE_UNSUBSCRIBE, "Unsubscribe"),
    ]

    hub_url = models.URLField(max_length=500, validators=[URLValidator(schemes=["http", "https"])])
    topic_url = models.URLField(max_length=500, validators=[URLValidator(schemes=["http", "https"])])
    callback_token = models.CharField(
        max_length=64, unique=True, db_index=True, default=generate_websub_callback_token
    )
    state = models.CharField(max_length=32, choices=STATE_CHOICES, default=STATE_PENDING_SUBSCRIBE)

    pending_mode = models.CharField(max_length=16, choices=MODE_CHOICES, blank=True)
    requested_lease_seconds = models.PositiveIntegerField(null=True, blank=True)
    confirmed_lease_seconds = models.PositiveIntegerField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    secret = models.CharField(max_length=WEBSUB_SECRET_STORAGE_MAX_LENGTH, blank=True)
    pending_secret = models.CharField(max_length=WEBSUB_SECRET_STORAGE_MAX_LENGTH, blank=True)
    pending_secret_set = models.BooleanField(default=False)

    last_challenge = models.CharField(max_length=200, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_request_at = models.DateTimeField(null=True, blank=True)
    last_request_mode = models.CharField(max_length=16, choices=MODE_CHOICES, blank=True)
    last_request_status_code = models.PositiveIntegerField(null=True, blank=True)
    last_request_error = models.TextField(blank=True)
    last_denied_at = models.DateTimeField(null=True, blank=True)
    last_denied_mode = models.CharField(max_length=16, choices=MODE_CHOICES, blank=True)
    last_denial_reason = models.CharField(max_length=500, blank=True)

    last_delivery_at = models.DateTimeField(null=True, blank=True)
    last_delivery_content_type = models.CharField(max_length=200, blank=True)
    last_delivery_size = models.PositiveIntegerField(null=True, blank=True)
    last_delivery_digest = models.CharField(max_length=64, blank=True)
    last_delivery_signature_algorithm = models.CharField(max_length=32, blank=True)
    last_delivery_status_code = models.PositiveIntegerField(null=True, blank=True)
    last_delivery_error = models.TextField(blank=True)
    last_accepted_delivery_at = models.DateTimeField(null=True, blank=True)
    last_accepted_delivery_digest = models.CharField(max_length=64, blank=True)
    recent_accepted_delivery_digests = models.JSONField(default=list, blank=True)

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["hub_url", "topic_url"], name="indieweb_websub_hub_topic_uniq"),
        ]
        indexes = [
            models.Index(fields=["topic_url", "state"]),
            models.Index(fields=["lease_expires_at"]),
        ]

    def __str__(self) -> str:
        return f"WebSub {self.state}: {self.topic_url} via {self.hub_url}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.secret and not self.is_encrypted_secret(self.secret):
            self.secret = self.encrypt_secret(self.secret)
        if self.pending_secret and not self.is_encrypted_secret(self.pending_secret):
            self.pending_secret = self.encrypt_secret(self.pending_secret)
        super().save(*args, **kwargs)

    @classmethod
    def is_encrypted_secret(cls, value: str) -> bool:
        """Return whether ``value`` is stored in encrypted-at-rest form."""
        return value.startswith(WEBSUB_SECRET_ENCRYPTED_PREFIX)

    @classmethod
    def encrypt_secret(cls, raw_secret: str) -> str:
        """Return encrypted-at-rest storage for a raw WebSub shared secret."""
        token = _websub_secret_fernet().encrypt(raw_secret.encode("utf-8")).decode("ascii")
        return f"{WEBSUB_SECRET_ENCRYPTED_PREFIX}{token}"

    @classmethod
    def decrypt_secret(cls, stored_secret: str) -> str:
        """Return the raw WebSub shared secret from storage."""
        if not stored_secret:
            return ""
        if not cls.is_encrypted_secret(stored_secret):
            return stored_secret
        token = stored_secret.removeprefix(WEBSUB_SECRET_ENCRYPTED_PREFIX)
        try:
            return _websub_secret_fernet().decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise WebSubSecretDecryptionError("WebSub secret could not be decrypted") from exc

    def get_secret(self) -> str:
        """Return the active raw WebSub shared secret for HMAC validation."""
        return self.decrypt_secret(self.secret)

    def set_secret(self, raw_secret: str) -> None:
        """Stage a raw active WebSub shared secret for encrypted storage."""
        self.secret = self.encrypt_secret(raw_secret) if raw_secret else ""

    def get_pending_secret(self) -> str:
        """Return the pending raw WebSub shared secret for verification."""
        return self.decrypt_secret(self.pending_secret)

    def set_pending_secret(self, raw_secret: str) -> None:
        """Stage a raw pending WebSub shared secret for encrypted storage."""
        self.pending_secret = self.encrypt_secret(raw_secret) if raw_secret else ""

    def masked_callback_token(self) -> str:
        """Return a non-secret display form for the callback token."""
        if not self.callback_token:
            return ""
        return f"{self.callback_token[:6]}...{self.callback_token[-6:]}"

    def masked_secret(self) -> str:
        """Return a non-secret display form for the active WebSub secret."""
        return "configured" if self.secret else ""

    def masked_pending_secret(self) -> str:
        """Return a non-secret display form for the pending WebSub secret."""
        return "configured" if self.pending_secret else ""


class WebSubDeliveryAttempt(models.Model):
    """Metadata-only history for one WebSub content distribution attempt."""

    subscription = models.ForeignKey(
        WebSubSubscription,
        related_name="delivery_attempts",
        on_delete=models.CASCADE,
    )
    received_at = models.DateTimeField(db_index=True)
    content_type = models.CharField(max_length=200, blank=True)
    size = models.PositiveIntegerField(null=True, blank=True)
    digest = models.CharField(max_length=64, blank=True)
    signature_algorithm = models.CharField(max_length=32, blank=True)
    status_code = models.PositiveIntegerField()
    error = models.CharField(max_length=500, blank=True)

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["subscription", "received_at"]),
            models.Index(fields=["status_code", "received_at"]),
        ]
        ordering = ("-received_at", "-pk")

    def __str__(self) -> str:
        return f"WebSub delivery {self.status_code}: {self.subscription_id} at {self.received_at}"


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

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save profile and sync quick-access fields with h_card data."""
        # Sync fields before saving
        self._sync_fields_from_h_card()

        # Validate
        self.full_clean()

        super().save(*args, **kwargs)

    def clean(self) -> None:
        """Validate h_card data before saving."""
        super().clean()
        if self.h_card:
            self._validate_h_card_urls()
            self._validate_h_card_emails()

    def _validate_h_card_urls(self) -> None:
        """Validate all URLs in h_card data."""
        url_validator = URLValidator()

        for field in ("url", "photo"):
            if field in self.h_card:
                for url in self.h_card[field]:
                    self._validate_single_url(url_validator, url, f"h_card.{field}")

        if "org" in self.h_card:
            for org in self.h_card["org"]:
                if isinstance(org, dict) and "url" in org:
                    self._validate_single_url(url_validator, org["url"], "h_card.org.url")

    @staticmethod
    def _validate_single_url(validator: URLValidator, url: str | dict[str, Any], context: str) -> None:
        """Validate a single URL value (string or dict with 'value' key)."""
        if isinstance(url, dict) and "value" in url:
            url_to_validate = url["value"]
        elif isinstance(url, str):
            url_to_validate = url
        else:
            return

        try:
            validator(url_to_validate)
        except ValidationError as e:
            raise ValidationError(f"Invalid URL in {context}: {url_to_validate}") from e

    def _validate_h_card_emails(self) -> None:
        """Validate all emails in h_card data."""
        email_validator = EmailValidator()
        if "email" in self.h_card:
            for email in self.h_card["email"]:
                try:
                    email_validator(email)
                except ValidationError as e:
                    raise ValidationError(f"Invalid email in h_card: {email}") from e

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
