from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from indieweb.websub import WebSubNotificationResult


@patch("indieweb.management.commands.notify_websub.notify_hubs")
def test_notify_websub_command_uses_configured_hubs(mock_notify_hubs):
    mock_notify_hubs.return_value = [
        WebSubNotificationResult(
            hub_url="https://hub.example/",
            topic_url="https://example.com/feed",
            success=True,
            status_code=204,
        )
    ]

    out = StringIO()
    call_command("notify_websub", "https://example.com/feed", stdout=out)

    assert "Notified 1/1 WebSub hubs for https://example.com/feed" in out.getvalue()
    assert "✓ https://hub.example/ (HTTP 204)" in out.getvalue()
    mock_notify_hubs.assert_called_once_with("https://example.com/feed", None, timeout=None)


@patch("indieweb.management.commands.notify_websub.notify_hubs")
def test_notify_websub_command_accepts_repeated_hub_arguments(mock_notify_hubs):
    mock_notify_hubs.return_value = [
        WebSubNotificationResult(
            hub_url="https://hub.example/",
            topic_url="https://example.com/feed",
            success=True,
            status_code=202,
        ),
        WebSubNotificationResult(
            hub_url="https://backup.example/websub",
            topic_url="https://example.com/feed",
            success=False,
            status_code=503,
            error="temporarily unavailable",
        ),
    ]

    out = StringIO()
    with pytest.raises(CommandError, match="failed"):
        call_command(
            "notify_websub",
            "https://example.com/feed",
            hub=["https://hub.example/", "https://backup.example/websub"],
            timeout=2.5,
            stdout=out,
        )

    output = out.getvalue()
    assert "Notified 1/2 WebSub hubs for https://example.com/feed" in output
    assert "✓ https://hub.example/ (HTTP 202)" in output
    assert "✗ https://backup.example/websub (HTTP 503)" in output
    mock_notify_hubs.assert_called_once_with(
        "https://example.com/feed",
        ["https://hub.example/", "https://backup.example/websub"],
        timeout=2.5,
    )


@patch("indieweb.management.commands.notify_websub.notify_hubs")
def test_notify_websub_command_reports_request_errors(mock_notify_hubs):
    mock_notify_hubs.return_value = [
        WebSubNotificationResult(
            hub_url="https://hub.example/",
            topic_url="https://example.com/feed",
            success=False,
            error="connection refused",
        )
    ]

    out = StringIO()
    with pytest.raises(CommandError, match="failed"):
        call_command("notify_websub", "https://example.com/feed", stdout=out)

    assert "✗ https://hub.example/ (connection refused)" in out.getvalue()


@patch("indieweb.management.commands.notify_websub.notify_hubs")
def test_notify_websub_command_rejects_missing_hubs(mock_notify_hubs):
    mock_notify_hubs.return_value = []

    with pytest.raises(CommandError, match="No WebSub hubs configured"):
        call_command("notify_websub", "https://example.com/feed")


@patch("indieweb.management.commands.notify_websub.notify_hubs")
def test_notify_websub_command_converts_validation_errors(mock_notify_hubs):
    mock_notify_hubs.side_effect = ValueError("topic URL must be a valid http:// or https:// URL")

    with pytest.raises(CommandError, match="topic URL must be a valid"):
        call_command("notify_websub", "not-a-url")


@patch("indieweb.management.commands.notify_websub.notify_hubs")
def test_notify_websub_command_shows_request_error_class_in_redact_mode(mock_notify_hubs, settings):
    settings.INDIEWEB_LOG_REDACTION = "redact"
    # notify_hubs records the exception class name only, never exception text.
    error = "WebmentionRedirectError"
    mock_notify_hubs.return_value = [
        WebSubNotificationResult(
            hub_url="https://hub.example/",
            topic_url="https://example.com/feed",
            success=False,
            error=error,
        )
    ]

    out = StringIO()
    with pytest.raises(CommandError, match="failed"):
        call_command("notify_websub", "https://example.com/feed", stdout=out)

    output = out.getvalue()
    assert "hub.example" not in output
    assert "(WebmentionRedirectError)" in output


@patch("indieweb.management.commands.notify_websub.notify_hubs")
def test_notify_websub_command_keeps_http_status_in_redact_mode(mock_notify_hubs, settings):
    settings.INDIEWEB_LOG_REDACTION = "redact"
    mock_notify_hubs.return_value = [
        WebSubNotificationResult(
            hub_url="https://hub.example/",
            topic_url="https://example.com/feed",
            success=False,
            status_code=503,
            error="hub body with https://body-marker.example/",
        )
    ]

    out = StringIO()
    with pytest.raises(CommandError, match="failed"):
        call_command("notify_websub", "https://example.com/feed", stdout=out)

    assert "(HTTP 503)" in out.getvalue()
    assert "body-marker" not in out.getvalue()
