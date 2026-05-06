from datetime import timedelta

import pytest
from django.utils import timezone
from examples import websub_workflows
from examples.websub_workflows import (
    WebSubDeliveryPayload,
    process_queued_websub_delivery,
    prune_websub_delivery_attempts,
    queue_websub_delivery,
    renew_websub_candidates,
    websub_delivery_hook,
)

from indieweb.models import WebSubDeliveryAttempt, WebSubSubscription
from indieweb.websub import WebSubSubscriptionRequestResult


class FakeQueue:
    def __init__(self):
        self.payloads: list[WebSubDeliveryPayload] = []

    def enqueue_websub_delivery(self, payload):
        self.payloads.append(payload)


def test_queue_websub_delivery_builds_small_payload_for_host_queue():
    queue = FakeQueue()

    payload = queue_websub_delivery(
        subscription_id=42,
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        body=b"<feed/>",
        headers={"Content-Type": "application/atom+xml"},
        queue=queue,
    )

    assert queue.payloads == [payload]
    assert payload.subscription_id == 42
    assert payload.hub_url == "https://hub.example/sub"
    assert payload.topic_url == "https://source.example/feed"
    assert payload.body == b"<feed/>"
    assert payload.headers == {"Content-Type": "application/atom+xml"}


def test_websub_delivery_hook_resolves_host_queue_adapter(monkeypatch):
    queue = FakeQueue()
    monkeypatch.setattr(websub_workflows, "get_host_delivery_queue", lambda: queue)

    websub_delivery_hook(
        subscription_id=7,
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        body=b"<feed/>",
        headers={"Content-Type": "application/atom+xml"},
    )

    assert len(queue.payloads) == 1
    assert queue.payloads[0].subscription_id == 7


class FakeProcessor:
    def __init__(self):
        self.calls = []

    def process_delivery(self, *, subscription, body, headers):
        self.calls.append({"subscription": subscription, "body": body, "headers": headers})


@pytest.mark.django_db
def test_process_queued_websub_delivery_delegates_feed_semantics_to_host_processor():
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_ACTIVE,
    )
    processor = FakeProcessor()
    payload = WebSubDeliveryPayload(
        subscription_id=subscription.pk,
        hub_url=subscription.hub_url,
        topic_url=subscription.topic_url,
        body=b"<feed><entry/></feed>",
        headers={"Content-Type": "application/atom+xml"},
    )

    result = process_queued_websub_delivery(payload, processor=processor)

    assert result.processed is True
    assert result.error == ""
    assert processor.calls == [
        {
            "subscription": subscription,
            "body": b"<feed><entry/></feed>",
            "headers": {"Content-Type": "application/atom+xml"},
        }
    ]


@pytest.mark.django_db
def test_process_queued_websub_delivery_reports_missing_subscription_without_parsing():
    processor = FakeProcessor()
    payload = WebSubDeliveryPayload(
        subscription_id=999,
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        body=b"<feed/>",
        headers={},
    )

    result = process_queued_websub_delivery(payload, processor=processor)

    assert result.processed is False
    assert result.error == "subscription no longer exists"
    assert processor.calls == []


@pytest.mark.django_db
def test_renew_websub_candidates_uses_existing_candidate_helper_and_injected_requester():
    now = timezone.now()
    due = WebSubSubscription.objects.create(
        hub_url="https://hub.example/due",
        topic_url="https://source.example/due",
        state=WebSubSubscription.STATE_ACTIVE,
        lease_expires_at=now + timedelta(hours=2),
    )
    WebSubSubscription.objects.create(
        hub_url="https://hub.example/later",
        topic_url="https://source.example/later",
        state=WebSubSubscription.STATE_ACTIVE,
        lease_expires_at=now + timedelta(days=3),
    )
    calls = []

    def requester(topic_url, hub_url, *, callback_base_url=None, lease_seconds=None, secret=None):
        calls.append(
            {
                "topic_url": topic_url,
                "hub_url": hub_url,
                "callback_base_url": callback_base_url,
                "lease_seconds": lease_seconds,
                "secret": secret,
            }
        )
        return WebSubSubscriptionRequestResult(subscription=due, mode="subscribe", success=True, status_code=202)

    attempts = renew_websub_candidates(
        callback_base_url="https://example.org/indieweb/websub",
        within=timedelta(days=1),
        lease_seconds=3600,
        secret_for_subscription=lambda subscription: f"secret-for-{subscription.pk}",
        now=now,
        requester=requester,
    )

    assert calls == [
        {
            "topic_url": due.topic_url,
            "hub_url": due.hub_url,
            "callback_base_url": "https://example.org/indieweb/websub",
            "lease_seconds": 3600,
            "secret": f"secret-for-{due.pk}",
        }
    ]
    assert attempts[0].subscription_id == due.pk
    assert attempts[0].success is True
    assert attempts[0].status_code == 202


@pytest.mark.django_db
def test_renew_websub_candidates_captures_requester_exceptions_as_results():
    now = timezone.now()
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/due",
        topic_url="https://source.example/due",
        state=WebSubSubscription.STATE_ACTIVE,
        lease_expires_at=now,
    )

    def requester(topic_url, hub_url, *, callback_base_url=None, lease_seconds=None, secret=None):
        raise RuntimeError("hub request failed")

    attempts = renew_websub_candidates(
        callback_base_url="https://example.org/indieweb/websub",
        now=now,
        requester=requester,
    )

    assert attempts[0].subscription_id == subscription.pk
    assert attempts[0].success is False
    assert attempts[0].error == "hub request failed"


@pytest.mark.django_db
def test_renew_websub_candidates_captures_secret_policy_exceptions_and_continues():
    now = timezone.now()
    failing = WebSubSubscription.objects.create(
        hub_url="https://hub.example/failing",
        topic_url="https://source.example/failing",
        state=WebSubSubscription.STATE_ACTIVE,
        lease_expires_at=now,
    )
    later = WebSubSubscription.objects.create(
        hub_url="https://hub.example/later",
        topic_url="https://source.example/later",
        state=WebSubSubscription.STATE_ACTIVE,
        lease_expires_at=now + timedelta(minutes=1),
    )
    calls = []

    def secret_for_subscription(subscription):
        if subscription == failing:
            raise RuntimeError("secret store unavailable")
        return "later-secret"

    def requester(topic_url, hub_url, *, callback_base_url=None, lease_seconds=None, secret=None):
        calls.append({"topic_url": topic_url, "hub_url": hub_url, "secret": secret})
        return WebSubSubscriptionRequestResult(subscription=later, mode="subscribe", success=True, status_code=202)

    attempts = renew_websub_candidates(
        callback_base_url="https://example.org/indieweb/websub",
        within=timedelta(hours=1),
        now=now,
        secret_for_subscription=secret_for_subscription,
        requester=requester,
    )

    assert [attempt.subscription_id for attempt in attempts] == [failing.pk, later.pk]
    assert attempts[0].success is False
    assert attempts[0].error == "secret store unavailable"
    assert attempts[1].success is True
    assert calls == [{"topic_url": later.topic_url, "hub_url": later.hub_url, "secret": "later-secret"}]


@pytest.mark.django_db
def test_renew_websub_candidates_forwards_none_secret_and_lease_seconds_without_policy():
    now = timezone.now()
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/due",
        topic_url="https://source.example/due",
        state=WebSubSubscription.STATE_ACTIVE,
        lease_expires_at=now,
    )
    calls = []

    def requester(topic_url, hub_url, *, callback_base_url=None, lease_seconds=None, secret=None):
        calls.append({"lease_seconds": lease_seconds, "secret": secret})
        return WebSubSubscriptionRequestResult(subscription=subscription, mode="subscribe", success=True)

    attempts = renew_websub_candidates(
        callback_base_url="https://example.org/indieweb/websub",
        now=now,
        requester=requester,
    )

    assert calls == [{"lease_seconds": None, "secret": None}]
    assert attempts[0].success is True


@pytest.mark.django_db
def test_prune_websub_delivery_attempts_deletes_only_rows_older_than_retention_cutoff():
    now = timezone.now()
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_ACTIVE,
    )
    old_attempt = WebSubDeliveryAttempt.objects.create(
        subscription=subscription,
        received_at=now - timedelta(days=91),
        status_code=204,
    )
    recent_attempt = WebSubDeliveryAttempt.objects.create(
        subscription=subscription,
        received_at=now - timedelta(days=10),
        status_code=204,
    )

    result = prune_websub_delivery_attempts(retention_days=90, now=now)

    assert result.retention_days == 90
    assert result.cutoff == now - timedelta(days=90)
    assert result.deleted_count == 1
    assert not WebSubDeliveryAttempt.objects.filter(pk=old_attempt.pk).exists()
    assert WebSubDeliveryAttempt.objects.filter(pk=recent_attempt.pk).exists()


def test_prune_websub_delivery_attempts_rejects_negative_retention():
    with pytest.raises(ValueError, match="non-negative"):
        prune_websub_delivery_attempts(retention_days=-1)
