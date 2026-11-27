"""Retention pruning for ``WebSubDeliveryAttempt`` diagnostics."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, connections, transaction
from django.db.models.signals import post_delete
from django.test.utils import CaptureQueriesContext

from indieweb.models import WebSubAcceptedDelivery, WebSubDeliveryAttempt, WebSubSubscription
from indieweb.websub import (
    WebSubDeliveryAttemptPruneError,
    prune_websub_delivery_attempts,
    websub_delivery_attempt_retention_days,
)

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
CUTOFF = NOW - timedelta(days=30)


@pytest.fixture
def subscription(db):
    return WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_ACTIVE,
        last_delivery_at=NOW - timedelta(days=90),
        last_delivery_status_code=204,
        last_delivery_error="summary stays",
    )


def _attempt(subscription, received_at, status_code=204):
    return WebSubDeliveryAttempt.objects.create(
        subscription=subscription, received_at=received_at, status_code=status_code
    )


@pytest.fixture
def attempts(subscription):
    return {
        "old": _attempt(subscription, CUTOFF - timedelta(days=60)),
        "just_before": _attempt(subscription, CUTOFF - timedelta(microseconds=1), status_code=403),
        "at_cutoff": _attempt(subscription, CUTOFF),
        "recent": _attempt(subscription, NOW - timedelta(days=1)),
    }


def _remaining(attempts) -> set[str]:
    stored = set(WebSubDeliveryAttempt.objects.values_list("pk", flat=True))
    return {name for name, attempt in attempts.items() if attempt.pk in stored}


def test_prune_deletes_only_attempts_older_than_the_cutoff(attempts):
    result = prune_websub_delivery_attempts(retention_days=30, now=NOW)

    assert (result.retention_days, result.cutoff, result.matched, result.deleted) == (30, CUTOFF, 2, 2)
    assert result.dry_run is False
    assert _remaining(attempts) == {"at_cutoff", "recent"}


def test_prune_dry_run_counts_without_deleting(attempts):
    result = prune_websub_delivery_attempts(retention_days=30, now=NOW, dry_run=True)

    assert (result.matched, result.deleted, result.dry_run) == (2, 0, True)
    assert _remaining(attempts) == set(attempts)


@pytest.mark.parametrize("dry_run", [False, True])
def test_prune_rejects_naive_reference_time(subscription, settings, django_assert_num_queries, dry_run):
    settings.TIME_ZONE = "America/Los_Angeles"
    # Interpreting the naive reference as local time would include this row.
    attempt = _attempt(subscription, CUTOFF + timedelta(hours=3))

    with django_assert_num_queries(0), pytest.raises(ValueError, match="timezone-aware"):
        prune_websub_delivery_attempts(retention_days=30, now=NOW.replace(tzinfo=None), dry_run=dry_run)

    assert WebSubDeliveryAttempt.objects.filter(pk=attempt.pk).exists()


def test_prune_accepts_naive_reference_time_without_timezone_support(subscription, settings):
    settings.USE_TZ = False
    cutoff = CUTOFF.replace(tzinfo=None)
    _attempt(subscription, cutoff - timedelta(seconds=1))
    retained = _attempt(subscription, cutoff)

    result = prune_websub_delivery_attempts(retention_days=30, now=NOW.replace(tzinfo=None))

    assert (result.cutoff, result.matched, result.deleted) == (cutoff, 1, 1)
    assert list(WebSubDeliveryAttempt.objects.values_list("pk", flat=True)) == [retained.pk]


def test_prune_leaves_subscriptions_and_replay_rows_untouched(subscription, attempts):
    accepted = WebSubAcceptedDelivery.objects.create(
        subscription=subscription, body_digest="a" * 64, accepted_at=CUTOFF - timedelta(days=60)
    )
    before = WebSubSubscription.objects.values().get(pk=subscription.pk)

    prune_websub_delivery_attempts(retention_days=30, now=NOW)

    assert WebSubAcceptedDelivery.objects.filter(pk=accepted.pk).exists()
    assert WebSubSubscription.objects.values().get(pk=subscription.pk) == before


def test_prune_drains_every_batch(subscription, django_assert_num_queries):
    for day in range(7):
        _attempt(subscription, CUTOFF - timedelta(days=day + 1))
    recent = _attempt(subscription, NOW)

    # 1 count + 4 batch selects (3, 3, 1, 0 rows) + 3 deletes,
    # plus a savepoint/release pair for each atomic batch (including empty).
    # SQLite also reserves the writer before each select.
    reservations = 4 if connection.vendor == "sqlite" else 0
    with django_assert_num_queries(16 + reservations):
        result = prune_websub_delivery_attempts(retention_days=30, now=NOW, batch_size=3)

    assert (result.matched, result.deleted) == (7, 7)
    assert list(WebSubDeliveryAttempt.objects.values_list("pk", flat=True)) == [recent.pk]


def test_prune_with_nothing_to_delete_reports_zero(attempts):
    result = prune_websub_delivery_attempts(retention_days=365, now=NOW)

    assert (result.matched, result.deleted) == (0, 0)
    assert _remaining(attempts) == set(attempts)


def test_prune_uses_the_setting_when_no_days_are_passed(attempts, settings):
    settings.INDIEWEB_WEBSUB_DELIVERY_ATTEMPT_RETENTION_DAYS = 30

    result = prune_websub_delivery_attempts(now=NOW)

    assert (result.retention_days, result.deleted) == (30, 2)


def test_explicit_days_override_the_setting(attempts, settings):
    settings.INDIEWEB_WEBSUB_DELIVERY_ATTEMPT_RETENTION_DAYS = 30

    result = prune_websub_delivery_attempts(retention_days=365, now=NOW)

    assert (result.retention_days, result.deleted) == (365, 0)


def test_prune_without_configured_retention_refuses_to_delete(attempts):
    with pytest.raises(ValueError, match="retention is not configured"):
        prune_websub_delivery_attempts(now=NOW)

    assert _remaining(attempts) == set(attempts)


@pytest.mark.parametrize("value", [0, -1, "0", "abc", True, False, 1.5, [30], ""])
def test_invalid_retention_setting_is_rejected(settings, value):
    settings.INDIEWEB_WEBSUB_DELIVERY_ATTEMPT_RETENTION_DAYS = value

    with pytest.raises(ValueError):
        websub_delivery_attempt_retention_days()


@pytest.mark.parametrize("value, expected", [(1, 1), (90, 90), ("45", 45)])
def test_valid_retention_setting_is_accepted(settings, value, expected):
    settings.INDIEWEB_WEBSUB_DELIVERY_ATTEMPT_RETENTION_DAYS = value

    assert websub_delivery_attempt_retention_days() == expected


@pytest.mark.parametrize("days", [0, -5])
def test_invalid_explicit_days_are_rejected(attempts, days):
    with pytest.raises(ValueError, match="positive integer"):
        prune_websub_delivery_attempts(retention_days=days, now=NOW)

    assert _remaining(attempts) == set(attempts)


@pytest.mark.parametrize("batch_size", [0, -1, True, 2.5])
def test_invalid_batch_size_is_rejected(attempts, batch_size):
    with pytest.raises(ValueError, match="batch size"):
        prune_websub_delivery_attempts(retention_days=30, now=NOW, batch_size=batch_size)

    assert _remaining(attempts) == set(attempts)


def _run_command(*args: str) -> str:
    out = StringIO()
    with patch("indieweb.websub.timezone.now", return_value=NOW):
        call_command("prune_websub_delivery_attempts", *args, stdout=out)
    return out.getvalue()


def test_command_deletes_and_reports_cutoff(attempts):
    output = _run_command("--days", "30", "--batch-size", "1")

    assert output.strip() == (
        f"Deleted 2 WebSub delivery attempts received before {CUTOFF.isoformat()} (retention: 30 days)"
    )
    assert _remaining(attempts) == {"at_cutoff", "recent"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("dry_run", "enclosing_transaction", "fail_on", "stream_error", "outcome"),
    [
        (False, False, "write", ValueError, "Committed deletions: 2"),
        (False, False, "flush", OSError, "Committed deletions: 2"),
        (False, True, "write", RuntimeError, "Deletions pending caller commit: 2"),
        (True, False, "write", OSError, "Dry run: would delete 2"),
    ],
)
def test_command_retains_prune_outcome_on_receipt_failure(
    attempts, monkeypatch, dry_run, enclosing_transaction, fail_on, stream_error, outcome
):
    def fail_output(*args):
        raise stream_error("synthetic output failure")

    out = StringIO()
    monkeypatch.setattr(out, fail_on, fail_output)
    monkeypatch.setattr("indieweb.websub.timezone.now", lambda: NOW)

    with transaction.atomic() if enclosing_transaction else nullcontext():
        with pytest.raises(CommandError) as error:
            call_command("prune_websub_delivery_attempts", days=30, batch_size=1, dry_run=dry_run, stdout=out)

        assert outcome in str(error.value)
        assert f"received before {CUTOFF.isoformat()} (retention: 30 days)" in str(error.value)
        assert isinstance(error.value.__cause__, stream_error)
        assert _remaining(attempts) == (set(attempts) if dry_run else {"at_cutoff", "recent"})
        if enclosing_transaction:
            transaction.set_rollback(True)

    assert _remaining(attempts) == (set(attempts) if dry_run or enclosing_transaction else {"at_cutoff", "recent"})


@pytest.mark.django_db(transaction=True)
def test_command_reports_only_committed_batches_after_commit_failure(attempts, monkeypatch):
    commit = connection.commit
    commits = 0

    def fail_second_commit():
        nonlocal commits
        commits += 1
        if commits == 2:
            raise DatabaseError("synthetic second-batch commit failure")
        commit()

    with monkeypatch.context() as patch_commit:
        patch_commit.setattr(connection, "commit", fail_second_commit)
        with pytest.raises(CommandError, match=r"committed deletions is 1\.$"):
            _run_command("--days", "30", "--batch-size", "1")

    assert _remaining(attempts) == {"just_before", "at_cutoff", "recent"}
    assert "Deleted 1 WebSub delivery attempts" in _run_command("--days", "30", "--batch-size", "1")
    assert _remaining(attempts) == {"at_cutoff", "recent"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(("failure", "fail_on"), [(DatabaseError, 2), (RuntimeError, 1)])
def test_prune_counts_committed_batch_when_a_host_on_commit_callback_fails(attempts, failure, fail_on):
    deletes = 0
    host_error = failure("synthetic host on_commit failure")

    def fail_after_commit():
        raise host_error

    def register_host_callback(sender, using, **kwargs):
        nonlocal deletes
        deletes += 1
        if deletes == fail_on:
            transaction.on_commit(fail_after_commit, using=using)

    post_delete.connect(register_host_callback, sender=WebSubDeliveryAttempt)
    try:
        with pytest.raises(WebSubDeliveryAttemptPruneError) as error:
            prune_websub_delivery_attempts(retention_days=30, now=NOW, batch_size=1)
    finally:
        post_delete.disconnect(register_host_callback, sender=WebSubDeliveryAttempt)

    assert error.value.deleted == fail_on
    assert error.value.__cause__ is host_error
    remaining = {"at_cutoff", "recent"}
    if fail_on == 1:
        remaining.add("just_before")
    assert _remaining(attempts) == remaining


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("fail_on", [1, 2])
def test_prune_propagates_runtime_error_before_current_batch_commits(attempts, fail_on):
    deletes = 0
    host_error = RuntimeError("synthetic host post_delete failure")

    def fail_before_commit(sender, **kwargs):
        nonlocal deletes
        deletes += 1
        if deletes == fail_on:
            raise host_error

    post_delete.connect(fail_before_commit, sender=WebSubDeliveryAttempt)
    try:
        with pytest.raises(RuntimeError) as error:
            prune_websub_delivery_attempts(retention_days=30, now=NOW, batch_size=1)
    finally:
        post_delete.disconnect(fail_before_commit, sender=WebSubDeliveryAttempt)

    assert error.value is host_error
    remaining = set(attempts)
    if fail_on == 2:
        remaining.remove("old")
    assert _remaining(attempts) == remaining


def test_command_dry_run_is_inert(attempts):
    output = _run_command("--days", "30", "--dry-run")

    assert output.strip() == (
        f"Dry run: would delete 2 WebSub delivery attempts received before {CUTOFF.isoformat()} (retention: 30 days)"
    )
    assert _remaining(attempts) == set(attempts)


def test_command_uses_the_setting(attempts, settings):
    settings.INDIEWEB_WEBSUB_DELIVERY_ATTEMPT_RETENTION_DAYS = 30

    assert "Deleted 2 WebSub delivery attempts" in _run_command()


@pytest.mark.parametrize("args", [(), ("--days", "0"), ("--days", "30", "--batch-size", "0")])
def test_command_rejects_missing_or_invalid_options_without_deleting(attempts, args):
    with pytest.raises(CommandError):
        _run_command(*args)

    assert _remaining(attempts) == set(attempts)


def test_command_rejects_an_invalid_setting(attempts, settings):
    settings.INDIEWEB_WEBSUB_DELIVERY_ATTEMPT_RETENTION_DAYS = "ninety"

    with pytest.raises(CommandError, match="INDIEWEB_WEBSUB_DELIVERY_ATTEMPT_RETENTION_DAYS"):
        _run_command()

    assert _remaining(attempts) == set(attempts)


class ReplicaRouter:
    """Send reads to the ``other`` database (a replica) and writes to ``default``."""

    def db_for_read(self, model, **hints):
        return "other"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        return True


@pytest.mark.django_db(databases=["default", "other"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_prune_reads_and_deletes_on_the_write_database(settings, dry_run):
    """A lagging read replica must not decide what is deleted or keep the batch loop running."""
    subscription = WebSubSubscription.objects.using("default").create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_ACTIVE,
    )
    for day in range(3):
        WebSubDeliveryAttempt.objects.using("default").create(
            subscription=subscription, received_at=CUTOFF - timedelta(days=day + 1), status_code=204
        )
    settings.DATABASE_ROUTERS = ["tests.test_prune_websub_delivery_attempts.ReplicaRouter"]

    with CaptureQueriesContext(connections["other"]) as replica_queries:
        result = prune_websub_delivery_attempts(retention_days=30, now=NOW, batch_size=2, dry_run=dry_run)

    assert len(replica_queries) == 0
    assert result.matched == 3
    assert result.deleted == (0 if dry_run else 3)
    assert WebSubDeliveryAttempt.objects.using("default").count() == (3 if dry_run else 0)
