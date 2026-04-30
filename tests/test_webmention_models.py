"""Test cases for Webmention models."""

from datetime import datetime, timezone

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from indieweb.models import Webmention, WebmentionNestedResponse, WebmentionSourceSnapshot


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


@pytest.mark.django_db
class TestWebmentionSourceSnapshotModel:
    """Test cases for persisted Webmention source snapshots."""

    def test_create_source_snapshot(self):
        """Test creating a source snapshot related to a Webmention."""
        webmention = Webmention.objects.create(
            source_url="https://example.com/post",
            target_url="https://mysite.com/article",
        )
        fetched_at = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)

        snapshot = WebmentionSourceSnapshot.objects.create(
            webmention=webmention,
            raw_source_html="<html><body>source</body></html>",
            final_source_url="https://example.com/final",
            content_digest="a" * 64,
            fetched_at=fetched_at,
            parsed_h_entry={"type": ["h-entry"]},
            nested_response_identities=["https://example.com/comment"],
        )

        assert snapshot.webmention == webmention
        assert webmention.source_snapshot == snapshot
        assert snapshot.raw_source_html == "<html><body>source</body></html>"
        assert snapshot.final_source_url == "https://example.com/final"
        assert snapshot.content_digest == "a" * 64
        assert snapshot.fetched_at == fetched_at
        assert snapshot.parsed_h_entry == {"type": ["h-entry"]}
        assert snapshot.nested_response_identities == ["https://example.com/comment"]
        assert snapshot.created
        assert snapshot.modified

    def test_source_snapshot_json_defaults(self):
        """Test JSON snapshot fields default to empty structures."""
        webmention = Webmention.objects.create(
            source_url="https://example.com/post",
            target_url="https://mysite.com/article",
        )

        snapshot = WebmentionSourceSnapshot.objects.create(
            webmention=webmention,
            raw_source_html="<html></html>",
            final_source_url="https://example.com/post",
            content_digest="b" * 64,
            fetched_at=datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc),
        )

        assert snapshot.parsed_h_entry == {}
        assert snapshot.nested_response_identities == []

    def test_source_snapshot_cascades_with_webmention(self):
        """Test deleting the parent Webmention deletes its source snapshot."""
        webmention = Webmention.objects.create(
            source_url="https://example.com/post",
            target_url="https://mysite.com/article",
        )
        snapshot = WebmentionSourceSnapshot.objects.create(
            webmention=webmention,
            raw_source_html="<html></html>",
            final_source_url="https://example.com/post",
            content_digest="c" * 64,
            fetched_at=datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc),
        )

        webmention.delete()

        assert not WebmentionSourceSnapshot.objects.filter(pk=snapshot.pk).exists()


@pytest.mark.django_db
class TestWebmentionNestedResponseModel:
    """Test cases for nested responses discovered inside a Webmention source."""

    def test_create_nested_response(self):
        """Test creating a nested response related to a parent Webmention."""
        webmention = Webmention.objects.create(
            source_url="https://example.com/post",
            target_url="https://mysite.com/article",
            status="verified",
        )
        seen_at = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)

        child = WebmentionNestedResponse.objects.create(
            webmention=webmention,
            identity="https://example.com/comments/1",
            response_url="https://example.com/comments/1",
            author_name="Nested Author",
            author_url="https://author.example/",
            author_photo="https://author.example/photo.jpg",
            content="Nested content",
            content_html="<p>Nested content</p>",
            published=seen_at,
            mention_type="reply",
            status="verified",
            first_seen_at=seen_at,
            last_seen_at=seen_at,
            verified_at=seen_at,
            parsed_h_entry={"type": ["h-entry"]},
            content_digest="d" * 64,
        )

        assert child.webmention == webmention
        assert list(webmention.nested_responses.all()) == [child]
        assert child.identity == "https://example.com/comments/1"
        assert child.response_url == "https://example.com/comments/1"
        assert child.author_name == "Nested Author"
        assert child.content == "Nested content"
        assert child.mention_type == "reply"
        assert child.status == "verified"
        assert child.is_currently_displayable is True
        assert child.parsed_h_entry == {"type": ["h-entry"]}
        assert child.content_digest == "d" * 64
        assert child.created
        assert child.modified

    def test_nested_response_defaults_and_displayability(self):
        """Test defaults and parent-status-dependent displayability."""
        webmention = Webmention.objects.create(
            source_url="https://example.com/post",
            target_url="https://mysite.com/article",
            status="verified",
        )
        seen_at = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)

        child = WebmentionNestedResponse.objects.create(
            webmention=webmention,
            identity="https://example.com/post#child",
            first_seen_at=seen_at,
            last_seen_at=seen_at,
        )

        assert child.status == "verified"
        assert child.mention_type == "mention"
        assert child.parsed_h_entry == {}
        assert child.content_digest == ""
        assert child.verified_at is None
        assert child.is_currently_displayable is True

        webmention.status = "failed"
        webmention.save(update_fields=["status", "modified"])
        child.refresh_from_db()

        assert child.status == "verified"
        assert child.is_currently_displayable is False

    def test_nested_response_identity_unique_per_parent(self):
        """Test that stable nested identities are unique per parent Webmention."""
        first_parent = Webmention.objects.create(
            source_url="https://example.com/post",
            target_url="https://mysite.com/article",
        )
        second_parent = Webmention.objects.create(
            source_url="https://example.net/post",
            target_url="https://mysite.com/article",
        )
        seen_at = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        identity = "https://comments.example/reply"

        WebmentionNestedResponse.objects.create(
            webmention=first_parent,
            identity=identity,
            first_seen_at=seen_at,
            last_seen_at=seen_at,
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            WebmentionNestedResponse.objects.create(
                webmention=first_parent,
                identity=identity,
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            )

        other_parent_child = WebmentionNestedResponse.objects.create(
            webmention=second_parent,
            identity=identity,
            first_seen_at=seen_at,
            last_seen_at=seen_at,
        )
        assert other_parent_child.identity == identity

    def test_nested_response_cascades_with_webmention(self):
        """Test deleting the parent Webmention deletes nested responses."""
        webmention = Webmention.objects.create(
            source_url="https://example.com/post",
            target_url="https://mysite.com/article",
        )
        child = WebmentionNestedResponse.objects.create(
            webmention=webmention,
            identity="https://example.com/post#child",
            first_seen_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
        )

        webmention.delete()

        assert not WebmentionNestedResponse.objects.filter(pk=child.pk).exists()
