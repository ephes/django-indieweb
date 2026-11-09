"""Webmention sender implementation."""

import logging
import math
import re
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag
from django.conf import settings
from django.db import router
from django.db.models import Case, F, Q, Value, When
from django.utils import timezone

from .http_client import (
    SAFE_HTTP_DEFAULT_LIMITS,
    SAFE_HTTP_DEFAULT_TIMEOUT,
    AddressResolver,
    HTTPResponseTooLarge,
    HTTPTotalTimeoutExceeded,
    RedirectedResponse,
    default_address_resolver,
    disable_client_cookies,
    is_safe_http_url,
    outbound_user_agent,
    request_with_webmention_redirects,
    stream_with_safe_redirects,
    validate_safe_http_url,
)
from .models import WebmentionOutboundTarget

logger = logging.getLogger(__name__)

DEFAULT_WEBMENTION_SENDER_FETCH_MAX_BYTES = 1024 * 1024
DEFAULT_WEBMENTION_SENDER_HEAD_MAX_BYTES = 64 * 1024
DEFAULT_WEBMENTION_SENDER_RESPONSE_MAX_BYTES = 1024 * 1024
DEFAULT_WEBMENTION_MAX_TARGETS_PER_SOURCE = 50
DEFAULT_WEBMENTION_MAX_TARGETS_PER_HOST = 5
DEFAULT_SALMENTION_RESEND_COOLDOWN_SECONDS = 24 * 60 * 60
DEFAULT_SALMENTION_SUCCESS_CUTOFF_SECONDS = 30 * 24 * 60 * 60
DEFAULT_SALMENTION_MAX_CONSECUTIVE_FAILURES = 5
DEFAULT_WEBMENTION_SEND_TOTAL_TIMEOUT_SECONDS = 30.0
# Per-operation timeouts for endpoint discovery and delivery. Each one only
# bounds a single connect, read, write or pool wait; the total budget from
# ``INDIEWEB_WEBMENTION_SEND_TOTAL_TIMEOUT_SECONDS`` bounds a whole call.
WEBMENTION_DISCOVERY_TIMEOUT = SAFE_HTTP_DEFAULT_TIMEOUT
WEBMENTION_DELIVERY_TIMEOUT = httpx.Timeout(connect=3.0, read=15.0, write=5.0, pool=2.0)


def _webmention_send_total_timeout() -> float:
    """Return the time budget in seconds for one outbound discovery, delivery or source fetch."""
    configured = getattr(
        settings, "INDIEWEB_WEBMENTION_SEND_TOTAL_TIMEOUT_SECONDS", DEFAULT_WEBMENTION_SEND_TOTAL_TIMEOUT_SECONDS
    )
    if isinstance(configured, (int, float)) and not isinstance(configured, bool):
        if math.isfinite(configured) and configured > 0:
            return float(configured)
    logger.warning(
        "Invalid INDIEWEB_WEBMENTION_SEND_TOTAL_TIMEOUT_SECONDS; using "
        f"{DEFAULT_WEBMENTION_SEND_TOTAL_TIMEOUT_SECONDS} seconds"
    )
    return DEFAULT_WEBMENTION_SEND_TOTAL_TIMEOUT_SECONDS


def _webmention_strict_redirects() -> bool:
    """Return whether endpoint delivery refuses cross-origin redirects."""
    return getattr(settings, "INDIEWEB_WEBMENTION_STRICT_REDIRECTS", False) is True


def _sender_fetch_max_bytes() -> int | None:
    return _optional_positive_int_setting(
        "INDIEWEB_WEBMENTION_FETCH_MAX_BYTES", DEFAULT_WEBMENTION_SENDER_FETCH_MAX_BYTES
    )


def _sender_response_max_bytes() -> int | None:
    """Return the decoded POST response cap; only explicit None disables it."""
    return _optional_positive_int_setting(
        "INDIEWEB_WEBMENTION_RESPONSE_MAX_BYTES", DEFAULT_WEBMENTION_SENDER_RESPONSE_MAX_BYTES
    )


def _sender_head_max_bytes() -> int | None:
    return _optional_positive_int_setting(
        "INDIEWEB_WEBMENTION_HEAD_MAX_BYTES", DEFAULT_WEBMENTION_SENDER_HEAD_MAX_BYTES
    )


def _positive_int_setting(name: str, default: int) -> int:
    configured = getattr(settings, name, default)
    try:
        if isinstance(configured, bool):
            raise ValueError("booleans are not counts")
        parsed = int(configured)
        if parsed <= 0 or (not isinstance(configured, str) and configured != parsed):
            raise ValueError("counts must be positive integers")
    except (TypeError, ValueError, OverflowError):
        logger.warning("Ignoring invalid %s value; using default %s", name, default)
        return default
    return parsed


def _optional_positive_int_setting(name: str, default: int) -> int | None:
    configured = getattr(settings, name, default)
    if configured is None:
        return None
    return _positive_int_setting(name, default)


def _salmention_resend_cooldown() -> timedelta:
    seconds = _positive_int_setting(
        "INDIEWEB_SALMENTION_RESEND_COOLDOWN_SECONDS", DEFAULT_SALMENTION_RESEND_COOLDOWN_SECONDS
    )
    try:
        return timedelta(seconds=seconds)
    except OverflowError:
        logger.warning("Ignoring invalid INDIEWEB_SALMENTION_RESEND_COOLDOWN_SECONDS; using default")
        return timedelta(seconds=DEFAULT_SALMENTION_RESEND_COOLDOWN_SECONDS)


def _salmention_success_cutoff() -> timedelta | None:
    seconds = _optional_positive_int_setting(
        "INDIEWEB_SALMENTION_SUCCESS_CUTOFF_SECONDS", DEFAULT_SALMENTION_SUCCESS_CUTOFF_SECONDS
    )
    if seconds is None:
        return None
    try:
        return timedelta(seconds=seconds)
    except OverflowError:
        logger.warning("Ignoring invalid INDIEWEB_SALMENTION_SUCCESS_CUTOFF_SECONDS; using default")
        return timedelta(seconds=DEFAULT_SALMENTION_SUCCESS_CUTOFF_SECONDS)


def _salmention_max_consecutive_failures() -> int:
    return _positive_int_setting(
        "INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES",
        DEFAULT_SALMENTION_MAX_CONSECUTIVE_FAILURES,
    )


def _canonical_destination_host(url: str) -> str | None:
    """Return a stable destination-host key for outbound fanout limits."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if not host:
        return None
    try:
        normalized_host = host.encode("idna").decode("ascii").lower()
    except (UnicodeError, UnicodeDecodeError):
        normalized_host = host.lower()
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"
    default_port = 443 if parsed.scheme.lower() == "https" else 80 if parsed.scheme.lower() == "http" else None
    if port is not None and port != default_port:
        return f"{normalized_host}:{port}"
    return normalized_host


def _webmention_max_targets_per_source() -> int | None:
    return _optional_positive_int_setting(
        "INDIEWEB_WEBMENTION_MAX_TARGETS_PER_SOURCE",
        DEFAULT_WEBMENTION_MAX_TARGETS_PER_SOURCE,
    )


def _webmention_max_targets_per_host() -> int | None:
    return _optional_positive_int_setting(
        "INDIEWEB_WEBMENTION_MAX_TARGETS_PER_HOST",
        DEFAULT_WEBMENTION_MAX_TARGETS_PER_HOST,
    )


def _split_outside_quotes(value: str, separator: str, *, angle_brackets: bool = False) -> list[str]:
    """Split ``value`` on ``separator`` outside quoted strings.

    With ``angle_brackets``, a ``<...>`` section that opens a part is kept
    intact as well. A backslash escapes the next character inside quotes.
    """
    parts: list[str] = []
    current: list[str] = []
    in_quotes = in_angle = escaped = False
    for char in value:
        if in_quotes:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_quotes = False
        elif in_angle:
            in_angle = char != ">"
        elif char == separator:
            parts.append("".join(current))
            current = []
            continue
        elif char == '"':
            in_quotes = True
        elif angle_brackets and char == "<" and not "".join(current).strip():
            in_angle = True
        current.append(char)
    parts.append("".join(current))
    return parts


def _split_link_value(link_value: str) -> tuple[str | None, list[str]]:
    """Return the ``<target>`` and raw parameters of one RFC 8288 link-value."""
    stripped = link_value.strip()
    closing = stripped.find(">")
    if not stripped.startswith("<") or closing == -1:
        return None, []
    target = stripped[1:closing].strip()
    params = _split_outside_quotes(stripped[closing + 1 :], ";")
    return (target or None), params


def _first_link_param(params: list[str], name: str) -> str | None:
    """Return the unquoted value of the first parameter called ``name``, or None."""
    for param in params:
        param_name, separator, raw_value = param.partition("=")
        if not separator or param_name.strip().lower() != name:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            return re.sub(r"\\(.)", r"\1", value[1:-1])
        return value
    return None


class WebmentionSender:
    """Sends webmentions to target URLs."""

    def __init__(self) -> None:
        self.timeout: httpx.Timeout = WEBMENTION_DISCOVERY_TIMEOUT
        self.post_timeout: httpx.Timeout = WEBMENTION_DELIVERY_TIMEOUT

    def extract_urls(self, html_content: str) -> list[str]:
        """Extract all URLs from HTML content.

        Args:
            html_content: HTML content to parse

        Returns:
            List of unique URLs found in the content
        """
        soup = BeautifulSoup(html_content, "html.parser")
        urls: list[str] = []
        seen: set[str] = set()

        # Find all anchor tags with href attributes
        for tag in soup.find_all("a", href=True):
            if isinstance(tag, Tag):
                href = tag.get("href")
                if href and isinstance(href, str) and href not in seen:
                    seen.add(href)
                    urls.append(href)

        return urls

    def discover_endpoint(self, target_url: str, *, client: httpx.Client | None = None) -> str | None:
        """Discover the webmention endpoint for a target URL.

        Probes HEAD first, then confirms discovery with GET even when HEAD
        advertises an endpoint. GET is authoritative: its ``Link`` header
        takes precedence over HTML, and a HEAD-only endpoint is not used.
        HEAD error statuses still allow GET discovery. SSRF, redirect and
        response-size failures stay fail-closed and are never retried with GET,
        including an unsafe or unresolvable HEAD-advertised endpoint.
        HEAD and GET share
        one ``INDIEWEB_WEBMENTION_SEND_TOTAL_TIMEOUT_SECONDS`` budget; a
        discovery over the budget returns ``None``.

        Args:
            target_url: The URL to discover the endpoint for
            client: Optional injected ``httpx.Client``. When provided, the SSRF
                resolver is skipped (DNS-based blocking and IP pinning), so
                callers injecting their own transport (typically tests) opt
                out of network-level safety checks. Production callers should
                leave this unset.

        Returns:
            The webmention endpoint URL or None if not found
        """
        close_client = client is None
        http_client = (
            client
            if client is not None
            else disable_client_cookies(
                httpx.Client(
                    verify=True,
                    trust_env=False,
                    limits=SAFE_HTTP_DEFAULT_LIMITS,
                    headers={"User-Agent": outbound_user_agent()},
                )
            )
        )
        resolver = default_address_resolver if close_client else None
        deadline = time.monotonic() + _webmention_send_total_timeout()
        try:
            validate_safe_http_url(target_url, resolver=resolver)
            # First try HEAD request to check Link headers
            discovered = request_with_webmention_redirects(
                http_client,
                "HEAD",
                target_url,
                resolver=resolver,
                timeout=self.timeout,
                max_bytes=_sender_head_max_bytes(),
                total_timeout=deadline - time.monotonic(),
            )
            # Preserve fail-closed validation of successful HEAD advertisements.
            # HEAD errors (e.g. 405) still allow a GET attempt.
            if discovered.response.is_success:
                self._endpoint_from_link_header(discovered, resolver=resolver)

            # Confirm with GET: Link header first, then HTML. The GET gets
            # only what is left of the discovery budget.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HTTPTotalTimeoutExceeded("HTTP total deadline exceeded")
            discovered = stream_with_safe_redirects(
                http_client,
                "GET",
                target_url,
                max_bytes=_sender_fetch_max_bytes(),
                resolver=resolver,
                timeout=self.timeout,
                total_timeout=remaining,
            )
            response = discovered.response
            response.raise_for_status()

            endpoint = self._endpoint_from_link_header(discovered, resolver=resolver)
            if endpoint:
                return endpoint

            endpoint = self._parse_html_for_endpoint(response.text, discovered.final_url)
            if endpoint:
                validate_safe_http_url(endpoint, resolver=resolver)
            return endpoint

        except Exception:
            # Return None for any errors during discovery
            return None
        finally:
            if close_client:
                http_client.close()

    def _endpoint_from_link_header(
        self, discovered: RedirectedResponse, *, resolver: AddressResolver | None
    ) -> str | None:
        """Return the validated absolute endpoint from a discovery response's ``Link`` header."""
        endpoint = self._parse_link_header(discovered.response.headers.get("Link", ""))
        if not endpoint:
            return None
        resolved_endpoint = urljoin(discovered.final_url, endpoint)
        validate_safe_http_url(resolved_endpoint, resolver=resolver)
        return resolved_endpoint

    def _parse_link_header(self, link_header: str) -> str | None:
        """Parse Link header for webmention endpoint.

        Args:
            link_header: The Link header value

        Returns:
            The webmention endpoint URL or None
        """
        if not link_header:
            return None

        # Per RFC 8288, a Link header is a comma-separated list of link-values,
        # each shaped ``<url>; param1=...; param2=...``. Commas and semicolons
        # inside ``<...>`` or inside a quoted parameter value are data, not
        # separators, so the header is tokenized instead of matched with a
        # comma-stopping regex. ``rel`` can appear at any position, quoted or
        # as a bare token; only the first ``rel`` of a link-value counts, and
        # it must contain the exact ``webmention`` token (case-insensitive).
        for link_value in _split_outside_quotes(link_header, ",", angle_brackets=True):
            target, params = _split_link_value(link_value)
            if target is None:
                continue
            rel = _first_link_param(params, "rel")
            if rel is not None and "webmention" in rel.lower().split():
                return target

        return None

    @staticmethod
    def _rel_attribute_includes_webmention(value: object) -> bool:
        """Return whether an HTML ``rel`` attribute names the exact ``webmention`` token.

        BeautifulSoup may parse ``rel`` as either a list of tokens or a raw
        string depending on the element and parser; require an exact token
        match in both cases so adversarial values like ``not-webmention``
        and ``webmention-foo`` are not accepted as endpoint declarations.
        """
        if isinstance(value, str):
            return "webmention" in value.lower().split()
        if isinstance(value, list):
            return any(isinstance(token, str) and token.lower() == "webmention" for token in value)
        return False

    def _parse_html_for_endpoint(self, html_content: str, base_url: str) -> str | None:
        """Parse HTML for webmention endpoint.

        Args:
            html_content: HTML content to parse
            base_url: Base URL for resolving relative URLs

        Returns:
            The webmention endpoint URL or None
        """
        soup = BeautifulSoup(html_content, "html.parser")

        # The first <link> or <a> in document order wins (Webmention spec 3.1.2).
        # An empty href is a valid relative reference to the page itself.
        element = soup.find(["link", "a"], rel=self._rel_attribute_includes_webmention, href=True)
        if isinstance(element, Tag):
            href = element.get("href")
            if isinstance(href, str):
                return urljoin(base_url, href)

        return None

    def send_webmention(
        self,
        source: str,
        target: str,
        endpoint: str,
        vouch: str | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> dict:
        """Send a webmention to an endpoint.

        Args:
            source: The source URL (your post)
            target: The target URL (the linked post)
            endpoint: The webmention endpoint URL
            vouch: Optional Vouch URL to include with the Webmention
            client: Optional injected ``httpx.Client``. See
                :meth:`discover_endpoint` for the safety semantics.

        The POST, including any redirects and the response body, must finish
        within ``INDIEWEB_WEBMENTION_SEND_TOTAL_TIMEOUT_SECONDS``. With
        ``INDIEWEB_WEBMENTION_STRICT_REDIRECTS = True`` a redirect to another
        origin fails the delivery instead of replaying the POST body there.

        The Vouch URL is only checked syntactically (``resolver=None``): the
        sender never fetches it, so its host is not resolved. The receiver
        fetches it, with its own SSRF checks, when it verifies the Vouch.

        Returns:
            Dict with 'success', 'status_code', and optionally 'error'
        """
        close_client = client is None
        http_client = (
            client
            if client is not None
            else disable_client_cookies(
                httpx.Client(
                    verify=True,
                    trust_env=False,
                    limits=SAFE_HTTP_DEFAULT_LIMITS,
                    headers={"User-Agent": outbound_user_agent()},
                )
            )
        )
        resolver = default_address_resolver if close_client else None
        try:
            validate_safe_http_url(endpoint, resolver=resolver)
            if vouch:
                # Syntactic check only, on purpose: the sender never fetches
                # the Vouch URL, so a DNS lookup would only add latency and a
                # failure mode. Resolve it here if this path ever fetches it.
                validate_safe_http_url(vouch, resolver=None)
            payload = {"source": source, "target": target}
            if vouch:
                payload["vouch"] = vouch
            delivered = request_with_webmention_redirects(
                http_client,
                "POST",
                endpoint,
                data=payload,
                resolver=resolver,
                timeout=self.post_timeout,
                max_bytes=_sender_response_max_bytes(),
                total_timeout=_webmention_send_total_timeout(),
                cross_origin_strip=_webmention_strict_redirects(),
            )
            response = delivered.response

            # Accept 200, 201, or 202 as success
            if response.status_code in [200, 201, 202]:
                return {"success": True, "status_code": response.status_code}
            else:
                # Non-success status code
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "error": f"HTTP {response.status_code}",
                }

        except HTTPResponseTooLarge as e:
            return {"success": False, "status_code": None, "error": f"response too large ({type(e).__name__})"}
        except httpx.RequestError as e:
            # Handle httpx exceptions (network errors, timeouts, etc.)
            status_code = None
            if hasattr(e, "response") and e.response is not None:
                status_code = e.response.status_code
            return {"success": False, "status_code": status_code, "error": type(e).__name__}
        except Exception as e:
            # Handle other exceptions
            return {"success": False, "status_code": None, "error": type(e).__name__}
        finally:
            if close_client:
                http_client.close()

    def fetch_content(self, url: str, *, client: httpx.Client | None = None) -> str | None:
        """Fetch HTML content from a URL.

        Args:
            url: URL to fetch
            client: Optional injected ``httpx.Client``. See
                :meth:`discover_endpoint` for the safety semantics.

        Returns:
            HTML content or None if error
        """
        close_client = client is None
        http_client = (
            client
            if client is not None
            else disable_client_cookies(
                httpx.Client(
                    verify=True,
                    trust_env=False,
                    limits=SAFE_HTTP_DEFAULT_LIMITS,
                    headers={"User-Agent": outbound_user_agent()},
                )
            )
        )
        resolver = default_address_resolver if close_client else None
        try:
            validate_safe_http_url(url, resolver=resolver)
            fetched = stream_with_safe_redirects(
                http_client,
                "GET",
                url,
                max_bytes=_sender_fetch_max_bytes(),
                resolver=resolver,
                timeout=SAFE_HTTP_DEFAULT_TIMEOUT,
                total_timeout=_webmention_send_total_timeout(),
            )
            response = fetched.response
            response.raise_for_status()
            return response.text
        except Exception:
            return None
        finally:
            if close_client:
                http_client.close()

    def send_webmentions(
        self,
        source_url: str,
        html_content: str | None = None,
        vouch_url: str | None = None,
        record_history: bool = True,
    ) -> list[dict]:
        """Send webmentions to all URLs found in the content.

        Args:
            source_url: The source URL (your post)
            html_content: Optional HTML content. If not provided, will be fetched.
            vouch_url: Optional Vouch URL to include with each sent Webmention
            record_history: Whether to record attempted deliveries in outbound target history

        Returns:
            List of results for each webmention attempt
        """
        # Fetch content if not provided
        if html_content is None:
            html_content = self.fetch_content(source_url)
            if html_content is None:
                return []

        # Extract deliverable target URLs from content
        target_urls = self.select_target_urls(source_url, html_content)

        # Send webmentions to each URL
        results = []

        for target_url in target_urls:
            attempt_started_at = timezone.now()
            # Discover endpoint
            endpoint = self.discover_endpoint(target_url)
            if endpoint:
                # Send webmention
                result = self.send_webmention(source_url, target_url, endpoint, vouch=vouch_url)
                result["target"] = target_url
                result["endpoint"] = endpoint
                results.append(result)
                if record_history:
                    self._record_outbound_target(
                        attempt_started_at=attempt_started_at,
                        source_url=source_url,
                        target_url=target_url,
                        endpoint=endpoint,
                        result=result,
                        vouch_url=vouch_url,
                        seen_in_source=True,
                        sent=True,
                    )

        return results

    def resend_salmentions(
        self,
        source_url: str,
        html_content: str | None = None,
        vouch_url: str | None = None,
    ) -> list[dict]:
        """Resend Webmentions to current and historical targets for a source URL.

        Args:
            source_url: The source URL (your post)
            html_content: Optional HTML content. If not provided, will be fetched.
            vouch_url: Optional Vouch URL to include with each sent Webmention

        Returns:
            List of results for each current or historical target, including provenance
        """
        if html_content is None:
            html_content = self.fetch_content(source_url)
            if html_content is None:
                return []

        target_urls, current_targets, historical_rows, historical_targets = self._salmention_target_context(
            source_url,
            html_content,
        )

        results = []
        for target_url in target_urls:
            provenance = self._target_provenance(target_url, current_targets, historical_targets)
            historical_only = provenance == "history"
            if historical_only:
                row = historical_rows[target_url]
                skipped = self._salmention_historical_skip_result(row, dry_run=False)
                if skipped is not None:
                    results.append(skipped)
                    continue

            attempt_started_at = timezone.now()
            endpoint = self.discover_endpoint(target_url)
            if endpoint:
                result = self.send_webmention(source_url, target_url, endpoint, vouch=vouch_url)
            else:
                result = {
                    "success": False,
                    "status_code": None,
                    "error": "No endpoint found",
                }

            result["target"] = target_url
            result["endpoint"] = endpoint
            result["provenance"] = provenance
            results.append(result)
            target = self._record_outbound_target(
                attempt_started_at=attempt_started_at,
                source_url=source_url,
                target_url=target_url,
                endpoint=endpoint,
                result=result,
                vouch_url=vouch_url,
                seen_in_source=target_url in current_targets,
                sent=endpoint is not None,
            )
            if historical_only and not result["success"] and self._delete_failed_outbound_target(target):
                # Retain policy flags, but distinguish this failed attempt from a pre-attempt drop.
                result["attempted"] = True
                result["dropped"] = True
                result["skipped"] = True
                result["skip_reason"] = "failure_drop"
                result["error"] = f"{result.get('error', 'Delivery failed')}; historical target dropped"

        return results

    def preview_salmention_resend_targets(
        self,
        source_url: str,
        html_content: str,
    ) -> list[dict]:
        """Return a dry-run Salmention resend preview without sending or recording history."""
        target_urls, current_targets, historical_rows, historical_targets = self._salmention_target_context(
            source_url,
            html_content,
        )

        results = []
        for target_url in target_urls:
            provenance = self._target_provenance(target_url, current_targets, historical_targets)
            if provenance == "history":
                skipped = self._salmention_historical_skip_result(historical_rows[target_url], dry_run=True)
                if skipped is not None:
                    results.append(skipped)
                    continue
            endpoint = self.discover_endpoint(target_url)
            results.append(
                {
                    "target": target_url,
                    "endpoint": endpoint,
                    "success": False,
                    "status_code": None,
                    "provenance": provenance,
                    "dry_run": True,
                    "error": "" if endpoint else "No endpoint found",
                }
            )
        return results

    def _salmention_target_context(
        self,
        source_url: str,
        html_content: str,
    ) -> tuple[list[str], set[str], dict[str, WebmentionOutboundTarget], set[str]]:
        """Return capped Salmention targets plus provenance inputs.

        Current source links are considered first, in document order, followed
        by exact-source historical targets that are not still present. The
        outbound fanout caps apply to the combined list before any endpoint
        discovery so resend and dry-run paths cannot bypass the ordinary
        sender's amplification guard.
        """
        current_target_urls = self._extract_external_target_urls(source_url, html_content)
        current_targets = set(current_target_urls)
        historical_rows = {
            row.target_url: row
            for row in WebmentionOutboundTarget.objects.filter(source_url=source_url).order_by("target_url")
        }
        historical_targets = set(historical_rows)

        ordered_targets: list[str] = []
        seen: set[str] = set()
        for target_url in [*current_target_urls, *historical_rows]:
            if target_url in seen:
                continue
            seen.add(target_url)
            ordered_targets.append(target_url)

        return self._limit_target_urls(ordered_targets), current_targets, historical_rows, historical_targets

    def select_target_urls(self, source_url: str, html_content: str) -> list[str]:
        """Return ordered current external targets after URL, same-host and fanout policy.

        Selection performs no network requests or history reads/writes, so ordinary
        sending and command previews can use exactly the same admission policy.
        """
        return self._limit_target_urls(self._extract_external_target_urls(source_url, html_content))

    def _extract_external_target_urls(self, source_url: str, html_content: str) -> list[str]:
        """Extract current absolute external HTTP(S) targets from HTML content."""
        urls = self.extract_urls(html_content)
        # Compare canonical hosts (lowercase, IDNA, default port dropped) so
        # ``https://Example.COM:443/x`` counts as the source's own domain.
        source_domain = _canonical_destination_host(source_url)
        target_urls = []

        for target_url in urls:
            if not is_safe_http_url(target_url, resolver=None):
                continue

            target_domain = _canonical_destination_host(target_url)
            if target_domain == source_domain:
                continue

            target_urls.append(target_url)

        return target_urls

    def _limit_target_urls(self, target_urls: list[str]) -> list[str]:
        """Apply per-source and per-destination fanout caps to outbound targets."""
        max_per_source = _webmention_max_targets_per_source()
        max_per_host = _webmention_max_targets_per_host()
        if max_per_source is None and max_per_host is None:
            return target_urls

        limited: list[str] = []
        host_counts: dict[str, int] = {}
        for target_url in target_urls:
            if max_per_source is not None and len(limited) >= max_per_source:
                break

            host = _canonical_destination_host(target_url)
            if host is None:
                continue
            if max_per_host is not None and host_counts.get(host, 0) >= max_per_host:
                continue

            host_counts[host] = host_counts.get(host, 0) + 1
            limited.append(target_url)
        return limited

    def _record_outbound_target(
        self,
        *,
        source_url: str,
        target_url: str,
        endpoint: str | None,
        result: dict,
        vouch_url: str | None,
        seen_in_source: bool,
        sent: bool,
        attempt_started_at: datetime | None = None,
    ) -> WebmentionOutboundTarget:
        """Create or refresh outbound Webmention target history for an attempt."""
        started = attempt_started_at or timezone.now()
        target, _ = WebmentionOutboundTarget.objects.get_or_create(source_url=source_url, target_url=target_url)
        using = router.db_for_write(WebmentionOutboundTarget, instance=target)
        current = Q(last_attempted_at__isnull=True) | Q(last_attempted_at__lte=started)
        after_success = Q(last_successful_attempt_at__isnull=True) | Q(last_successful_attempt_at__lte=started)
        success = bool(result.get("success"))
        # Every expression sees the current stored row in one atomic SQL update.
        updates: dict[str, Any] = {
            "modified": timezone.now(),
            "last_attempted_at": Case(When(current, then=Value(started)), default=F("last_attempted_at")),
            "last_status_code": Case(
                When(current, then=Value(result.get("status_code"))), default=F("last_status_code")
            ),
            "last_success": Case(When(current, then=Value(success)), default=F("last_success")),
            "last_error": Case(When(current, then=Value(result.get("error") or "")), default=F("last_error")),
            "consecutive_failures": (
                Case(When(current, then=Value(0)), default=F("consecutive_failures"))
                if success
                else Case(When(after_success, then=F("consecutive_failures") + 1), default=F("consecutive_failures"))
            ),
        }
        if success:
            updates["last_successful_attempt_at"] = Case(
                When(current, then=Value(started)), default=F("last_successful_attempt_at")
            )
        if endpoint:
            fresh_endpoint = Q(endpoint_discovered_at__isnull=True) | Q(endpoint_discovered_at__lte=started)
            updates["endpoint_url"] = Case(When(fresh_endpoint, then=Value(endpoint)), default=F("endpoint_url"))
            updates["endpoint_discovered_at"] = Case(
                When(fresh_endpoint, then=Value(started)), default=F("endpoint_discovered_at")
            )
        if sent:
            fresh_sent = Q(last_sent_at__isnull=True) | Q(last_sent_at__lte=started)
            updates["first_sent_at"] = Case(
                When(Q(first_sent_at__isnull=True) | Q(first_sent_at__gt=started), then=Value(started)),
                default=F("first_sent_at"),
            )
            updates["last_sent_at"] = Case(When(fresh_sent, then=Value(started)), default=F("last_sent_at"))
            updates["last_vouch_url"] = Case(
                When(fresh_sent, then=Value(vouch_url or "")), default=F("last_vouch_url")
            )
        if seen_in_source:
            updates["last_seen_in_source_at"] = Case(
                When(
                    Q(last_seen_in_source_at__isnull=True) | Q(last_seen_in_source_at__lte=started),
                    then=Value(started),
                ),
                default=F("last_seen_in_source_at"),
            )
        for field_name, expression in updates.items():
            if isinstance(expression, Case):
                expression.output_field = WebmentionOutboundTarget._meta.get_field(field_name)
        WebmentionOutboundTarget.objects.using(using).filter(pk=target.pk).update(**updates)
        target.refresh_from_db(using=using)
        return target

    def _target_provenance(self, target_url: str, current_targets: set[str], historical_targets: set[str]) -> str:
        """Return the resend provenance label for a target URL."""
        if target_url in current_targets and target_url in historical_targets:
            return "both"
        if target_url in current_targets:
            return "current"
        return "history"

    def _salmention_historical_skip_result(
        self,
        row: WebmentionOutboundTarget,
        *,
        dry_run: bool,
    ) -> dict | None:
        """Return a policy skip result for a historical-only target, if one applies."""
        now = timezone.now()
        if self._salmention_failure_limit_reached(row):
            if not dry_run and not self._delete_failed_outbound_target(row):
                # A concurrent attempt changed or removed this history. Reconsider
                # from a fresh snapshot on the next invocation, without sending now.
                return self._salmention_skip_result(
                    row.target_url,
                    "history_changed",
                    "Historical target changed during failure pruning",
                    dry_run=False,
                )
            return self._salmention_skip_result(
                row.target_url,
                "failure_drop",
                "Historical target dropped after consecutive failures",
                dry_run=dry_run,
                dropped=True,
            )

        last_attempted_at = row.last_attempted_at or row.last_sent_at
        if last_attempted_at and now - last_attempted_at < _salmention_resend_cooldown():
            return self._salmention_skip_result(
                row.target_url,
                "cooldown",
                "Historical target skipped during resend cooldown",
                dry_run=dry_run,
            )

        success_cutoff = _salmention_success_cutoff()
        success_reference = row.last_seen_in_source_at or row.first_sent_at or row.last_attempted_at or row.created
        if row.last_success and success_cutoff is not None and now - success_reference >= success_cutoff:
            return self._salmention_skip_result(
                row.target_url,
                "success_cutoff",
                "Historical target skipped after successful resend cutoff",
                dry_run=dry_run,
            )

        return None

    def _salmention_skip_result(
        self,
        target_url: str,
        reason: str,
        error: str,
        *,
        dry_run: bool,
        dropped: bool = False,
    ) -> dict:
        """Build a Salmention policy skip result."""
        result = {
            "success": False,
            "status_code": None,
            "error": error,
            "target": target_url,
            "endpoint": None,
            "provenance": "history",
            "skipped": True,
            "skip_reason": reason,
        }
        if dry_run:
            result["dry_run"] = True
        if dropped:
            result["dropped"] = True
        return result

    def _delete_failed_outbound_target(self, row: WebmentionOutboundTarget) -> bool:
        """Delete only the failed generation inspected by the caller."""
        using = router.db_for_write(WebmentionOutboundTarget, instance=row)
        deleted, _ = (
            WebmentionOutboundTarget.objects.using(using)
            .filter(
                pk=row.pk,
                last_attempted_at=row.last_attempted_at,
                last_success=False,
                consecutive_failures__gte=_salmention_max_consecutive_failures(),
            )
            .delete()
        )
        return bool(deleted)

    def _salmention_failure_limit_reached(self, row: WebmentionOutboundTarget) -> bool:
        """Return whether a target has reached the historical failure drop threshold."""
        return row.consecutive_failures >= _salmention_max_consecutive_failures()
