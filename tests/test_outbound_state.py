"""Synthetic overlapping outgoing requests must preserve newer state."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

import httpx
import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from indieweb.models import WebmentionOutboundTarget, WebSubSubscription
from indieweb.senders import WebmentionSender
from indieweb.websub import confirm_websub_verification, request_websub_subscription


@pytest.mark.django_db
@pytest.mark.parametrize("newer", ["confirmed", "pending"])
@pytest.mark.parametrize("response", ["timeout", "rejected", "accepted"])
def test_old_subscription_result_preserves_new_generation(newer, response):
    topic = "https://topic.example/"
    hub = "https://hub.example/"
    base = "https://callback.example/"
    snapshots = []

    def handler(request):
        row = WebSubSubscription.objects.get(topic_url=topic)
        if newer == "confirmed":
            confirm_websub_verification(
                row, mode="subscribe", topic_url=topic, challenge="challenge", lease_seconds=3600
            )
        else:
            with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(202))) as nested:
                request_websub_subscription(
                    topic, hub, callback_base_url=base, secret="newer-synthetic-secret-20x", client=nested
                )
        snapshots.append(WebSubSubscription.objects.values().get(pk=row.pk))
        if response == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        return httpx.Response(202 if response == "accepted" else 400)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        result = request_websub_subscription(
            topic, hub, callback_base_url=base, secret="older-synthetic-secret-20x", client=c
        )
    stored = WebSubSubscription.objects.get(pk=result.subscription.pk)
    if newer == "pending" or response != "accepted":
        assert WebSubSubscription.objects.values().get(pk=stored.pk) == snapshots[0]
    else:
        assert stored.state == "active"
        assert stored.get_secret() == "older-synthetic-secret-20x"


def _record(*, success=False, **kwargs):
    return WebmentionSender()._record_outbound_target(
        source_url="https://source.example/",
        target_url="https://target.example/",
        endpoint="https://endpoint.example/",
        result={"success": success, "status_code": 200 if success else 503},
        vouch_url=None,
        seen_in_source=True,
        sent=True,
        **kwargs,
    )


@pytest.mark.django_db
def test_stale_history_snapshot_does_not_lose_a_failure():
    row = _record()
    stale = WebmentionOutboundTarget.objects.get(pk=row.pk)
    _record()
    # Emulate a previously fetched history row; the counter must derive from DB state.
    with patch.object(type(WebmentionOutboundTarget.objects), "get_or_create", return_value=(stale, False)):
        _record()
    row.refresh_from_db()
    assert row.consecutive_failures == 3


@pytest.mark.django_db
def test_late_failed_send_preserves_newer_success_and_observation(monkeypatch):
    sender = WebmentionSender()
    old = timezone.now() - timedelta(seconds=10)
    new = timezone.now()
    monkeypatch.setattr(sender, "discover_endpoint", lambda target: "https://old-endpoint.example/")

    def send(*args, **kwargs):
        with patch("indieweb.senders.timezone.now", return_value=new):
            _record(success=True)
        return {"success": False, "status_code": 503}

    monkeypatch.setattr(sender, "send_webmention", send)
    with patch("indieweb.senders.timezone.now", return_value=old):
        sender.send_webmentions("https://source.example/", '<a href="https://target.example/">target</a>')
    row = WebmentionOutboundTarget.objects.get()
    assert row.last_success
    assert row.consecutive_failures == 0
    assert row.last_seen_in_source_at == new
    assert row.endpoint_url == "https://endpoint.example/"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("existing", [False, True])
def test_concurrent_history_failures_count_twice(existing):
    if connection.vendor == "sqlite" and "mode=memory" in str(connection.settings_dict["NAME"]):
        pytest.skip("SQLite shared-cache memory tables do not wait for locks; use DJANGO_INDIEWEB_TEST_SQLITE_PATH")
    if existing:
        _record(success=True)
    barrier = Barrier(2)

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return _record().pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: worker(), range(2)))
    assert ids[0] == ids[1]
    assert WebmentionOutboundTarget.objects.count() == 1
    assert WebmentionOutboundTarget.objects.get().consecutive_failures == 2


@pytest.mark.django_db
@pytest.mark.parametrize("phase", ["before_attempt", "after_attempt"])
def test_failure_drop_cannot_delete_newer_success(monkeypatch, settings, phase):
    settings.INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES = 1
    row = _record()
    sender = WebmentionSender()
    original = sender._delete_failed_outbound_target

    def raced(stale):
        _record(success=True)
        return original(stale)

    monkeypatch.setattr(sender, "_delete_failed_outbound_target", raced)
    if phase == "before_attempt":
        result = sender._salmention_historical_skip_result(row, dry_run=False)
        assert result["skip_reason"] == "history_changed"
        assert not result.get("dropped")
    else:
        # Let the historical row enter delivery, then reach the failure threshold.
        WebmentionOutboundTarget.objects.filter(pk=row.pk).update(
            consecutive_failures=0, last_attempted_at=timezone.now() - timedelta(days=2)
        )
        monkeypatch.setattr(sender, "discover_endpoint", lambda target: "https://endpoint.example/")
        monkeypatch.setattr(sender, "send_webmention", lambda *args, **kwargs: {"success": False, "status_code": 503})
        results = sender.resend_salmentions("https://source.example/", "")
        assert len(results) == 1
        assert not results[0].get("dropped")
    row.refresh_from_db()
    assert row.last_success
    assert row.consecutive_failures == 0


@pytest.mark.django_db
def test_migration_seeds_only_successful_history():
    import importlib
    from types import SimpleNamespace

    from django.apps import apps

    success = _record(success=True)
    WebmentionOutboundTarget.objects.filter(pk=success.pk).update(last_successful_attempt_at=None)
    failure = WebmentionOutboundTarget.objects.create(
        source_url="https://source.example/",
        target_url="https://failed.example/",
        last_attempted_at=timezone.now(),
        last_success=False,
    )
    migration = importlib.import_module(
        "indieweb.migrations.0031_webmentionoutboundtarget_last_successful_attempt_at_and_more"
    )
    migration.seed_success_watermark(apps, SimpleNamespace(connection=connection))
    success.refresh_from_db()
    failure.refresh_from_db()
    assert success.last_successful_attempt_at == success.last_attempted_at
    assert failure.last_successful_attempt_at is None


@pytest.mark.django_db
def test_concurrent_failure_drop_never_recreates_history(monkeypatch, settings):
    settings.INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES = 1
    _record()
    sender = WebmentionSender()
    original = sender._delete_failed_outbound_target
    discoveries = []

    def raced(stale):
        WebmentionOutboundTarget.objects.filter(pk=stale.pk).delete()
        return original(stale)

    monkeypatch.setattr(sender, "_delete_failed_outbound_target", raced)
    monkeypatch.setattr(sender, "discover_endpoint", lambda target: discoveries.append(target))
    results = sender.resend_salmentions("https://source.example/", "")
    assert discoveries == []
    assert not WebmentionOutboundTarget.objects.exists()
    assert results[0]["skip_reason"] == "history_changed"
    assert not results[0].get("dropped")
