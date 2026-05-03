"""Publisher-side WebSub helpers."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import HttpResponseBase

logger = logging.getLogger(__name__)

DEFAULT_WEBSUB_TIMEOUT = 10.0
WEBSUB_ALLOWED_SCHEMES = ("http", "https")


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
    http_client = client or httpx.Client(timeout=request_timeout, follow_redirects=False)
    results: list[WebSubNotificationResult] = []
    try:
        for hub_url in hub_urls:
            try:
                response = http_client.post(hub_url, data=data)
            except httpx.RequestError as exc:
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
