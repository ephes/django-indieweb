"""Sanitizers for untrusted remote IndieWeb content."""

from __future__ import annotations

from urllib.parse import urlparse

import nh3
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

_SAFE_REMOTE_URL_VALIDATOR = URLValidator(schemes=["http", "https"])
_REMOTE_HTML_URL_ATTRIBUTES = {"href", "cite"}


def _webmention_html_attribute_filter(_tag: str, attribute: str, value: str) -> str | None:
    """Drop URL attributes unless remote content provided an absolute HTTP(S) URL."""
    if attribute in _REMOTE_HTML_URL_ATTRIBUTES:
        return sanitize_remote_webmention_url(value) or None
    return value


_WEBMENTION_HTML_CLEANER = nh3.Cleaner(
    tags={
        "a",
        "abbr",
        "b",
        "blockquote",
        "br",
        "cite",
        "code",
        "del",
        "em",
        "i",
        "li",
        "ol",
        "p",
        "pre",
        "q",
        "s",
        "span",
        "strong",
        "ul",
    },
    attributes={
        "a": {"href", "title"},
        "abbr": {"title"},
        "blockquote": {"cite"},
        "q": {"cite"},
    },
    clean_content_tags={
        "embed",
        "form",
        "iframe",
        "math",
        "object",
        "script",
        "style",
        "svg",
        "template",
    },
    link_rel="nofollow noopener ugc",
    strip_comments=True,
    url_schemes={"http", "https"},
    attribute_filter=_webmention_html_attribute_filter,
)


def sanitize_webmention_html(value: str | None) -> str:
    """Return a safe HTML fragment for remote Webmention display."""
    if not value:
        return ""
    return _WEBMENTION_HTML_CLEANER.clean(value)


def sanitize_remote_webmention_url(value: str | None) -> str:
    """Return an absolute HTTP(S) URL for remote Webmention fields, or an empty string."""
    if not value:
        return ""

    candidate = value.strip()
    if not candidate:
        return ""

    try:
        parsed = urlparse(candidate)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return ""
        # Accessing these properties raises ValueError for malformed IPv6 or ports.
        if parsed.hostname is None:
            return ""
        _ = parsed.port
        _SAFE_REMOTE_URL_VALIDATOR(candidate)
    except (TypeError, ValueError, ValidationError):
        return ""

    return candidate
