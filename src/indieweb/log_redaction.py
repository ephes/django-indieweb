"""Privacy-oriented log redaction helpers.

INDIEWEB_LOG_REDACTION = "passthrough" | "redact"
- "passthrough" (default): values pass through unchanged.
- "redact": helpers return a stable HMAC-SHA256 digest (truncated to 12 hex
  chars) keyed with SECRET_KEY for correlation without disclosure.

The digest is one-way and stable per input: log consumers can correlate
events by digest without seeing the URL/state/me values themselves.
"""

from __future__ import annotations

import hmac
from hashlib import sha256
from typing import Literal
from urllib.parse import urlparse

from django.conf import settings

Mode = Literal["passthrough", "redact"]


def _resolve_mode(mode: Mode | None) -> Mode:
    if mode in ("passthrough", "redact"):
        return mode
    configured = getattr(settings, "INDIEWEB_LOG_REDACTION", "passthrough")
    return "redact" if configured == "redact" else "passthrough"


def _digest(value: str) -> str:
    secret_key = settings.SECRET_KEY
    key_bytes = secret_key.encode("utf-8") if isinstance(secret_key, str) else bytes(secret_key)
    return hmac.new(key_bytes, value.encode("utf-8"), sha256).hexdigest()[:12]


def redact_url(url: str, *, mode: Mode | None = None) -> str:
    """Return ``url`` unchanged in passthrough mode, or a stable 12-hex digest in redact mode."""
    if _resolve_mode(mode) == "passthrough":
        return url
    return _digest(url)


def redact_url_origin(url: str, *, mode: Mode | None = None) -> str:
    """Return scheme+host of ``url`` unchanged in passthrough mode, or a stable 12-hex digest in redact mode.

    The redacted form is stable for any URL with the same scheme+host pair,
    so log consumers can group events by origin without seeing paths.
    """
    if _resolve_mode(mode) == "passthrough":
        return url
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{(parsed.hostname or '').lower()}"
    return _digest(origin)


def redact_state(value: str, *, mode: Mode | None = None) -> str:
    """Return ``value`` unchanged in passthrough mode, or a stable 12-hex digest in redact mode."""
    if _resolve_mode(mode) == "passthrough":
        return value
    return _digest(value)
