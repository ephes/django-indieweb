"""Backend-aware pruning and streaming metadata-only lease inspection."""

import sqlite3
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.models import QuerySet
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from indieweb import websub
from indieweb.models import WebSubAcceptedDelivery, WebSubDeliveryAttempt, WebSubSubscription


def attempts(row, count, received_at):
    WebSubDeliveryAttempt.objects.bulk_create(
        [
            WebSubDeliveryAttempt(subscription=row, received_at=received_at, size=0, digest="a" * 64, status_code=204)
            for _ in range(count)
        ]
    )


@pytest.mark.django_db(transaction=True)
def test_prune_respects_write_backend_parameter_budget(monkeypatch):
    now = timezone.now()
    row = WebSubSubscription.objects.create(hub_url="https://hub.example/", topic_url="https://topic.example/")
    attempts(row, 73, now - timedelta(days=90))
    attempts(row, 1, now)
    replay = WebSubAcceptedDelivery.objects.create(subscription=row, body_digest="b" * 64, accepted_at=now)
    raw = connection.connection
    old_limit = raw.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 16) if connection.vendor == "sqlite" else None
    # Django 6.1 reads SQLite's runtime limit; older supported versions expose
    # a static capability, so advertise the lowered test-backend capability.
    if connection.features.max_query_params is None or connection.features.max_query_params > 16:
        monkeypatch.setattr(type(connection.features), "max_query_params", property(lambda self: 16))
    sizes = []

    def observe(execute, sql, params, many, context):
        if sql.lstrip().upper().startswith("DELETE"):
            sizes.append(len(params))
        return execute(sql, params, many, context)

    try:
        with connection.execute_wrapper(observe):
            result = websub.prune_websub_delivery_attempts(retention_days=30, now=now, batch_size=10**6)
    finally:
        if old_limit is not None:
            raw.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, old_limit)
    assert result.matched == result.deleted == 73
    assert max(sizes) <= 16
    assert WebSubDeliveryAttempt.objects.get().received_at == now
    assert WebSubAcceptedDelivery.objects.get().pk == replay.pk


@pytest.mark.django_db(transaction=True)
def test_prune_rolls_back_failing_batch_only(monkeypatch):
    now = timezone.now()
    row = WebSubSubscription.objects.create(hub_url="https://hub.example/", topic_url="https://topic.example/")
    attempts(row, 5, now - timedelta(days=90))
    ids = list(WebSubDeliveryAttempt.objects.order_by("pk").values_list("pk", flat=True))
    original = QuerySet.delete
    calls = []

    def delete_then_fail(queryset):
        result = original(queryset)
        calls.append(result)
        if len(calls) == 2:
            raise RuntimeError("synthetic batch failure")
        return result

    with patch.object(QuerySet, "delete", delete_then_fail), pytest.raises(RuntimeError, match="batch failure"):
        websub.prune_websub_delivery_attempts(retention_days=30, now=now, batch_size=2)
    assert list(WebSubDeliveryAttempt.objects.order_by("pk").values_list("pk", flat=True)) == ids[2:]
    assert websub.prune_websub_delivery_attempts(retention_days=30, now=now, batch_size=2).deleted == 3


@pytest.mark.django_db
def test_cli_streams_projected_lease_metadata(monkeypatch):
    now = timezone.now()
    WebSubSubscription.objects.bulk_create(
        [
            WebSubSubscription(
                hub_url="https://hub.example/",
                topic_url=f"https://topic.example/{i}",
                state="active",
                secret="synthetic-ciphertext",
                last_delivery_error="synthetic-diagnostic",
                lease_expires_at=now,
            )
            for i in range(1105)
        ]
    )
    original = QuerySet.iterator
    chunks = []

    def iterator(queryset, chunk_size=None):
        chunks.append(chunk_size)
        yield from original(queryset, chunk_size=chunk_size)

    out = StringIO()
    with patch.object(QuerySet, "iterator", iterator), CaptureQueriesContext(connection) as queries:
        call_command("websub_subscriptions", stdout=out)
    assert chunks == [500]
    selects = [q["sql"] for q in queries if q["sql"].lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1
    selected = selects[0].split(" FROM ")[0]
    for private in ("secret", "last_delivery", "callback_token", "request_generation"):
        assert private not in selected
    ids = list(WebSubSubscription.objects.order_by("lease_expires_at", "pk").values_list("pk", flat=True))
    lines = out.getvalue().splitlines()[1:]
    assert [int(line.split("#")[1].split()[0]) for line in lines] == ids
    assert isinstance(websub.summarize_websub_leases(now=now), list)
    assert [s.subscription_id for s in websub.summarize_websub_leases(now=now)] == ids
