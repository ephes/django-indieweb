from io import StringIO
from unittest.mock import Mock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from indieweb.models import WebmentionOutboundTarget

pytestmark = pytest.mark.django_db


def test_command_with_invalid_url():
    """Test command with invalid source URL."""
    with pytest.raises(CommandError) as exc:
        call_command("send_webmentions", "not-a-url")

    assert "Source URL must start with http:// or https://" in str(exc.value)


@patch("indieweb.management.commands.send_webmentions.WebmentionSender")
def test_command_with_content_provided(mock_sender_class):
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
        "https://example.com/my-post", '<a href="https://target1.com/post">Link</a>', vouch_url=None
    )
    mock_sender.resend_salmentions.assert_not_called()


def test_command_with_invalid_vouch_url():
    """Test command rejects malformed Vouch URLs."""
    with pytest.raises(CommandError) as exc:
        call_command("send_webmentions", "https://example.com/my-post", vouch="not-a-url")

    assert "Vouch URL must be a valid http:// or https:// URL" in str(exc.value)

    with pytest.raises(CommandError) as exc:
        call_command("send_webmentions", "https://example.com/my-post", vouch="http:///")

    assert "Vouch URL must be a valid http:// or https:// URL" in str(exc.value)


@patch("indieweb.management.commands.send_webmentions.WebmentionSender")
def test_command_passes_vouch_url(mock_sender_class):
    """Test command passes the optional Vouch URL to the sender."""
    mock_sender = Mock()
    mock_sender_class.return_value = mock_sender
    mock_sender.extract_urls.return_value = ["https://target.com/post"]
    mock_sender.send_webmentions.return_value = []

    out = StringIO()
    call_command(
        "send_webmentions",
        "https://example.com/my-post",
        content='<a href="https://target.com/post">Link</a>',
        vouch="https://trusted.example/vouch-for-example",
        stdout=out,
    )

    mock_sender.send_webmentions.assert_called_once_with(
        "https://example.com/my-post",
        '<a href="https://target.com/post">Link</a>',
        vouch_url="https://trusted.example/vouch-for-example",
    )


@patch("indieweb.management.commands.send_webmentions.WebmentionSender")
def test_command_fetch_content(mock_sender_class):
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
def test_command_fetch_content_failure(mock_sender_class):
    """Test command when content fetch fails."""
    mock_sender = Mock()
    mock_sender_class.return_value = mock_sender

    mock_sender.fetch_content.return_value = None

    with pytest.raises(CommandError) as exc:
        call_command("send_webmentions", "https://example.com/my-post")

    assert "Failed to fetch content from https://example.com/my-post" in str(exc.value)


@patch("indieweb.management.commands.send_webmentions.WebmentionSender")
def test_command_dry_run(mock_sender_class):
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
    WebmentionOutboundTarget.objects.create(
        source_url="https://example.com/my-post",
        target_url="https://history.example/post",
    )

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
    assert "https://history.example/post" not in output

    # Should not actually send webmentions in dry run
    mock_sender.send_webmentions.assert_not_called()
    mock_sender.resend_salmentions.assert_not_called()


@patch("indieweb.management.commands.send_webmentions.WebmentionSender")
@patch("sys.stdin", StringIO('<a href="https://target.com">Link from stdin</a>'))
def test_command_stdin_input(mock_sender_class):
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
def test_command_no_webmentions_sent(mock_sender_class):
    """Test command when no webmentions are sent."""
    mock_sender = Mock()
    mock_sender_class.return_value = mock_sender

    mock_sender.extract_urls.return_value = []
    mock_sender.send_webmentions.return_value = []

    out = StringIO()
    call_command("send_webmentions", "https://example.com/my-post", content="<p>No links here</p>", stdout=out)

    output = out.getvalue()
    assert "No webmentions were sent (no valid targets found)" in output


@patch("indieweb.management.commands.send_webmentions.WebmentionSender")
def test_salmention_resend_calls_resend_sender_api(mock_sender_class):
    """Test Salmention resend mode calls the sender resend API instead of ordinary send."""
    mock_sender = Mock()
    mock_sender_class.return_value = mock_sender

    html_content = '<a href="https://target.com/post">Link</a>'
    mock_sender.extract_urls.return_value = ["https://target.com/post"]
    mock_sender.resend_salmentions.return_value = [
        {
            "target": "https://target.com/post",
            "endpoint": "https://target.com/webmention",
            "success": True,
            "status_code": 202,
            "provenance": "current",
        }
    ]

    out = StringIO()
    call_command(
        "send_webmentions",
        "https://example.com/my-post",
        content=html_content,
        salmention_resend=True,
        stdout=out,
    )

    mock_sender.resend_salmentions.assert_called_once_with("https://example.com/my-post", html_content, vouch_url=None)
    mock_sender.send_webmentions.assert_not_called()


@patch("indieweb.management.commands.send_webmentions.WebmentionSender")
def test_salmention_resend_passes_vouch_url(mock_sender_class):
    """Test Salmention resend mode validates and passes Vouch through."""
    mock_sender = Mock()
    mock_sender_class.return_value = mock_sender
    mock_sender.extract_urls.return_value = ["https://target.com/post"]
    mock_sender.resend_salmentions.return_value = []

    out = StringIO()
    call_command(
        "send_webmentions",
        "https://example.com/my-post",
        content='<a href="https://target.com/post">Link</a>',
        salmention_resend=True,
        vouch="https://trusted.example/vouch-for-example",
        stdout=out,
    )

    mock_sender.resend_salmentions.assert_called_once_with(
        "https://example.com/my-post",
        '<a href="https://target.com/post">Link</a>',
        vouch_url="https://trusted.example/vouch-for-example",
    )


@patch("indieweb.management.commands.send_webmentions.WebmentionSender")
@patch("sys.stdin", StringIO('<a href="https://target.com">Link from stdin</a>'))
def test_salmention_resend_stdin_input(mock_sender_class):
    """Test Salmention resend mode reads content from stdin."""
    mock_sender = Mock()
    mock_sender_class.return_value = mock_sender
    mock_sender.extract_urls.return_value = ["https://target.com"]
    mock_sender.resend_salmentions.return_value = []

    out = StringIO()
    call_command(
        "send_webmentions",
        "https://example.com/my-post",
        content="-",
        salmention_resend=True,
        stdout=out,
    )

    mock_sender.resend_salmentions.assert_called_once_with(
        "https://example.com/my-post",
        '<a href="https://target.com">Link from stdin</a>',
        vouch_url=None,
    )


@patch("indieweb.management.commands.send_webmentions.WebmentionSender")
def test_salmention_resend_output_includes_provenance_and_no_endpoint(mock_sender_class):
    """Test Salmention resend output labels success, failure, and no-endpoint results."""
    mock_sender = Mock()
    mock_sender_class.return_value = mock_sender
    mock_sender.extract_urls.return_value = [
        "https://current.example/post",
        "https://both.example/post",
        "https://history.example/post",
    ]
    mock_sender.resend_salmentions.return_value = [
        {
            "target": "https://current.example/post",
            "endpoint": "https://current.example/webmention",
            "success": True,
            "status_code": 202,
            "provenance": "current",
        },
        {
            "target": "https://both.example/post",
            "endpoint": "https://both.example/webmention",
            "success": False,
            "status_code": 500,
            "error": "HTTP 500",
            "provenance": "both",
        },
        {
            "target": "https://history.example/post",
            "endpoint": None,
            "success": False,
            "status_code": None,
            "error": "No endpoint found",
            "provenance": "history",
        },
    ]

    out = StringIO()
    call_command(
        "send_webmentions",
        "https://example.com/my-post",
        content='<a href="https://current.example/post">Current</a>',
        salmention_resend=True,
        stdout=out,
    )

    output = out.getvalue()
    assert "Resent 1/3 Salmention webmentions successfully" in output
    assert "✓ [current] https://current.example/post -> https://current.example/webmention (HTTP 202)" in output
    assert "✗ [both] https://both.example/post -> https://both.example/webmention (Error: HTTP 500)" in output
    assert "✗ [history] https://history.example/post (Error: No endpoint found)" in output


@patch("indieweb.management.commands.send_webmentions.WebmentionSender")
def test_salmention_resend_no_results_message(mock_sender_class):
    """Test Salmention resend mode reports an accurate no-target message."""
    mock_sender = Mock()
    mock_sender_class.return_value = mock_sender
    mock_sender.extract_urls.return_value = []
    mock_sender.resend_salmentions.return_value = []

    out = StringIO()
    call_command(
        "send_webmentions",
        "https://example.com/my-post",
        content="<p>No links here</p>",
        salmention_resend=True,
        stdout=out,
    )

    assert "No Salmention resends were sent (no current or historical targets found)" in out.getvalue()


@patch("indieweb.management.commands.send_webmentions.WebmentionSender")
def test_salmention_resend_dry_run_includes_current_history_and_both(mock_sender_class):
    """Test resend dry-run previews exact-source current and historical union targets."""
    mock_sender = Mock()
    mock_sender_class.return_value = mock_sender
    mock_sender.extract_urls.return_value = [
        "https://current.example/post",
        "https://both.example/post",
        "https://example.com/same-domain",
        "/relative",
    ]
    mock_sender.preview_salmention_resend_targets.return_value = [
        {
            "target": "https://current.example/post",
            "endpoint": "https://current.example/post/webmention",
            "success": False,
            "status_code": None,
            "provenance": "current",
            "dry_run": True,
            "error": "",
        },
        {
            "target": "https://history.example/post",
            "endpoint": "https://history.example/post/webmention",
            "success": False,
            "status_code": None,
            "provenance": "history",
            "dry_run": True,
            "error": "",
        },
        {
            "target": "https://both.example/post",
            "endpoint": "https://both.example/post/webmention",
            "success": False,
            "status_code": None,
            "provenance": "both",
            "dry_run": True,
            "error": "",
        },
    ]

    out = StringIO()
    call_command(
        "send_webmentions",
        "https://example.com/my-post",
        content='<a href="https://current.example/post">Current</a>',
        dry_run=True,
        salmention_resend=True,
        stdout=out,
    )

    output = out.getvalue()
    assert "[current] https://current.example/post -> https://current.example/post/webmention" in output
    assert "[history] https://history.example/post -> https://history.example/post/webmention" in output
    assert "[both] https://both.example/post -> https://both.example/post/webmention" in output
    assert "https://other-history.example/post" not in output
    assert "https://example.com/same-domain" not in output
    assert "/relative" not in output
    mock_sender.preview_salmention_resend_targets.assert_called_once_with(
        "https://example.com/my-post",
        '<a href="https://current.example/post">Current</a>',
    )
    mock_sender.discover_endpoint.assert_not_called()
    mock_sender.send_webmentions.assert_not_called()
    mock_sender.resend_salmentions.assert_not_called()


@patch("indieweb.management.commands.send_webmentions.WebmentionSender")
def test_salmention_resend_dry_run_reports_no_endpoint_without_history_write(mock_sender_class):
    """Test resend dry-run shows no-endpoint targets without updating history."""
    mock_sender = Mock()
    mock_sender_class.return_value = mock_sender
    mock_sender.extract_urls.return_value = ["https://current.example/post"]
    mock_sender.preview_salmention_resend_targets.return_value = [
        {
            "target": "https://current.example/post",
            "endpoint": None,
            "success": False,
            "status_code": None,
            "provenance": "current",
            "dry_run": True,
            "error": "No endpoint found",
        },
        {
            "target": "https://history.example/post",
            "endpoint": None,
            "success": False,
            "status_code": None,
            "provenance": "history",
            "dry_run": True,
            "error": "No endpoint found",
        },
    ]
    existing = WebmentionOutboundTarget.objects.create(
        source_url="https://example.com/my-post",
        target_url="https://history.example/post",
        endpoint_url="https://history.example/old-webmention",
    )

    out = StringIO()
    call_command(
        "send_webmentions",
        "https://example.com/my-post",
        content='<a href="https://current.example/post">Current</a>',
        dry_run=True,
        salmention_resend=True,
        stdout=out,
    )

    output = out.getvalue()
    assert "[current] https://current.example/post (no endpoint found)" in output
    assert "[history] https://history.example/post (no endpoint found)" in output
    assert WebmentionOutboundTarget.objects.count() == 1
    existing.refresh_from_db()
    assert existing.endpoint_url == "https://history.example/old-webmention"
    mock_sender.send_webmentions.assert_not_called()
    mock_sender.resend_salmentions.assert_not_called()


@patch("indieweb.management.commands.send_webmentions.WebmentionSender")
def test_salmention_resend_output_reports_policy_skips(mock_sender_class):
    """Test resend output separates sent results from policy skips."""
    mock_sender = Mock()
    mock_sender_class.return_value = mock_sender
    mock_sender.extract_urls.return_value = []
    mock_sender.resend_salmentions.return_value = [
        {
            "target": "https://history.example/post",
            "endpoint": None,
            "success": False,
            "status_code": None,
            "error": "Historical target skipped during resend cooldown",
            "provenance": "history",
            "skipped": True,
            "skip_reason": "cooldown",
        }
    ]

    out = StringIO()
    call_command(
        "send_webmentions",
        "https://example.com/my-post",
        content="<p>No links here</p>",
        salmention_resend=True,
        stdout=out,
    )

    output = out.getvalue()
    assert "Resent 0/0 Salmention webmentions successfully (1 skipped by policy)" in output
    assert (
        "- [history] https://history.example/post (skipped: Historical target skipped during resend cooldown)"
        in output
    )


@patch("indieweb.management.commands.send_webmentions.WebmentionSender")
def test_salmention_resend_dry_run_reports_policy_skips_without_history_write(mock_sender_class):
    """Test dry-run reports policy drops through the preview API without mutating history."""
    mock_sender = Mock()
    mock_sender_class.return_value = mock_sender
    mock_sender.extract_urls.return_value = []
    mock_sender.preview_salmention_resend_targets.return_value = [
        {
            "target": "https://history.example/post",
            "endpoint": None,
            "success": False,
            "status_code": None,
            "error": "Historical target dropped after consecutive failures",
            "provenance": "history",
            "skipped": True,
            "skip_reason": "failure_drop",
            "dropped": True,
            "dry_run": True,
        }
    ]
    existing = WebmentionOutboundTarget.objects.create(
        source_url="https://example.com/my-post",
        target_url="https://history.example/post",
        consecutive_failures=5,
    )

    out = StringIO()
    call_command(
        "send_webmentions",
        "https://example.com/my-post",
        content="<p>No links here</p>",
        dry_run=True,
        salmention_resend=True,
        stdout=out,
    )

    assert (
        "- [history] https://history.example/post (dropped: Historical target dropped after consecutive failures)"
        in out.getvalue()
    )
    existing.refresh_from_db()
    assert existing.consecutive_failures == 5
    mock_sender.send_webmentions.assert_not_called()
    mock_sender.resend_salmentions.assert_not_called()
