"""
Webmention processing logic.

Handles fetching, parsing, and verifying webmentions.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import httpx
import mf2py
from django.conf import settings
from django.dispatch import Signal
from django.utils import timezone
from django.utils.module_loading import import_string

from .models import Webmention

if TYPE_CHECKING:
    from .interfaces import SpamChecker

logger = logging.getLogger(__name__)

# Signal sent when a webmention is received and processed
webmention_received = Signal()


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
            response = self._fetch_source(source_url)

            # Check response status
            if response.status_code == 410:
                # Source has been deleted
                webmention.status = "failed"
                webmention.save()
                logger.info(f"Source URL returned 410 Gone: {source_url}")
                return webmention

            if response.status_code != 200:
                webmention.status = "failed"
                webmention.save()
                logger.warning(f"Failed to fetch source URL {source_url}: {response.status_code}")
                return webmention

            # Check content type
            content_type = response.headers.get("content-type", "").lower()
            if not content_type.startswith("text/html"):
                webmention.status = "failed"
                webmention.save()
                logger.warning(f"Source URL is not HTML: {content_type}")
                return webmention

            # Verify target link exists
            if not self._verify_target_link(response.text, target_url):
                webmention.status = "failed"
                webmention.save()
                logger.warning(f"Target URL {target_url} not found in source")
                return webmention

            # Parse microformats2
            self._parse_microformats(webmention, response.text, source_url, target_url)

            # Check for spam (reload checker for test compatibility)
            spam_checker = self._get_spam_checker()
            if spam_checker:
                spam_result = spam_checker.check(webmention)
                webmention.spam_check_result = spam_result
                if spam_result.get("is_spam", False):
                    webmention.status = "spam"
                    webmention.save()
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
            webmention.status = "failed"
            webmention.save()
            return webmention

    def _fetch_source(self, source_url: str) -> httpx.Response:
        """Fetch the source URL."""
        headers = {"User-Agent": "django-indieweb/1.0"}
        with httpx.Client() as client:
            return client.get(source_url, headers=headers, timeout=30)

    def _verify_target_link(self, html_content: str, target_url: str) -> bool:
        """Verify that the target URL is linked in the source content."""
        # Simple check for the URL in href attributes
        # This could be made more sophisticated with proper HTML parsing
        return f'href="{target_url}"' in html_content or f"href='{target_url}'" in html_content

    def _parse_microformats(self, webmention: Webmention, html_content: str, source_url: str, target_url: str) -> None:
        """Parse microformats2 data from HTML content."""
        # Parse microformats
        parsed = mf2py.parse(doc=html_content, url=source_url)

        # Find h-entry that mentions the target
        h_entry = self._find_mentioning_entry(parsed, target_url)
        if not h_entry:
            # No microformats found, use defaults
            return

        # Extract author information
        author = self._extract_author(h_entry, source_url)
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
        """Find the h-entry that mentions the target URL."""
        items = parsed.get("items", [])
        for item in items:
            if "h-entry" in item.get("type", []):
                # Check if this entry mentions the target
                properties = item.get("properties", {})

                # Check various properties for the target URL
                for prop in ["in-reply-to", "like-of", "repost-of", "bookmark-of", "mention-of"]:
                    if target_url in properties.get(prop, []):
                        return item  # type: ignore[no-any-return]

                # Check content for the URL
                content = properties.get("content", [])
                for c in content:
                    if isinstance(c, dict) and target_url in c.get("html", ""):
                        return item  # type: ignore[no-any-return]
                    elif isinstance(c, str) and target_url in c:
                        return item  # type: ignore[no-any-return]

        # If no h-entry found, return the first one if available
        for item in items:
            if "h-entry" in item.get("type", []):
                return item  # type: ignore[no-any-return]

        return None

    def _extract_author(self, h_entry: dict[str, Any], source_url: str) -> dict[str, str]:
        """Extract author information from h-entry."""
        properties = h_entry.get("properties", {})
        author_data = properties.get("author", [])

        if not author_data:
            return {}

        author = author_data[0] if isinstance(author_data, list) else author_data

        # If author is a string, it's just the name
        if isinstance(author, str):
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
                result["url"] = urljoin(source_url, result["url"])
            if result["photo"] and not result["photo"].startswith("http"):
                result["photo"] = urljoin(source_url, result["photo"])

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
                "html": content.get("html", content.get("value", "")),
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
        if target_url in properties.get("in-reply-to", []):
            return "reply"
        elif target_url in properties.get("like-of", []):
            return "like"
        elif target_url in properties.get("repost-of", []):
            return "repost"
        elif target_url in properties.get("bookmark-of", []):
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
