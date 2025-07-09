"""
Pluggable interfaces for Webmention integration.

These interfaces allow projects to customize how webmentions are handled
without modifying django-indieweb core code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from django.urls import resolve
from django.urls.exceptions import Resolver404

if TYPE_CHECKING:
    from .models import Webmention


class URLResolver(ABC):
    """Interface for resolving target URLs to content objects."""

    @abstractmethod
    def resolve(self, target_url: str) -> Any | None:
        """
        Resolve a target URL to a content object.

        Args:
            target_url: The URL to resolve

        Returns:
            Content object if found, None otherwise
        """
        pass

    @abstractmethod
    def get_absolute_url(self, content_object: Any) -> str:
        """
        Get the absolute URL for a content object.

        Args:
            content_object: The content object

        Returns:
            Absolute URL as string
        """
        pass


class SpamChecker(ABC):
    """Interface for spam checking webmentions."""

    @abstractmethod
    def check(self, webmention: Webmention) -> dict[str, Any]:
        """
        Check if a webmention is spam.

        Args:
            webmention: The webmention to check

        Returns:
            Dict with at least:
            - 'is_spam': bool
            - 'confidence': float (0.0-1.0)
            - 'details': Optional explanation
        """
        pass


class CommentAdapter(ABC):
    """Optional interface for converting webmentions to comments."""

    @abstractmethod
    def create_comment(self, webmention: Webmention, content_object: Any) -> Any:
        """
        Create a comment from a webmention.

        Args:
            webmention: The webmention to convert
            content_object: The target content object

        Returns:
            Created comment object
        """
        pass


# Default implementations


class SimpleURLResolver(URLResolver):
    """Simple URL resolver that uses Django's URL resolver."""

    def resolve(self, target_url: str) -> Any | None:
        """
        Basic implementation using Django's resolve().

        This is a minimal implementation that doesn't actually
        resolve to content objects. Projects should implement
        their own resolver.
        """
        try:
            parsed = urlparse(target_url)
            resolve(parsed.path)
            # In a real implementation, you would:
            # 1. Check the view and URL parameters
            # 2. Load the appropriate model instance
            # 3. Return the content object
            # For now, just return None as this is a stub
            return None
        except (Resolver404, Exception):
            return None

    def get_absolute_url(self, content_object: Any) -> str:
        """Get absolute URL for a content object."""
        if hasattr(content_object, "get_absolute_url"):
            url = content_object.get_absolute_url()
            return str(url) if url else ""
        return ""


class NoOpSpamChecker(SpamChecker):
    """Default spam checker that accepts everything."""

    def check(self, webmention: Webmention) -> dict[str, Any]:
        """Always returns not spam."""
        return {
            "is_spam": False,
            "confidence": 0.0,
            "details": None,
        }
