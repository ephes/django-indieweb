"""
Webmention processing logic.

Handles fetching, parsing, and verifying webmentions.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import ParseResult, parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx
import mf2py
from bs4 import BeautifulSoup, Tag
from django.conf import settings
from django.contrib.sites.models import Site
from django.dispatch import Signal
from django.utils import timezone
from django.utils.module_loading import import_string

from .http_client import RedirectedResponse, request_with_webmention_redirects
from .models import Profile, Webmention

if TYPE_CHECKING:
    from .interfaces import SpamChecker

logger = logging.getLogger(__name__)

# Signal sent when a webmention is received and processed
webmention_received = Signal()
TRAILING_TEXT_URL_PUNCTUATION = ".,;:!?\"'"
LEADING_TEXT_URL_PUNCTUATION = "([{<\"'"
WRAPPING_TEXT_URL_PUNCTUATION = {
    ")": "(",
    "]": "[",
    "}": "{",
    ">": "<",
}


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

    def process_webmention(self, source_url: str, target_url: str) -> Webmention:
        """
        Process a webmention by fetching and parsing the source.

        Args:
            source_url: The URL that mentions the target
            target_url: The URL being mentioned

        Returns:
            Webmention object with processing results
        """
        logger.info(f"Processing webmention from {source_url} to {target_url}")

        # Get or create webmention
        webmention, created = Webmention.objects.get_or_create(
            source_url=source_url,
            target_url=target_url,
        )

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

            # Verify target link exists
            if not self._verify_target_link(response.text, target_url):
                self._mark_webmention_failed(webmention)
                logger.warning(f"Target URL {target_url} not found in source")
                return webmention

            # Parse microformats2
            self._parse_microformats(webmention, response.text, fetched.final_url, target_url)

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

            # Mark as verified
            webmention.status = "verified"
            webmention.verified_at = timezone.now()
            webmention.save()

            # Send signal
            webmention_received.send(
                sender=self.__class__,
                webmention=webmention,
                source_url=source_url,
                target_url=target_url,
            )

            logger.info(f"Successfully processed webmention from {source_url}")
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
        with httpx.Client() as client:
            return request_with_webmention_redirects(client, "GET", source_url, headers=headers, timeout=30)

    def _verify_target_link(self, html_content: str, target_url: str) -> bool:
        """Verify that the target URL is linked in the source content."""
        return _html_links_to_target(html_content, target_url)

    def _parse_microformats(self, webmention: Webmention, html_content: str, base_url: str, target_url: str) -> None:
        """Parse microformats2 data from HTML content."""
        # Parse microformats
        parsed = mf2py.parse(doc=html_content, url=base_url)

        # Find h-entry that mentions the target
        h_entry = self._find_mentioning_entry(parsed, target_url)
        if not h_entry:
            # No microformats found, use defaults
            return

        # Extract author information
        author = self._extract_author(h_entry, parsed, base_url)

        # Check if this is a local author
        author_url = author.get("url", "")
        local_profile = self._get_local_profile(author_url)

        if local_profile:
            # Use local profile data
            webmention.author_name = local_profile.name
            webmention.author_url = local_profile.url
            webmention.author_photo = local_profile.photo_url
        else:
            # Use parsed data
            webmention.author_name = author.get("name", "")
            webmention.author_url = author.get("url", "")
            webmention.author_photo = author.get("photo", "")

        # Extract content
        content_data = self._extract_content(h_entry)
        webmention.content = content_data.get("text", "")
        webmention.content_html = content_data.get("html", "")

        # Extract published date
        published = self._extract_published(h_entry)
        if published:
            webmention.published = published

        # Determine mention type
        webmention.mention_type = self._determine_mention_type(h_entry, target_url)

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
        for item in items:
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

            # Recursively search children
            children = item.get("children", [])
            if children:
                result = self._search_for_mentioning_entry(children, target_url)
                if result:
                    return result

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
                if url in urls:
                    return item

            # Recursively search children
            children = item.get("children", [])
            if children:
                result = self._search_items_for_h_card(children, url)
                if result:
                    return result

        return None

    def _extract_author(self, h_entry: dict[str, Any], parsed: dict[str, Any], base_url: str) -> dict[str, str]:
        """
        Extract author information from h-entry.

        Implements a subset of the microformats2 authorship algorithm:
        - Extracts author from nested h-card in author property
        - Resolves author URL references to h-cards on the same page
        - Falls back to using URL as name if no h-card found

        Does NOT currently implement:
        - Fetching remote author URLs
        - Following rel=author links
        - Using page-level h-card as fallback

        See: https://indieweb.org/authorship
        """
        properties = h_entry.get("properties", {})
        author_data = properties.get("author", [])

        if not author_data:
            return {}

        author = author_data[0] if isinstance(author_data, list) else author_data

        # If author is a string, check if it's a URL
        if isinstance(author, str):
            # If it looks like a URL, try to find a matching h-card
            if author.startswith("http://") or author.startswith("https://"):
                # Look for h-card with matching URL in the parsed items
                h_card = self._find_h_card_by_url(parsed, author)
                if h_card:
                    # Extract info from the h-card
                    card_props = h_card.get("properties", {})
                    return {
                        "name": self._get_first_property(card_props, "name"),
                        "url": self._get_first_property(card_props, "url"),
                        "photo": self._get_first_property(card_props, "photo"),
                    }
                # If no h-card found, use URL as both url and name (fallback to previous behavior)
                # This ensures something is visible to users even when the h-card is missing
                return {"url": author, "name": author, "photo": ""}
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

            result = {
                "name": self._get_first_property(author_props, "name"),
                "url": self._get_first_property(author_props, "url"),
                "photo": self._get_first_property(author_props, "photo"),
            }

            # Make relative URLs absolute
            if result["url"] and not result["url"].startswith("http"):
                result["url"] = urljoin(base_url, result["url"])
            if result["photo"] and not result["photo"].startswith("http"):
                result["photo"] = urljoin(base_url, result["photo"])

            return result

        return {}

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
