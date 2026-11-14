"""Operator commands report complete batches and reject invalid time windows."""

from contextlib import nullcontext
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import Mock

import httpx
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from indieweb import websub
from indieweb.models import WebmentionOutboundTarget
from indieweb.senders import WebmentionSender

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("resend", [False, True])
@pytest.mark.parametrize("outcomes", [(True, True), (False, True), (False, False), ("skipped", "skipped")])
def test_webmention_command_batch_exit(monkeypatch, resend, outcomes):
    sender = Mock()
    sender.extract_urls.return_value = []
    results = [
        {
            "target": f"https://target{i}.example/post",
            "endpoint": "https://endpoint.example/",
            "success": outcome is True,
            "status_code": 202 if outcome is True else None,
            "error": "policy skip" if outcome == "skipped" else "delivery failed",
            "provenance": "current",
            "skipped": outcome == "skipped",
        }
        for i, outcome in enumerate(outcomes)
    ]
    sender.send_webmentions.return_value = sender.resend_salmentions.return_value = results
    monkeypatch.setattr("indieweb.management.commands.send_webmentions.WebmentionSender", lambda: sender)
    output = StringIO()
    failed = any(outcome is False for outcome in outcomes)
    with pytest.raises(CommandError, match="failed") if failed else nullcontext():
        call_command(
            "send_webmentions",
            "https://source.example/post",
            content="<p>test</p>",
            salmention_resend=resend,
            stdout=output,
        )
    text = output.getvalue()
    assert "successfully" in text
    for result in results:
        assert result["target"] in text


@pytest.mark.parametrize("statuses", [(204, 202), (503, 204), (503, 500)])
@pytest.mark.parametrize("redact", [False, True])
def test_notification_batch_attempts_every_hub_before_exit(monkeypatch, settings, statuses, redact):
    settings.INDIEWEB_LOG_REDACTION = "redact" if redact else "off"
    hubs = ["https://first.example/private", "https://second.example/private"]
    requested = []

    def respond(request):
        requested.append(str(request.url))
        return httpx.Response(statuses[len(requested) - 1])

    real_notify = websub.notify_hubs
    output = StringIO()
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(
            "indieweb.management.commands.notify_websub.notify_hubs",
            lambda topic, hubs, timeout: real_notify(topic, hubs, timeout=timeout, client=client),
        )
        failed = any(status >= 400 for status in statuses)
        with pytest.raises(CommandError, match="failed") if failed else nullcontext():
            call_command("notify_websub", "https://source.example/feed", hub=hubs, stdout=output)
    assert requested == hubs
    text = output.getvalue()
    assert f"Notified {sum(status < 400 for status in statuses)}/2" in text
    for status in statuses:
        assert f"HTTP {status}" in text
    if redact:
        assert "first.example" not in text and "second.example" not in text and "/private" not in text


@pytest.mark.parametrize("hours", [float("nan"), float("inf"), -float("inf"), 1e300, 1e8, -1])
def test_renewal_command_rejects_invalid_window_before_queries(hours, django_assert_num_queries):
    with django_assert_num_queries(0), pytest.raises(CommandError, match="renewal-window-hours"):
        call_command("websub_subscriptions", renewal_window_hours=hours)


@pytest.mark.django_db
@pytest.mark.parametrize("hours", [0, 6])
def test_renewal_command_accepts_ordinary_windows(hours):
    output = StringIO()
    call_command("websub_subscriptions", renewal_window_hours=hours, stdout=output)
    assert "No WebSub subscriptions" in output.getvalue()


@pytest.mark.parametrize("days", [1000000, 10**20])
@pytest.mark.parametrize("dry_run", [False, True])
def test_prune_command_rejects_out_of_range_cutoff(days, dry_run, django_assert_num_queries, monkeypatch):
    monkeypatch.setattr("indieweb.websub.timezone.now", lambda: datetime(2026, 1, 1, tzinfo=UTC))
    with django_assert_num_queries(0), pytest.raises(CommandError, match="retention"):
        call_command("prune_websub_delivery_attempts", days=days, dry_run=dry_run)


@pytest.mark.parametrize("dry_run", [False, True])
def test_prune_api_date_boundary(dry_run, django_assert_num_queries):
    with django_assert_num_queries(0), pytest.raises(ValueError, match="retention"):
        websub.prune_websub_delivery_attempts(retention_days=1, now=datetime.min.replace(tzinfo=UTC), dry_run=dry_run)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "source,same_host",
    [
        ("https://Example.COM/post", ["https://example.com/a", "https://EXAMPLE.com:443/b"]),
        ("https://xn--bcher-kva.example/post", ["https://bücher.example/a", "https://XN--BCHER-KVA.example:443/b"]),
    ],
)
def test_ordinary_preview_matches_live_target_policy(monkeypatch, settings, source, same_host):
    settings.INDIEWEB_WEBMENTION_MAX_TARGETS_PER_SOURCE = 2
    settings.INDIEWEB_WEBMENTION_MAX_TARGETS_PER_HOST = 1
    external = [
        "https://one.example/a",
        "https://ONE.example:443/b",
        "https://two.example/a",
        "https://three.example/a",
    ]
    html = "".join(f'<a href="{url}">link</a>' for url in [*same_host, *external])
    discovered = []
    delivered = []

    def discover(self, target, **kwargs):
        discovered.append(target)
        return "https://endpoint.example/"

    def send(self, source, target, endpoint, **kwargs):
        delivered.append(target)
        return {"success": True, "status_code": 202}

    monkeypatch.setattr(WebmentionSender, "discover_endpoint", discover)
    monkeypatch.setattr(WebmentionSender, "send_webmention", send)
    output = StringIO()
    call_command("send_webmentions", source, content=html, dry_run=True, stdout=output)
    expected = [external[0], external[2]]
    assert discovered == expected
    assert delivered == []
    assert not WebmentionOutboundTarget.objects.exists()
    for target in expected:
        assert target in output.getvalue()
    discovered.clear()
    call_command("send_webmentions", source, content=html, stdout=StringIO())
    assert discovered == delivered == expected


@pytest.mark.parametrize("dry_run", [False, True])
def test_prune_accepts_earliest_representable_cutoff(dry_run):
    result = websub.prune_websub_delivery_attempts(
        retention_days=1, now=datetime(1, 1, 2, tzinfo=UTC), dry_run=dry_run
    )
    assert result.cutoff == datetime.min.replace(tzinfo=UTC)
    assert result.matched == result.deleted == 0


@pytest.mark.parametrize("endpoint", [None, "https://history.example/webmention"])
@pytest.mark.parametrize("previous_failures", [1, 2])
def test_salmention_drop_exit_distinguishes_attempts_from_policy_skips(
    monkeypatch, settings, endpoint, previous_failures
):
    settings.INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES = 2
    WebmentionOutboundTarget.objects.create(
        source_url="https://source.example/post",
        target_url="https://history.example/post",
        consecutive_failures=previous_failures,
    )
    discovered = Mock(return_value=endpoint)
    sent = Mock(return_value={"success": False, "status_code": 503, "error": "HTTP 503"})
    monkeypatch.setattr(WebmentionSender, "discover_endpoint", discovered)
    monkeypatch.setattr(WebmentionSender, "send_webmention", sent)
    output = StringIO()
    attempted = previous_failures == 1
    with pytest.raises(CommandError, match="failed") if attempted else nullcontext():
        call_command(
            "send_webmentions",
            "https://source.example/post",
            content="<p>no current links</p>",
            salmention_resend=True,
            stdout=output,
        )
    assert discovered.call_count == int(attempted)
    assert sent.call_count == int(attempted and endpoint is not None)
    assert not WebmentionOutboundTarget.objects.exists()
    assert "historical target dropped" in output.getvalue().lower()
    assert f"Resent 0/{int(attempted)}" in output.getvalue()
