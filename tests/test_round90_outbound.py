"""Bounded source-run work and historical selection."""

from unittest.mock import Mock

import httpx
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from indieweb import senders
from indieweb.models import WebmentionOutboundTarget
from indieweb.senders import WebmentionSender

SOURCE = "https://source.example/"


@pytest.mark.django_db
def test_history_selection_projects_and_stops_at_cap(settings):
    settings.INDIEWEB_WEBMENTION_MAX_TARGETS_PER_SOURCE = 2
    WebmentionOutboundTarget.objects.bulk_create(
        [
            WebmentionOutboundTarget(source_url=SOURCE, target_url=f"https://h{i:04}.example/", last_error="x" * 10000)
            for i in range(500)
        ]
    )
    with CaptureQueriesContext(connection) as queries:
        targets, current, rows, history = WebmentionSender()._salmention_target_context(SOURCE, "")
    assert targets == ["https://h0000.example/", "https://h0001.example/"]
    assert len(rows) == len(history) == 2
    assert all('"last_error"' not in query["sql"] for query in queries)


@pytest.mark.django_db
@pytest.mark.parametrize("preview", [False, True])
def test_history_scan_budget_refuses_before_network(settings, monkeypatch, preview):
    settings.INDIEWEB_SALMENTION_HISTORY_SCAN_LIMIT = 3
    settings.INDIEWEB_WEBMENTION_MAX_TARGETS_PER_SOURCE = 3
    settings.INDIEWEB_WEBMENTION_MAX_TARGETS_PER_HOST = 1
    WebmentionOutboundTarget.objects.bulk_create(
        [WebmentionOutboundTarget(source_url=SOURCE, target_url=f"https://same.example/{i}") for i in range(10)]
    )
    sender = WebmentionSender()
    discovery = Mock()
    monkeypatch.setattr(sender, "discover_endpoint", discovery)
    operation = sender.preview_salmention_resend_targets if preview else sender.resend_salmentions
    with pytest.raises(ValueError, match="history scan budget"):
        operation(SOURCE, "")
    discovery.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("resend", [False, True])
def test_source_deadline_does_not_record_unattempted_targets(settings, monkeypatch, resend):
    settings.INDIEWEB_WEBMENTION_SOURCE_TOTAL_TIMEOUT_SECONDS = 5
    clock = [100.0]
    monkeypatch.setattr(senders.time, "monotonic", lambda: clock[0])
    sender = WebmentionSender()
    calls = []

    def discovery(target, **kwargs):
        calls.append(target)
        clock[0] += 3
        return "https://endpoint.example/"

    def send(*args, **kwargs):
        clock[0] += 1
        return {"success": True, "status_code": 202}

    monkeypatch.setattr(sender, "discover_endpoint", discovery)
    monkeypatch.setattr(sender, "send_webmention", send)
    targets = [f"https://t{i}.example/" for i in range(3)]
    html = "".join(f'<a href="{target}">link</a>' for target in targets)
    operation = sender.resend_salmentions if resend else sender.send_webmentions
    results = operation(SOURCE, html)
    assert results[0]["success"]
    assert all(result.get("unattempted") and result["error"] == "Source deadline exceeded" for result in results[1:])
    assert calls == targets[:2]
    assert list(WebmentionOutboundTarget.objects.values_list("target_url", flat=True)) == targets[:1]


def test_remaining_source_budget_reaches_transport(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(senders.time, "monotonic", lambda: clock[0])
    budgets = []

    def transport(client, method, url, **kwargs):
        budgets.append(kwargs["total_timeout"])
        clock[0] += 1
        return senders.RedirectedResponse(httpx.Response(200, request=httpx.Request(method, url)), url)

    monkeypatch.setattr(senders, "request_with_webmention_redirects", transport)
    monkeypatch.setattr(senders, "stream_with_safe_redirects", transport)
    with httpx.Client() as client:
        WebmentionSender().discover_endpoint("https://target.example/", client=client, deadline=102.5)
        WebmentionSender().send_webmention(
            SOURCE, "https://target.example/", "https://endpoint.example/", client=client, deadline=102.5
        )
    assert budgets == [2.5, 1.5, 0.5]


@pytest.mark.django_db(transaction=True)
def test_parallel_historical_resends_reserve_before_http(monkeypatch, concurrent_database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event

    from django.db import close_old_connections

    WebmentionOutboundTarget.objects.create(source_url=SOURCE, target_url="https://history.example/")
    barrier, entered, release = Barrier(2), Event(), Event()
    sends = []
    original = WebmentionSender._salmention_target_context

    def select(self, *args):
        result = original(self, *args)
        barrier.wait(timeout=10)
        return result

    def discover(self, target, **kwargs):
        entered.set()
        assert release.wait(10)
        return "https://endpoint.example/"

    def send(self, *args, **kwargs):
        sends.append(args)
        return {"success": True, "status_code": 202}

    monkeypatch.setattr(WebmentionSender, "_salmention_target_context", select)
    monkeypatch.setattr(WebmentionSender, "discover_endpoint", discover)
    monkeypatch.setattr(WebmentionSender, "send_webmention", send)

    def worker():
        close_old_connections()
        try:
            return WebmentionSender().resend_salmentions(SOURCE, "")
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        assert entered.wait(10)
        # The winning HTTP owner stays blocked until the other worker has skipped.
        from concurrent.futures import FIRST_COMPLETED, wait

        try:
            done, _ = wait(futures, timeout=3, return_when=FIRST_COMPLETED)
            assert len(done) == 1
            assert next(iter(done)).result()[0]["skip_reason"] in {"claimed", "history_changed"}
        finally:
            release.set()
        results = [future.result() for future in futures]
    assert len(sends) == 1
    assert sum(bool(result[0]["success"]) for result in results) == 1


@pytest.mark.django_db
def test_expired_claim_recovery_fences_old_completion():
    from datetime import timedelta

    from django.utils import timezone

    row = WebmentionOutboundTarget.objects.create(source_url=SOURCE, target_url="https://history.example/")
    sender = WebmentionSender()
    old, skipped = sender._claim_historical_target(row, deadline=senders.time.monotonic() + 5)
    assert skipped is None and old is not None
    WebmentionOutboundTarget.objects.filter(pk=row.pk).update(
        resend_claim_expires_at=timezone.now() - timedelta(seconds=1)
    )
    new, skipped = sender._claim_historical_target(row, deadline=senders.time.monotonic() + 5)
    assert skipped is None and new != old
    result = sender._record_outbound_target(
        source_url=SOURCE,
        target_url=row.target_url,
        endpoint=None,
        result={"success": False},
        vouch_url=None,
        seen_in_source=False,
        sent=False,
        claim=old,
    )
    assert result is None
    row.refresh_from_db()
    assert row.resend_claim == new and row.consecutive_failures == 0
    result = sender._record_outbound_target(
        source_url=SOURCE,
        target_url=row.target_url,
        endpoint="https://endpoint.example/",
        result={"success": True},
        vouch_url=None,
        seen_in_source=False,
        sent=True,
        claim=new,
    )
    assert result is not None
    assert result.last_success and result.resend_claim is None
