"""Controlled integer settings and privacy at the receive error boundary."""

from datetime import timedelta
from unittest.mock import Mock

import httpx
import pytest

from indieweb import processors, senders
from indieweb.log_redaction import redact_url
from indieweb.models import Webmention
from indieweb.processors import WebmentionProcessor

COUNT_SETTINGS = [
    (processors._webmention_fetch_max_bytes, "INDIEWEB_WEBMENTION_FETCH_MAX_BYTES", 1024 * 1024, True),
    (processors._webmention_max_stored_bytes, "INDIEWEB_WEBMENTION_MAX_STORED_BYTES", 2 * 1024 * 1024, False),
    (senders._sender_fetch_max_bytes, "INDIEWEB_WEBMENTION_FETCH_MAX_BYTES", 1024 * 1024, True),
    (senders._sender_head_max_bytes, "INDIEWEB_WEBMENTION_HEAD_MAX_BYTES", 64 * 1024, True),
    (senders._sender_response_max_bytes, "INDIEWEB_WEBMENTION_RESPONSE_MAX_BYTES", 1024 * 1024, True),
    (senders._webmention_max_targets_per_source, "INDIEWEB_WEBMENTION_MAX_TARGETS_PER_SOURCE", 50, True),
    (senders._webmention_max_targets_per_host, "INDIEWEB_WEBMENTION_MAX_TARGETS_PER_HOST", 5, True),
    (senders._salmention_max_consecutive_failures, "INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES", 5, False),
]


@pytest.mark.parametrize("getter,name,default,optional", COUNT_SETTINGS)
@pytest.mark.parametrize("value", [float("inf"), -float("inf"), float("nan"), True, False, 1.5, 0, -1, "invalid"])
def test_invalid_integer_settings_fall_back(settings, getter, name, default, optional, value):
    setattr(settings, name, value)
    assert getter() == default


@pytest.mark.parametrize("getter,name,default,optional", COUNT_SETTINGS)
@pytest.mark.parametrize("value", [7, 7.0, "7", None])
def test_integral_settings_and_explicit_none(settings, getter, name, default, optional, value):
    setattr(settings, name, value)
    assert getter() == (None if value is None and optional else default if value is None else 7)


@pytest.mark.parametrize(
    "getter,name,default,optional",
    [
        (senders._salmention_resend_cooldown, "INDIEWEB_SALMENTION_RESEND_COOLDOWN_SECONDS", 86400, False),
        (senders._salmention_success_cutoff, "INDIEWEB_SALMENTION_SUCCESS_CUTOFF_SECONDS", 30 * 86400, True),
    ],
)
@pytest.mark.parametrize("value", [float("inf"), True, 1.5, 10**100, 86400 * 10**9, "7", None])
def test_timer_settings_are_representable(settings, getter, name, default, optional, value):
    setattr(settings, name, value)
    expected = None if value is None and optional else timedelta(seconds=7 if value == "7" else default)
    assert getter() == expected


@pytest.mark.django_db
@pytest.mark.parametrize("failure", ["transport", "spam_checker"])
@pytest.mark.parametrize("mode", ["redact", "passthrough"])
def test_collection_exception_logs_only_safe_category(monkeypatch, caplog, settings, failure, mode):
    settings.INDIEWEB_LOG_REDACTION = mode
    source = "https://source.example/reply?private_query=synthetic-query#synthetic-fragment"
    target = "https://target.example/post"
    private_detail = "invented-content synthetic-password https://user:synthetic-password@source.example/private"

    def handler(request):
        if failure == "transport":
            raise httpx.ReadError(private_detail)
        return httpx.Response(200, headers={"content-type": "text/html"}, text=f'<a href="{target}">target</a>')

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        processor = WebmentionProcessor(client=client)
        checker = Mock()
        checker.check.side_effect = RuntimeError(private_detail)
        monkeypatch.setattr(processor, "_get_spam_checker", lambda: checker if failure == "spam_checker" else None)
        result = processor.process_webmention(source, target)
    assert result.status == "failed"
    assert Webmention.objects.get(pk=result.pk).status == "failed"
    if failure == "spam_checker":
        checker.check.assert_called_once()
    assert redact_url(source) in caplog.text
    if mode == "redact":
        assert "synthetic-query" not in caplog.text
        assert "synthetic-fragment" not in caplog.text
    assert ("transport error" if failure == "transport" else "unexpected error") in caplog.text
    for private in (
        "synthetic-password",
        "invented-content",
        "RuntimeError",
        "ReadError",
    ):
        assert private not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
