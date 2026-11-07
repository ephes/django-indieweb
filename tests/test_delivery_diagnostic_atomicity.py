"""Atomic delivery diagnostics on the subscription's routed write database."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event, get_ident
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connections
from django.db.models import QuerySet
from django.utils import timezone

from indieweb.models import WebSubDeliveryAttempt, WebSubSubscription
from indieweb.websub import record_websub_delivery


class DiagnosticRouter:
    def db_for_write(self, model, **hints):
        # Intentionally conflicting attempt routing: the diagnostic pair must
        # follow the subscription's write alias explicitly.
        return "other" if model is WebSubSubscription else "default"


@pytest.mark.django_db(databases=["default", "other"])
@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("status", [204, 500])
@pytest.mark.parametrize("fail", [False, True])
def test_delivery_diagnostics_are_atomic(settings, routed, status, fail):
    alias = "other" if routed else "default"
    settings.DATABASE_ROUTERS = [DiagnosticRouter()] if routed else []
    subscription = WebSubSubscription.objects.using(alias).create(
        hub_url="https://hub.example/", topic_url="https://topic.example/"
    )
    before = WebSubSubscription.objects.using(alias).values().get(pk=subscription.pk)
    original = QuerySet.create
    calls = []

    def create_attempt(self, **kwargs):
        if self.model is WebSubDeliveryAttempt:
            calls.append((self.db, connections[self.db].in_atomic_block))
        result = original(self, **kwargs)
        if fail and self.model is WebSubDeliveryAttempt:
            raise RuntimeError("synthetic diagnostic failure after insert")
        return result

    def record():
        record_websub_delivery(
            subscription,
            b"synthetic payload",
            content_type="text/plain" * 30,
            status_code=status,
            error="E" * 700,
            signature_algorithm="sha256",
        )

    with patch.object(QuerySet, "create", create_attempt):
        if fail:
            with pytest.raises(RuntimeError, match="after insert"):
                record()
        else:
            record()
    assert calls == [(alias, True)]
    if fail:
        assert WebSubSubscription.objects.using(alias).values().get(pk=subscription.pk) == before
        assert not WebSubDeliveryAttempt.objects.using(alias).exists()
    else:
        subscription.refresh_from_db(using=alias)
        attempt = WebSubDeliveryAttempt.objects.using(alias).get()
        assert subscription.last_delivery_status_code == attempt.status_code == status
        assert subscription.last_delivery_digest == attempt.digest
        assert subscription.last_delivery_at == attempt.received_at
        assert subscription.last_delivery_content_type == attempt.content_type == ("text/plain" * 30)[:200]
        assert subscription.last_delivery_error == attempt.error == "E" * 500
        assert subscription.last_delivery_size == attempt.size == len(b"synthetic payload")
        if status == 204:
            assert subscription.last_accepted_delivery_at == attempt.received_at
            assert subscription.last_accepted_delivery_digest == attempt.digest
        else:
            assert subscription.last_accepted_delivery_at is None
    if routed:
        assert not WebSubSubscription.objects.using("default").exists()
        assert not WebSubDeliveryAttempt.objects.using("default").exists()


@pytest.mark.django_db(databases=["default", "other"])
@pytest.mark.parametrize("routed", [False, True])
def test_stale_diagnostics_preserve_rotated_secrets(settings, routed):
    alias = "other" if routed else "default"
    settings.DATABASE_ROUTERS = [DiagnosticRouter()] if routed else []
    settings.SECRET_KEY = "synthetic-old-key"
    settings.SECRET_KEY_FALLBACKS = []
    subscription = WebSubSubscription.objects.using(alias).create(
        hub_url="https://hub.example/",
        topic_url="https://topic.example/",
        secret="synthetic-old-active",
        pending_secret="synthetic-old-pending",
    )
    stale = WebSubSubscription.objects.using(alias).get(pk=subscription.pk)
    settings.SECRET_KEY = "synthetic-new-key"
    settings.SECRET_KEY_FALLBACKS = ["synthetic-old-key"]
    subscription.secret = "synthetic-new-active"
    subscription.pending_secret = "synthetic-new-pending"
    subscription.save(using=alias, update_fields=["secret", "pending_secret"])
    credentials = WebSubSubscription.objects.using(alias).values("secret", "pending_secret").get(pk=subscription.pk)

    record_websub_delivery(stale, b"synthetic payload", content_type="text/plain", status_code=204)

    assert (
        WebSubSubscription.objects.using(alias).values("secret", "pending_secret").get(pk=subscription.pk)
        == credentials
    )
    subscription.refresh_from_db(using=alias)
    assert subscription.get_secret() == "synthetic-new-active"
    assert subscription.get_pending_secret() == "synthetic-new-pending"
    assert WebSubDeliveryAttempt.objects.using(alias).count() == 1


@pytest.mark.django_db(transaction=True, databases=["default", "other"])
@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("older_status,newer_status", [(204, 204), (204, 500), (500, 204), (500, 500)])
def test_older_observation_commits_last(settings, routed, older_status, newer_status):
    alias = "other" if routed else "default"
    settings.DATABASE_ROUTERS = [DiagnosticRouter()] if routed else []
    subscription = WebSubSubscription.objects.using(alias).create(
        hub_url="https://hub.example/", topic_url="https://topic.example/"
    )
    older = timezone.now() - timedelta(seconds=10)
    newer = older + timedelta(seconds=1)
    stamped = Event()
    release = Event()
    caller_thread = get_ident()
    real_now = timezone.now

    def observation_time():
        if get_ident() != caller_thread:
            stamped.set()
            assert release.wait(10), "newer writer did not finish"
            return older
        return real_now()

    def older_writer():
        close_old_connections()
        try:
            stale = WebSubSubscription.objects.using(alias).get(pk=subscription.pk)
            record_websub_delivery(stale, b"older", content_type="text/older", status_code=older_status)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool, patch("indieweb.websub.timezone.now", observation_time):
        future = pool.submit(older_writer)
        try:
            assert stamped.wait(10), "older writer did not stamp its observation"
            with patch("indieweb.websub.timezone.now", return_value=newer):
                record_websub_delivery(subscription, b"newer", content_type="text/newer", status_code=newer_status)
        finally:
            release.set()
        future.result(timeout=10)

    subscription.refresh_from_db(using=alias)
    assert subscription.last_delivery_at == newer
    assert subscription.last_delivery_digest == hashlib.sha256(b"newer").hexdigest()
    assert subscription.last_delivery_content_type == "text/newer"
    assert subscription.last_delivery_status_code == newer_status
    accepted_at = newer if newer_status == 204 else older if older_status == 204 else None
    assert subscription.last_accepted_delivery_at == accepted_at
    if accepted_at is not None:
        body = b"newer" if newer_status == 204 else b"older"
        assert subscription.last_accepted_delivery_digest == hashlib.sha256(body).hexdigest()
    assert set(WebSubDeliveryAttempt.objects.using(alias).values_list("received_at", flat=True)) == {older, newer}
    if routed:
        assert not WebSubDeliveryAttempt.objects.using("default").exists()


@pytest.mark.django_db
def test_equal_observation_keeps_first_summary():
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/", topic_url="https://topic.example/"
    )
    with patch("indieweb.websub.timezone.now", return_value=timezone.now()):
        record_websub_delivery(subscription, b"first", content_type="text/plain", status_code=204)
        record_websub_delivery(subscription, b"second", content_type="text/plain", status_code=204)
    subscription.refresh_from_db()
    assert (
        subscription.last_delivery_digest
        == subscription.last_accepted_delivery_digest
        == hashlib.sha256(b"first").hexdigest()
    )
    assert WebSubDeliveryAttempt.objects.count() == 2
