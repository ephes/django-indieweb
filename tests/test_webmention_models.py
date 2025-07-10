"""Test cases for Webmention models."""

from datetime import datetime, timezone

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from indieweb.models import Webmention


@pytest.mark.django_db
class TestWebmentionModel:
    """Test cases for the Webmention model."""

    def test_create_webmention(self):
        """Test creating a basic webmention."""
        webmention = Webmention.objects.create(
            source_url="https://example.com/post1",
            target_url="https://mysite.com/article1",
        )

        assert webmention.source_url == "https://example.com/post1"
        assert webmention.target_url == "https://mysite.com/article1"
        assert webmention.status == "pending"
        assert webmention.mention_type == "mention"
        assert webmention.created
        assert webmention.modified
        assert webmention.verified_at is None

    def test_url_validation(self):
        """Test that URLField validates URLs properly."""
        # Valid URLs should work
        webmention = Webmention(
            source_url="https://example.com/post",
            target_url="https://mysite.com/article",
        )
        webmention.full_clean()  # Should not raise

        # Invalid URLs should fail
        webmention = Webmention(
            source_url="not-a-url",
            target_url="https://mysite.com/article",
        )
        with pytest.raises(ValidationError):
            webmention.full_clean()

    def test_status_choices(self):
        """Test that status field only accepts valid choices."""
        valid_statuses = ["pending", "verified", "failed", "spam"]

        for status in valid_statuses:
            webmention = Webmention.objects.create(
                source_url=f"https://example.com/{status}",
                target_url="https://mysite.com/article",
                status=status,
            )
            assert webmention.status == status

    def test_unique_constraint(self):
        """Test that source_url and target_url combination is unique."""
        Webmention.objects.create(
            source_url="https://example.com/post1",
            target_url="https://mysite.com/article1",
        )

        # Creating duplicate should fail
        with pytest.raises(IntegrityError):
            Webmention.objects.create(
                source_url="https://example.com/post1",
                target_url="https://mysite.com/article1",
            )

    def test_microformats_fields(self):
        """Test microformats2 extracted data fields."""
        webmention = Webmention.objects.create(
            source_url="https://example.com/post1",
            target_url="https://mysite.com/article1",
            author_name="John Doe",
            author_url="https://example.com/johndoe",
            author_photo="https://example.com/johndoe.jpg",
            content="This is a reply to your article.",
            content_html="<p>This is a reply to your article.</p>",
            published=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        )

        assert webmention.author_name == "John Doe"
        assert webmention.author_url == "https://example.com/johndoe"
        assert webmention.author_photo == "https://example.com/johndoe.jpg"
        assert webmention.content == "This is a reply to your article."
        assert webmention.content_html == "<p>This is a reply to your article.</p>"
        assert webmention.published.year == 2024

    def test_mention_types(self):
        """Test different webmention types."""
        mention_types = ["mention", "like", "reply", "repost"]

        for mention_type in mention_types:
            webmention = Webmention.objects.create(
                source_url=f"https://example.com/{mention_type}",
                target_url="https://mysite.com/article",
                mention_type=mention_type,
            )
            assert webmention.mention_type == mention_type

    def test_spam_check_result_json_field(self):
        """Test that spam_check_result can store JSON data."""
        spam_data = {
            "is_spam": True,
            "confidence": 0.95,
            "details": "Detected spam patterns",
        }

        webmention = Webmention.objects.create(
            source_url="https://spam.com/post",
            target_url="https://mysite.com/article",
            status="spam",
            spam_check_result=spam_data,
        )

        assert webmention.spam_check_result == spam_data
        assert webmention.spam_check_result["is_spam"] is True
        assert webmention.spam_check_result["confidence"] == 0.95

    def test_verified_timestamp(self):
        """Test that verified_at is set when status changes to verified."""
        webmention = Webmention.objects.create(
            source_url="https://example.com/post",
            target_url="https://mysite.com/article",
        )

        assert webmention.verified_at is None

        # Update to verified status
        webmention.status = "verified"
        webmention.verified_at = datetime.now(timezone.utc)
        webmention.save()

        assert webmention.verified_at is not None

    def test_string_representation(self):
        """Test the string representation of a webmention."""
        webmention = Webmention(
            source_url="https://example.com/post",
            target_url="https://mysite.com/article",
            mention_type="reply",
        )

        # Should include source, target, and type in string representation
        str_repr = str(webmention)
        assert "https://example.com/post" in str_repr
        assert "https://mysite.com/article" in str_repr
        assert "reply" in str_repr

    def test_long_urls_support(self):
        """Test that the model supports long URLs up to 500 characters."""
        long_path = "a" * 450  # Create a long path
        long_url = f"https://example.com/{long_path}"

        webmention = Webmention.objects.create(
            source_url=long_url,
            target_url="https://mysite.com/article",
        )

        assert len(webmention.source_url) > 400
        assert webmention.source_url == long_url
