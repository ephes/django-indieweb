from __future__ import annotations

import hashlib
import hmac
import logging
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, HttpResponseBase
from django.utils.encoding import force_bytes
from django.views.generic import View

logger = logging.getLogger(__name__)


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
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def get_rate_limit_config(endpoint_key: str) -> RateLimitConfig | None:
    """Return the validated rate-limit config for ``endpoint_key``.

    ``INDIEWEB_RATE_LIMITS`` defaults to disabled. Invalid global or per-key
    values are ignored so an optional hardening setting cannot crash protocol
    endpoints.
    """
    configured = getattr(settings, "INDIEWEB_RATE_LIMITS", None)
    if not configured:
        return None
    if not isinstance(configured, Mapping):
        logger.warning("Ignoring invalid INDIEWEB_RATE_LIMITS value; expected a mapping")
        return None

    endpoint_config = configured.get(endpoint_key)
    if not endpoint_config:
        return None
    if not isinstance(endpoint_config, Mapping):
        logger.warning(f"Ignoring invalid rate-limit config for {endpoint_key!r}; expected a mapping")
        return None

    limit = _positive_int(endpoint_config.get("limit"))
    window = _positive_int(endpoint_config.get("window"))
    if limit is None or window is None:
        logger.warning(
            f"Ignoring invalid rate-limit config for {endpoint_key!r}; limit and window must be positive integers"
        )
        return None
    return RateLimitConfig(limit=limit, window=window)


def _client_identity(request: HttpRequest) -> str:
    """Return the client identity used for rate-limit counters."""
    value = request.META.get("REMOTE_ADDR", "")
    if value is None:
        return ""
    return str(value)


def _cache_key(endpoint_key: str, method: str, identity: str) -> str:
    identity_digest = hmac.new(
        force_bytes(settings.SECRET_KEY),
        identity.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"indieweb:rate-limit:v2:{endpoint_key}:{method}:{identity_digest}"


def _retry_after(counter_key: str, now: float, fallback_window: int) -> int:
    reset_at = cache.get(f"{counter_key}:reset")
    if not isinstance(reset_at, int | float):
        return fallback_window
    return max(1, math.ceil(reset_at - now))


def check_rate_limit(request: HttpRequest, endpoint_key: str) -> RateLimitResult:
    """Check and increment the configured rate limit for a request."""
    config = get_rate_limit_config(endpoint_key)
    if config is None:
        return RateLimitResult(allowed=True)

    now = time.time()
    method = (request.method or "").upper()
    counter_key = _cache_key(endpoint_key, method, _client_identity(request))
    reset_key = f"{counter_key}:reset"
    reset_at = now + config.window

    cache.add(reset_key, reset_at, config.window)
    cache.add(counter_key, 0, config.window)
    try:
        count = cache.incr(counter_key)
    except ValueError:
        cache.set(counter_key, 1, config.window)
        cache.set(reset_key, reset_at, config.window)
        count = 1

    if count <= config.limit:
        return RateLimitResult(allowed=True)
    return RateLimitResult(allowed=False, retry_after=_retry_after(counter_key, now, config.window))


def rate_limit_response(result: RateLimitResult) -> HttpResponse:
    """Build the standard response for an exceeded endpoint rate limit."""
    response = HttpResponse("rate limit exceeded", status=429, content_type="text/plain")
    if result.retry_after is not None:
        response["Retry-After"] = str(result.retry_after)
    return response


class RateLimitMixin(View):
    """Apply a configured rate limit before dispatching to endpoint work."""

    rate_limit_key: str | None = None

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponseBase:
        if self.rate_limit_key is not None:
            result = check_rate_limit(request, self.rate_limit_key)
            if not result.allowed:
                return rate_limit_response(result)
        return super().dispatch(request, *args, **kwargs)
