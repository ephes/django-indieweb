"""
Webmention processing logic.

Handles fetching, parsing, and verifying webmentions.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import ParseResult, parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx
import mf2py
from bs4 import BeautifulSoup, Tag
from django.conf import settings
from django.contrib.sites.models import Site
from django.dispatch import Signal
from django.utils import timezone
from django.utils.module_loading import import_string

from .http_client import (
    SAFE_HTTP_DEFAULT_TIMEOUT,
    HTTPResponseTooLarge,
    RedirectedResponse,
    response_text_with_limit,
    stream_with_safe_redirects,
)
from .models import Profile, Webmention, WebmentionNestedResponse, WebmentionSourceSnapshot
from .sanitizers import sanitize_remote_webmention_url, sanitize_webmention_html

if TYPE_CHECKING:
    from .interfaces import SpamChecker

logger = logging.getLogger(__name__)

# Signal sent when a webmention is received and processed
webmention_received = Signal()
MAX_NESTED_RESPONSE_IDENTITY_LENGTH = 500
DEFAULT_WEBMENTION_FETCH_MAX_BYTES = 1024 * 1024
DEFAULT_WEBMENTION_NESTED_RESPONSE_MAX_DEPTH = 8
DEFAULT_WEBMENTION_NESTED_RESPONSE_MAX_CANDIDATES = 100
DEFAULT_WEBMENTION_SEARCH_MAX_ITEMS = 1000
TRAILING_TEXT_URL_PUNCTUATION = ".,;:!?\"'"
LEADING_TEXT_URL_PUNCTUATION = "([{<\"'"
WRAPPING_TEXT_URL_PUNCTUATION = {
    ")": "(",
    "]": "[",
    "}": "{",
    ">": "<",
}


def _positive_int_setting(name: str, default: int) -> int:
    configured = getattr(settings, name, default)
    try:
        parsed = int(configured)
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid %s value; using default %s", name, default)
        return default
    if parsed <= 0:
        logger.warning("Ignoring non-positive %s value; using default %s", name, default)
        return default
    return parsed


def _optional_positive_int_setting(name: str, default: int) -> int | None:
    configured = getattr(settings, name, default)
    if configured is None:
        return None
    return _positive_int_setting(name, default)


def _webmention_fetch_max_bytes() -> int | None:
    return _optional_positive_int_setting("INDIEWEB_WEBMENTION_FETCH_MAX_BYTES", DEFAULT_WEBMENTION_FETCH_MAX_BYTES)


def _webmention_nested_max_depth() -> int:
    return _positive_int_setting(
        "INDIEWEB_WEBMENTION_NESTED_RESPONSE_MAX_DEPTH",
        DEFAULT_WEBMENTION_NESTED_RESPONSE_MAX_DEPTH,
    )


def _webmention_nested_max_candidates() -> int:
    return _positive_int_setting(
        "INDIEWEB_WEBMENTION_NESTED_RESPONSE_MAX_CANDIDATES",
        DEFAULT_WEBMENTION_NESTED_RESPONSE_MAX_CANDIDATES,
    )


def _webmention_search_max_items() -> int:
    return _positive_int_setting("INDIEWEB_WEBMENTION_SEARCH_MAX_ITEMS", DEFAULT_WEBMENTION_SEARCH_MAX_ITEMS)


def _reject_vouch_policy(**kwargs: Any) -> bool:
    """Reject all vouchers when a configured trust policy cannot be used."""
    return False


def _canonical_netloc_for_match(parsed: ParseResult) -> str | None:
    """Return a canonical netloc for URL target matching, or ``None`` if malformed."""
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None

    if not host:
        return None

    normalized_host = host.lower()
    if normalized_host.startswith("www."):
        normalized_host = normalized_host[4:]
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"

    userinfo = ""
    if "@" in parsed.netloc:
        userinfo = parsed.netloc.rsplit("@", 1)[0] + "@"

    netloc = f"{userinfo}{normalized_host}"
    if port is not None:
        netloc = f"{netloc}:{port}"
    return netloc


def _canonicalize_url_for_match(value: str) -> str:
    """Return a conservative canonical URL string for Webmention target matching."""
    try:
        parsed = urlparse(value)
    except ValueError:
        return value

    if not parsed.scheme or not parsed.netloc:
        return value

    scheme = parsed.scheme.lower()
    netloc = _canonical_netloc_for_match(parsed)
    if netloc is None:
        return value

    path = parsed.path
    if path not in ("", "/") and path.endswith("/"):
        path = path[:-1]

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query = urlencode(sorted(query_pairs))

    return urlunparse((scheme, netloc, path, parsed.params, query, ""))


def _is_absolute_url_for_match(value: str) -> bool:
    """Return whether ``value`` is eligible for URL canonicalization matching."""
    try:
        parsed = urlparse(value)
        return bool(parsed.scheme and parsed.netloc)
    except ValueError:
        return False


def _urls_match(left: str, right: str) -> bool:
    """Compare two URLs using the conservative Webmention target matching policy."""
    if left == right:
        return True
    if not _is_absolute_url_for_match(left) or not _is_absolute_url_for_match(right):
        return False
    return _canonicalize_url_for_match(left) == _canonicalize_url_for_match(right)


def _html_links_to_target(html_content: str, target_url: str) -> bool:
    """Return whether ``html_content`` contains an href value matching ``target_url``."""
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup.find_all(href=True):
        if isinstance(tag, Tag):
            href = tag.get("href")
            if isinstance(href, str) and _urls_match(href, target_url):
                return True
    return False


def _canonical_domain_for_vouch(value: str) -> str | None:
    """Return a conservative domain string for Vouch matching."""
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if parsed.scheme.lower() not in ("http", "https"):
        return None
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if not host:
        return None
    normalized = host.lower()
    if normalized.startswith("www."):
        normalized = normalized[4:]
    if ":" in normalized and not normalized.startswith("["):
        normalized = f"[{normalized}]"
    if port is not None:
        normalized = f"{normalized}:{port}"
    return normalized


def _href_links_to_domain(href: str, source_domain: str) -> bool:
    """Return whether an href points at the source domain for Vouch verification."""
    return _canonical_domain_for_vouch(href) == source_domain


def _html_links_to_source_domain(html_content: str, source_url: str) -> bool:
    """Return whether ``html_content`` contains an HTTP(S) hyperlink to the source URL's domain."""
    source_domain = _canonical_domain_for_vouch(source_url)
    if source_domain is None:
        return False

    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup.find_all(href=True):
        if isinstance(tag, Tag):
            href = tag.get("href")
            if isinstance(href, str) and _href_links_to_domain(href, source_domain):
                return True
    return False


def _strip_plain_text_url_punctuation(value: str) -> str:
    """Strip surrounding prose punctuation without removing balanced URL parentheses."""
    candidate = value.lstrip(LEADING_TEXT_URL_PUNCTUATION).rstrip(TRAILING_TEXT_URL_PUNCTUATION)
    while candidate:
        closing = candidate[-1]
        opening = WRAPPING_TEXT_URL_PUNCTUATION.get(closing)
        if opening is None or candidate.count(opening) >= candidate.count(closing):
            break
        candidate = candidate[:-1]
    return candidate


class WebmentionProcessor:
    """Process webmentions by fetching and parsing source URLs."""

    def __init__(self) -> None:
        """Initialize the processor with configured spam checker."""
        self.spam_checker = self._get_spam_checker()
        # Force reload of spam checker for tests with override_settings
        self._spam_checker_loaded = False

    def _get_spam_checker(self) -> SpamChecker | None:
        """Load spam checker from settings."""
        spam_checker_path = getattr(settings, "INDIEWEB_SPAM_CHECKER", None)
        if spam_checker_path:
            try:
                spam_checker_class = import_string(spam_checker_path)
                return spam_checker_class()  # type: ignore[no-any-return]
            except Exception as e:
                logger.error(f"Failed to load spam checker {spam_checker_path}: {e}")
        return None

    def process_webmention(self, source_url: str, target_url: str, vouch_url: str | None = None) -> Webmention:  # noqa: C901
        """
        Process a webmention by fetching and parsing the source.

        Args:
            source_url: The URL that mentions the target
            target_url: The URL being mentioned
            vouch_url: Optional Vouch URL submitted with the Webmention

        Returns:
            Webmention object with processing results
        """
        logger.info(f"Processing webmention from {source_url} to {target_url}")

        # Get or create webmention
        webmention, _created = Webmention.objects.get_or_create(
            source_url=source_url,
            target_url=target_url,
        )
        if vouch_url is not None and webmention.vouch_url != vouch_url:
            webmention.vouch_url = vouch_url
            webmention.vouch_verified_at = None
            webmention.save(update_fields=["vouch_url", "vouch_verified_at", "modified"])

        try:
            # Fetch source URL
            fetched = self._fetch_source(source_url)
            response = fetched.response

            # Check response status
            if response.status_code == 410:
                # Source has been deleted
                self._mark_webmention_failed(webmention)
                logger.info(f"Source URL returned 410 Gone: {source_url}")
                return webmention

            if response.status_code != 200:
                self._mark_webmention_failed(webmention)
                logger.warning(f"Failed to fetch source URL {source_url}: {response.status_code}")
                return webmention

            # Check content type
            content_type = response.headers.get("content-type", "").lower()
            if not content_type.startswith("text/html"):
                self._mark_webmention_failed(webmention)
                logger.warning(f"Source URL is not HTML: {content_type}")
                return webmention

            source_html = response_text_with_limit(response, max_bytes=_webmention_fetch_max_bytes())

            # Verify target link exists
            if not self._verify_target_link(source_html, target_url):
                self._mark_webmention_failed(webmention)
                logger.warning(f"Target URL {target_url} not found in source")
                return webmention

            fetched_at = timezone.now()

            # Parse microformats2
            _parsed, h_entry = self._parse_microformats(webmention, source_html, fetched.final_url, target_url)

            if not self._verify_vouch_for_webmention(webmention, source_url):
                self._mark_webmention_failed(webmention)
                logger.warning(f"Vouch verification failed for webmention from {source_url}")
                return webmention

            # Check for spam (reload checker for test compatibility)
            spam_checker = self._get_spam_checker()
            if spam_checker:
                spam_result = spam_checker.check(webmention)
                webmention.spam_check_result = spam_result
                if spam_result.get("is_spam", False):
                    webmention.status = "spam"
                    webmention.verified_at = None
                    webmention.save(update_fields=["spam_check_result", "status", "verified_at", "modified"])
                    webmention.refresh_from_db()
                    logger.info(f"Webmention marked as spam: {source_url}")
                    return webmention

            previous_nested_identities = self._previous_nested_response_identities(webmention)
            nested_response_candidates = self._nested_response_candidates(h_entry or {}, fetched.final_url)

            # Mark as verified
            webmention.status = "verified"
            webmention.verified_at = timezone.now()
            webmention.save()
            self._sync_nested_responses_safely(
                webmention=webmention,
                candidates=nested_response_candidates,
                previous_identities=previous_nested_identities,
                seen_at=fetched_at,
            )
            self._store_source_snapshot_safely(
                webmention=webmention,
                raw_source_html=source_html,
                final_source_url=fetched.final_url,
                fetched_at=fetched_at,
                h_entry=h_entry,
            )

            # Send signal
            webmention_received.send(
                sender=self.__class__,
                webmention=webmention,
                source_url=source_url,
                target_url=target_url,
            )

            logger.info(f"Successfully processed webmention from {source_url}")
            return webmention

        except HTTPResponseTooLarge as e:
            logger.warning(f"Fetched Webmention source exceeded size limit for {source_url}: {e}")
            self._mark_webmention_failed(webmention)
            return webmention
        except Exception as e:
            logger.error(f"Error processing webmention from {source_url}: {e}")
            self._mark_webmention_failed(webmention)
            return webmention

    def _mark_webmention_failed(self, webmention: Webmention) -> None:
        """Mark a Webmention as failed without discarding previously parsed fields."""
        webmention.status = "failed"
        webmention.verified_at = None
        webmention.save(update_fields=["status", "verified_at", "modified"])
        webmention.refresh_from_db()

    def _fetch_source(self, source_url: str) -> RedirectedResponse:
        """Fetch the source URL with explicit bounded redirect handling."""
        headers = {"User-Agent": "django-indieweb/1.0"}
        with httpx.Client(verify=True) as client:
            return stream_with_safe_redirects(
                client,
                "GET",
                source_url,
                headers=headers,
                max_bytes=_webmention_fetch_max_bytes(),
                timeout=SAFE_HTTP_DEFAULT_TIMEOUT,
            )

    def _fetch_vouch(self, vouch_url: str) -> RedirectedResponse:
        """Fetch a Vouch URL with the same bounded redirect policy as source fetches."""
        headers = {"User-Agent": "django-indieweb/1.0"}
        with httpx.Client(verify=True) as client:
            return stream_with_safe_redirects(
                client,
                "GET",
                vouch_url,
                headers=headers,
                max_bytes=_webmention_fetch_max_bytes(),
                timeout=SAFE_HTTP_DEFAULT_TIMEOUT,
            )

    def _verify_target_link(self, html_content: str, target_url: str) -> bool:
        """Verify that the target URL is linked in the source content."""
        return _html_links_to_target(html_content, target_url)

    def _verify_vouch_for_webmention(self, webmention: Webmention, source_url: str) -> bool:
        """Verify optional Vouch metadata when receiver policy enables it."""
        if not webmention.vouch_url:
            if getattr(settings, "INDIEWEB_WEBMENTION_VOUCH_REQUIRED", False):
                return False
            return True

        if not self._vouch_verification_enabled():
            return True

        if not self._vouch_url_trusted(webmention, source_url, webmention.vouch_url):
            return False

        fetched = self._fetch_vouch(webmention.vouch_url)
        response = fetched.response
        if not self._vouch_url_trusted(webmention, source_url, webmention.vouch_url, fetched.final_url):
            return False
        if response.status_code != 200:
            return False
        content_type = response.headers.get("content-type", "").lower()
        if not content_type.startswith("text/html"):
            return False
        try:
            vouch_html = response_text_with_limit(response, max_bytes=_webmention_fetch_max_bytes())
        except HTTPResponseTooLarge:
            return False
        if not _html_links_to_source_domain(vouch_html, source_url):
            return False

        webmention.vouch_verified_at = timezone.now()
        webmention.save(update_fields=["vouch_verified_at", "modified"])
        return True

    def _vouch_verification_enabled(self) -> bool:
        """Return whether this deployment verifies submitted Vouch URLs."""
        return (
            getattr(settings, "INDIEWEB_WEBMENTION_VOUCH_REQUIRED", False)
            or getattr(settings, "INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY", None) is not None
            or bool(self._configured_vouch_trusted_domains())
        )

    def _get_vouch_trust_policy(self) -> Callable[..., bool] | None:
        """Load the optional configured Vouch trust-policy callable."""
        policy_path = getattr(settings, "INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY", None)
        if not policy_path:
            return None
        try:
            policy = import_string(policy_path)
        except Exception as exc:
            logger.error(f"Failed to load INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY {policy_path}: {exc}")
            return cast("Callable[..., bool]", _reject_vouch_policy)
        if not callable(policy):
            logger.error(f"INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY {policy_path!r} is not callable")
            return _reject_vouch_policy
        return cast("Callable[..., bool]", policy)

    def _vouch_url_trusted(
        self,
        webmention: Webmention,
        source_url: str,
        vouch_url: str,
        final_vouch_url: str | None = None,
    ) -> bool:
        """Return whether the configured Vouch receiver policy trusts a voucher URL."""
        policy = self._get_vouch_trust_policy()
        if policy is not None:
            try:
                return bool(
                    policy(
                        webmention=webmention,
                        source_url=source_url,
                        target_url=webmention.target_url,
                        vouch_url=vouch_url,
                        final_vouch_url=final_vouch_url,
                    )
                )
            except Exception as exc:
                logger.error(f"INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY raised for vouch_url={vouch_url!r}: {exc}")
                return False

        if not self._configured_vouch_trusted_domains():
            if getattr(settings, "INDIEWEB_WEBMENTION_VOUCH_REQUIRED", False):
                logger.warning(
                    "INDIEWEB_WEBMENTION_VOUCH_REQUIRED is enabled but no Vouch trust policy or trusted domains "
                    "are configured"
                )
            return False

        return self._vouch_domain_trusted(final_vouch_url or vouch_url)

    def _configured_vouch_trusted_domains(self) -> set[str]:
        """Return configured external domains that can be used by the default Vouch trust policy."""
        trusted_domains: set[str] = set()
        configured_value = getattr(settings, "INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS", None) or ()
        configured_domains = (configured_value,) if isinstance(configured_value, str) else configured_value
        for configured_domain in configured_domains:
            if isinstance(configured_domain, str):
                configured_url = configured_domain if "://" in configured_domain else f"https://{configured_domain}"
                normalized = _canonical_domain_for_vouch(configured_url)
                if normalized:
                    trusted_domains.add(normalized)
        return trusted_domains

    def _vouch_domain_trusted(self, url: str) -> bool:
        """Return whether a Vouch URL is on this site or an explicitly trusted domain."""
        domain = _canonical_domain_for_vouch(url)
        if domain is None:
            return False

        trusted_domains = self._configured_vouch_trusted_domains()
        if not trusted_domains:
            return False

        try:
            current_domain = _canonical_domain_for_vouch(f"https://{Site.objects.get_current().domain}")
            if current_domain:
                trusted_domains.add(current_domain)
        except Site.DoesNotExist:
            pass

        return domain in trusted_domains

    def _parse_microformats(
        self,
        webmention: Webmention,
        html_content: str,
        base_url: str,
        target_url: str,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Parse microformats2 data from HTML content."""
        # Parse microformats
        parsed = mf2py.parse(doc=html_content, url=base_url)

        # Find h-entry that mentions the target
        h_entry = self._find_mentioning_entry(parsed, target_url)
        if not h_entry:
            # No microformats found, use defaults
            return parsed, None

        # Extract author information
        author = self._extract_author(h_entry, parsed, base_url)

        # Check if this is a local author
        author_url = author.get("url", "")
        local_profile = self._get_local_profile(author_url)

        if local_profile:
            # Use local profile data
            webmention.author_name = local_profile.name
            webmention.author_url = sanitize_remote_webmention_url(local_profile.url)
            webmention.author_photo = sanitize_remote_webmention_url(local_profile.photo_url)
        else:
            # Use parsed data
            webmention.author_name = author.get("name", "")
            webmention.author_url = sanitize_remote_webmention_url(author.get("url", ""))
            webmention.author_photo = sanitize_remote_webmention_url(author.get("photo", ""))

        # Extract content
        content_data = self._extract_content(h_entry)
        webmention.content = content_data.get("text", "")
        webmention.content_html = sanitize_webmention_html(content_data.get("html", ""))

        # Extract published date
        published = self._extract_published(h_entry)
        if published:
            webmention.published = published

        # Determine mention type
        webmention.mention_type = self._determine_mention_type(h_entry, target_url)
        return parsed, h_entry

    def _store_source_snapshot(
        self,
        *,
        webmention: Webmention,
        raw_source_html: str,
        final_source_url: str,
        fetched_at: datetime,
        h_entry: dict[str, Any] | None,
    ) -> None:
        """Persist the latest verified source snapshot for future Salmention comparison."""
        normalized_h_entry = self._normalize_snapshot_json(h_entry or {})
        nested_response_identities = self._nested_response_identities(h_entry or {}, final_source_url)
        WebmentionSourceSnapshot.objects.update_or_create(
            webmention=webmention,
            defaults={
                "raw_source_html": raw_source_html,
                "final_source_url": final_source_url,
                "content_digest": hashlib.sha256(raw_source_html.encode("utf-8")).hexdigest(),
                "fetched_at": fetched_at,
                "parsed_h_entry": normalized_h_entry,
                "nested_response_identities": nested_response_identities,
            },
        )

    def _store_source_snapshot_safely(
        self,
        *,
        webmention: Webmention,
        raw_source_html: str,
        final_source_url: str,
        fetched_at: datetime,
        h_entry: dict[str, Any] | None,
    ) -> None:
        """Store a source snapshot without changing parent verification on failure."""
        try:
            self._store_source_snapshot(
                webmention=webmention,
                raw_source_html=raw_source_html,
                final_source_url=final_source_url,
                fetched_at=fetched_at,
                h_entry=h_entry,
            )
        except Exception:
            logger.exception(f"Failed to store source snapshot for webmention {webmention.pk}")

    def _normalize_snapshot_json(self, value: dict[str, Any]) -> dict[str, Any]:
        """Return a JSON-safe parsed snapshot without mutating the parser result."""
        return cast("dict[str, Any]", json.loads(json.dumps(value, sort_keys=True, default=str)))

    def _previous_nested_response_identities(self, webmention: Webmention) -> set[str]:
        """Return nested identities from the previous successful source snapshot."""
        try:
            values = WebmentionSourceSnapshot.objects.get(webmention=webmention).nested_response_identities
        except WebmentionSourceSnapshot.DoesNotExist:
            return set()
        if not isinstance(values, list):
            return set()
        return {value for value in values if isinstance(value, str)}

    def _nested_response_candidates(self, h_entry: dict[str, Any], base_url: str) -> list[dict[str, Any]]:
        """Extract stable nested response rows from a parsed parent h-entry."""
        candidates: list[dict[str, Any]] = []
        seen_identities: set[str] = set()
        for nested_entry in self._nested_h_entries(h_entry):
            identity = self._nested_response_identity(nested_entry, base_url)
            if not identity or identity in seen_identities:
                continue
            seen_identities.add(identity)
            normalized_entry = self._normalize_snapshot_json(nested_entry)
            author = self._extract_nested_response_author(nested_entry, base_url)
            content = self._extract_content(nested_entry)
            response_url = self._nested_response_url(nested_entry, base_url)
            candidates.append(
                {
                    "identity": identity,
                    "response_url": response_url,
                    "author_name": author.get("name", ""),
                    "author_url": sanitize_remote_webmention_url(author.get("url", "")),
                    "author_photo": sanitize_remote_webmention_url(author.get("photo", "")),
                    "content": content.get("text", ""),
                    "content_html": sanitize_webmention_html(content.get("html", "")),
                    "published": self._extract_published(nested_entry),
                    "mention_type": self._determine_mention_type(nested_entry, base_url),
                    "parsed_h_entry": normalized_entry,
                    "content_digest": self._nested_response_digest(normalized_entry),
                }
            )
        return candidates

    def _extract_nested_response_author(self, h_entry: dict[str, Any], base_url: str) -> dict[str, str]:
        """Extract explicit child author data without falling back to the parent page author."""
        properties = h_entry.get("properties", {})
        if not isinstance(properties, dict):
            return {}
        author_data = properties.get("author", [])
        if not author_data:
            return {}
        author = author_data[0] if isinstance(author_data, list) else author_data
        return self._extract_nested_explicit_author(author, base_url)

    def _extract_nested_explicit_author(self, author: str | dict[str, Any], base_url: str) -> dict[str, str]:
        """Extract explicit child author data without document-level h-card fallbacks."""
        if isinstance(author, str):
            if self._is_author_url_reference(author):
                resolved_author_url = urljoin(base_url, author)
                return {"url": resolved_author_url, "name": resolved_author_url, "photo": ""}
            return {"name": author}

        if isinstance(author, dict):
            author_props = author.get("properties", {}) if "properties" in author else author
            if isinstance(author_props, dict):
                return self._extract_author_properties(author_props, base_url)

        return {}

    def _nested_response_url(self, h_entry: dict[str, Any], base_url: str) -> str:
        """Return the best URL for a nested response when one is available."""
        properties = h_entry.get("properties", {})
        if not isinstance(properties, dict):
            return ""
        # The display URL prefers u-url even when the stable identity prefers uid.
        response_url = (
            self._first_url_identity(properties.get("url"), base_url)
            or self._first_url_identity(properties.get("uid"), base_url)
            or ""
        )
        return response_url if len(response_url) <= MAX_NESTED_RESPONSE_IDENTITY_LENGTH else ""

    def _nested_response_digest(self, normalized_entry: dict[str, Any]) -> str:
        """Return a digest for change detection on a normalized nested h-entry."""
        return hashlib.sha256(json.dumps(normalized_entry, sort_keys=True).encode("utf-8")).hexdigest()

    def _sync_nested_responses_safely(
        self,
        *,
        webmention: Webmention,
        candidates: list[dict[str, Any]],
        previous_identities: set[str],
        seen_at: datetime,
    ) -> None:
        """Persist child responses without changing parent verification on failure."""
        try:
            self._sync_nested_responses(
                webmention=webmention,
                candidates=candidates,
                previous_identities=previous_identities,
                seen_at=seen_at,
            )
        except Exception:
            logger.exception(f"Failed to sync nested responses for webmention {webmention.pk}")

    def _sync_nested_responses(
        self,
        *,
        webmention: Webmention,
        candidates: list[dict[str, Any]],
        previous_identities: set[str],
        seen_at: datetime,
    ) -> None:
        """Create, update, and retire child responses for the latest verified parent source."""
        current_identities = {candidate["identity"] for candidate in candidates}
        newly_discovered_identities = current_identities - previous_identities
        # The current slice upserts all stable current children; the previous snapshot comparison is kept explicit
        # so later notification/rendering work can distinguish newly discovered nested responses.
        if newly_discovered_identities:
            logger.debug(
                "Discovered %d new nested responses for webmention %s",
                len(newly_discovered_identities),
                webmention.pk,
            )

        for candidate in candidates:
            self._upsert_nested_response(webmention=webmention, candidate=candidate, seen_at=seen_at)

        # QuerySet.update() does not run auto_now, so modified is set explicitly for retired rows.
        WebmentionNestedResponse.objects.filter(webmention=webmention).exclude(
            identity__in=current_identities
        ).exclude(status="missing").update(status="missing", verified_at=None, modified=timezone.now())

    def _upsert_nested_response(
        self,
        *,
        webmention: Webmention,
        candidate: dict[str, Any],
        seen_at: datetime,
    ) -> None:
        """Create or update one stable nested response row."""
        defaults = {
            "response_url": candidate["response_url"],
            "author_name": candidate["author_name"],
            "author_url": candidate["author_url"],
            "author_photo": candidate["author_photo"],
            "content": candidate["content"],
            "content_html": candidate["content_html"],
            "published": candidate["published"],
            "mention_type": candidate["mention_type"],
            "status": "verified",
            "first_seen_at": seen_at,
            "last_seen_at": seen_at,
            "verified_at": seen_at,
            "parsed_h_entry": candidate["parsed_h_entry"],
            "content_digest": candidate["content_digest"],
        }
        nested_response, created = WebmentionNestedResponse.objects.get_or_create(
            webmention=webmention,
            identity=candidate["identity"],
            defaults=defaults,
        )
        if created:
            return

        nested_response.status = "verified"
        nested_response.last_seen_at = seen_at
        nested_response.verified_at = seen_at
        nested_response.parsed_h_entry = candidate["parsed_h_entry"]
        nested_response.content_digest = candidate["content_digest"]
        nested_response.mention_type = candidate["mention_type"]
        update_fields = [
            "status",
            "last_seen_at",
            "verified_at",
            "parsed_h_entry",
            "content_digest",
            "mention_type",
            "modified",
        ]

        for field in (
            "response_url",
            "author_name",
            "author_url",
            "author_photo",
            "content",
            "content_html",
            "published",
        ):
            setattr(nested_response, field, candidate[field])
            update_fields.append(field)

        nested_response.save(update_fields=update_fields)

    def _nested_response_identities(self, h_entry: dict[str, Any], base_url: str) -> list[str]:
        """Collect stable identities for nested h-entry items inside the parent h-entry."""
        identities: set[str] = set()
        for nested_entry in self._nested_h_entries(h_entry):
            identity = self._nested_response_identity(nested_entry, base_url)
            if identity:
                identities.add(identity)
        return sorted(identities)

    def _nested_h_entries(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        """Return h-entry descendants of a parsed microformats item, excluding the item itself."""
        nested_entries: list[dict[str, Any]] = []
        max_depth = _webmention_nested_max_depth()
        max_candidates = _webmention_nested_max_candidates()

        def visit(candidate: dict[str, Any], depth: int) -> None:
            if depth >= max_depth or len(nested_entries) >= max_candidates:
                return
            for child in candidate.get("children", []):
                if not isinstance(child, dict):
                    continue
                if "h-entry" in child.get("type", []):
                    nested_entries.append(child)
                    if len(nested_entries) >= max_candidates:
                        return
                visit(child, depth + 1)
                if len(nested_entries) >= max_candidates:
                    return

        visit(item, 0)
        return nested_entries

    def _nested_response_identity(self, h_entry: dict[str, Any], base_url: str) -> str | None:
        """Return the preferred stable identity for a nested h-entry."""
        properties = h_entry.get("properties", {})
        if isinstance(properties, dict):
            for prop in ("uid", "url"):
                identity = self._first_url_identity(properties.get(prop), base_url)
                if self._valid_nested_response_identity(identity):
                    return identity

        element_id = h_entry.get("id")
        if isinstance(element_id, str) and element_id:
            identity = urljoin(base_url, f"#{element_id}")
            if self._valid_nested_response_identity(identity):
                return identity
        return None

    def _valid_nested_response_identity(self, identity: str | None) -> bool:
        """Return whether an extracted nested response identity can be stored."""
        return bool(identity and len(identity) <= MAX_NESTED_RESPONSE_IDENTITY_LENGTH)

    def _first_url_identity(self, values: Any, base_url: str) -> str | None:
        """Return the first HTTP(S) URL identity from a microformats property value."""
        candidates = values if isinstance(values, list) else [values]
        for candidate in candidates:
            if isinstance(candidate, dict):
                candidate = candidate.get("value")
            if not isinstance(candidate, str) or not candidate:
                continue
            resolved = urljoin(base_url, candidate)
            parsed = urlparse(resolved)
            if parsed.scheme in ("http", "https") and parsed.netloc:
                return resolved
        return None

    def _find_mentioning_entry(self, parsed: dict[str, Any], target_url: str) -> dict[str, Any] | None:
        """
        Find the h-entry that mentions the target URL.

        Recursively searches through items and their children to handle nested structures.
        """
        items = parsed.get("items", [])
        # First pass: look for h-entry that explicitly mentions the target
        result = self._search_for_mentioning_entry(items, target_url)
        if result:
            return result

        # Second pass: return the first h-entry found (fallback)
        return self._search_for_any_h_entry(items)

    def _search_for_mentioning_entry(self, items: list[dict[str, Any]], target_url: str) -> dict[str, Any] | None:
        """Recursively search for an h-entry that mentions the target URL."""
        max_depth = _webmention_nested_max_depth()
        max_items = _webmention_search_max_items()
        searched = 0
        stack = [(item, 0) for item in reversed(items) if isinstance(item, dict)]

        while stack and searched < max_items:
            item, depth = stack.pop()
            searched += 1
            if "h-entry" in item.get("type", []):
                # Check if this entry mentions the target
                properties = item.get("properties", {})

                # Check various properties for the target URL
                for prop in ["in-reply-to", "like-of", "repost-of", "bookmark-of", "mention-of"]:
                    if self._property_links_to_target(properties, prop, target_url):
                        return item

                # Check content for the URL
                content = properties.get("content", [])
                for c in content:
                    if isinstance(c, dict) and self._content_links_to_target(c, target_url):
                        return item
                    elif isinstance(c, str) and self._text_links_to_target(c, target_url):
                        return item

            if depth >= max_depth:
                continue
            children = item.get("children", [])
            stack.extend((child, depth + 1) for child in reversed(children) if isinstance(child, dict))

        return None

    def _property_links_to_target(self, properties: dict[str, Any], prop: str, target_url: str) -> bool:
        """Return whether a microformats URL property matches the target."""
        values = properties.get(prop, [])
        if not isinstance(values, list):
            values = [values]
        for value in values:
            if isinstance(value, str) and _urls_match(value, target_url):
                return True
            if isinstance(value, dict):
                candidate = value.get("value")
                if isinstance(candidate, str) and _urls_match(candidate, target_url):
                    return True
        return False

    def _content_links_to_target(self, content: dict[str, Any], target_url: str) -> bool:
        """Return whether parsed microformats content links to the target."""
        html = content.get("html")
        if isinstance(html, str) and _html_links_to_target(html, target_url):
            return True
        value = content.get("value")
        return isinstance(value, str) and self._text_links_to_target(value, target_url)

    def _text_links_to_target(self, value: str, target_url: str) -> bool:
        """Return whether a plain-text microformats value is exactly or URL-token linked to the target."""
        if _urls_match(value, target_url):
            return True
        for token in value.split():
            candidate = _strip_plain_text_url_punctuation(token)
            if _urls_match(candidate, target_url):
                return True
        return False

    def _search_for_any_h_entry(self, items: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Recursively search for any h-entry (fallback)."""
        for item in items:
            if "h-entry" in item.get("type", []):
                return item

            # Recursively search children
            children = item.get("children", [])
            if children:
                result = self._search_for_any_h_entry(children)
                if result:
                    return result

        return None

    def _find_h_card_by_url(self, parsed: dict[str, Any], url: str) -> dict[str, Any] | None:
        """
        Find an h-card in the parsed data that has a matching URL.

        Recursively searches through items and their children to handle nested structures
        like h-feeds containing h-entries with nested h-cards.
        """
        items = parsed.get("items", [])
        return self._search_items_for_h_card(items, url)

    def _search_items_for_h_card(self, items: list[dict[str, Any]], url: str) -> dict[str, Any] | None:
        """Recursively search through items and their children for a matching h-card."""
        for item in items:
            # Check if this item is an h-card with matching URL
            if "h-card" in item.get("type", []):
                properties = item.get("properties", {})
                urls = properties.get("url", [])
                if not isinstance(urls, list):
                    urls = [urls]
                for candidate_url in urls:
                    if isinstance(candidate_url, str) and _urls_match(candidate_url, url):
                        return item

            # Recursively search children
            children = item.get("children", [])
            if children:
                result = self._search_items_for_h_card(children, url)
                if result:
                    return result

        return None

    def _find_h_card_by_author_reference(
        self, parsed: dict[str, Any], author_url: str, base_url: str
    ) -> dict[str, Any] | None:
        """Find an h-card referenced by an author URL or same-document fragment."""
        resolved_url = urljoin(base_url, author_url)
        parsed_url = urlparse(resolved_url)

        if parsed_url.fragment:
            h_card = self._find_h_card_by_id(parsed, parsed_url.fragment)
            if h_card:
                return h_card

        return self._find_h_card_by_url(parsed, resolved_url)

    def _find_h_card_by_id(self, parsed: dict[str, Any], element_id: str) -> dict[str, Any] | None:
        """Find an h-card by its parsed HTML id."""
        items = parsed.get("items", [])
        return self._search_items_for_h_card_id(items, element_id)

    def _search_items_for_h_card_id(self, items: list[dict[str, Any]], element_id: str) -> dict[str, Any] | None:
        """Recursively search through items and their children for an h-card with a matching id."""
        for item in items:
            if "h-card" in item.get("type", []) and item.get("id") == element_id:
                return item

            children = item.get("children", [])
            if children:
                result = self._search_items_for_h_card_id(children, element_id)
                if result:
                    return result

        return None

    def _extract_author(self, h_entry: dict[str, Any], parsed: dict[str, Any], base_url: str) -> dict[str, str]:
        """
        Extract author information from h-entry.

        Implements the receive-side local/same-page portion of the microformats2 authorship algorithm:
        - Extracts author from nested h-card in author property
        - Resolves author URL references to h-cards on the same page
        - Uses rel=author references to h-cards already parsed from the page
        - Falls back to a single unambiguous page-level h-card when no explicit author exists
        - Falls back to using URL as name if no h-card found

        Does NOT currently implement:
        - Fetching remote author URLs

        See: https://indieweb.org/authorship
        """
        properties = h_entry.get("properties", {})
        author_data = properties.get("author", [])

        if author_data:
            author = author_data[0] if isinstance(author_data, list) else author_data
            return self._extract_explicit_author(author, parsed, base_url)

        rel_author = self._find_author_from_rel_author(parsed, base_url)
        if rel_author:
            return rel_author

        return self._find_page_h_card_author(parsed, base_url)

    def _extract_explicit_author(
        self, author: str | dict[str, Any], parsed: dict[str, Any], base_url: str
    ) -> dict[str, str]:
        """Extract author data from an h-entry author property."""
        if isinstance(author, str):
            if self._is_author_url_reference(author):
                h_card = self._find_h_card_by_author_reference(parsed, author, base_url)
                if h_card:
                    return self._extract_h_card_author(h_card, base_url)
                # If no h-card found, use URL as both url and name (fallback to previous behavior)
                # This ensures something is visible to users even when the h-card is missing
                resolved_author_url = urljoin(base_url, author)
                return {"url": resolved_author_url, "name": resolved_author_url, "photo": ""}
            # Otherwise, it's a plain text name
            return {"name": author}

        # If author is an h-card
        if isinstance(author, dict):
            # Check if it's a microformat object with properties
            if "properties" in author:
                author_props = author.get("properties", {})
            else:
                # Might be a simplified format
                author_props = author

            return self._extract_author_properties(author_props, base_url)

        return {}

    def _is_author_url_reference(self, value: str) -> bool:
        """Return whether a string author value should be treated as a URL reference."""
        parsed = urlparse(value)
        return parsed.scheme in ("http", "https") or value.startswith(("/", "./", "../", "#"))

    def _find_author_from_rel_author(self, parsed: dict[str, Any], base_url: str) -> dict[str, str]:
        """Resolve rel=author links to h-cards already present in the parsed source document."""
        rels = parsed.get("rels", {})
        author_urls = rels.get("author", [])
        if not isinstance(author_urls, list):
            author_urls = [author_urls]

        for author_url in author_urls:
            if not isinstance(author_url, str):
                continue
            h_card = self._find_h_card_by_author_reference(parsed, author_url, base_url)
            if h_card:
                return self._extract_h_card_author(h_card, base_url)

        return {}

    def _find_page_h_card_author(self, parsed: dict[str, Any], base_url: str) -> dict[str, str]:
        """Use a single page-level h-card as a conservative fallback author."""
        h_cards = self._find_page_level_h_cards(parsed)
        if len(h_cards) != 1:
            return {}
        return self._extract_h_card_author(h_cards[0], base_url)

    def _find_page_level_h_cards(self, parsed: dict[str, Any]) -> list[dict[str, Any]]:
        """Find h-cards outside h-entry items for page-level authorship fallback."""
        items = parsed.get("items", [])
        return self._collect_page_level_h_cards(items)

    def _collect_page_level_h_cards(
        self, items: list[dict[str, Any]], inside_h_entry: bool = False
    ) -> list[dict[str, Any]]:
        """Collect h-cards that are not descendants of an h-entry."""
        h_cards = []
        for item in items:
            item_types = item.get("type", [])
            item_inside_h_entry = inside_h_entry or "h-entry" in item_types
            if "h-card" in item_types and not item_inside_h_entry:
                h_cards.append(item)

            children = item.get("children", [])
            if children:
                h_cards.extend(self._collect_page_level_h_cards(children, item_inside_h_entry))

        return h_cards

    def _extract_h_card_author(self, h_card: dict[str, Any], base_url: str) -> dict[str, str]:
        """Extract normalized author fields from an h-card item."""
        return self._extract_author_properties(h_card.get("properties", {}), base_url)

    def _extract_author_properties(self, properties: dict[str, Any], base_url: str) -> dict[str, str]:
        """Extract author properties and resolve relative URL fields."""
        result = {
            "name": self._get_first_property(properties, "name"),
            "url": self._get_first_property(properties, "url"),
            "photo": self._get_first_property(properties, "photo"),
        }

        if result["url"]:
            result["url"] = urljoin(base_url, result["url"])
        if result["photo"]:
            result["photo"] = urljoin(base_url, result["photo"])

        return result

    def _extract_content(self, h_entry: dict[str, Any]) -> dict[str, str]:
        """Extract content from h-entry."""
        properties = h_entry.get("properties", {})
        content_data = properties.get("content", [])

        if not content_data:
            # Try summary as fallback
            summary = self._get_first_property(properties, "summary")
            if summary:
                return {"text": summary, "html": summary}
            return {"text": "", "html": ""}

        content = content_data[0] if isinstance(content_data, list) else content_data

        if isinstance(content, dict):
            return {
                "text": content.get("value", ""),
                "html": content.get("html") or content.get("value", ""),
            }
        elif isinstance(content, str):
            return {"text": content, "html": content}

        return {"text": "", "html": ""}

    def _extract_published(self, h_entry: dict[str, Any]) -> datetime | None:
        """Extract published date from h-entry."""
        properties = h_entry.get("properties", {})
        published = self._get_first_property(properties, "published")

        if published:
            try:
                # Parse ISO format datetime
                if isinstance(published, str):
                    # Handle timezone-aware datetime strings
                    if published.endswith("Z"):
                        published = published[:-1] + "+00:00"
                    return datetime.fromisoformat(published)
            except ValueError:
                logger.warning(f"Failed to parse published date: {published}")

        return None

    def _determine_mention_type(self, h_entry: dict[str, Any], target_url: str) -> str:
        """Determine the type of mention."""
        properties = h_entry.get("properties", {})

        # Check for specific mention types
        if self._property_links_to_target(properties, "in-reply-to", target_url):
            return "reply"
        elif self._property_links_to_target(properties, "like-of", target_url):
            return "like"
        elif self._property_links_to_target(properties, "repost-of", target_url):
            return "repost"
        elif self._property_links_to_target(properties, "bookmark-of", target_url):
            return "mention"  # Treat bookmarks as mentions for now

        # Default to generic mention
        return "mention"

    def _get_first_property(self, properties: dict[str, Any], key: str) -> str:
        """Get the first value of a property."""
        values = properties.get(key, [])
        if values and isinstance(values, list) and len(values) > 0:
            value = values[0]
            if isinstance(value, str):
                return value
            elif isinstance(value, dict):
                # Handle complex microformats objects
                return value.get("value", "")  # type: ignore[no-any-return]
        return ""

    def _get_local_profile(self, author_url: str) -> Profile | None:
        """Check if author URL belongs to a local user."""
        if not author_url:
            return None

        try:
            # Check if URL matches a local profile
            current_site = Site.objects.get_current()
            parsed = urlparse(author_url)

            if parsed.netloc == current_site.domain:
                return Profile.objects.get(url=author_url)
        except (Profile.DoesNotExist, Site.DoesNotExist):
            pass

        return None


def process_queued_webmention(webmention_id: int) -> Webmention:
    """Process an existing queued Webmention row.

    Queue integrations can call this helper from their worker process after the
    receive endpoint has created or reused a pending ``Webmention`` row.
    """
    # Load by id first so worker integrations get an explicit DoesNotExist for missing queued rows.
    webmention = Webmention.objects.get(pk=webmention_id)
    return WebmentionProcessor().process_webmention(
        webmention.source_url,
        webmention.target_url,
        vouch_url=webmention.vouch_url or None,
    )
