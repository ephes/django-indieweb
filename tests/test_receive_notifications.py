"""A committed receive remains successful when an integration receiver fails."""

import logging

import httpx
import pytest

from indieweb.models import Webmention, WebmentionSourceSnapshot
from indieweb.processors import WebmentionProcessor, webmention_received


@pytest.mark.django_db(transaction=True)
def test_postcommit_notification_failure_is_robust_and_redacted(caplog):
    calls = []
    marker = "invented-private-exception-body"

    def first(sender, **kwargs):
        calls.append("first")

    def middle(sender, **kwargs):
        calls.append("middle")
        raise RuntimeError(marker * 1000)

    def last(sender, **kwargs):
        calls.append("last")

    receivers = [first, middle, last]
    for receiver in receivers:
        webmention_received.connect(receiver, weak=False)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(
                '<html><a href="https://target.example/">target</a>'
                '<article class="h-entry"><p class="e-content">synthetic</p></article></html>'
            ),
        )
    )
    try:
        with (
            httpx.Client(transport=transport) as client,
            caplog.at_level(logging.ERROR),
        ):
            row = WebmentionProcessor(client=client).process_webmention(
                "https://source.example/", "https://target.example/"
            )
        assert row.status == "verified"
        assert Webmention.objects.get(pk=row.pk).status == "verified"
        assert WebmentionSourceSnapshot.objects.filter(webmention=row).exists()
        assert calls == ["first", "middle", "last"]
        assert "RuntimeError" in caplog.text
        assert marker not in caplog.text
        assert len(caplog.text) < 1000
        assert all(not r.exc_info and not r.exc_text for r in caplog.records)
    finally:
        for receiver in receivers:
            webmention_received.disconnect(receiver)
