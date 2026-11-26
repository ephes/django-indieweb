"""Synthetic overlapping outgoing requests must preserve newer state."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import timedelta
from itertools import permutations
from threading import Barrier, Event
from unittest.mock import patch

import httpx
import pytest
from django.db import close_old_connections, connection, connections, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from indieweb.models import WebmentionOutboundTarget, WebSubSubscription
from indieweb.senders import OUTBOUND_FAILURE_ATTEMPTS_LIMIT, WebmentionSender
from indieweb.websub import confirm_websub_verification, request_websub_subscription


@pytest.mark.django_db(transaction=True)
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("original_mode", "retry_mode", "initial_state", "pending_state", "verified_state"),
    [
        ("unsubscribe", "unsubscribe", "active", "pending_unsubscribe", "unsubscribed"),
        ("unsubscribe", "subscribe", "active", "pending_unsubscribe", "unsubscribed"),
        ("subscribe", "unsubscribe", "pending_subscribe", "pending_subscribe", "active"),
        ("subscribe", "subscribe", "active", "active", "active"),
    ],
)
def test_failed_subscription_retry_restores_prior_verification(
    client, original_mode, retry_mode, initial_state, pending_state, verified_state
):
    original_secret = "original-synthetic-secret"
    row = WebSubSubscription.objects.create(
        hub_url="https://hub.example/",
        topic_url="https://topic.example/",
        state=initial_state,
        confirmed_lease_seconds=3600 if initial_state == "active" else None,
        lease_expires_at=timezone.now() + timedelta(hours=1) if initial_state == "active" else None,
    )

    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(202))) as hub:
        original = request_websub_subscription(
            row.topic_url,
            row.hub_url,
            mode=original_mode,
            lease_seconds=3600,
            secret=original_secret if original_mode == "subscribe" else None,
            callback_base_url="https://callback.example/",
            client=hub,
        )
    assert original.success
    assert original.subscription.state == pending_state
    assert original.subscription.pending_mode == original_mode

    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as hub:
        retry = request_websub_subscription(
            row.topic_url,
            row.hub_url,
            mode=retry_mode,
            lease_seconds=7200,
            secret="retry-synthetic-secret" if retry_mode == "subscribe" else None,
            callback_base_url="https://callback.example/",
            client=hub,
        )
    assert not retry.success
    assert retry.subscription.state == pending_state
    assert retry.subscription.pending_mode == original_mode
    assert retry.subscription.requested_lease_seconds == 3600
    assert retry.subscription.confirmed_lease_seconds == original.subscription.confirmed_lease_seconds
    assert retry.subscription.lease_expires_at == original.subscription.lease_expires_at
    assert retry.subscription.request_generation != original.subscription.request_generation
    assert retry.subscription.last_request_mode == retry_mode
    assert retry.subscription.last_request_status_code == 503

    response = client.get(
        reverse("indieweb:websub-callback", args=[original.subscription.callback_token]),
        {"hub.mode": original_mode, "hub.topic": row.topic_url, "hub.challenge": "original-challenge"},
    )
    assert response.status_code == 200
    assert response.content == b"original-challenge"
    row.refresh_from_db()
    assert row.state == verified_state
    assert row.pending_mode == ""
    if original_mode == "subscribe":
        assert row.get_secret() == original_secret
        assert row.confirmed_lease_seconds == 3600


def _accepted_subscribe(row, secret):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(202))) as hub:
        result = request_websub_subscription(
            row.topic_url,
            row.hub_url,
            mode="subscribe",
            lease_seconds=3600,
            secret=secret,
            callback_base_url="https://callback.example/",
            client=hub,
        )
    assert result.success
    return result


@pytest.mark.django_db(transaction=True)
def test_failed_retry_does_not_restore_overlapping_in_flight_retry(client):
    row = WebSubSubscription.objects.create(hub_url="https://hub.example/", topic_url="https://topic.example/")
    original = _accepted_subscribe(row, "original-synthetic-secret")

    def newest_retry_fails_first(request):
        with httpx.Client(transport=httpx.MockTransport(lambda inner: httpx.Response(503))) as inner_hub:
            newest = request_websub_subscription(
                row.topic_url,
                row.hub_url,
                mode="subscribe",
                secret="newest-synthetic-secret-x",
                callback_base_url="https://callback.example/",
                client=inner_hub,
            )
        assert not newest.success
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(newest_retry_fails_first)) as hub:
        overlapped = request_websub_subscription(
            row.topic_url,
            row.hub_url,
            mode="subscribe",
            secret="rejected-synthetic-secret",
            callback_base_url="https://callback.example/",
            client=hub,
        )
    assert not overlapped.success
    row.refresh_from_db()
    # The in-flight retry's staged secret must not become verifiable.
    assert row.pending_mode == ""
    assert row.state == WebSubSubscription.STATE_DENIED

    response = client.get(
        reverse("indieweb:websub-callback", args=[original.subscription.callback_token]),
        {"hub.mode": "subscribe", "hub.topic": row.topic_url, "hub.challenge": "original-challenge"},
    )
    assert response.status_code != 200
    row.refresh_from_db()
    assert row.state == WebSubSubscription.STATE_DENIED
    assert row.secret == ""


@pytest.mark.django_db(transaction=True)
def test_failed_retry_keeps_lease_edits_saved_while_in_flight():
    row = WebSubSubscription.objects.create(hub_url="https://hub.example/", topic_url="https://topic.example/")
    _accepted_subscribe(row, "original-synthetic-secret")
    edited_expiry = timezone.now() + timedelta(hours=3)

    def edit_then_fail(request):
        # Mirrors an admin save: lease fields change, the request generation does not.
        WebSubSubscription.objects.filter(pk=row.pk).update(
            requested_lease_seconds=5000,
            confirmed_lease_seconds=1234,
            lease_expires_at=edited_expiry,
        )
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(edit_then_fail)) as hub:
        retry = request_websub_subscription(
            row.topic_url,
            row.hub_url,
            mode="subscribe",
            lease_seconds=7200,
            secret="retry-synthetic-secret-x",
            callback_base_url="https://callback.example/",
            client=hub,
        )
    assert not retry.success
    assert retry.subscription.pending_mode == "subscribe"
    assert retry.subscription.requested_lease_seconds == 5000
    assert retry.subscription.confirmed_lease_seconds == 1234
    assert retry.subscription.lease_expires_at == edited_expiry


@pytest.mark.django_db(transaction=True)
def test_failed_unsubscribe_retry_settles_orphaned_pending_state():
    row = WebSubSubscription.objects.create(
        hub_url="https://hub.example/",
        topic_url="https://topic.example/",
        state=WebSubSubscription.STATE_PENDING_UNSUBSCRIBE,
    )
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as hub:
        retry = request_websub_subscription(
            row.topic_url,
            row.hub_url,
            mode="unsubscribe",
            callback_base_url="https://callback.example/",
            client=hub,
        )
    assert not retry.success
    assert retry.subscription.state == WebSubSubscription.STATE_DENIED
    assert retry.subscription.pending_mode == ""


@pytest.mark.django_db(transaction=True)
def test_sqlite_overlapping_subscription_preparations(sqlite_wal, monkeypatch):
    row = WebSubSubscription.objects.create(
        hub_url="https://hub.example/",
        topic_url="https://topic.example/",
        state=WebSubSubscription.STATE_ACTIVE,
    )
    first_has_read, second_is_writing = Event(), Event()
    generations = {}
    save = WebSubSubscription.save

    def pause_first_save(subscription, *args, **kwargs):
        lease = subscription.requested_lease_seconds
        if lease == 3600:
            first_has_read.set()
            assert second_is_writing.wait(timeout=10)
        generations[lease] = subscription.request_generation
        return save(subscription, *args, **kwargs)

    def signal_second_write(execute, sql, params, many, context):
        if sql.startswith('UPDATE "indieweb_websubsubscription"'):
            second_is_writing.set()
        return execute(sql, params, many, context)

    def respond(request):
        assert connection.get_autocommit()
        return httpx.Response(202)

    def renew(lease):
        try:
            with httpx.Client(transport=httpx.MockTransport(respond)) as hub:
                return request_websub_subscription(
                    row.topic_url,
                    row.hub_url,
                    lease_seconds=lease,
                    secret="synthetic-renewal-secret",
                    callback_base_url="https://callback.example/",
                    client=hub,
                )
        finally:
            connections.close_all()

    def renew_second():
        with connection.execute_wrapper(signal_second_write):
            return renew(7200)

    monkeypatch.setattr(WebSubSubscription, "save", pause_first_save)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(renew, 3600)
        assert first_has_read.wait(timeout=10)
        second = pool.submit(renew_second)
        assert first.result(timeout=15).success
        assert second.result(timeout=15).success

    row.refresh_from_db()
    assert row.state == WebSubSubscription.STATE_ACTIVE
    assert row.pending_mode == WebSubSubscription.MODE_SUBSCRIBE
    assert row.requested_lease_seconds == 7200
    assert row.request_generation == generations[7200] != generations[3600]


@pytest.mark.django_db(transaction=True, databases=["default", "other"])
@pytest.mark.parametrize("outer_transaction", ["atomic", "manual"])
def test_subscription_request_refuses_open_write_transaction(settings, outer_transaction):
    class SubscriptionRouter:
        def db_for_write(self, model, **hints):
            if model is WebSubSubscription:
                return "other"
            return None

    settings.DATABASE_ROUTERS = [SubscriptionRouter()]
    other = connections["other"]
    row = WebSubSubscription.objects.using("other").create(
        hub_url="https://hub.example/",
        topic_url="https://topic.example/",
        state=WebSubSubscription.STATE_ACTIVE,
    )
    subscriptions = WebSubSubscription.objects.using("other").filter(pk=row.pk)
    original = subscriptions.values().get()
    manually_managed = outer_transaction == "manual"
    if manually_managed:
        other.set_autocommit(False)
    try:
        with (
            nullcontext() if manually_managed else transaction.atomic(using="other"),
            patch("indieweb.websub.httpx.Client") as client_factory,
            patch("indieweb.websub._post_subscription_request", return_value=httpx.Response(202)) as post,
        ):
            with pytest.raises(RuntimeError, match="require autocommit"):
                request_websub_subscription(
                    row.topic_url,
                    row.hub_url,
                    secret="synthetic-renewal-secret",
                    callback_base_url="https://callback.example/",
                )
            assert subscriptions.values().get() == original
            client_factory.assert_not_called()
            post.assert_not_called()
    finally:
        if manually_managed:
            other.rollback()
            other.set_autocommit(True)


@pytest.mark.django_db(transaction=True)
def test_hub_can_verify_subscription_on_independent_connection(concurrent_database):
    topic = "https://topic.example/"
    hub_url = "https://hub.example/"

    def verify():
        try:
            row = WebSubSubscription.objects.get(topic_url=topic, hub_url=hub_url)
            assert row.pending_mode == WebSubSubscription.MODE_SUBSCRIBE
            response = Client().get(
                reverse("indieweb:websub-callback", args=[row.callback_token]),
                {"hub.mode": "subscribe", "hub.topic": topic, "hub.challenge": "challenge", "hub.lease_seconds": 3600},
            )
            assert response.status_code == 200
            assert response.content == b"challenge"
        finally:
            connections.close_all()

    def respond(request):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(verify).result(timeout=10)
        return httpx.Response(202)

    with httpx.Client(transport=httpx.MockTransport(respond)) as hub:
        result = request_websub_subscription(
            topic,
            hub_url,
            secret="synthetic-renewal-secret",
            callback_base_url="https://callback.example/",
            client=hub,
        )
    assert result.success
    assert result.subscription.state == WebSubSubscription.STATE_ACTIVE
    assert result.subscription.pending_mode == ""


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
    monkeypatch.setattr(sender, "discover_endpoint", lambda target, **kwargs: "https://old-endpoint.example/")

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


@pytest.mark.django_db
def test_current_target_completion_preserves_historical_claim(monkeypatch):
    sender = WebmentionSender()
    source = "https://source.example/"
    target = "https://target.example/"
    row = WebmentionOutboundTarget.objects.create(source_url=source, target_url=target)
    start = timezone.now()
    current_start = start + timedelta(seconds=1)
    monkeypatch.setattr(sender, "discover_endpoint", lambda target, **kwargs: "https://endpoint.example/")

    def send(*args, **kwargs):
        row.refresh_from_db()
        claim = row.resend_claim
        expires = row.resend_claim_expires_at
        assert claim is not None and expires > current_start

        with (
            patch.object(sender, "send_webmention", return_value={"success": True, "status_code": 200}),
            patch("indieweb.senders.timezone.now", return_value=current_start),
        ):
            [current] = sender.send_webmentions(source, f'<a href="{target}">target</a>')
        assert current["success"]
        row.refresh_from_db()
        assert (row.resend_claim, row.resend_claim_expires_at) == (claim, expires)
        assert row.last_attempted_at == row.last_seen_in_source_at == current_start
        assert row.last_status_code == 200
        return {"success": True, "status_code": 202}

    monkeypatch.setattr(sender, "send_webmention", send)
    with patch("indieweb.senders.timezone.now", return_value=start):
        [historical] = sender.resend_salmentions(source, "")
    assert historical["success"] and historical["provenance"] == "history"
    row.refresh_from_db()
    assert row.resend_claim is None and row.resend_claim_expires_at is None
    assert row.first_sent_at == start
    assert row.last_sent_at == current_start
    assert row.last_status_code == 200


@pytest.mark.django_db
def test_late_success_prevents_older_failure_from_pruning(monkeypatch, settings):
    settings.INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES = 2
    sender = WebmentionSender()
    started = timezone.now()
    success_at = started + timedelta(seconds=1)
    newest_failure_at = started + timedelta(seconds=2)
    row = _record(success=True, attempt_started_at=started - timedelta(days=2))
    monkeypatch.setattr(sender, "discover_endpoint", lambda target, **kwargs: "https://endpoint.example/")

    def send(*args, **kwargs):
        _record(attempt_started_at=newest_failure_at)
        _record(success=True, attempt_started_at=success_at)
        return {"success": False, "status_code": 410}

    monkeypatch.setattr(sender, "send_webmention", send)
    with patch("indieweb.senders.timezone.now", return_value=started):
        [historical] = sender.resend_salmentions(row.source_url, "")
    assert historical["status_code"] == 410
    assert not historical.get("dropped")
    row.refresh_from_db()
    assert row.last_attempted_at == newest_failure_at
    assert row.last_status_code == 503 and not row.last_success
    assert row.consecutive_failures == 1
    assert row.last_successful_attempt_at == success_at


@pytest.mark.django_db
@pytest.mark.parametrize("order", list(permutations(range(3))))
def test_history_failure_streak_uses_attempt_order(settings, order):
    settings.INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES = 2
    started = timezone.now() - timedelta(days=2)
    attempts = [started + timedelta(seconds=index) for index in range(3)]
    for index in order:
        _record(attempt_started_at=attempts[index], success=index == 1)

    row = WebmentionOutboundTarget.objects.get()
    assert row.last_attempted_at == attempts[2]
    assert row.last_successful_attempt_at == attempts[1]
    assert not row.last_success
    assert row.consecutive_failures == 1
    assert WebmentionSender()._salmention_historical_skip_result(row, dry_run=False) is None
    assert WebmentionOutboundTarget.objects.filter(pk=row.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("attempt_field", ["last_attempted_at", "last_sent_at"])
@pytest.mark.parametrize(
    ("offset", "success", "expected"),
    [(1, False, 4), (-1, True, 3), (1, True, 0)],
)
def test_legacy_failure_streak_settles_at_its_last_known_attempt(attempt_field, offset, success, expected):
    legacy_at = timezone.now() - timedelta(days=2)
    row = _record(attempt_started_at=legacy_at - timedelta(hours=1), success=True)
    WebmentionOutboundTarget.objects.filter(pk=row.pk).update(
        consecutive_failures=3,
        failure_attempts={},
        last_successful_attempt_at=None,
        last_attempted_at=legacy_at if attempt_field == "last_attempted_at" else None,
        last_sent_at=legacy_at,
    )

    _record(attempt_started_at=legacy_at + timedelta(seconds=offset), success=success)
    row.refresh_from_db()
    assert row.consecutive_failures == expected
    assert sum(row.failure_attempts.values()) == expected


@pytest.mark.django_db
def test_history_failure_attempts_stay_bounded_and_keep_the_streak():
    started = timezone.now() - timedelta(days=2)
    failures = OUTBOUND_FAILURE_ATTEMPTS_LIMIT * 3
    for offset in range(failures):
        _record(attempt_started_at=started + timedelta(seconds=offset))

    row = WebmentionOutboundTarget.objects.get()
    assert len(row.failure_attempts) == OUTBOUND_FAILURE_ATTEMPTS_LIMIT
    assert sum(row.failure_attempts.values()) == failures
    assert row.consecutive_failures == failures

    # A late success inside the retained window clears only failures folded at or before it.
    oldest_kept = failures - OUTBOUND_FAILURE_ATTEMPTS_LIMIT
    _record(attempt_started_at=started + timedelta(seconds=oldest_kept), success=True)
    row.refresh_from_db()
    assert row.consecutive_failures == OUTBOUND_FAILURE_ATTEMPTS_LIMIT - 1
    assert len(row.failure_attempts) == OUTBOUND_FAILURE_ATTEMPTS_LIMIT - 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_history_success_discards_only_earlier_failure(concurrent_database):
    started = timezone.now() - timedelta(days=2)
    _record(attempt_started_at=started)
    barrier = Barrier(2)

    def worker(offset, success):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            _record(attempt_started_at=started + timedelta(seconds=offset), success=success)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        failure = pool.submit(worker, 2, False)
        success = pool.submit(worker, 1, True)
        failure.result(timeout=15)
        success.result(timeout=15)

    row = WebmentionOutboundTarget.objects.get()
    assert row.last_attempted_at == started + timedelta(seconds=2)
    assert row.last_successful_attempt_at == started + timedelta(seconds=1)
    assert row.consecutive_failures == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("existing", [False, True])
def test_concurrent_history_failures_count_twice(existing, concurrent_database):
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
        monkeypatch.setattr(sender, "discover_endpoint", lambda target, **kwargs: "https://endpoint.example/")
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
    monkeypatch.setattr(sender, "discover_endpoint", lambda target, **kwargs: discoveries.append(target))
    results = sender.resend_salmentions("https://source.example/", "")
    assert discoveries == []
    assert not WebmentionOutboundTarget.objects.exists()
    assert results[0]["skip_reason"] == "history_changed"
    assert not results[0].get("dropped")


@pytest.mark.django_db
def test_history_write_error_keeps_caller_transaction_usable():
    source = "https://source.example/"
    target = "https://target.example/"
    sender = WebmentionSender()

    def broken_history(**kwargs):
        # A real database error aborts the surrounding PostgreSQL transaction
        # unless the history write runs in its own savepoint.
        with connection.cursor() as cursor:
            cursor.execute("SELECT synthetic_missing_column FROM indieweb_webmentionoutboundtarget")

    with (
        patch.object(sender, "discover_endpoint", return_value="https://endpoint.example/"),
        patch.object(sender, "send_webmention", return_value={"success": True, "status_code": 202}),
        patch.object(sender, "_record_outbound_target", side_effect=broken_history),
        patch("indieweb.senders.logger.warning") as warning,
    ):
        assert connection.in_atomic_block
        (result,) = sender.send_webmentions(source, [target])

    (message,) = (call.args[0] for call in warning.call_args_list)
    assert message.startswith("Failed to record outbound Webmention history: ")
    assert "synthetic_missing_column" not in message and source not in message

    assert result["history_error"] == "Outbound history update failed"
    assert result["success"] is True
    WebmentionOutboundTarget.objects.create(source_url=source, target_url=target)
    assert WebmentionOutboundTarget.objects.filter(source_url=source).count() == 1


@pytest.mark.django_db
def test_claim_release_error_keeps_caller_transaction_usable():
    source = "https://source.example/"
    target = "https://target.example/"
    WebmentionOutboundTarget.objects.create(source_url=source, target_url=target)
    sender = WebmentionSender()

    def broken_query(*args, **kwargs):
        with connection.cursor() as cursor:
            cursor.execute("SELECT synthetic_missing_column FROM indieweb_webmentionoutboundtarget")

    with (
        patch.object(sender, "discover_endpoint", return_value="https://endpoint.example/"),
        patch.object(sender, "send_webmention", return_value={"success": True, "status_code": 202}),
        patch.object(sender, "_record_outbound_target", side_effect=broken_query),
        patch.object(sender, "_release_historical_claim", side_effect=broken_query) as release,
    ):
        assert connection.in_atomic_block
        (result,) = sender.resend_salmentions(source, "")

    release.assert_called_once()
    assert result["history_error"] == "Outbound history update failed"
    assert WebmentionOutboundTarget.objects.filter(source_url=source).count() == 1


@pytest.mark.django_db
def test_failure_drop_error_keeps_receipt_and_caller_transaction_usable(settings):
    settings.INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES = 2
    source = "https://source.example/"
    failing = "https://failing.example/"
    healthy = "https://healthy.example/"
    WebmentionOutboundTarget.objects.create(source_url=source, target_url=failing, consecutive_failures=1)
    WebmentionOutboundTarget.objects.create(source_url=source, target_url=healthy)
    sender = WebmentionSender()

    def broken_drop(row):
        with connection.cursor() as cursor:
            cursor.execute("SELECT synthetic_missing_column FROM indieweb_webmentionoutboundtarget")

    with (
        patch.object(sender, "discover_endpoint", side_effect=lambda url, **kwargs: None if url == failing else url),
        patch.object(sender, "send_webmention", return_value={"success": True, "status_code": 202}),
        patch.object(sender, "_delete_failed_outbound_target", side_effect=broken_drop) as drop,
    ):
        assert connection.in_atomic_block
        first, second = sender.resend_salmentions(source, "")

    drop.assert_called_once()
    assert first["target"] == failing and first["error"] == "No endpoint found"
    assert first["history_error"] == "Outbound history update failed" and "dropped" not in first
    assert second["target"] == healthy and second["success"] is True and "history_error" not in second
    rows = {row.target_url: row for row in WebmentionOutboundTarget.objects.filter(source_url=source)}
    assert rows[failing].consecutive_failures == 2
    assert rows[healthy].last_status_code == 202
