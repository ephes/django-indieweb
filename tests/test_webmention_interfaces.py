"""Test cases for Webmention pluggable interfaces."""

from abc import ABC
from typing import Any

import pytest
from django.conf import settings
from django.test import override_settings

from indieweb.interfaces import (
    CommentAdapter,
    NoOpSpamChecker,
    SimpleURLResolver,
    SpamChecker,
    URLResolver,
)
from indieweb.models import Webmention


class TestInterfaces:
    """Test that interfaces are properly defined as abstract base classes."""

    def test_url_resolver_is_abstract(self):
        """Test that URLResolver cannot be instantiated directly."""
        with pytest.raises(TypeError):
            URLResolver()

    def test_spam_checker_is_abstract(self):
        """Test that SpamChecker cannot be instantiated directly."""
        with pytest.raises(TypeError):
            SpamChecker()

    def test_comment_adapter_is_abstract(self):
        """Test that CommentAdapter cannot be instantiated directly."""
        with pytest.raises(TypeError):
            CommentAdapter()

    def test_interfaces_inherit_from_abc(self):
        """Test that all interfaces inherit from ABC."""
        assert issubclass(URLResolver, ABC)
        assert issubclass(SpamChecker, ABC)
        assert issubclass(CommentAdapter, ABC)


@pytest.mark.django_db
class TestSimpleURLResolver:
    """Test cases for SimpleURLResolver implementation."""

    def test_resolve_returns_none_for_invalid_url(self):
        """Test that resolve returns None for invalid URLs."""
        resolver = SimpleURLResolver()

        # Test various invalid URLs
        assert resolver.resolve("https://external.com/post") is None
        assert resolver.resolve("not-a-url") is None
        assert resolver.resolve("") is None

    def test_get_absolute_url_with_object_having_method(self):
        """Test get_absolute_url with an object that has the method."""
        resolver = SimpleURLResolver()

        # Mock object with get_absolute_url method
        class MockObject:
            def get_absolute_url(self):
                return "/test/url/"

        obj = MockObject()
        assert resolver.get_absolute_url(obj) == "/test/url/"

    def test_get_absolute_url_without_method_returns_empty(self):
        """Test get_absolute_url returns empty string for objects without the method."""
        resolver = SimpleURLResolver()

        # Object without get_absolute_url
        obj = object()
        assert resolver.get_absolute_url(obj) == ""


@pytest.mark.django_db
class TestNoOpSpamChecker:
    """Test cases for NoOpSpamChecker implementation."""

    def test_check_always_returns_not_spam(self):
        """Test that NoOpSpamChecker always returns not spam."""
        checker = NoOpSpamChecker()

        # Create a test webmention
        webmention = Webmention(
            source_url="https://spam.com/bad-post",
            target_url="https://mysite.com/article",
            content="Buy cheap products now!!!",
        )

        result = checker.check(webmention)

        assert result["is_spam"] is False
        assert result["confidence"] == 0.0
        assert result["details"] is None

    def test_check_returns_correct_structure(self):
        """Test that check returns the expected dictionary structure."""
        checker = NoOpSpamChecker()
        webmention = Webmention(
            source_url="https://example.com/post",
            target_url="https://mysite.com/article",
        )

        result = checker.check(webmention)

        # Check all required keys are present
        assert "is_spam" in result
        assert "confidence" in result
        assert "details" in result

        # Check types
        assert isinstance(result["is_spam"], bool)
        assert isinstance(result["confidence"], float)


class TestCustomImplementations:
    """Test that custom implementations can be created."""

    def test_custom_url_resolver_implementation(self):
        """Test creating a custom URLResolver implementation."""

        class CustomURLResolver(URLResolver):
            def resolve(self, target_url: str) -> Any | None:
                if target_url == "https://mysite.com/special":
                    return {"type": "special", "id": 123}
                return None

            def get_absolute_url(self, content_object: Any) -> str:
                if isinstance(content_object, dict) and content_object.get("type") == "special":
                    return f"/special/{content_object['id']}/"
                return ""

        resolver = CustomURLResolver()

        # Test resolve
        assert resolver.resolve("https://mysite.com/special") == {"type": "special", "id": 123}
        assert resolver.resolve("https://other.com/post") is None

        # Test get_absolute_url
        assert resolver.get_absolute_url({"type": "special", "id": 123}) == "/special/123/"
        assert resolver.get_absolute_url({"type": "other"}) == ""

    def test_custom_spam_checker_implementation(self):
        """Test creating a custom SpamChecker implementation."""

        class CustomSpamChecker(SpamChecker):
            def check(self, webmention: Webmention) -> dict[str, Any]:
                # Simple keyword-based spam detection
                spam_keywords = ["buy now", "cheap", "viagra", "casino"]
                content_lower = webmention.content.lower()

                is_spam = any(keyword in content_lower for keyword in spam_keywords)
                confidence = 0.9 if is_spam else 0.1

                return {
                    "is_spam": is_spam,
                    "confidence": confidence,
                    "details": "Keyword-based detection",
                }

        checker = CustomSpamChecker()

        # Test spam detection
        spam_webmention = Webmention(
            source_url="https://spam.com/post",
            target_url="https://mysite.com/article",
            content="Buy cheap products now!",
        )

        result = checker.check(spam_webmention)
        assert result["is_spam"] is True
        assert result["confidence"] == 0.9

        # Test non-spam
        normal_webmention = Webmention(
            source_url="https://friend.com/post",
            target_url="https://mysite.com/article",
            content="Great article, thanks for sharing!",
        )

        result = checker.check(normal_webmention)
        assert result["is_spam"] is False
        assert result["confidence"] == 0.1

    def test_custom_comment_adapter_implementation(self):
        """Test creating a custom CommentAdapter implementation."""

        class CustomCommentAdapter(CommentAdapter):
            def create_comment(self, webmention: Webmention, content_object: Any) -> Any:
                # Simulate creating a comment
                return {
                    "id": 123,
                    "author": webmention.author_name,
                    "content": webmention.content,
                    "object_id": getattr(content_object, "id", None),
                }

        adapter = CustomCommentAdapter()

        webmention = Webmention(
            source_url="https://friend.com/post",
            target_url="https://mysite.com/article",
            author_name="John Doe",
            content="Nice post!",
        )

        # Mock content object
        class MockContent:
            id = 456

        comment = adapter.create_comment(webmention, MockContent())

        assert comment["id"] == 123
        assert comment["author"] == "John Doe"
        assert comment["content"] == "Nice post!"
        assert comment["object_id"] == 456


@pytest.mark.django_db
class TestSettingsConfiguration:
    """Test loading interfaces from settings."""

    @override_settings(
        INDIEWEB_URL_RESOLVER="indieweb.interfaces.SimpleURLResolver",
        INDIEWEB_SPAM_CHECKER="indieweb.interfaces.NoOpSpamChecker",
        INDIEWEB_COMMENT_ADAPTER=None,
    )
    def test_loading_interfaces_from_settings(self):
        """Test that interfaces can be loaded from Django settings."""
        from django.utils.module_loading import import_string

        # Load URL resolver
        resolver_path = settings.INDIEWEB_URL_RESOLVER
        resolver_class = import_string(resolver_path)
        resolver = resolver_class()
        assert isinstance(resolver, SimpleURLResolver)

        # Load spam checker
        checker_path = settings.INDIEWEB_SPAM_CHECKER
        checker_class = import_string(checker_path)
        checker = checker_class()
        assert isinstance(checker, NoOpSpamChecker)

        # Comment adapter is None
        adapter_path = settings.INDIEWEB_COMMENT_ADAPTER
        assert adapter_path is None
