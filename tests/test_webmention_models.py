"""Test cases for Webmention models."""

from datetime import datetime, timezone

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from indieweb.models import (
    Webmention,
    WebmentionNestedResponse,
    WebmentionOutboundTarget,
    WebmentionSourceSnapshot,
)


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


@pytest.mark.django_db
class TestWebmentionOutboundTargetModel:
    """Test cases for outbound Webmention target history."""

    def test_create_outbound_target_with_documented_fields(self):
        """Test creating a complete outbound target-history row."""
        endpoint_discovered_at = datetime(2026, 5, 2, 10, 0, 0, tzinfo=timezone.utc)
        first_sent_at = datetime(2026, 5, 2, 10, 1, 0, tzinfo=timezone.utc)
        last_sent_at = datetime(2026, 5, 2, 10, 2, 0, tzinfo=timezone.utc)
        last_seen_at = datetime(2026, 5, 2, 10, 3, 0, tzinfo=timezone.utc)

        target = WebmentionOutboundTarget.objects.create(
            source_url="https://source.example/posts/1",
            target_url="https://target.example/articles/1",
            endpoint_url="https://target.example/webmention",
            endpoint_discovered_at=endpoint_discovered_at,
            first_sent_at=first_sent_at,
            last_sent_at=last_sent_at,
            last_status_code=202,
            last_success=True,
            last_error="",
            last_vouch_url="https://source.example/vouch",
            last_seen_in_source_at=last_seen_at,
        )

        assert target.source_url == "https://source.example/posts/1"
        assert target.target_url == "https://target.example/articles/1"
        assert target.endpoint_url == "https://target.example/webmention"
        assert target.endpoint_discovered_at == endpoint_discovered_at
        assert target.first_sent_at == first_sent_at
        assert target.last_sent_at == last_sent_at
        assert target.last_status_code == 202
        assert target.last_success is True
        assert target.last_error == ""
        assert target.last_vouch_url == "https://source.example/vouch"
        assert target.last_seen_in_source_at == last_seen_at
        assert target.created
        assert target.modified

    def test_outbound_target_defaults(self):
        """Test nullable diagnostic and result fields default to an unsent state."""
        target = WebmentionOutboundTarget.objects.create(
            source_url="https://source.example/posts/defaults",
            target_url="https://target.example/articles/defaults",
        )

        assert target.endpoint_url == ""
        assert target.endpoint_discovered_at is None
        assert target.first_sent_at is None
        assert target.last_sent_at is None
        assert target.last_status_code is None
        assert target.last_success is False
        assert target.last_error == ""
        assert target.last_vouch_url == ""
        assert target.last_seen_in_source_at is None

    @pytest.mark.parametrize(
        ("source_url", "target_url"),
        [
            ("not-a-url", "https://target.example/articles/1"),
            ("https://source.example/posts/1", "not-a-url"),
            ("ftp://source.example/posts/1", "https://target.example/articles/1"),
            ("https://source.example/posts/1", "ftp://target.example/articles/1"),
        ],
    )
    def test_outbound_target_url_validation(self, source_url, target_url):
        """Test source and target URLs must be valid HTTP(S) URLs."""
        target = WebmentionOutboundTarget(source_url=source_url, target_url=target_url)

        with pytest.raises(ValidationError):
            target.full_clean()

    def test_outbound_target_unique_by_exact_source_and_target(self):
        """Test source_url and target_url are unique as an exact pair."""
        WebmentionOutboundTarget.objects.create(
            source_url="https://source.example/posts/1",
            target_url="https://target.example/articles/1",
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            WebmentionOutboundTarget.objects.create(
                source_url="https://source.example/posts/1",
                target_url="https://target.example/articles/1",
            )

    def test_outbound_target_preserves_exact_url_identity(self):
        """Test URL variants are not silently canonicalized or collapsed."""
        source_url = "https://source.example/posts/1"
        target_urls = [
            "https://target.example/articles/1",
            "https://target.example/articles/1/",
            "https://target.example/articles/1?a=1&b=2",
            "https://target.example/articles/1?b=2&a=1",
            "https://target.example/articles/1#comments",
            "https://TARGET.example/articles/1",
        ]

        for target_url in target_urls:
            WebmentionOutboundTarget.objects.create(source_url=source_url, target_url=target_url)

        assert (
            list(
                WebmentionOutboundTarget.objects.filter(source_url=source_url)
                .order_by("id")
                .values_list(
                    "target_url",
                    flat=True,
                )
            )
            == target_urls
        )

    def test_outbound_target_preserves_exact_source_identity(self):
        """Test source URL variants are not silently canonicalized or collapsed."""
        target_url = "https://target.example/articles/1"
        source_urls = [
            "https://source.example/posts/1",
            "https://source.example/posts/1/",
            "https://source.example/posts/1?a=1&b=2",
            "https://source.example/posts/1?b=2&a=1",
            "https://source.example/posts/1#comments",
            "https://SOURCE.example/posts/1",
        ]

        for source_url in source_urls:
            WebmentionOutboundTarget.objects.create(source_url=source_url, target_url=target_url)

        assert (
            list(
                WebmentionOutboundTarget.objects.filter(target_url=target_url)
                .order_by("id")
                .values_list(
                    "source_url",
                    flat=True,
                )
            )
            == source_urls
        )

    def test_outbound_target_result_fields_persist_updates(self):
        """Test endpoint diagnostics, latest result, Vouch, and last-seen fields persist."""
        target = WebmentionOutboundTarget.objects.create(
            source_url="https://source.example/posts/2",
            target_url="https://target.example/articles/2",
        )
        endpoint_discovered_at = datetime(2026, 5, 2, 11, 0, 0, tzinfo=timezone.utc)
        first_sent_at = datetime(2026, 5, 2, 11, 1, 0, tzinfo=timezone.utc)
        last_sent_at = datetime(2026, 5, 2, 11, 2, 0, tzinfo=timezone.utc)
        last_seen_at = datetime(2026, 5, 2, 11, 3, 0, tzinfo=timezone.utc)

        target.endpoint_url = "https://target.example/webmention"
        target.endpoint_discovered_at = endpoint_discovered_at
        target.first_sent_at = first_sent_at
        target.last_sent_at = last_sent_at
        target.last_status_code = 500
        target.last_success = False
        target.last_error = "HTTP 500"
        target.last_vouch_url = "https://source.example/vouch"
        target.last_seen_in_source_at = last_seen_at
        target.save()

        target.refresh_from_db()

        assert target.endpoint_url == "https://target.example/webmention"
        assert target.endpoint_discovered_at == endpoint_discovered_at
        assert target.first_sent_at == first_sent_at
        assert target.last_sent_at == last_sent_at
        assert target.last_status_code == 500
        assert target.last_success is False
        assert target.last_error == "HTTP 500"
        assert target.last_vouch_url == "https://source.example/vouch"
        assert target.last_seen_in_source_at == last_seen_at

    def test_outbound_target_string_representation(self):
        """Test string representation includes source and target context."""
        target = WebmentionOutboundTarget(
            source_url="https://source.example/posts/1",
            target_url="https://target.example/articles/1",
        )

        string_value = str(target)

        assert "Outbound Webmention" in string_value
        assert "https://source.example/posts/1" in string_value
        assert "https://target.example/articles/1" in string_value
