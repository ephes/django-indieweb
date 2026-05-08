"""WebSub publisher and subscriber helpers."""

from __future__ import annotations

import hashlib
import hmac
import inspect
import logging
import warnings
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.http import HttpResponseBase
from django.utils import timezone
from django.utils.module_loading import import_string

from .http_client import (
    HTTPResponseTooLarge,
    UnsafeHTTPUrlError,
    WebmentionRedirectError,
    default_address_resolver,
    request_with_safe_redirects,
    validate_safe_http_url,
)
from .models import (
    WEBSUB_SECRET_ENCRYPTED_PREFIX,
    WebSubAcceptedDelivery,
    WebSubDeliveryAttempt,
    WebSubSubscription,
)

logger = logging.getLogger(__name__)

DEFAULT_WEBSUB_TIMEOUT = 10.0
DEFAULT_WEBSUB_DELIVERY_MAX_BYTES = 1024 * 1024
DEFAULT_WEBSUB_HUB_RESPONSE_MAX_BYTES = 256 * 1024
DEFAULT_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS = 300
DEFAULT_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX = 64
DEFAULT_WEBSUB_MIN_LEASE_SECONDS = 5 * 60
DEFAULT_WEBSUB_MAX_LEASE_SECONDS = 30 * 24 * 60 * 60
WEBSUB_LEASE_BOUNDS_FLOOR_SECONDS = 60
WEBSUB_LEASE_BOUNDS_CEILING_SECONDS = 90 * 24 * 60 * 60
WEBSUB_SECRET_MIN_BYTES = 20
WEBSUB_SECRET_MAX_BYTES = 200
WEBSUB_ALLOWED_SCHEMES = ("http", "https")
WEBSUB_SUBSCRIPTION_MODES = (WebSubSubscription.MODE_SUBSCRIBE, WebSubSubscription.MODE_UNSUBSCRIBE)
WEBSUB_SIGNATURE_ALGORITHMS = {
    "sha1": hashlib.sha1,
    "sha256": hashlib.sha256,
    "sha384": hashlib.sha384,
    "sha512": hashlib.sha512,
}
WEBSUB_SIGNATURE_STRENGTH = {"sha1": 1, "sha256": 2, "sha384": 3, "sha512": 4}


@dataclass(frozen=True)
class WebSubLink:
    """One WebSub discovery link."""

    rel: str
    url: str


@dataclass(frozen=True)
class WebSubNotificationResult:
    """Result from notifying one WebSub hub about a changed topic."""

    hub_url: str
    topic_url: str
    success: bool
    status_code: int | None = None
    error: str = ""


@dataclass(frozen=True)
class WebSubSubscriptionRequestResult:
    """Result from asking a hub to subscribe or unsubscribe a callback."""

    subscription: WebSubSubscription
    mode: str
    success: bool
    status_code: int | None = None
    error: str = ""


@dataclass(frozen=True)
class WebSubLeaseSummary:
    """Operator-facing summary of one WebSub subscription lease."""

    subscription_id: int
    hub_url: str
    topic_url: str
    state: str
    lease_expires_at: datetime | None
    expired: bool


class WebSubSecretRequiresHTTPSError(ValueError):
    """Raised when ``hub.secret`` would be sent over a plain-HTTP hub URL."""


class WebSubDeliveryHookError(Exception):
    """Configured WebSub delivery hook failed to load or run."""


class WebSubDeliveryEnqueueError(Exception):
    """Configured WebSub delivery enqueue hook failed to load or run."""


def _as_string_tuple(value: Any, *, setting_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Iterable):
        raise ValueError(f"{setting_name} must be a string or iterable of strings")

    values = tuple(value)
    if not all(isinstance(item, str) and item for item in values):
        raise ValueError(f"{setting_name} must contain non-empty strings")
    return values


def _validate_url(value: str, *, label: str) -> str:
    validator = URLValidator(schemes=list(WEBSUB_ALLOWED_SCHEMES))
    try:
        validator(value)
    except ValidationError as exc:
        raise ValueError(f"{label} must be a valid http:// or https:// URL") from exc
    return value


def get_websub_hubs(hubs: Sequence[str] | str | None = None) -> tuple[str, ...]:
    """Return validated WebSub hub URLs from ``hubs`` or ``INDIEWEB_WEBSUB_HUBS``."""
    configured_hubs = getattr(settings, "INDIEWEB_WEBSUB_HUBS", ()) if hubs is None else hubs
    parsed_hubs = _as_string_tuple(configured_hubs, setting_name="INDIEWEB_WEBSUB_HUBS")
    return tuple(_validate_url(hub_url, label="hub URL") for hub_url in parsed_hubs)


def build_websub_links(topic_url: str, hubs: Sequence[str] | str | None = None) -> tuple[WebSubLink, ...]:
    """Build WebSub discovery links for a topic.

    The result contains one ``rel=hub`` link for each hub and exactly one
    ``rel=self`` link for the topic URL, matching the WebSub publisher
    discovery requirements.
    """
    validated_topic_url = _validate_url(topic_url, label="topic URL")
    hub_urls = get_websub_hubs(hubs)
    if not hub_urls:
        raise ValueError("at least one WebSub hub URL is required")
    hub_links = tuple(WebSubLink(rel="hub", url=hub_url) for hub_url in hub_urls)
    return (*hub_links, WebSubLink(rel="self", url=validated_topic_url))


def websub_link_header(topic_url: str, hubs: Sequence[str] | str | None = None) -> str:
    """Return a combined HTTP ``Link`` header value for WebSub discovery."""
    return ", ".join(f'<{link.url}>; rel="{link.rel}"' for link in build_websub_links(topic_url, hubs))


def add_websub_link_header(
    response: HttpResponseBase,
    topic_url: str,
    hubs: Sequence[str] | str | None = None,
) -> HttpResponseBase:
    """Add WebSub discovery links to a Django response's ``Link`` header."""
    header_value = websub_link_header(topic_url, hubs)
    if response.has_header("Link"):
        response["Link"] = f"{response['Link']}, {header_value}"
    else:
        response["Link"] = header_value
    return response


def _websub_timeout(timeout: float | None) -> float:
    configured = DEFAULT_WEBSUB_TIMEOUT if timeout is None else timeout
    try:
        parsed = float(configured)
    except (TypeError, ValueError) as exc:
        raise ValueError("WebSub timeout must be a positive number") from exc
    if parsed <= 0:
        raise ValueError("WebSub timeout must be a positive number")
    return parsed


def _positive_int(value: int | str | None, *, label: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return parsed


def _non_negative_int(value: int | str | None, *, label: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a non-negative integer") from exc
    if parsed < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return parsed


def _validate_subscription_mode(mode: str) -> str:
    if mode not in WEBSUB_SUBSCRIPTION_MODES:
        raise ValueError("WebSub subscription mode must be 'subscribe' or 'unsubscribe'")
    return mode


def _delivery_max_bytes() -> int | None:
    """Return the per-callback delivery body cap, or ``None`` to disable.

    ``None`` is the explicit "disable cap" sentinel. Any other malformed value —
    including the empty string that ``_positive_int`` translates back to ``None`` —
    falls back to the default cap so an empty environment variable does not silently
    weaken the protection.
    """
    configured = getattr(settings, "INDIEWEB_WEBSUB_DELIVERY_MAX_BYTES", DEFAULT_WEBSUB_DELIVERY_MAX_BYTES)
    if configured is None:
        return None
    try:
        parsed = _positive_int(configured, label="WebSub delivery max bytes")
    except ValueError:
        logger.warning("Ignoring invalid INDIEWEB_WEBSUB_DELIVERY_MAX_BYTES value; using the default limit")
        return DEFAULT_WEBSUB_DELIVERY_MAX_BYTES
    if parsed is None:
        logger.warning("Ignoring empty INDIEWEB_WEBSUB_DELIVERY_MAX_BYTES value; using the default limit")
        return DEFAULT_WEBSUB_DELIVERY_MAX_BYTES
    return parsed


def _hub_response_max_bytes() -> int | None:
    """Return the decoded byte cap applied to hub HTTP responses, or ``None`` to disable.

    ``None`` is the explicit "disable cap" sentinel. Any other malformed value —
    including the empty string that ``_positive_int`` translates back to ``None`` —
    falls back to the default cap so an empty environment variable does not silently
    weaken the protection.
    """
    configured = getattr(settings, "INDIEWEB_WEBSUB_HUB_RESPONSE_MAX_BYTES", DEFAULT_WEBSUB_HUB_RESPONSE_MAX_BYTES)
    if configured is None:
        return None
    try:
        parsed = _positive_int(configured, label="WebSub hub response max bytes")
    except ValueError:
        logger.warning(
            "Ignoring invalid INDIEWEB_WEBSUB_HUB_RESPONSE_MAX_BYTES value; using the default limit",
        )
        return DEFAULT_WEBSUB_HUB_RESPONSE_MAX_BYTES
    if parsed is None:
        logger.warning(
            "Ignoring empty INDIEWEB_WEBSUB_HUB_RESPONSE_MAX_BYTES value; using the default limit",
        )
        return DEFAULT_WEBSUB_HUB_RESPONSE_MAX_BYTES
    return parsed


def _delivery_content_type_allowed(content_type: str) -> bool:
    configured = getattr(settings, "INDIEWEB_WEBSUB_DELIVERY_ALLOWED_TYPES", None)
    if configured is None:
        return True
    try:
        allowed_types = _as_string_tuple(configured, setting_name="INDIEWEB_WEBSUB_DELIVERY_ALLOWED_TYPES")
    except ValueError:
        logger.warning("Ignoring invalid INDIEWEB_WEBSUB_DELIVERY_ALLOWED_TYPES value; allowing all delivery types")
        return True
    if not allowed_types:
        return True
    base_content_type = content_type.split(";", 1)[0].strip().lower()
    return base_content_type in {allowed.lower() for allowed in allowed_types}


def _setting_enabled(name: str, *, default: bool = False) -> bool:
    return bool(getattr(settings, name, default))


def _configured_positive_int(name: str, *, default: int, label: str) -> int:
    configured = getattr(settings, name, default)
    try:
        parsed = _positive_int(configured, label=label)
    except ValueError:
        logger.warning("Ignoring invalid %s value; using the default", name)
        return default
    return parsed if parsed is not None else default


def _clamp_to_lease_range(value: int, *, setting_name: str) -> int:
    """Clamp ``value`` to ``[WEBSUB_LEASE_BOUNDS_FLOOR_SECONDS, WEBSUB_LEASE_BOUNDS_CEILING_SECONDS]``.

    Out-of-range values produce a warning and are pulled to the nearest in-range bound so a
    misconfigured ``INDIEWEB_WEBSUB_MIN_LEASE_SECONDS`` / ``INDIEWEB_WEBSUB_MAX_LEASE_SECONDS``
    cannot disable the documented protection (e.g. accepting one-second leases or thousand-year
    leases).
    """
    if value < WEBSUB_LEASE_BOUNDS_FLOOR_SECONDS:
        logger.warning(
            "Clamping %s=%d to WebSub lease floor of %d seconds",
            setting_name,
            value,
            WEBSUB_LEASE_BOUNDS_FLOOR_SECONDS,
        )
        return WEBSUB_LEASE_BOUNDS_FLOOR_SECONDS
    if value > WEBSUB_LEASE_BOUNDS_CEILING_SECONDS:
        logger.warning(
            "Clamping %s=%d to WebSub lease ceiling of %d seconds",
            setting_name,
            value,
            WEBSUB_LEASE_BOUNDS_CEILING_SECONDS,
        )
        return WEBSUB_LEASE_BOUNDS_CEILING_SECONDS
    return value


def _confirmed_lease_bounds() -> tuple[int, int]:
    minimum = _clamp_to_lease_range(
        _configured_positive_int(
            "INDIEWEB_WEBSUB_MIN_LEASE_SECONDS",
            default=DEFAULT_WEBSUB_MIN_LEASE_SECONDS,
            label="WebSub minimum lease seconds",
        ),
        setting_name="INDIEWEB_WEBSUB_MIN_LEASE_SECONDS",
    )
    maximum = _clamp_to_lease_range(
        _configured_positive_int(
            "INDIEWEB_WEBSUB_MAX_LEASE_SECONDS",
            default=DEFAULT_WEBSUB_MAX_LEASE_SECONDS,
            label="WebSub maximum lease seconds",
        ),
        setting_name="INDIEWEB_WEBSUB_MAX_LEASE_SECONDS",
    )
    if minimum > maximum:
        logger.warning("Ignoring invalid WebSub lease bounds; using the defaults")
        return DEFAULT_WEBSUB_MIN_LEASE_SECONDS, DEFAULT_WEBSUB_MAX_LEASE_SECONDS
    return minimum, maximum


def _clamp_confirmed_lease_seconds(lease_seconds: int | None) -> int | None:
    if lease_seconds is None:
        return None
    minimum, maximum = _confirmed_lease_bounds()
    return min(max(lease_seconds, minimum), maximum)


def _delivery_replay_history_max() -> int | None:
    """Return the per-subscription replay history cap, or ``None`` to disable pruning.

    ``None`` is the explicit "disable cap" sentinel. Any other malformed value —
    including the empty string that ``_positive_int`` translates back to ``None`` —
    falls back to the default so an empty environment variable does not silently
    weaken the protection by allowing the cache to grow without bound.
    """
    configured = getattr(
        settings,
        "INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX",
        DEFAULT_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX,
    )
    if configured is None:
        return None
    try:
        parsed = _positive_int(configured, label="WebSub delivery replay history max")
    except ValueError:
        logger.warning(
            "Ignoring invalid INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX value; using the default cap",
        )
        return DEFAULT_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX
    if parsed is None:
        logger.warning(
            "Ignoring empty INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX value; using the default cap",
        )
        return DEFAULT_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX
    return parsed


def _delivery_replay_window_seconds() -> int | None:
    configured = getattr(
        settings,
        "INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS",
        DEFAULT_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS,
    )
    if configured is None:
        return None
    try:
        parsed = _non_negative_int(configured, label="WebSub delivery replay window seconds")
    except ValueError:
        logger.warning(
            "Ignoring invalid INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS value; using the default window"
        )
        return DEFAULT_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS
    if parsed == 0:
        return None
    return parsed


def _validate_websub_secret(secret: str | None) -> str | None:
    if secret is None:
        return None
    if secret == "":
        raise ValueError("WebSub secret must not be empty; pass None to omit hub.secret")
    if secret.startswith(WEBSUB_SECRET_ENCRYPTED_PREFIX):
        raise ValueError("WebSub secret uses a reserved prefix")
    secret_bytes = secret.encode("utf-8")
    if len(secret_bytes) > WEBSUB_SECRET_MAX_BYTES:
        raise ValueError("WebSub secret must be at most 200 bytes")
    if len(secret_bytes) < WEBSUB_SECRET_MIN_BYTES:
        raise ValueError("WebSub secret must be at least 20 bytes")
    return secret


def build_websub_callback_url(
    subscription: WebSubSubscription,
    callback_base_url: str | None = None,
) -> str:
    """Return the absolute subscriber callback URL for ``subscription``.

    ``callback_base_url`` defaults to ``INDIEWEB_WEBSUB_CALLBACK_BASE_URL`` and
    must be an absolute URL for the callback route prefix, without the token.
    The subscription token is appended as a path component.
    """
    configured_base = callback_base_url or getattr(settings, "INDIEWEB_WEBSUB_CALLBACK_BASE_URL", None)
    if not configured_base:
        raise ValueError("INDIEWEB_WEBSUB_CALLBACK_BASE_URL is required for subscriber requests")
    base = _validate_url(str(configured_base), label="WebSub callback base URL")
    callback_url = f"{base.rstrip('/')}/{subscription.callback_token}/"
    return _validate_url(callback_url, label="WebSub callback URL")


def _save_subscription_request_success(
    subscription: WebSubSubscription,
    *,
    mode: str,
    status_code: int,
) -> None:
    subscription.last_request_at = timezone.now()
    subscription.last_request_mode = mode
    subscription.last_request_status_code = status_code
    subscription.last_request_error = ""
    subscription.save(
        update_fields=[
            "last_request_at",
            "last_request_mode",
            "last_request_status_code",
            "last_request_error",
            "modified",
        ]
    )


def _save_subscription_request_failure(
    subscription: WebSubSubscription,
    *,
    mode: str,
    previous_state: str,
    previous_pending_secret: str,
    previous_pending_secret_set: bool,
    status_code: int | None,
    error: str,
) -> None:
    subscription.last_request_at = timezone.now()
    subscription.last_request_mode = mode
    subscription.last_request_status_code = status_code
    subscription.last_request_error = error[:500]
    subscription.pending_mode = ""
    subscription.pending_secret = previous_pending_secret
    subscription.pending_secret_set = previous_pending_secret_set
    if mode == WebSubSubscription.MODE_SUBSCRIBE and previous_state != WebSubSubscription.STATE_ACTIVE:
        subscription.state = WebSubSubscription.STATE_DENIED
    else:
        subscription.state = previous_state
    subscription.save(
        update_fields=[
            "state",
            "pending_mode",
            "pending_secret",
            "pending_secret_set",
            "last_request_at",
            "last_request_mode",
            "last_request_status_code",
            "last_request_error",
            "modified",
        ]
    )


def _prepare_subscription_request(
    topic_url: str,
    hub_url: str,
    *,
    mode: str,
    lease_seconds: int | None,
    secret: str | None,
) -> tuple[WebSubSubscription, str, str, str, bool]:
    validated_topic_url = _validate_url(topic_url, label="topic URL")
    validated_hub_url = _validate_url(hub_url, label="hub URL")
    validated_mode = _validate_subscription_mode(mode)
    validated_lease_seconds = _positive_int(lease_seconds, label="lease seconds")
    validated_secret = _validate_websub_secret(secret) if validated_mode == WebSubSubscription.MODE_SUBSCRIBE else None

    if validated_mode == WebSubSubscription.MODE_UNSUBSCRIBE:
        try:
            subscription = WebSubSubscription.objects.get(hub_url=validated_hub_url, topic_url=validated_topic_url)
        except WebSubSubscription.DoesNotExist as exc:
            raise ValueError("cannot unsubscribe an unknown WebSub subscription") from exc
    else:
        subscription, _created = WebSubSubscription.objects.get_or_create(
            hub_url=validated_hub_url,
            topic_url=validated_topic_url,
        )

    previous_state = subscription.state
    previous_pending_secret = subscription.pending_secret
    previous_pending_secret_set = subscription.pending_secret_set
    if validated_mode == WebSubSubscription.MODE_SUBSCRIBE:
        if previous_state != WebSubSubscription.STATE_ACTIVE:
            subscription.state = WebSubSubscription.STATE_PENDING_SUBSCRIBE
            subscription.confirmed_lease_seconds = None
            subscription.lease_expires_at = None
    else:
        subscription.state = WebSubSubscription.STATE_PENDING_UNSUBSCRIBE
    subscription.pending_mode = validated_mode
    subscription.requested_lease_seconds = validated_lease_seconds
    if validated_mode == WebSubSubscription.MODE_SUBSCRIBE:
        subscription.set_pending_secret(validated_secret or "")
        subscription.pending_secret_set = validated_secret is not None
    subscription.save(
        update_fields=[
            "state",
            "pending_mode",
            "requested_lease_seconds",
            "confirmed_lease_seconds",
            "lease_expires_at",
            "pending_secret",
            "pending_secret_set",
            "modified",
        ]
    )
    return subscription, validated_mode, previous_state, previous_pending_secret, previous_pending_secret_set


def _post_subscription_request(
    *,
    hub_url: str,
    mode: str,
    topic_url: str,
    callback_url: str,
    secret: str | None,
    lease_seconds: int | None = None,
    timeout: float | None = None,
    client: httpx.Client | None = None,
    use_resolver: bool | None = None,
) -> httpx.Response:
    """Send a single WebSub subscribe/unsubscribe ``POST`` to ``hub_url``.

    Performs the HTTPS-required gate for ``hub.secret`` before any network
    call, validates the hub URL with the shared SSRF helper when no caller
    client is injected, and routes the POST through the strict cross-origin
    redirect helper so a hub redirect cannot replay the ``hub.secret``-bearing
    body to a different origin.

    When ``use_resolver`` is ``None`` (the default) the SSRF resolver is used
    only when this helper opens its own ``httpx.Client``; injected clients
    skip DNS-based blocking and IP pinning, mirroring the
    ``request_websub_subscription`` injection contract. Pass ``use_resolver``
    explicitly to override that default — for example,
    ``request_websub_subscription`` opens its own client and forwards it to
    this helper while requesting that the resolver still run.

    Returns the raw :class:`httpx.Response`. Callers are responsible for
    inspecting status, recording subscription state changes, and translating
    network errors into operator-facing failures.
    """
    if secret and urlparse(hub_url).scheme.lower() != "https":
        raise WebSubSecretRequiresHTTPSError("WebSub subscription with hub.secret requires an https hub_url")

    data: dict[str, str | int] = {
        "hub.mode": mode,
        "hub.callback": callback_url,
        "hub.topic": topic_url,
    }
    if lease_seconds is not None:
        data["hub.lease_seconds"] = lease_seconds
    if secret is not None and mode == WebSubSubscription.MODE_SUBSCRIBE:
        data["hub.secret"] = secret

    request_timeout = _websub_timeout(timeout)
    close_client = client is None
    http_client = client or httpx.Client(timeout=request_timeout, follow_redirects=False, verify=True, trust_env=False)
    if use_resolver is None:
        use_resolver = close_client
    resolver = default_address_resolver if use_resolver else None
    try:
        validate_safe_http_url(hub_url, resolver=resolver)
        delivered = request_with_safe_redirects(
            http_client,
            "POST",
            hub_url,
            data=data,
            resolver=resolver,
            max_bytes=_hub_response_max_bytes(),
            cross_origin_strip=True,
        )
        return delivered.response
    finally:
        if close_client:
            http_client.close()


def request_websub_subscription(
    topic_url: str,
    hub_url: str,
    *,
    mode: str = WebSubSubscription.MODE_SUBSCRIBE,
    callback_base_url: str | None = None,
    lease_seconds: int | None = None,
    secret: str | None = None,
    timeout: float | None = None,
    client: httpx.Client | None = None,
) -> WebSubSubscriptionRequestResult:
    """Ask a hub to subscribe or unsubscribe django-indieweb's callback.

    The request uses WebSub's form fields: ``hub.mode``, ``hub.callback``,
    ``hub.topic``, optional ``hub.lease_seconds``, and optional ``hub.secret``
    for subscribe requests. A successful HTTP response means the hub accepted
    the request and should later verify the callback; verification state is
    confirmed by the callback view.
    """
    (
        subscription,
        validated_mode,
        previous_state,
        previous_pending_secret,
        previous_pending_secret_set,
    ) = _prepare_subscription_request(
        topic_url,
        hub_url,
        mode=mode,
        lease_seconds=lease_seconds,
        secret=secret,
    )
    callback_url = build_websub_callback_url(subscription, callback_base_url)
    configured_timeout = timeout if timeout is not None else getattr(settings, "INDIEWEB_WEBSUB_TIMEOUT", None)
    request_timeout = _websub_timeout(configured_timeout)

    close_client = client is None
    http_client = client or httpx.Client(timeout=request_timeout, follow_redirects=False, verify=True, trust_env=False)
    try:
        try:
            response = _post_subscription_request(
                hub_url=subscription.hub_url,
                mode=validated_mode,
                topic_url=subscription.topic_url,
                callback_url=callback_url,
                secret=secret if validated_mode == WebSubSubscription.MODE_SUBSCRIBE else None,
                lease_seconds=lease_seconds,
                timeout=request_timeout,
                client=http_client,
                use_resolver=close_client,
            )
        except (
            WebSubSecretRequiresHTTPSError,
            httpx.RequestError,
            UnsafeHTTPUrlError,
            WebmentionRedirectError,
            HTTPResponseTooLarge,
        ) as exc:
            logger.warning(f"WebSub subscription request failed for hub={subscription.hub_url!r}: {exc}")
            _save_subscription_request_failure(
                subscription,
                mode=validated_mode,
                previous_state=previous_state,
                previous_pending_secret=previous_pending_secret,
                previous_pending_secret_set=previous_pending_secret_set,
                status_code=None,
                error=str(exc),
            )
            return WebSubSubscriptionRequestResult(
                subscription=subscription,
                mode=validated_mode,
                success=False,
                error=str(exc),
            )

        if response.is_success:
            _save_subscription_request_success(subscription, mode=validated_mode, status_code=response.status_code)
            return WebSubSubscriptionRequestResult(
                subscription=subscription,
                mode=validated_mode,
                success=True,
                status_code=response.status_code,
            )

        error = response.text[:500]
        _save_subscription_request_failure(
            subscription,
            mode=validated_mode,
            previous_state=previous_state,
            previous_pending_secret=previous_pending_secret,
            previous_pending_secret_set=previous_pending_secret_set,
            status_code=response.status_code,
            error=error,
        )
        return WebSubSubscriptionRequestResult(
            subscription=subscription,
            mode=validated_mode,
            success=False,
            status_code=response.status_code,
            error=error,
        )
    finally:
        if close_client:
            http_client.close()


def confirm_websub_verification(
    subscription: WebSubSubscription,
    *,
    mode: str,
    topic_url: str,
    challenge: str,
    lease_seconds: str | int | None,
) -> None:
    """Confirm a WebSub callback verification request or raise ``ValueError``."""
    validated_mode = _validate_subscription_mode(mode)
    if not challenge:
        raise ValueError("WebSub verification challenge is required")
    if topic_url != subscription.topic_url:
        raise ValueError("WebSub verification topic does not match subscription")
    if subscription.pending_mode != validated_mode:
        raise ValueError("WebSub verification mode does not match pending subscription mode")

    if validated_mode == WebSubSubscription.MODE_SUBSCRIBE:
        if subscription.state not in {
            WebSubSubscription.STATE_PENDING_SUBSCRIBE,
            WebSubSubscription.STATE_ACTIVE,
        }:
            raise ValueError("WebSub subscription is not pending subscribe verification")
        confirmed_lease = _positive_int(lease_seconds, label="lease seconds")
        if confirmed_lease is None:
            confirmed_lease = subscription.requested_lease_seconds
        confirmed_lease = _clamp_confirmed_lease_seconds(confirmed_lease)
        subscription.state = WebSubSubscription.STATE_ACTIVE
        subscription.confirmed_lease_seconds = confirmed_lease
        subscription.lease_expires_at = (
            timezone.now() + timedelta(seconds=confirmed_lease) if confirmed_lease is not None else None
        )
        if subscription.pending_secret_set:
            subscription.set_secret(subscription.get_pending_secret())
    else:
        if subscription.state != WebSubSubscription.STATE_PENDING_UNSUBSCRIBE:
            raise ValueError("WebSub subscription is not pending unsubscribe verification")
        subscription.state = WebSubSubscription.STATE_UNSUBSCRIBED
        subscription.confirmed_lease_seconds = None
        subscription.lease_expires_at = None

    subscription.last_challenge = challenge
    subscription.last_verified_at = timezone.now()
    subscription.pending_mode = ""
    subscription.pending_secret = ""
    subscription.pending_secret_set = False
    subscription.save(
        update_fields=[
            "state",
            "pending_mode",
            "secret",
            "pending_secret",
            "pending_secret_set",
            "confirmed_lease_seconds",
            "lease_expires_at",
            "last_challenge",
            "last_verified_at",
            "modified",
        ]
    )


def record_websub_denial(
    subscription: WebSubSubscription,
    *,
    topic_url: str,
    reason: str,
) -> None:
    """Record a WebSub ``hub.mode=denied`` verification callback.

    A denial is accepted only for the tokenized subscription and exact topic
    URL. If the denied callback corresponds to a pending subscribe request,
    the subscription moves to ``denied``. If it corresponds to a pending
    unsubscribe request, the existing subscription remains ``active`` because
    the hub rejected cancellation. In both cases pending request/secret staging
    is cleared so operators can inspect and retry explicitly.
    """
    if topic_url != subscription.topic_url:
        raise ValueError("WebSub denial topic does not match subscription")
    if subscription.pending_mode not in WEBSUB_SUBSCRIPTION_MODES:
        raise ValueError("WebSub denial does not match a pending subscription request")

    now = timezone.now()
    denied_mode = subscription.pending_mode
    if denied_mode == WebSubSubscription.MODE_SUBSCRIBE:
        if subscription.state not in {
            WebSubSubscription.STATE_PENDING_SUBSCRIBE,
            WebSubSubscription.STATE_ACTIVE,
        }:
            raise ValueError("WebSub denial does not match pending subscribe verification")
        was_active_renewal = subscription.state == WebSubSubscription.STATE_ACTIVE
        if not was_active_renewal:
            subscription.state = WebSubSubscription.STATE_DENIED
            subscription.confirmed_lease_seconds = None
            subscription.lease_expires_at = None
    else:
        if subscription.state != WebSubSubscription.STATE_PENDING_UNSUBSCRIBE:
            raise ValueError("WebSub denial does not match pending unsubscribe verification")
        subscription.state = WebSubSubscription.STATE_ACTIVE

    subscription.last_denied_at = now
    subscription.last_denied_mode = denied_mode
    subscription.last_denial_reason = reason[:500]
    subscription.pending_mode = ""
    update_fields = [
        "state",
        "pending_mode",
        "confirmed_lease_seconds",
        "lease_expires_at",
        "last_denied_at",
        "last_denied_mode",
        "last_denial_reason",
        "modified",
    ]
    # Preserve any staged secret rotation when denying a renewal of an
    # already-active subscription: the active secret continues to validate
    # incoming hub deliveries, and the operator can retry the renewal
    # without rebuilding the staged rotation. For non-active denials
    # (e.g. an initial pending subscribe rejected by the hub), clear the
    # pending secret so a follow-up subscribe starts fresh.
    if subscription.state != WebSubSubscription.STATE_ACTIVE:
        subscription.pending_secret = ""
        subscription.pending_secret_set = False
        update_fields.extend(["pending_secret", "pending_secret_set"])
    subscription.save(update_fields=update_fields)


def get_websub_expired_subscriptions(*, now: datetime | None = None) -> QuerySet[WebSubSubscription]:
    """Return active subscriptions whose confirmed lease has expired."""
    reference_time = now or timezone.now()
    return WebSubSubscription.objects.filter(
        state=WebSubSubscription.STATE_ACTIVE,
        lease_expires_at__isnull=False,
        lease_expires_at__lte=reference_time,
    ).order_by("lease_expires_at", "pk")


def get_websub_renewal_candidates(
    *,
    within: timedelta = timedelta(days=1),
    now: datetime | None = None,
) -> QuerySet[WebSubSubscription]:
    """Return active subscriptions whose lease expires within ``within``.

    Already-expired active subscriptions are included in the candidate set.
    """
    if within < timedelta(0):
        raise ValueError("renewal candidate window must be non-negative")
    reference_time = now or timezone.now()
    return WebSubSubscription.objects.filter(
        state=WebSubSubscription.STATE_ACTIVE,
        lease_expires_at__isnull=False,
        lease_expires_at__lte=reference_time + within,
    ).order_by("lease_expires_at", "pk")


def summarize_websub_leases(
    *,
    within: timedelta = timedelta(days=1),
    now: datetime | None = None,
) -> list[WebSubLeaseSummary]:
    """Return metadata-only lease status summaries for operator inspection."""
    reference_time = now or timezone.now()
    subscriptions = get_websub_renewal_candidates(within=within, now=reference_time)
    summaries: list[WebSubLeaseSummary] = []
    for subscription in subscriptions:
        lease_expires_at = subscription.lease_expires_at
        expired = lease_expires_at is not None and lease_expires_at <= reference_time
        summaries.append(
            WebSubLeaseSummary(
                subscription_id=subscription.pk,
                hub_url=subscription.hub_url,
                topic_url=subscription.topic_url,
                state=subscription.state,
                lease_expires_at=lease_expires_at,
                expired=expired,
            )
        )
    return summaries


def delivery_body_too_large(body: bytes) -> bool:
    """Return whether a WebSub delivery body exceeds the configured size limit."""
    max_bytes = _delivery_max_bytes()
    return max_bytes is not None and len(body) > max_bytes


def delivery_max_bytes() -> int | None:
    """Return the configured WebSub delivery byte limit."""
    return _delivery_max_bytes()


def delivery_content_length_too_large(content_length: str | None) -> bool:
    """Return whether a WebSub delivery ``Content-Length`` exceeds the configured limit."""
    max_bytes = _delivery_max_bytes()
    if max_bytes is None or not content_length:
        return False
    try:
        parsed = int(content_length)
    except (TypeError, ValueError):
        return False
    return parsed > max_bytes


def delivery_content_type_allowed(content_type: str) -> bool:
    """Return whether a WebSub delivery content type is accepted by configuration."""
    return _delivery_content_type_allowed(content_type)


def _signature_headers(headers: Mapping[str, str]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for header_name in ("X-Hub-Signature-256", "X-Hub-Signature"):
        value = headers.get(header_name)
        if value:
            for part in (part.strip() for part in value.split(",") if part.strip()):
                algorithm, separator, received_digest = part.partition("=")
                if separator == "=" and received_digest:
                    values.append((algorithm.lower(), received_digest))
    return values


def validate_websub_delivery_signature(
    subscription: WebSubSubscription,
    body: bytes,
    headers: Mapping[str, str],
) -> str | None:
    """Validate a signed WebSub delivery.

    Returns the accepted algorithm name, or ``None`` when the subscription has
    no secret and no validation is required. Raises ``ValueError`` for missing,
    malformed, unsupported, or mismatched signatures.
    """
    secret = subscription.get_secret()
    if not secret:
        if _setting_enabled("INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES"):
            raise ValueError("WebSub delivery signature is required but the subscription has no secret")
        return None

    signatures = _signature_headers(headers)
    allowed_algorithms = set(WEBSUB_SIGNATURE_ALGORITHMS)
    if not _setting_enabled("INDIEWEB_WEBSUB_ALLOW_SHA1_SIGNATURES"):
        allowed_algorithms.discard("sha1")
    supported_signatures = [
        (algorithm, received_digest)
        for algorithm, received_digest in signatures
        if algorithm in allowed_algorithms and algorithm in WEBSUB_SIGNATURE_ALGORITHMS
    ]
    if not supported_signatures:
        raise ValueError("WebSub delivery signature did not include a supported algorithm")

    strongest = max(WEBSUB_SIGNATURE_STRENGTH[algorithm] for algorithm, _received_digest in supported_signatures)
    for algorithm, received_digest in supported_signatures:
        if WEBSUB_SIGNATURE_STRENGTH[algorithm] != strongest:
            continue
        # Multiple signatures for the strongest algorithm are allowed; any valid
        # digest for that strongest algorithm authenticates the delivery.
        digestmod = WEBSUB_SIGNATURE_ALGORITHMS[algorithm]
        expected = hmac.new(secret.encode("utf-8"), body, digestmod).hexdigest()
        if hmac.compare_digest(expected, received_digest):
            return algorithm
    raise ValueError("WebSub delivery signature did not validate")


def delivery_is_replay(
    subscription: WebSubSubscription,
    body: bytes,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether ``body`` duplicates any accepted delivery in the replay window.

    .. deprecated::
        ``delivery_is_replay`` is replaced by :func:`accept_websub_delivery`,
        which performs the replay check and acceptance gate atomically against
        the ``WebSubAcceptedDelivery`` table. The legacy helper is retained for
        backwards compatibility and continues to consult the new table.
    """
    warnings.warn(
        "delivery_is_replay is deprecated; use accept_websub_delivery for atomic replay-check + acceptance",
        DeprecationWarning,
        stacklevel=2,
    )
    replay_window_seconds = _delivery_replay_window_seconds()
    if replay_window_seconds is None:
        return False
    received_at = now or timezone.now()
    cutoff = received_at - timedelta(seconds=replay_window_seconds)
    body_digest = hashlib.sha256(body).hexdigest()

    return WebSubAcceptedDelivery.objects.filter(
        subscription=subscription,
        body_digest=body_digest,
        accepted_at__gte=cutoff,
    ).exists()


def accept_websub_delivery(
    subscription: WebSubSubscription,
    body_digest: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Atomically gate a delivery body against the per-subscription replay window.

    Returns ``True`` when the digest was accepted (this is a fresh delivery)
    and ``False`` when the digest collides with an earlier accepted delivery
    inside the configured replay window.

    The implementation prunes expired rows inside an outer atomic block and
    inserts the new row in an inner ``transaction.atomic()`` savepoint so an
    ``IntegrityError`` from the unique constraint on ``(subscription,
    body_digest)`` rolls back only the failing insert. The unique constraint
    plus Django's transaction write serialization is what guarantees that two
    concurrent identical deliveries cannot both record an acceptance,
    independent of whether the backend supports ``SELECT FOR UPDATE``.

    Cap-by-count maintenance is best-effort: under concurrent distinct-digest
    deliveries the count can momentarily exceed the cap because we do not lock
    the subscription row. Replay correctness is unaffected because each digest
    still goes through the unique-constraint gate.
    """
    received_at = now or timezone.now()
    replay_window_seconds = _delivery_replay_window_seconds()
    history_max = _delivery_replay_history_max()

    with transaction.atomic():
        if replay_window_seconds is not None:
            cutoff = received_at - timedelta(seconds=replay_window_seconds)
            WebSubAcceptedDelivery.objects.filter(
                subscription=subscription,
                accepted_at__lt=cutoff,
            ).delete()

        try:
            with transaction.atomic():  # savepoint
                WebSubAcceptedDelivery.objects.create(
                    subscription=subscription,
                    body_digest=body_digest,
                    accepted_at=received_at,
                )
        except IntegrityError:
            return False

        if history_max is not None and history_max > 0:
            keep_ids = list(
                WebSubAcceptedDelivery.objects.filter(subscription=subscription)
                .order_by("-accepted_at", "-pk")
                .values_list("pk", flat=True)[:history_max]
            )
            WebSubAcceptedDelivery.objects.filter(subscription=subscription).exclude(pk__in=keep_ids).delete()

    return True


def _hook_accepts_body_digest(callable_obj: Any) -> bool:
    """Return whether ``callable_obj`` advertises a ``body_digest`` keyword argument.

    A hook accepts ``body_digest`` if its signature has either an explicit
    parameter named ``body_digest`` or a ``**kwargs``-style ``VAR_KEYWORD``
    parameter. ``inspect.signature`` can raise ``TypeError`` or ``ValueError``
    for some builtins or proxies — in that case we conservatively report
    ``False`` so the hook receives the legacy keyword set unchanged.
    """
    try:
        sig = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return False
    for param in sig.parameters.values():
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            return True
        if param.name == "body_digest":
            return True
    return False


def record_websub_delivery(
    subscription: WebSubSubscription,
    body: bytes,
    *,
    content_type: str,
    status_code: int,
    error: str = "",
    signature_algorithm: str | None = None,
) -> None:
    """Record metadata for the latest WebSub delivery attempt."""
    received_at = timezone.now()
    clipped_content_type = content_type[:200]
    delivery_size = len(body)
    delivery_digest = hashlib.sha256(body).hexdigest()
    clipped_error = error[:500]
    subscription.last_delivery_at = received_at
    subscription.last_delivery_content_type = clipped_content_type
    subscription.last_delivery_size = delivery_size
    subscription.last_delivery_digest = delivery_digest
    subscription.last_delivery_signature_algorithm = signature_algorithm or ""
    subscription.last_delivery_status_code = status_code
    subscription.last_delivery_error = clipped_error
    update_fields = [
        "last_delivery_at",
        "last_delivery_content_type",
        "last_delivery_size",
        "last_delivery_digest",
        "last_delivery_signature_algorithm",
        "last_delivery_status_code",
        "last_delivery_error",
        "modified",
    ]
    if status_code == 204:
        subscription.last_accepted_delivery_at = received_at
        subscription.last_accepted_delivery_digest = delivery_digest
        update_fields.extend(["last_accepted_delivery_at", "last_accepted_delivery_digest"])
        # ``recent_accepted_delivery_digests`` is no longer the source of truth for
        # replay detection: ``WebSubAcceptedDelivery`` rows written by
        # :func:`accept_websub_delivery` provide an atomic per-digest gate.
        # The JSON field is left in place on the model for migration
        # compatibility and will be removed in a follow-up cleanup commit.
    subscription.save(update_fields=update_fields)
    WebSubDeliveryAttempt.objects.create(
        subscription=subscription,
        received_at=received_at,
        content_type=clipped_content_type,
        size=delivery_size,
        digest=delivery_digest,
        signature_algorithm=signature_algorithm or "",
        status_code=status_code,
        error=clipped_error,
    )


def get_websub_delivery_hook() -> Any | None:
    """Load the optional WebSub delivery hook callable."""
    hook_path = getattr(settings, "INDIEWEB_WEBSUB_DELIVERY_HOOK", None)
    if not hook_path:
        return None
    try:
        hook = import_string(hook_path)
    except Exception as exc:
        logger.exception(f"Failed to load INDIEWEB_WEBSUB_DELIVERY_HOOK {hook_path!r}")
        raise WebSubDeliveryHookError from exc
    if not callable(hook):
        logger.error(f"INDIEWEB_WEBSUB_DELIVERY_HOOK {hook_path!r} is not callable")
        raise WebSubDeliveryHookError
    return hook


def process_websub_delivery(
    subscription: WebSubSubscription,
    body: bytes,
    headers: Mapping[str, str],
    *,
    body_digest: str | None = None,
) -> None:
    """Call the optional host hook for an accepted WebSub delivery.

    When ``body_digest`` is supplied and the configured hook signature accepts
    it (an explicit ``body_digest`` parameter or a ``**kwargs`` parameter),
    the digest is forwarded so hosts can use it as an idempotency key. Hooks
    with the legacy signature continue to receive the existing keyword set
    unchanged.
    """
    hook = get_websub_delivery_hook()
    if hook is None:
        return
    hook_kwargs: dict[str, Any] = {
        "subscription_id": subscription.pk,
        "hub_url": subscription.hub_url,
        "topic_url": subscription.topic_url,
        "body": body,
        "headers": dict(headers),
    }
    if body_digest is not None and _hook_accepts_body_digest(hook):
        hook_kwargs["body_digest"] = body_digest
    try:
        hook(**hook_kwargs)
    except Exception as exc:
        logger.exception(f"WebSub delivery hook failed for subscription {subscription.pk}")
        raise WebSubDeliveryHookError from exc


def get_websub_delivery_enqueue() -> Any | None:
    """Load the optional WebSub delivery enqueue callable."""
    enqueue_path = getattr(settings, "INDIEWEB_WEBSUB_DELIVERY_ENQUEUE", None)
    if not enqueue_path:
        return None
    try:
        enqueue = import_string(enqueue_path)
    except Exception as exc:
        logger.exception(f"Failed to load INDIEWEB_WEBSUB_DELIVERY_ENQUEUE {enqueue_path!r}")
        raise WebSubDeliveryEnqueueError from exc
    if not callable(enqueue):
        logger.error(f"INDIEWEB_WEBSUB_DELIVERY_ENQUEUE {enqueue_path!r} is not callable")
        raise WebSubDeliveryEnqueueError
    return enqueue


def enqueue_websub_delivery(
    subscription: WebSubSubscription,
    body: bytes,
    headers: Mapping[str, str],
    *,
    body_digest: str | None = None,
) -> bool:
    """Hand an accepted WebSub delivery to the configured enqueue callable.

    Returns ``True`` when the enqueue callable was invoked successfully, ``False``
    when no ``INDIEWEB_WEBSUB_DELIVERY_ENQUEUE`` setting is configured. Raises
    ``WebSubDeliveryEnqueueError`` for import failures, non-callables, and
    runtime exceptions raised by the configured callable so the caller can
    record a failed delivery and return HTTP 500.

    When ``body_digest`` is supplied and the configured callable advertises a
    ``body_digest`` keyword argument (or a ``**kwargs`` parameter), the digest
    is forwarded so the enqueued payload carries an idempotency key. Callables
    with the legacy signature receive the existing keyword set unchanged.
    """
    enqueue = get_websub_delivery_enqueue()
    if enqueue is None:
        return False
    enqueue_kwargs: dict[str, Any] = {
        "subscription_id": subscription.pk,
        "hub_url": subscription.hub_url,
        "topic_url": subscription.topic_url,
        "body": body,
        "headers": dict(headers),
    }
    if body_digest is not None and _hook_accepts_body_digest(enqueue):
        enqueue_kwargs["body_digest"] = body_digest
    try:
        enqueue(**enqueue_kwargs)
    except Exception as exc:
        logger.exception(f"WebSub delivery enqueue hook failed for subscription {subscription.pk}")
        raise WebSubDeliveryEnqueueError from exc
    return True


def notify_hubs(
    topic_url: str,
    hubs: Sequence[str] | str | None = None,
    *,
    timeout: float | None = None,
    client: httpx.Client | None = None,
) -> list[WebSubNotificationResult]:
    """Notify configured WebSub hubs that ``topic_url`` has changed.

    Sends the widely-supported publisher notification form as an
    ``application/x-www-form-urlencoded`` POST with ``hub.mode=publish`` and
    ``hub.url=<topic_url>``. Network failures and non-2xx hub responses are
    captured in the returned results instead of being raised. When callers
    inject ``client``, that trusted client is responsible for its own redirect
    policy.
    """
    validated_topic_url = _validate_url(topic_url, label="topic URL")
    hub_urls = get_websub_hubs(hubs)
    if not hub_urls:
        return []
    configured_timeout = timeout if timeout is not None else getattr(settings, "INDIEWEB_WEBSUB_TIMEOUT", None)
    request_timeout = _websub_timeout(configured_timeout)
    data = {"hub.mode": "publish", "hub.url": validated_topic_url}

    close_client = client is None
    http_client = client or httpx.Client(timeout=request_timeout, follow_redirects=False, verify=True, trust_env=False)
    resolver = default_address_resolver if close_client else None
    results: list[WebSubNotificationResult] = []
    try:
        for hub_url in hub_urls:
            try:
                validate_safe_http_url(hub_url, resolver=resolver)
                delivered = request_with_safe_redirects(
                    http_client,
                    "POST",
                    hub_url,
                    data=data,
                    resolver=resolver,
                    max_bytes=_hub_response_max_bytes(),
                    cross_origin_strip=True,
                )
                response = delivered.response
            except (httpx.RequestError, UnsafeHTTPUrlError, WebmentionRedirectError, HTTPResponseTooLarge) as exc:
                logger.warning(f"WebSub hub notification failed for {hub_url!r}: {exc}")
                results.append(
                    WebSubNotificationResult(
                        hub_url=hub_url,
                        topic_url=validated_topic_url,
                        success=False,
                        error=str(exc),
                    )
                )
                continue

            success = response.is_success
            results.append(
                WebSubNotificationResult(
                    hub_url=hub_url,
                    topic_url=validated_topic_url,
                    success=success,
                    status_code=response.status_code,
                    error="" if success else response.text[:500],
                )
            )
    finally:
        if close_client:
            http_client.close()

    return results
