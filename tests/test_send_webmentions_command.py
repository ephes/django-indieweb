from io import StringIO
from unittest.mock import Mock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


class TestSendWebmentionsCommand(TestCase):
    """Test cases for send_webmentions management command."""

    def test_command_with_invalid_url(self):
        """Test command with invalid source URL."""
        with pytest.raises(CommandError) as exc:
            call_command("send_webmentions", "not-a-url")

        assert "Source URL must start with http:// or https://" in str(exc.value)

    @patch("indieweb.management.commands.send_webmentions.WebmentionSender")
    def test_command_with_content_provided(self, mock_sender_class):
        """Test command when HTML content is provided."""
        mock_sender = Mock()
        mock_sender_class.return_value = mock_sender

        mock_sender.extract_urls.return_value = ["https://target1.com/post", "https://target2.com/post"]
        mock_sender.send_webmentions.return_value = [
            {
                "target": "https://target1.com/post",
                "endpoint": "https://target1.com/webmention",
                "success": True,
                "status_code": 202,
            },
            {
                "target": "https://target2.com/post",
                "endpoint": "https://target2.com/webmention",
                "success": False,
                "error": "Connection refused",
            },
        ]

        out = StringIO()
        call_command(
            "send_webmentions",
            "https://example.com/my-post",
            content='<a href="https://target1.com/post">Link</a>',
            stdout=out,
        )

        output = out.getvalue()
        assert "Found 2 URLs in content" in output
        assert "Sent 1/2 webmentions successfully" in output
        assert "✓ https://target1.com/post" in output
        assert "✗ https://target2.com/post" in output

        mock_sender.send_webmentions.assert_called_once_with(
            "https://example.com/my-post", '<a href="https://target1.com/post">Link</a>'
        )

    @patch("indieweb.management.commands.send_webmentions.WebmentionSender")
    def test_command_fetch_content(self, mock_sender_class):
        """Test command when content needs to be fetched."""
        mock_sender = Mock()
        mock_sender_class.return_value = mock_sender

        mock_sender.fetch_content.return_value = '<a href="https://target.com">Link</a>'
        mock_sender.extract_urls.return_value = ["https://target.com"]
        mock_sender.send_webmentions.return_value = [
            {
                "target": "https://target.com",
                "endpoint": "https://target.com/webmention",
                "success": True,
                "status_code": 200,
            }
        ]

        out = StringIO()
        call_command("send_webmentions", "https://example.com/my-post", stdout=out)

        output = out.getvalue()
        assert "Fetching content from https://example.com/my-post..." in output
        assert "Found 1 URLs in content" in output
        assert "Sent 1/1 webmentions successfully" in output

        mock_sender.fetch_content.assert_called_once_with("https://example.com/my-post")

    @patch("indieweb.management.commands.send_webmentions.WebmentionSender")
    def test_command_fetch_content_failure(self, mock_sender_class):
        """Test command when content fetch fails."""
        mock_sender = Mock()
        mock_sender_class.return_value = mock_sender

        mock_sender.fetch_content.return_value = None

        with pytest.raises(CommandError) as exc:
            call_command("send_webmentions", "https://example.com/my-post")

        assert "Failed to fetch content from https://example.com/my-post" in str(exc.value)

    @patch("indieweb.management.commands.send_webmentions.WebmentionSender")
    def test_command_dry_run(self, mock_sender_class):
        """Test command in dry run mode."""
        mock_sender = Mock()
        mock_sender_class.return_value = mock_sender

        mock_sender.extract_urls.return_value = [
            "https://target.com/post",
            "https://example.com/other-post",  # Same domain
            "/relative-url",  # Relative URL
        ]
        mock_sender.discover_endpoint.side_effect = [
            "https://target.com/webmention",
            None,  # Second call would be for a different URL
        ]

        out = StringIO()
        call_command(
            "send_webmentions",
            "https://example.com/my-post",
            content='<a href="https://target.com/post">Link</a>',
            dry_run=True,
            stdout=out,
        )

        output = out.getvalue()
        assert "DRY RUN MODE" in output
        assert "Found 3 URLs in content" in output
        assert "https://target.com/post -> https://target.com/webmention" in output
        assert "https://example.com/other-post (skipped: same domain)" in output

        # Should not actually send webmentions in dry run
        mock_sender.send_webmentions.assert_not_called()

    @patch("indieweb.management.commands.send_webmentions.WebmentionSender")
    @patch("sys.stdin", StringIO('<a href="https://target.com">Link from stdin</a>'))
    def test_command_stdin_input(self, mock_sender_class):
        """Test command reading content from stdin."""
        mock_sender = Mock()
        mock_sender_class.return_value = mock_sender

        mock_sender.extract_urls.return_value = ["https://target.com"]
        mock_sender.send_webmentions.return_value = []

        out = StringIO()
        call_command("send_webmentions", "https://example.com/my-post", content="-", stdout=out)

        # Verify stdin content was used
        mock_sender.send_webmentions.assert_called_once()
        args = mock_sender.send_webmentions.call_args[0]
        assert args[1] == '<a href="https://target.com">Link from stdin</a>'

    @patch("indieweb.management.commands.send_webmentions.WebmentionSender")
    def test_command_no_webmentions_sent(self, mock_sender_class):
        """Test command when no webmentions are sent."""
        mock_sender = Mock()
        mock_sender_class.return_value = mock_sender

        mock_sender.extract_urls.return_value = []
        mock_sender.send_webmentions.return_value = []

        out = StringIO()
        call_command("send_webmentions", "https://example.com/my-post", content="<p>No links here</p>", stdout=out)

        output = out.getvalue()
        assert "No webmentions were sent (no valid targets found)" in output
