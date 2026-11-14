"""Replay acceptance failures and retention use the authoritative database."""

import sqlite3
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import IntegrityError, connections, transaction
from django.db.models import QuerySet
from django.utils import timezone

from indieweb.models import WebSubAcceptedDelivery, WebSubSubscription
from indieweb.websub import accept_websub_delivery
from tests.test_websub_database_boundaries import ReplayRouter


@pytest.fixture
def routed_subscription(settings):
    settings.DATABASE_ROUTERS = [ReplayRouter()]
    settings.INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS = 60
    settings.INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX = 2
    return WebSubSubscription.objects.using("other").create(
        hub_url="https://hub.example/", topic_url="https://topic.example/"
    )


@pytest.mark.django_db(databases=["default", "other"], transaction=True)
@pytest.mark.parametrize("failure", ["synthetic", "not-null"])
def test_unrelated_integrity_failure_is_not_a_replay(routed_subscription, failure):
    original = QuerySet.create

    def fail_insert(queryset, **kwargs):
        if queryset.model is WebSubAcceptedDelivery:
            if failure == "synthetic":
                raise IntegrityError("synthetic unrelated constraint")
            kwargs["body_digest"] = None
        return original(queryset, **kwargs)

    expired = WebSubAcceptedDelivery.objects.using("other").create(
        subscription=routed_subscription,
        body_digest="e" * 64,
        accepted_at=timezone.now() - timedelta(seconds=120),
    )
    with transaction.atomic(using="other"):
        with patch.object(QuerySet, "create", fail_insert), pytest.raises(IntegrityError):
            accept_websub_delivery(routed_subscription, "a" * 64)
        assert WebSubAcceptedDelivery.objects.using("other").filter(pk=expired.pk).exists()
        assert accept_websub_delivery(routed_subscription, "b" * 64)
        assert not accept_websub_delivery(routed_subscription, "b" * 64)
    assert WebSubAcceptedDelivery.objects.using("default").count() == 0


@pytest.mark.django_db(databases=["default", "other"], transaction=True)
def test_missing_subscription_is_a_storage_failure(routed_subscription):
    missing = WebSubSubscription(pk=routed_subscription.pk + 1000)
    with pytest.raises(IntegrityError):
        accept_websub_delivery(missing, "a" * 64)
    assert WebSubAcceptedDelivery.objects.using("other").count() == 0


@pytest.mark.django_db(databases=["default", "other"], transaction=True)
def test_large_retained_history_stays_in_the_database(settings, routed_subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX = 1100
    now = timezone.now()
    rows = WebSubAcceptedDelivery.objects.using("other")
    rows.bulk_create(
        [
            WebSubAcceptedDelivery(subscription=routed_subscription, body_digest=f"{i:064x}", accepted_at=now)
            for i in range(1101)
        ],
        batch_size=100,
    )
    expired = rows.create(
        subscription=routed_subscription, body_digest="e" * 64, accepted_at=now - timedelta(seconds=61)
    )
    # Exercise the backend's historical 999-variable ceiling even on modern SQLite.
    connection = connections["other"]
    old_limit = None
    if connection.vendor == "sqlite":
        old_limit = connection.connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
    try:
        assert accept_websub_delivery(routed_subscription, "f" * 64, now=now)
    finally:
        if old_limit is not None:
            connection.connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, old_limit)
    assert rows.count() == 1100
    assert not rows.filter(pk=expired.pk).exists()
    assert not rows.filter(body_digest__in=[f"{i:064x}" for i in range(2)]).exists()
    assert rows.filter(body_digest=f"{2:064x}").exists()
    assert rows.filter(body_digest="f" * 64).exists()
    assert WebSubAcceptedDelivery.objects.using("default").count() == 0


@pytest.mark.django_db(databases=["default", "other"], transaction=True)
def test_exact_window_and_count_boundaries(settings, routed_subscription):
    now = timezone.now()
    cutoff = now - timedelta(seconds=60)
    rows = WebSubAcceptedDelivery.objects.using("other")
    rows.create(subscription=routed_subscription, body_digest="a" * 64, accepted_at=cutoff)
    rows.create(subscription=routed_subscription, body_digest="b" * 64, accepted_at=now)
    assert not accept_websub_delivery(routed_subscription, "a" * 64, now=now)
    assert rows.count() == 2
    assert accept_websub_delivery(routed_subscription, "c" * 64, now=now)
    assert set(rows.values_list("body_digest", flat=True)) == {"b" * 64, "c" * 64}
