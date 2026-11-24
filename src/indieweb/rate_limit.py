from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.cache import DEFAULT_CACHE_ALIAS, cache, caches
from django.core.cache.backends.dummy import DummyCache
from django.http import HttpRequest, HttpResponse, HttpResponseBase
from django.utils.encoding import force_bytes
from django.views.generic import View

logger = logging.getLogger(__name__)

RATE_LIMITS_SETTING = "INDIEWEB_RATE_LIMITS"

# Counter bucket shared by every HTTP method the endpoint does not implement.
UNSUPPORTED_METHOD_BUCKET = "OTHER"

# Fit signed 32-bit counter/timeout domains used by common cache backends.
MAX_RATE_LIMIT_INTEGER = 2_147_483_647


@dataclass(frozen=True)
class RateLimitConfig:
    """Validated rate-limit configuration for one endpoint key."""

    limit: int
    window: int


@dataclass(frozen=True)
class RateLimitResult:
    """Result of checking a request against a configured rate limit."""

    allowed: bool
    retry_after: int | None = None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed <= 0 or parsed > MAX_RATE_LIMIT_INTEGER:
        return None
    if not isinstance(value, str) and parsed != value:
        return None
    return parsed


def rate_limit_settings() -> Mapping[str, object]:
    """Read the endpoint settings without accessing the cache."""
    configured = getattr(settings, RATE_LIMITS_SETTING, None)
    if configured is None or configured is False:
        return {}
    if not isinstance(configured, Mapping):
        raise ValueError("expected a mapping")
    return configured


def parse_rate_limit_config(endpoint_config: object) -> RateLimitConfig | None:
    """Parse a single endpoint's budget, returning None when disabled."""
    if endpoint_config is None or endpoint_config is False:
        return None
    if not isinstance(endpoint_config, Mapping):
        raise ValueError("expected a mapping")
    if not endpoint_config:
        return None

    limit = _positive_int(endpoint_config.get("limit"))
    window = _positive_int(endpoint_config.get("window"))
    if limit is None or window is None:
        raise ValueError(f"limit and window must be positive integers up to {MAX_RATE_LIMIT_INTEGER}")
    return RateLimitConfig(limit=limit, window=window)


def get_rate_limit_config(endpoint_key: str) -> RateLimitConfig | None:
    """Return the endpoint's validated budget, logging and ignoring invalid settings."""
    try:
        configured = rate_limit_settings()
    except ValueError as exc:
        logger.warning("Ignoring invalid %s value; %s", RATE_LIMITS_SETTING, exc)
        return None
    try:
        return parse_rate_limit_config(configured.get(endpoint_key))
    except ValueError as exc:
        logger.warning("Ignoring invalid rate-limit config for %r; %s", endpoint_key, exc)
        return None


def _client_identity(request: HttpRequest) -> str:
    """Return the client identity used for rate-limit counters."""
    value = request.META.get("REMOTE_ADDR", "")
    fallback = "" if value is None else str(value)
    hops = getattr(settings, "INDIEWEB_RATE_LIMIT_TRUSTED_PROXY_HOPS", 0)
    if isinstance(hops, bool) or not isinstance(hops, int) or hops < 0:
        logger.warning("Invalid INDIEWEB_RATE_LIMIT_TRUSTED_PROXY_HOPS; using REMOTE_ADDR")
        return fallback
    if hops == 0:
        return fallback
    forwarded = request.headers.get("x-forwarded-for", "")
    if not isinstance(forwarded, str):
        return fallback
    addresses = forwarded.split(",")
    if len(addresses) < hops:
        return fallback
    try:
        return str(ipaddress.ip_address(addresses[-hops].strip()))
    except ValueError:
        return fallback


def _cache_key(endpoint_key: str, method: str, identity: str) -> str:
    identity_digest = hmac.new(
        force_bytes(settings.SECRET_KEY),
        identity.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"indieweb:rate-limit:v3:{endpoint_key}:{method}:{identity_digest}"


def check_rate_limit(request: HttpRequest, endpoint_key: str, *, method_bucket: str | None = None) -> RateLimitResult:
    """Check and increment the configured rate limit for a request.

    Counters are keyed by endpoint, ``method_bucket`` and client identity.
    ``method_bucket`` defaults to the upper-cased request method;
    ``RateLimitMixin`` passes ``UNSUPPORTED_METHOD_BUCKET`` for methods the
    view does not implement.

    Counts are best-effort: portable get/set operations can lose concurrent
    increments. The stored deadline, rather than the backend TTL, fixes the
    window. If the cache cannot keep a counter the
    request is rejected (fail closed) with ``Retry-After`` set to the remaining window.
    ``DummyCache`` is the documented exception: it never stores anything, so
    it disables rate limiting instead of rejecting every request.
    """
    config = get_rate_limit_config(endpoint_key)
    if config is None:
        return RateLimitResult(allowed=True)
    if isinstance(caches[DEFAULT_CACHE_ALIAS], DummyCache):
        return RateLimitResult(allowed=True)

    now = time.time()
    bucket = method_bucket if method_bucket is not None else (request.method or "").upper()
    counter_key = _cache_key(endpoint_key, bucket, _client_identity(request))

    retry_after = config.window
    try:
        counter = cache.get(counter_key)
        if counter is None or now >= counter["reset_at"]:
            counter = {"count": 0, "reset_at": now + config.window}
        count = counter["count"] + 1
        reset_at = counter["reset_at"]
        remaining = reset_at - now
        retry_after = max(1, min(config.window, math.ceil(remaining)))
        cache.set(counter_key, {"count": count, "reset_at": reset_at}, timeout=retry_after)
        stored = cache.get(counter_key)
    except Exception:
        # Cache backends expose different exception types. Never log their
        # messages or traceback: connection details can contain credentials.
        logger.warning("Rate-limit cache unavailable for %r; rejecting request", endpoint_key)
        return RateLimitResult(allowed=False, retry_after=retry_after)
    if stored is None:
        logger.warning(f"Rate-limit counter for {endpoint_key!r} could not be stored in the cache; rejecting request")
        return RateLimitResult(allowed=False, retry_after=retry_after)
    if count <= config.limit:
        return RateLimitResult(allowed=True)
    return RateLimitResult(allowed=False, retry_after=max(1, math.ceil(remaining)))


def rate_limit_response(result: RateLimitResult) -> HttpResponse:
    """Build the standard response for an exceeded endpoint rate limit."""
    response = HttpResponse("rate limit exceeded", status=429, content_type="text/plain")
    if result.retry_after is not None:
        response["Retry-After"] = str(result.retry_after)
    return response


class RateLimitMixin(View):
    """Apply a configured rate limit before dispatching to endpoint work."""

    rate_limit_key: str | None = None

    def _rate_limit_method_bucket(self, request: HttpRequest) -> str:
        """Return the counter bucket for the request method.

        Each method the view implements keeps its own counter. Every other
        method shares one bucket, so a client cannot create a cache key per
        invented method name or gain an extra allowance per unsupported method.
        """
        method = (request.method or "").lower()
        if method in self.http_method_names and hasattr(self, method):
            return method.upper()
        return UNSUPPORTED_METHOD_BUCKET

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponseBase:
        if self.rate_limit_key is not None:
            result = check_rate_limit(
                request, self.rate_limit_key, method_bucket=self._rate_limit_method_bucket(request)
            )
            if not result.allowed:
                return rate_limit_response(result)
        return super().dispatch(request, *args, **kwargs)
