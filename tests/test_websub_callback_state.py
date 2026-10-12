"""WebSub verification and denial transitions act on the stored row, not a stale instance."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import connection, connections
from django.db.models import QuerySet
from django.utils import timezone

from indieweb.models import WebSubSubscription
from indieweb.websub import confirm_websub_verification, record_websub_denial

ACTIVE_SECRET = "active-secret-value-20x"
NEW_SECRET = "new-secret-value-20x"
DAY = 24 * 60 * 60


def _pending_subscribe(**overrides) -> WebSubSubscription:
    values = {
        "hub_url": "https://hub.example/sub",
        "topic_url": "https://source.example/feed",
        "state": WebSubSubscription.STATE_PENDING_SUBSCRIBE,
        "pending_mode": WebSubSubscription.MODE_SUBSCRIBE,
        "requested_lease_seconds": DAY,
    }
    values.update(overrides)
    return WebSubSubscription.objects.create(**values)


def _confirm(subscription: WebSubSubscription, *, mode: str = "subscribe", lease_seconds: int | None = DAY) -> None:
    confirm_websub_verification(
        subscription,
        mode=mode,
        topic_url=subscription.topic_url,
        challenge="challenge",
        lease_seconds=lease_seconds,
    )


def _deny(subscription: WebSubSubscription) -> None:
    record_websub_denial(subscription, topic_url=subscription.topic_url, reason="stale denial")


def _stale_copy(subscription: WebSubSubscription) -> WebSubSubscription:
    return WebSubSubscription.objects.get(pk=subscription.pk)


@pytest.mark.django_db
def test_stale_denial_cannot_demote_a_confirmed_subscription():
    subscription = _pending_subscribe()
    subscription.set_pending_secret(NEW_SECRET)
    subscription.pending_secret_set = True
    subscription.save()
    confirming = _stale_copy(subscription)
    denying = _stale_copy(subscription)

    _confirm(confirming)
    with pytest.raises(ValueError, match="does not match a pending subscription request"):
        _deny(denying)

    stored = _stale_copy(subscription)
    assert stored.state == WebSubSubscription.STATE_ACTIVE
    assert stored.confirmed_lease_seconds == DAY
    assert stored.lease_expires_at is not None
    assert stored.get_secret() == NEW_SECRET
    assert stored.last_denied_at is None
    assert stored.last_denial_reason == ""


@pytest.mark.django_db
def test_stale_confirmation_cannot_revive_a_denied_subscription():
    subscription = _pending_subscribe()
    subscription.set_pending_secret(NEW_SECRET)
    subscription.pending_secret_set = True
    subscription.save()
    denying = _stale_copy(subscription)
    confirming = _stale_copy(subscription)

    _deny(denying)
    with pytest.raises(ValueError, match="mode does not match pending subscription mode"):
        _confirm(confirming)

    stored = _stale_copy(subscription)
    assert stored.state == WebSubSubscription.STATE_DENIED
    assert stored.confirmed_lease_seconds is None
    assert stored.lease_expires_at is None
    assert stored.secret == ""
    assert stored.last_verified_at is None


@pytest.mark.django_db
def test_stale_denial_cannot_reactivate_a_confirmed_unsubscribe():
    subscription = _pending_subscribe(
        state=WebSubSubscription.STATE_PENDING_UNSUBSCRIBE,
        pending_mode=WebSubSubscription.MODE_UNSUBSCRIBE,
        confirmed_lease_seconds=DAY,
        lease_expires_at=timezone.now() + timedelta(seconds=DAY),
    )
    confirming = _stale_copy(subscription)
    denying = _stale_copy(subscription)

    _confirm(confirming, mode="unsubscribe", lease_seconds=None)
    with pytest.raises(ValueError):
        _deny(denying)

    stored = _stale_copy(subscription)
    assert stored.state == WebSubSubscription.STATE_UNSUBSCRIBED
    assert stored.lease_expires_at is None


@pytest.mark.django_db
def test_duplicate_renewal_confirmation_is_rejected_and_keeps_the_first_lease():
    subscription = _pending_subscribe(
        state=WebSubSubscription.STATE_ACTIVE,
        confirmed_lease_seconds=DAY,
        lease_expires_at=timezone.now() + timedelta(seconds=DAY),
    )
    first = _stale_copy(subscription)
    second = _stale_copy(subscription)

    _confirm(first, lease_seconds=DAY)
    with pytest.raises(ValueError, match="mode does not match pending subscription mode"):
        _confirm(second, lease_seconds=DAY // 2)

    assert _stale_copy(subscription).confirmed_lease_seconds == DAY


@pytest.mark.django_db
def test_stale_instance_cannot_defeat_the_renewal_lease_ratchet():
    """The ratchet floor comes from the stored lease, not the caller's older view of the row."""
    subscription = _pending_subscribe()
    stale = _stale_copy(subscription)  # still sees ``pending_subscribe`` and no confirmed lease
    _confirm(_stale_copy(subscription), lease_seconds=DAY)
    # A later renewal request is pending on the now-active row.
    WebSubSubscription.objects.filter(pk=subscription.pk).update(pending_mode=WebSubSubscription.MODE_SUBSCRIBE)

    _confirm(stale, lease_seconds=300)

    stored = _stale_copy(subscription)
    assert stored.state == WebSubSubscription.STATE_ACTIVE
    assert stored.confirmed_lease_seconds == DAY // 2


@pytest.mark.django_db
def test_transition_leaves_the_caller_instance_matching_the_stored_row():
    subscription = _pending_subscribe()
    stale = _stale_copy(subscription)
    WebSubSubscription.objects.filter(pk=subscription.pk).update(last_request_error="recorded elsewhere")

    _confirm(stale)

    assert stale.state == WebSubSubscription.STATE_ACTIVE
    assert stale.last_request_error == "recorded elsewhere"
    assert _stale_copy(subscription).last_request_error == "recorded elsewhere"


@pytest.mark.django_db
@pytest.mark.parametrize("transition", [_confirm, _deny])
def test_transition_for_a_deleted_subscription_is_rejected(transition):
    subscription = _pending_subscribe()
    stale = _stale_copy(subscription)
    WebSubSubscription.objects.filter(pk=subscription.pk).delete()

    with pytest.raises(ValueError, match="no longer exists"):
        transition(stale)

    assert not WebSubSubscription.objects.filter(pk=subscription.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("transition", [_confirm, _deny])
def test_transition_reloads_the_row_with_a_lock_inside_a_transaction(transition):
    subscription = _pending_subscribe()
    locked_in_atomic_block: list[bool] = []
    original = QuerySet.select_for_update

    def recording_select_for_update(queryset, *args, **kwargs):
        if queryset.model is WebSubSubscription:
            locked_in_atomic_block.append(connection.in_atomic_block)
        return original(queryset, *args, **kwargs)

    with patch.object(QuerySet, "select_for_update", recording_select_for_update):
        transition(subscription)

    assert locked_in_atomic_block == [True]


@pytest.mark.django_db
def test_rejected_transition_does_not_write():
    subscription = _pending_subscribe()
    _confirm(_stale_copy(subscription))
    before = WebSubSubscription.objects.values().get(pk=subscription.pk)

    with pytest.raises(ValueError):
        _deny(subscription)

    assert WebSubSubscription.objects.values().get(pk=subscription.pk) == before


@pytest.mark.django_db(databases=["default", "other"])
@pytest.mark.parametrize("transition", [_confirm, _deny])
def test_transition_uses_the_database_of_the_subscription(transition):
    """A row in another database is locked, reloaded and saved there, not in ``default``."""
    values = {
        "hub_url": "https://hub.example/sub",
        "topic_url": "https://source.example/feed",
        "state": WebSubSubscription.STATE_PENDING_SUBSCRIBE,
        "pending_mode": WebSubSubscription.MODE_SUBSCRIBE,
        "requested_lease_seconds": DAY,
    }
    in_default = WebSubSubscription.objects.using("default").create(**values)
    in_other = WebSubSubscription.objects.using("other").create(pk=in_default.pk, **values)
    locks: list[tuple[str, bool]] = []
    original = QuerySet.select_for_update

    def recording_select_for_update(queryset, *args, **kwargs):
        if queryset.model is WebSubSubscription:
            locks.append((queryset.db, connections[queryset.db].in_atomic_block))
        return original(queryset, *args, **kwargs)

    with patch.object(QuerySet, "select_for_update", recording_select_for_update):
        transition(in_other)

    assert locks == [("other", True)]
    assert in_other._state.db == "other"
    untouched = WebSubSubscription.objects.using("default").get(pk=in_default.pk)
    changed = WebSubSubscription.objects.using("other").get(pk=in_other.pk)
    assert untouched.state == WebSubSubscription.STATE_PENDING_SUBSCRIBE
    assert untouched.pending_mode == WebSubSubscription.MODE_SUBSCRIBE
    assert changed.pending_mode == ""
    assert changed.state != WebSubSubscription.STATE_PENDING_SUBSCRIBE
