"""Locality checks for Micropub action URLs.

Micropub ``update``, ``delete``, ``undelete`` and media ``delete`` requests
name the affected resource by URL. Before such a URL reaches the configured
handler, the endpoint checks that it is local to the site:

* With ``INDIEWEB_MICROPUB_CANONICAL_ORIGINS`` set, an absolute URL must use
  one of the configured origins (scheme, host and port).
* Without it, an absolute URL must name the host of the current request, so
  the check inherits the project's ``ALLOWED_HOSTS`` and proxy configuration.
* A relative reference is accepted only as an absolute path (``/2026/post/``),
  never as a network-path (``//host/``) or path-relative (``post/``,
  ``../post``) reference.
* The path must not contain ``.``/``..`` segments, backslashes, or control
  characters, including percent-encoded forms.

The handler still owns URL resolution and ownership checks; see the handler
contract in ``docs/micropub.rst``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any
from urllib.parse import unquote, urlsplit

from django.conf import settings

logger = logging.getLogger(__name__)

CANONICAL_ORIGINS_SETTING = "INDIEWEB_MICROPUB_CANONICAL_ORIGINS"

Origin = tuple[str, str, int | None]

_DEFAULT_PORTS = {"http": 80, "https": 443}
_MAX_DECODE_ROUNDS = 4

_warned_invalid: set[str] = set()


def _normalized_port(scheme: str, port: int | None) -> int | None:
    return None if port == _DEFAULT_PORTS.get(scheme) else port


def parse_origin(value: Any) -> Origin:
    """Parse one configured origin such as ``"https://example.com"``.

    Raises ``ValueError`` unless ``value`` is an http(s) origin without
    userinfo, path (other than ``/``), query, or fragment.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("origin must be a non-empty string")
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError as exc:
        raise ValueError("origin is not a valid URL") from exc
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        raise ValueError("origin must use http or https")
    if not parts.hostname:
        raise ValueError("origin must include a host")
    if parts.username is not None or parts.password is not None:
        raise ValueError("origin must not include userinfo")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("origin must not include a path, query, or fragment")
    return scheme, parts.hostname.lower(), _normalized_port(scheme, port)


def parse_canonical_origins(value: Any) -> tuple[Origin, ...]:
    """Parse ``INDIEWEB_MICROPUB_CANONICAL_ORIGINS`` (a string or an iterable of strings)."""
    if isinstance(value, str):
        candidates: Iterable[Any] = (value,)
    elif isinstance(value, Iterable) and not isinstance(value, bytes | bytearray | dict):
        candidates = tuple(value)
    else:
        raise ValueError("expected an origin string or an iterable of origin strings")
    origins = tuple(parse_origin(candidate) for candidate in candidates)
    if not origins:
        raise ValueError("expected at least one origin")
    return origins


def configured_canonical_origins() -> tuple[Origin, ...] | None:
    """Return the configured canonical origins, ``None`` when unset, or ``()`` when invalid.

    Only ``None`` (or an absent setting) means unset; an empty string or empty
    list is invalid and fails closed.

    An invalid setting fails closed: callers treat ``()`` as "no URL is
    local". The problem is logged once per distinct value and reported by the
    ``indieweb.E001`` system check.
    """
    value = getattr(settings, CANONICAL_ORIGINS_SETTING, None)
    if value is None:
        return None
    try:
        return parse_canonical_origins(value)
    except ValueError as exc:
        marker = repr(value)[:200]
        if marker not in _warned_invalid:
            _warned_invalid.add(marker)
            logger.error(
                f"Invalid {CANONICAL_ORIGINS_SETTING} ({type(exc).__name__}); rejecting all Micropub action URLs. "
                "The indieweb.E001 system check (manage.py check) reports the problem."
            )
        return ()


def _has_unsafe_characters(value: str) -> bool:
    return "\\" in value or any(ord(char) < 0x20 or ord(char) == 0x7F or char.isspace() for char in value)


def path_is_safe(path: str) -> bool:
    """Return whether ``path`` is free of dot segments, backslashes, and control characters.

    The path is percent-decoded repeatedly (up to a small bound) so encoded
    forms such as ``%2e%2e%2f`` are caught as well. A path that still
    contains percent-escapes after the bound is rejected.
    """
    current = path
    for _round in range(_MAX_DECODE_ROUNDS):
        if _has_unsafe_characters(current):
            return False
        if any(segment in (".", "..") for segment in current.split("/")):
            return False
        decoded = unquote(current)
        if decoded == current:
            return True
        current = decoded
    return False


def _origin_matches_request(request: Any, scheme: str, hostname: str, port: int | None) -> bool:
    try:
        request_parts = urlsplit(f"//{request.get_host()}")
        request_port = request_parts.port
    except ValueError:
        return False
    if not request_parts.hostname:
        return False
    request_scheme = (getattr(request, "scheme", None) or scheme).lower()
    submitted = (hostname, _normalized_port(scheme, port))
    current = (request_parts.hostname.lower(), _normalized_port(request_scheme, request_port))
    return submitted == current


def absolute_url_is_local(request: Any, url: str) -> bool:
    """Return whether absolute ``url`` uses a canonical origin (or, if unset, the request host).

    With canonical origins configured the comparison covers scheme, host, and
    port. Without them it keeps the historic host/port comparison against
    ``request.get_host()``.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not parts.netloc or not parts.hostname:
        return False
    if parts.username is not None or parts.password is not None:
        return False
    hostname = parts.hostname.lower()
    origins = configured_canonical_origins()
    if origins is not None:
        return (scheme, hostname, _normalized_port(scheme, port)) in origins
    return _origin_matches_request(request, scheme, hostname, port)


def action_url_is_local(request: Any, url: str) -> bool:
    """Return whether a Micropub action URL may be forwarded to the handler."""
    if not isinstance(url, str) or not url or _has_unsafe_characters(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme or parts.netloc:
        if not absolute_url_is_local(request, url):
            return False
    elif not url.startswith("/") or url.startswith("//"):
        return False
    return path_is_safe(parts.path)
