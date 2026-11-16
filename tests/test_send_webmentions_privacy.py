"""All command display paths use synthetic credentials and hostile remote text."""

from io import StringIO
from unittest.mock import Mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from indieweb.log_redaction import redact_url, text_fingerprint
from indieweb.management.commands import send_webmentions as command

SOURCE = "https://user:SOURCE_SECRET@source.example/post?token=QUERY_SECRET#FRAGMENT_SECRET"
TARGET = "https://user:TARGET_SECRET@target.example/\x1b[31mpost;session=PATH_SECRET?token=QUERY_SECRET"
ENDPOINT = "https://user:ENDPOINT_SECRET@endpoint.example/receive?token=QUERY_SECRET"
ERROR = "REMOTE_SECRET\x1b[31m\r\nforged status"


@pytest.fixture(params=["passthrough", "redact"])
def private_sender(request, settings, monkeypatch):
    settings.INDIEWEB_LOG_REDACTION = request.param
    sender = Mock()
    sender.extract_urls.return_value = [TARGET]
    sender.fetch_content.return_value = "<p>synthetic</p>"
    sender.select_target_urls.return_value = [TARGET, TARGET]
    sender.discover_endpoint.side_effect = [ENDPOINT, None]
    monkeypatch.setattr(command, "WebmentionSender", lambda: sender)
    return sender


def assert_private(output):
    for secret in [
        "SOURCE_SECRET",
        "TARGET_SECRET",
        "ENDPOINT_SECRET",
        "QUERY_SECRET",
        "FRAGMENT_SECRET",
        "PATH_SECRET",
        "REMOTE_SECRET",
        "PROVENANCE_SECRET",
    ]:
        assert secret not in output
    assert all(ord(char) >= 32 or char == "\n" for char in output)


@pytest.mark.parametrize("fetch_fails", [False, True])
def test_source_fetch_messages_are_private(private_sender, fetch_fails):
    private_sender.send_webmentions.return_value = []
    if fetch_fails:
        private_sender.fetch_content.return_value = None
    out, err = StringIO(), StringIO()
    try:
        call_command("send_webmentions", SOURCE, stdout=out, stderr=err, no_color=True)
    except CommandError as exc:
        assert fetch_fails
        assert_private(str(exc))
        assert redact_url(SOURCE) in str(exc)
    assert_private(out.getvalue() + err.getvalue())
    assert redact_url(SOURCE) in out.getvalue()


def test_ordinary_dry_run_urls_are_private(private_sender):
    out = StringIO()
    call_command("send_webmentions", SOURCE, content="<p>synthetic</p>", dry_run=True, stdout=out, no_color=True)
    output = out.getvalue()
    assert_private(output)
    assert "Selected 2 targets" in output
    assert f"{redact_url(TARGET)} -> {redact_url(ENDPOINT)}" in output
    assert f"{redact_url(TARGET)} (no endpoint found)" in output


@pytest.mark.parametrize("resend,dry_run", [(False, False), (True, False), (True, True)])
def test_result_rows_are_private(private_sender, resend, dry_run):
    base = {
        "target": TARGET,
        "endpoint": ENDPOINT,
        "provenance": "history",
        "status_code": None,
        "success": False,
        "error": ERROR,
    }
    results = [
        {**base, "success": True, "status_code": 202},
        base,
        {**base, "endpoint": None},
        {**base, "skipped": True, "provenance": "PROVENANCE_SECRET\x1b[31m", "skip_reason": ERROR},
        {**base, "skipped": True, "dropped": True, "attempted": True},
    ]
    private_sender.send_webmentions.return_value = results
    private_sender.resend_salmentions.return_value = results
    private_sender.preview_salmention_resend_targets.return_value = results
    out, err = StringIO(), StringIO()
    try:
        call_command(
            "send_webmentions",
            SOURCE,
            content="<p>synthetic</p>",
            salmention_resend=resend,
            dry_run=dry_run,
            stdout=out,
            stderr=err,
            no_color=True,
        )
    except CommandError as exc:
        assert not dry_run
        assert "deliveries failed" in str(exc)
        assert_private(str(exc))
    output = out.getvalue() + err.getvalue()
    assert_private(output)
    assert redact_url(TARGET) in output
    assert redact_url(ENDPOINT) in output
    if not dry_run:
        assert text_fingerprint(ERROR) in output
        assert ("1/4" if resend else "1/3") in output
        assert "HTTP 202" in output
        if resend:
            assert f"✗ [history] {redact_url(TARGET)} (Error: {text_fingerprint(ERROR)})" in output


@pytest.mark.parametrize("dry_run", [False, True])
def test_salmention_selection_errors_are_private(private_sender, dry_run):
    private_sender.resend_salmentions.side_effect = ValueError(ERROR)
    private_sender.preview_salmention_resend_targets.side_effect = ValueError(ERROR)
    with pytest.raises(CommandError) as exc:
        call_command(
            "send_webmentions",
            SOURCE,
            content="<p>synthetic</p>",
            salmention_resend=True,
            dry_run=dry_run,
            stdout=StringIO(),
            no_color=True,
        )
    assert_private(str(exc.value))
    assert text_fingerprint(ERROR) in str(exc.value)
    assert exc.value.__suppress_context__
