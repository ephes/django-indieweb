"""Webmention sender implementation."""

import re
from datetime import timedelta
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag
from django.conf import settings
from django.utils import timezone

from .http_client import (
    SAFE_HTTP_DEFAULT_LIMITS,
    SAFE_HTTP_DEFAULT_TIMEOUT,
    HTTPResponseTooLarge,
    default_address_resolver,
    disable_client_cookies,
    is_safe_http_url,
    outbound_user_agent,
    request_with_webmention_redirects,
    stream_with_safe_redirects,
    validate_safe_http_url,
)
from .models import WebmentionOutboundTarget

DEFAULT_WEBMENTION_SENDER_FETCH_MAX_BYTES = 1024 * 1024
DEFAULT_WEBMENTION_SENDER_RESPONSE_MAX_BYTES = 1024 * 1024
DEFAULT_SALMENTION_RESEND_COOLDOWN_SECONDS = 24 * 60 * 60
DEFAULT_SALMENTION_SUCCESS_CUTOFF_SECONDS = 30 * 24 * 60 * 60
DEFAULT_SALMENTION_MAX_CONSECUTIVE_FAILURES = 5


def _sender_fetch_max_bytes() -> int | None:
    configured = getattr(settings, "INDIEWEB_WEBMENTION_FETCH_MAX_BYTES", DEFAULT_WEBMENTION_SENDER_FETCH_MAX_BYTES)
    if configured is None:
        return None
    try:
        parsed = int(configured)
    except (TypeError, ValueError):
        return DEFAULT_WEBMENTION_SENDER_FETCH_MAX_BYTES
    return parsed if parsed > 0 else DEFAULT_WEBMENTION_SENDER_FETCH_MAX_BYTES


def _sender_response_max_bytes() -> int | None:
    """Return the decoded byte cap applied to Webmention endpoint POST responses.

    ``None`` is the explicit "disable cap" sentinel. Any malformed value falls
    back to the default cap so an invalid setting does not silently let a
    hostile endpoint return an unbounded body.
    """
    configured = getattr(
        settings, "INDIEWEB_WEBMENTION_RESPONSE_MAX_BYTES", DEFAULT_WEBMENTION_SENDER_RESPONSE_MAX_BYTES
    )
    if configured is None:
        return None
    try:
        parsed = int(configured)
    except (TypeError, ValueError):
        return DEFAULT_WEBMENTION_SENDER_RESPONSE_MAX_BYTES
    return parsed if parsed > 0 else DEFAULT_WEBMENTION_SENDER_RESPONSE_MAX_BYTES


def _positive_int_setting(name: str, default: int) -> int:
    configured = getattr(settings, name, default)
    try:
        parsed = int(configured)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _optional_positive_int_setting(name: str, default: int) -> int | None:
    configured = getattr(settings, name, default)
    if configured is None:
        return None
    return _positive_int_setting(name, default)


def _salmention_resend_cooldown() -> timedelta:
    return timedelta(
        seconds=_positive_int_setting(
            "INDIEWEB_SALMENTION_RESEND_COOLDOWN_SECONDS",
            DEFAULT_SALMENTION_RESEND_COOLDOWN_SECONDS,
        )
    )


def _salmention_success_cutoff() -> timedelta | None:
    seconds = _optional_positive_int_setting(
        "INDIEWEB_SALMENTION_SUCCESS_CUTOFF_SECONDS",
        DEFAULT_SALMENTION_SUCCESS_CUTOFF_SECONDS,
    )
    if seconds is None:
        return None
    return timedelta(seconds=seconds)


def _salmention_max_consecutive_failures() -> int:
    return _positive_int_setting(
        "INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES",
        DEFAULT_SALMENTION_MAX_CONSECUTIVE_FAILURES,
    )


class WebmentionSender:
    """Sends webmentions to target URLs."""

    def __init__(self) -> None:
        self.timeout = 10
        self.post_timeout = 30

    def extract_urls(self, html_content: str) -> list[str]:
        """Extract all URLs from HTML content.

        Args:
            html_content: HTML content to parse

        Returns:
            List of unique URLs found in the content
        """
        soup = BeautifulSoup(html_content, "html.parser")
        urls: set[str] = set()

        # Find all anchor tags with href attributes
        for tag in soup.find_all("a", href=True):
            if isinstance(tag, Tag):
                href = tag.get("href")
                if href and isinstance(href, str):
                    urls.add(href)

        return list(urls)

    def discover_endpoint(self, target_url: str, *, client: httpx.Client | None = None) -> str | None:
        """Discover the webmention endpoint for a target URL.

        First checks HTTP Link headers, then falls back to parsing HTML.

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
        try:
            validate_safe_http_url(target_url, resolver=resolver)
            # First try HEAD request to check Link headers
            discovered = request_with_webmention_redirects(
                http_client, "HEAD", target_url, resolver=resolver, timeout=self.timeout
            )
            response = discovered.response
            response.raise_for_status()

            # Check Link header
            link_header = response.headers.get("Link", "")
            endpoint = self._parse_link_header(link_header)
            if endpoint:
                resolved_endpoint = urljoin(discovered.final_url, endpoint)
                validate_safe_http_url(resolved_endpoint, resolver=resolver)
                return resolved_endpoint

            # Fall back to GET request to parse HTML
            discovered = stream_with_safe_redirects(
                http_client,
                "GET",
                target_url,
                max_bytes=_sender_fetch_max_bytes(),
                resolver=resolver,
                timeout=SAFE_HTTP_DEFAULT_TIMEOUT,
            )
            response = discovered.response
            response.raise_for_status()

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

    def _parse_link_header(self, link_header: str) -> str | None:
        """Parse Link header for webmention endpoint.

        Args:
            link_header: The Link header value

        Returns:
            The webmention endpoint URL or None
        """
        if not link_header:
            return None

        # Per RFC 8288, a Link header is a comma-separated list of entries,
        # each shaped ``<url>; param1=...; param2=...``. The ``rel``
        # parameter can appear at any position within an entry. The
        # previous regex pinned ``rel`` immediately after ``<url>;``,
        # which silently dropped valid headers like
        # ``<url>; type="text/html"; rel="webmention"``. The previous
        # ``\bwebmention\b`` match also accepted substrings such as
        # ``not-webmention`` and ``webmention-foo`` because ``-`` is a
        # non-word character.
        #
        # Find each ``<url>`` and its trailing parameter section (up to
        # the next entry or end of header), then look for any
        # ``rel="..."`` parameter and require an exact ``webmention``
        # token in its whitespace-separated value (case-insensitive).
        entry_pattern = re.compile(r"<([^>]+)>([^,]*)")
        rel_pattern = re.compile(r'rel\s*=\s*"([^"]*)"', re.IGNORECASE)
        for url_match, params in entry_pattern.findall(link_header):
            url_str = str(url_match).strip()
            rel_match = rel_pattern.search(str(params))
            if rel_match is None:
                continue
            if "webmention" in rel_match.group(1).lower().split():
                return url_str

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

        rel_filter = self._rel_attribute_includes_webmention

        # Check <link> tags
        link = soup.find("link", rel=rel_filter)
        if link and isinstance(link, Tag):
            href = link.get("href")
            if href and isinstance(href, str):
                return urljoin(base_url, href)

        # Check <a> tags
        a = soup.find("a", rel=rel_filter)
        if a and isinstance(a, Tag):
            href = a.get("href")
            if href and isinstance(href, str):
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
            return {"success": False, "status_code": None, "error": f"response too large: {e}"}
        except httpx.RequestError as e:
            # Handle httpx exceptions (network errors, timeouts, etc.)
            status_code = None
            if hasattr(e, "response") and e.response is not None:
                status_code = e.response.status_code
            return {"success": False, "status_code": status_code, "error": str(e)}
        except Exception as e:
            # Handle other exceptions
            return {"success": False, "status_code": None, "error": str(e)}
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
        target_urls = self._extract_external_target_urls(source_url, html_content)

        # Send webmentions to each URL
        results = []

        for target_url in target_urls:
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

        current_targets = set(self._extract_external_target_urls(source_url, html_content))
        historical_rows = {
            row.target_url: row for row in WebmentionOutboundTarget.objects.filter(source_url=source_url)
        }
        historical_targets = set(historical_rows)

        results = []
        for target_url in sorted(current_targets | historical_targets):
            provenance = self._target_provenance(target_url, current_targets, historical_targets)
            historical_only = provenance == "history"
            if historical_only:
                row = historical_rows[target_url]
                skipped = self._salmention_historical_skip_result(row, dry_run=False)
                if skipped is not None:
                    results.append(skipped)
                    continue

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
                source_url=source_url,
                target_url=target_url,
                endpoint=endpoint,
                result=result,
                vouch_url=vouch_url,
                seen_in_source=target_url in current_targets,
                sent=endpoint is not None,
            )
            if historical_only and not result["success"] and self._salmention_failure_limit_reached(target):
                target.delete()
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
        current_targets = set(self._extract_external_target_urls(source_url, html_content))
        historical_rows = {
            row.target_url: row for row in WebmentionOutboundTarget.objects.filter(source_url=source_url)
        }
        historical_targets = set(historical_rows)

        results = []
        for target_url in sorted(current_targets | historical_targets):
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

    def _extract_external_target_urls(self, source_url: str, html_content: str) -> list[str]:
        """Extract current absolute external HTTP(S) targets from HTML content."""
        urls = self.extract_urls(html_content)
        source_domain = urlparse(source_url).netloc
        target_urls = []

        for target_url in urls:
            if not is_safe_http_url(target_url, resolver=None):
                continue

            target_domain = urlparse(target_url).netloc
            if target_domain == source_domain:
                continue

            target_urls.append(target_url)

        return target_urls

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
    ) -> WebmentionOutboundTarget:
        """Create or refresh outbound Webmention target history for an attempt."""
        now = timezone.now()
        target, _ = WebmentionOutboundTarget.objects.get_or_create(
            source_url=source_url,
            target_url=target_url,
        )

        if endpoint:
            target.endpoint_url = endpoint
            target.endpoint_discovered_at = now
        if sent:
            if target.first_sent_at is None:
                target.first_sent_at = now
            target.last_sent_at = now
            target.last_vouch_url = vouch_url or ""
        target.last_attempted_at = now
        target.last_status_code = result.get("status_code")
        success = bool(result.get("success"))
        target.last_success = success
        target.last_error = result.get("error") or ""
        if success:
            target.consecutive_failures = 0
        else:
            target.consecutive_failures += 1
        if seen_in_source:
            target.last_seen_in_source_at = now
        target.save()
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
            if not dry_run:
                row.delete()
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

    def _salmention_failure_limit_reached(self, row: WebmentionOutboundTarget) -> bool:
        """Return whether a target has reached the historical failure drop threshold."""
        return row.consecutive_failures >= _salmention_max_consecutive_failures()
