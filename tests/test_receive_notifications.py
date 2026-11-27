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


@pytest.mark.django_db(transaction=True)
def test_snapshot_write_and_logging_failures_preserve_verified_receive(monkeypatch):
    source = "https://source.example/parent"
    target = "https://target.example/post"
    child = "https://source.example/child"
    html = (
        f'<article class="h-entry"><a class="u-in-reply-to" href="{target}">reply</a>'
        f'<article class="h-entry"><a class="u-url" href="{child}">child</a>'
        '<div class="e-content">synthetic child</div></article></article>'
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=html)
    )
    notifications = []
    logged = []

    def receive(sender, webmention, **kwargs):
        notifications.append((webmention.pk, webmention.status))

    class FailingHandler(logging.Handler):
        def emit(self, record):
            logged.append(record.getMessage())
            raise RuntimeError("synthetic logging failure")

    logger = logging.getLogger("indieweb.processors")
    handler = FailingHandler(level=logging.ERROR)
    logger.addHandler(handler)
    webmention_received.connect(receive)
    try:
        with httpx.Client(transport=transport) as client:
            processor = WebmentionProcessor(client=client)
            store_snapshot = processor._store_source_snapshot

            def write_then_fail(**kwargs):
                store_snapshot(**kwargs)
                raise RuntimeError("synthetic snapshot write failure")

            monkeypatch.setattr(processor, "_store_source_snapshot", write_then_fail)
            parent = processor.process_webmention(source, target)
    finally:
        webmention_received.disconnect(receive)
        logger.removeHandler(handler)

    parent.refresh_from_db()
    assert parent.status == "verified"
    assert parent.verified_at is not None
    assert list(parent.nested_responses.values_list("identity", "status")) == [(child, "verified")]
    assert not WebmentionSourceSnapshot.objects.filter(webmention=parent).exists()
    assert logged == [f"Failed to store source snapshot for webmention {parent.pk}"]
    assert notifications == [(parent.pk, "verified")]
