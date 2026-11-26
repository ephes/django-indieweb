from io import StringIO
from unittest.mock import ANY, Mock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from indieweb import senders
from indieweb.models import WebmentionOutboundTarget

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("salmention_resend", [False, True])
def test_command_parses_source_once_for_count_and_selection(dry_run, salmention_resend, settings):
    settings.INDIEWEB_WEBMENTION_MAX_TARGETS_PER_HOST = 1
    source = "https://source.example/post"
    current = "https://current.example/post"
    both = "https://both.example/post"
    history = "https://history.example/post"
    WebmentionOutboundTarget.objects.bulk_create(
        [WebmentionOutboundTarget(source_url=source, target_url=url) for url in (both, history)]
    )
    links = [current, "/relative", "https://source.example/other", both, "https://current.example/other", current]
    content = "".join(f'<a href="{url}">Link</a>' for url in links)
    out = StringIO()
    with (
        patch.object(senders, "BeautifulSoup", wraps=senders.BeautifulSoup) as parse,
        patch.object(
            senders.WebmentionSender, "discover_endpoint", side_effect=lambda url, **kwargs: url + "/wm"
        ) as discover,
        patch.object(
            senders.WebmentionSender, "send_webmention", return_value={"success": True, "status_code": 202}
        ) as send,
    ):
        call_command(
            "send_webmentions",
            source,
            content=content,
            dry_run=dry_run,
            salmention_resend=salmention_resend,
            stdout=out,
        )

    expected = [current, both, history] if salmention_resend else [current, both]
    assert [call.args[0] for call in discover.call_args_list] == expected
    assert [call.args[1] for call in send.call_args_list] == ([] if dry_run else expected)
    assert "Found 5 URLs in content" in out.getvalue()
    parse.assert_called_once_with(content, "html.parser")


@pytest.mark.parametrize("salmention_resend", [False, True])
def test_command_reports_history_recording_errors_separately(salmention_resend):
    source = "https://source.example/post"
    target = "https://target.example/post"
    method = "resend_salmentions" if salmention_resend else "send_webmentions"
    receipt = {
        "target": target,
        "endpoint": "https://target.example/webmention",
        "provenance": "current",
        "success": True,
        "status_code": 202,
        "history_error": "Outbound history update failed",
    }
    out = StringIO()
    with (
        patch.object(senders.WebmentionSender, method, return_value=[receipt]),
        pytest.raises(CommandError, match="Could not update outbound history for 1 target"),
    ):
        call_command(
            "send_webmentions",
            source,
            content=f'<a href="{target}">Link</a>',
            salmention_resend=salmention_resend,
            stdout=out,
        )

    assert "1/1" in out.getvalue()
    assert "HTTP 202" in out.getvalue()
    assert "outbound history update failed" in out.getvalue()


def test_command_with_invalid_url():
    """Test command with invalid source URL."""
    with pytest.raises(CommandError) as exc:
        call_command("send_webmentions", "not-a-url")

    assert "Source URL must be a valid http:// or https:// URL" in str(exc.value)


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
    with pytest.raises(CommandError, match="failed"):
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
        "https://example.com/my-post", mock_sender.extract_urls.return_value, vouch_url=None, deadline=ANY
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
        ["https://target.com/post"],
        vouch_url="https://trusted.example/vouch-for-example",
        deadline=ANY,
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

    mock_sender.fetch_content.assert_called_once_with("https://example.com/my-post", deadline=ANY)


def test_command_empty_fetch_previews_historical_targets():
    source = "https://source.example/post"
    target = "https://history.example/post"
    endpoint = "https://history.example/webmention"
    WebmentionOutboundTarget.objects.create(source_url=source, target_url=target)
    explicit = StringIO()
    fetched = StringIO()

    with (
        patch.object(senders.WebmentionSender, "fetch_content", return_value="") as fetch,
        patch.object(senders.WebmentionSender, "discover_endpoint", return_value=endpoint) as discover,
    ):
        call_command("send_webmentions", source, content="", dry_run=True, salmention_resend=True, stdout=explicit)
        call_command("send_webmentions", source, dry_run=True, salmention_resend=True, stdout=fetched)

    fetch.assert_called_once_with(source, deadline=ANY)
    assert [call.args[0] for call in discover.call_args_list] == [target, target]
    assert f"[history] {target} -> {endpoint}" in explicit.getvalue()
    assert fetched.getvalue().replace(f"Fetching content from {source}...\n", "") == explicit.getvalue()


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
    mock_sender.select_target_urls.return_value = ["https://target.com/post"]
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
    assert "Selected 1 targets after URL, same-host and fanout policy exclusions" in output
    mock_sender.select_target_urls.assert_called_once_with(
        "https://example.com/my-post", mock_sender.extract_urls.return_value
    )
    assert "https://history.example/post" not in output

    # Should not actually send webmentions in dry run
    mock_sender.send_webmentions.assert_not_called()
    mock_sender.resend_salmentions.assert_not_called()


@pytest.mark.parametrize("deadline_exceeded", [False, True])
def test_command_dry_run_checks_deadline_after_final_discovery(settings, monkeypatch, deadline_exceeded):
    settings.INDIEWEB_WEBMENTION_SOURCE_TOTAL_TIMEOUT_SECONDS = 1
    now = 100.0
    first = "https://first.example/post"
    final = "https://final.example/post"
    endpoint = "https://first.example/webmention"
    out = StringIO()

    def discover(url, *, deadline):
        nonlocal now
        assert deadline == 101.0
        if url == first:
            return endpoint
        assert url == final
        if deadline_exceeded:
            now = deadline + 1.0
        return None

    monkeypatch.setattr(senders.time, "monotonic", lambda: now)
    with patch.object(senders.WebmentionSender, "discover_endpoint", side_effect=discover) as mock_discover:
        options = {
            "content": f'<a href="{first}">First</a><a href="{final}">Final</a>',
            "dry_run": True,
            "stdout": out,
        }
        if deadline_exceeded:
            with pytest.raises(CommandError, match="Source deadline exceeded"):
                call_command("send_webmentions", "https://source.example/post", **options)
        else:
            call_command("send_webmentions", "https://source.example/post", **options)

    assert [call.args[0] for call in mock_discover.call_args_list] == [first, final]
    assert f"{first} -> {endpoint}" in out.getvalue()
    assert (f"{final} (no endpoint found)" in out.getvalue()) is not deadline_exceeded


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
    mock_sender.extract_urls.assert_called_once_with('<a href="https://target.com">Link from stdin</a>')
    mock_sender.send_webmentions.assert_called_once_with(
        "https://example.com/my-post", ["https://target.com"], vouch_url=None, deadline=ANY
    )


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


def test_command_reports_deadline_when_selection_returns_no_targets(settings, monkeypatch):
    settings.INDIEWEB_WEBMENTION_SOURCE_TOTAL_TIMEOUT_SECONDS = 1
    now = 100.0

    def select_no_targets(sender, source_url, html_content):
        nonlocal now
        now += 2.0
        return []

    monkeypatch.setattr(senders.time, "monotonic", lambda: now)
    monkeypatch.setattr(senders.WebmentionSender, "select_target_urls", select_no_targets)
    out = StringIO()
    with (
        patch.object(senders.WebmentionSender, "discover_endpoint") as discover,
        patch.object(senders.WebmentionSender, "send_webmention") as send,
        pytest.raises(CommandError, match="1 Webmention deliveries failed"),
    ):
        call_command("send_webmentions", "https://source.example/post", content="<p>No links</p>", stdout=out)

    assert "Source deadline exceeded" in out.getvalue()
    assert "no valid targets found" not in out.getvalue()
    discover.assert_not_called()
    send.assert_not_called()
    assert not WebmentionOutboundTarget.objects.exists()


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

    mock_sender.resend_salmentions.assert_called_once_with(
        "https://example.com/my-post", ["https://target.com/post"], vouch_url=None, deadline=ANY
    )
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
        ["https://target.com/post"],
        vouch_url="https://trusted.example/vouch-for-example",
        deadline=ANY,
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

    mock_sender.extract_urls.assert_called_once_with('<a href="https://target.com">Link from stdin</a>')
    mock_sender.resend_salmentions.assert_called_once_with(
        "https://example.com/my-post", ["https://target.com"], vouch_url=None, deadline=ANY
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
    with pytest.raises(CommandError, match="failed"):
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
        "https://example.com/my-post", mock_sender.extract_urls.return_value, deadline=ANY
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
