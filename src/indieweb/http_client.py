"""Shared HTTP helpers for IndieWeb protocol clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

WEBMENTION_ALLOWED_REDIRECT_SCHEMES = ("http", "https")
WEBMENTION_MAX_REDIRECTS = 5
WEBMENTION_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


class WebmentionRedirectError(Exception):
    """Raised when a Webmention HTTP redirect cannot be followed safely."""


@dataclass(frozen=True)
class RedirectedResponse:
    """HTTP response plus the URL reached after following redirects."""

    response: httpx.Response
    final_url: str


def request_with_webmention_redirects(
    client: httpx.Client,
    method: str,
    url: str,
    **request_kwargs: Any,
) -> RedirectedResponse:
    """Run an HTTP request with explicit bounded Webmention redirect handling.

    Redirects are followed only to absolute ``http`` and ``https`` URLs after
    resolving relative ``Location`` values against the URL that produced the
    redirect. The original method and request body are preserved across all
    followed redirects, including Webmention endpoint ``POST`` delivery.
    """
    current_url = url
    request_method = getattr(client, method.lower())

    for redirects_followed in range(WEBMENTION_MAX_REDIRECTS + 1):
        response = request_method(current_url, **request_kwargs)
        if response.status_code not in WEBMENTION_REDIRECT_STATUS_CODES:
            return RedirectedResponse(response=response, final_url=current_url)

        location = response.headers.get("location") or response.headers.get("Location")
        if not location:
            return RedirectedResponse(response=response, final_url=current_url)

        if redirects_followed >= WEBMENTION_MAX_REDIRECTS:
            raise WebmentionRedirectError(f"exceeded {WEBMENTION_MAX_REDIRECTS} Webmention redirects")

        next_url = urljoin(current_url, location)
        parsed = urlparse(next_url)
        if parsed.scheme.lower() not in WEBMENTION_ALLOWED_REDIRECT_SCHEMES or not parsed.netloc:
            raise WebmentionRedirectError(f"unsupported Webmention redirect target: {next_url}")

        current_url = next_url

    raise WebmentionRedirectError(f"exceeded {WEBMENTION_MAX_REDIRECTS} Webmention redirects")
