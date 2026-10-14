"""Privacy-oriented log redaction helpers.

INDIEWEB_LOG_REDACTION = "passthrough" | "redact"
- "passthrough" (default): values pass through unchanged.
- "redact": helpers return a stable HMAC-SHA256 digest (truncated to 12 hex
  chars) keyed with SECRET_KEY for correlation without disclosure.
- Values are matched case-insensitively; any other value fails closed to
  "redact" and is logged once as a warning.

The digest is one-way and stable per input: log consumers can correlate
events by digest without seeing the URL/state/me values themselves.
"""

from __future__ import annotations

import hmac
import logging
from hashlib import sha256
from typing import Literal, cast
from urllib.parse import urlparse

from django.conf import settings

logger = logging.getLogger(__name__)

Mode = Literal["passthrough", "redact"]

# Leading token characters kept by ``redact_token`` in passthrough mode.
TOKEN_PREFIX_LENGTH = 4


_warned_settings: set[str] = set()


def configured_mode() -> Mode:
    """Return the ``INDIEWEB_LOG_REDACTION`` mode, failing closed to ``"redact"``.

    Values are compared case-insensitively after trimming whitespace. Any
    other value (a typo, ``True``, ``"yes"``) is treated as ``"redact"`` and
    logged once as a warning, so a misspelled opt-in never leaks values.
    """
    configured = getattr(settings, "INDIEWEB_LOG_REDACTION", "passthrough")
    if isinstance(configured, str):
        normalized = configured.strip().lower()
        if normalized in ("passthrough", "redact"):
            return cast(Mode, normalized)
    marker = repr(configured)
    if marker not in _warned_settings:
        _warned_settings.add(marker)
        logger.warning(
            'INDIEWEB_LOG_REDACTION=%s is not "passthrough" or "redact"; using "redact"',
            marker[:64],
        )
    return "redact"


def _resolve_mode(mode: Mode | None) -> Mode:
    if mode in ("passthrough", "redact"):
        return mode
    return configured_mode()


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


def redact_text(value: str, *, mode: Mode | None = None) -> str:
    """Return free-form ``value`` unchanged in passthrough mode, or ``<redacted:DIGEST>`` in redact mode.

    Use this for text that is not a single URL or identifier but may embed
    one, such as an exception message from an outbound request. The digest
    still lets operators group identical failures.
    """
    if _resolve_mode(mode) == "passthrough":
        return value
    return f"<redacted:{_digest(value)}>"


def redact_token(value: str, *, mode: Mode | None = None) -> str:
    """Return a non-secret display form for a bearer token or auth code.

    Bearer tokens and authorization codes must never be logged in full,
    so even in passthrough mode this helper truncates the input to its
    first 4 characters with a trailing ellipsis, enough to tell tokens
    apart in diagnostics without disclosing a useful share of the secret.
    In redact mode the token is replaced
    with a stable 12-hex HMAC digest so events for the same token can
    still be correlated without exposing any leading bytes of the
    secret.
    """
    if _resolve_mode(mode) == "passthrough":
        return f"{value[:TOKEN_PREFIX_LENGTH]}..." if value else ""
    return _digest(value)
