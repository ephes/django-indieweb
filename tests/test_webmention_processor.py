"""Test cases for WebmentionProcessor."""

from unittest.mock import Mock, patch

import pytest
from django.test import RequestFactory, override_settings
from django.utils import timezone as django_timezone

from indieweb.models import Webmention
from indieweb.processors import WebmentionProcessor


@pytest.mark.django_db
class TestWebmentionProcessor:
    """Test cases for the WebmentionProcessor class."""

    @pytest.fixture
    def processor(self):
        """Create a WebmentionProcessor instance."""
        return WebmentionProcessor()

    @pytest.fixture
    def factory(self):
        """Create a RequestFactory instance."""
        return RequestFactory()

    def test_processor_fetches_source_url(self, processor):
        """Test that processor fetches the source URL."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = '<html><body><a href="https://mysite.com/article">Link</a></body></html>'

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            mock_client.get.assert_called_once_with(
                source_url, headers={"User-Agent": "django-indieweb/1.0"}, timeout=30
            )
            assert webmention.status == "verified"

    def test_processor_handles_fetch_errors(self, processor):
        """Test that processor handles fetch errors gracefully."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = Exception("Network error")

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "failed"
            assert webmention.source_url == source_url
            assert webmention.target_url == target_url

    def test_processor_verifies_target_link_exists(self, processor):
        """Test that processor verifies the target link exists in source."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        # Test with link present
        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = f'<html><body><a href="{target_url}">Link to article</a></body></html>'

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)
            assert webmention.status == "verified"

        # Test with link missing
        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = "<html><body>No link here</body></html>"

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)
            assert webmention.status == "failed"

    def test_processor_handles_404_response(self, processor):
        """Test that processor handles 404 responses."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 404

            mock_response.text = "Not found"

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)
            assert webmention.status == "failed"

    def test_processor_parses_microformats2(self, processor):
        """Test that processor parses microformats2 data."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <div class="p-author h-card">
                    <img class="u-photo" src="https://example.com/avatar.jpg" alt="John Doe">
                    <a class="p-name u-url" href="https://example.com">John Doe</a>
                </div>
                <div class="e-content">
                    <p>Great article! <a href="{target_url}">Check it out</a></p>
                </div>
                <time class="dt-published" datetime="2024-01-15T10:00:00Z">January 15, 2024</time>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_name == "John Doe"
            assert webmention.author_url == "https://example.com"
            assert webmention.author_photo == "https://example.com/avatar.jpg"
            assert "Great article!" in webmention.content
            assert webmention.published is not None

    def test_processor_detects_mention_types(self, processor):
        """Test that processor correctly detects different mention types."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        # Test reply
        reply_html = f'''
        <html>
        <body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">In reply to</a>
                <div class="e-content">This is a reply</div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = reply_html

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)
            assert webmention.mention_type == "reply"

        # Test like
        like_html = f'''
        <html>
        <body>
            <article class="h-entry">
                <a class="u-like-of" href="{target_url}">Liked</a>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = like_html

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)
            assert webmention.mention_type == "like"

        # Test repost
        repost_html = f'''
        <html>
        <body>
            <article class="h-entry">
                <a class="u-repost-of" href="{target_url}">Reposted</a>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = repost_html

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)
            assert webmention.mention_type == "repost"

    def test_processor_handles_no_microformats(self, processor):
        """Test that processor handles pages without microformats."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <body>
            <p>Simple page with <a href="{target_url}">a link</a></p>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_name == ""
            assert webmention.author_url == ""
            assert webmention.mention_type == "mention"

    @override_settings(INDIEWEB_SPAM_CHECKER="indieweb.interfaces.NoOpSpamChecker")
    def test_processor_uses_spam_checker(self, processor):
        """Test that processor uses configured spam checker."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        html_content = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            # Patch the spam checker to verify it's called
            with patch("indieweb.interfaces.NoOpSpamChecker.check") as mock_check:
                mock_check.return_value = {
                    "is_spam": False,
                    "confidence": 0.0,
                    "details": None,
                }

                webmention = processor.process_webmention(source_url, target_url)

                mock_check.assert_called_once()
                assert webmention.status == "verified"
                assert webmention.spam_check_result is not None

    @override_settings(INDIEWEB_SPAM_CHECKER="indieweb.interfaces.NoOpSpamChecker")
    def test_processor_marks_spam(self, processor):
        """Test that processor marks webmentions as spam when detected."""
        source_url = "https://spam.com/post"
        target_url = "https://mysite.com/article"

        html_content = f'<html><body>Buy cheap stuff! <a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            # Mock spam checker to return spam
            with patch("indieweb.interfaces.NoOpSpamChecker.check") as mock_check:
                mock_check.return_value = {
                    "is_spam": True,
                    "confidence": 0.95,
                    "details": "Spam keywords detected",
                }

                webmention = processor.process_webmention(source_url, target_url)

                assert webmention.status == "spam"
                assert webmention.spam_check_result["is_spam"] is True

    def test_processor_updates_existing_webmention(self, processor):
        """Test that processor updates existing webmention."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        # Create existing webmention
        existing = Webmention.objects.create(
            source_url=source_url,
            target_url=target_url,
            status="pending",
            author_name="Old Name",
        )

        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <div class="p-author h-card">
                    <a class="p-name" href="https://example.com">New Name</a>
                </div>
                <div class="e-content">Updated content <a href="{target_url}">link</a></div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.id == existing.id
            assert webmention.author_name == "New Name"
            assert webmention.status == "verified"
            assert "Updated content" in webmention.content

    def test_processor_handles_deleted_source(self, processor):
        """Test that processor handles when source is deleted."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        # Create existing verified webmention
        existing = Webmention.objects.create(
            source_url=source_url,
            target_url=target_url,
            status="verified",
            author_name="John Doe",
            content="Original content",
        )

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 410  # Gone

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.id == existing.id
            assert webmention.status == "failed"
            # Original content should be preserved
            assert webmention.author_name == "John Doe"
            assert webmention.content == "Original content"

    def test_processor_emits_signal(self, processor):
        """Test that processor emits webmention_received signal."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        html_content = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            with patch("indieweb.processors.webmention_received.send") as mock_signal:
                webmention = processor.process_webmention(source_url, target_url)

                mock_signal.assert_called_once_with(
                    sender=WebmentionProcessor,
                    webmention=webmention,
                    source_url=source_url,
                    target_url=target_url,
                )

    def test_processor_sets_verified_timestamp(self, processor):
        """Test that processor sets verified_at timestamp."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        html_content = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            before = django_timezone.now()
            webmention = processor.process_webmention(source_url, target_url)
            after = django_timezone.now()

            assert webmention.verified_at is not None
            assert before <= webmention.verified_at <= after

    def test_processor_handles_non_html_content(self, processor):
        """Test that processor rejects non-HTML content."""
        source_url = "https://example.com/data.json"
        target_url = "https://mysite.com/article"

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = '{"data": "json"}'

            mock_response.headers = {"content-type": "application/json"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)
            assert webmention.status == "failed"

    def test_processor_handles_relative_author_urls(self, processor):
        """Test that processor handles relative URLs in author data."""
        source_url = "https://example.com/posts/123"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <div class="p-author h-card">
                    <img class="u-photo" src="/avatar.jpg" alt="John">
                    <a class="p-name u-url" href="/about">John Doe</a>
                </div>
                <div class="e-content">
                    Content with <a href="{target_url}">link</a>
                </div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.author_url == "https://example.com/about"
            assert webmention.author_photo == "https://example.com/avatar.jpg"

    def test_processor_extracts_text_content(self, processor):
        """Test that processor extracts both text and HTML content."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <div class="e-content">
                    <p>This is <strong>bold</strong> text with a <a href="{target_url}">link</a>.</p>
                </div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.content == "This is bold text with a link."
            assert "<strong>bold</strong>" in webmention.content_html

    def test_processor_logging(self, processor, caplog):
        """Test that processor logs appropriate messages."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        html_content = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            import logging

            with caplog.at_level(logging.INFO):
                processor.process_webmention(source_url, target_url)

            assert "Processing webmention" in caplog.text
            assert "Successfully processed webmention" in caplog.text
