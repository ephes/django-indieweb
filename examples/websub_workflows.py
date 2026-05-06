"""Host-owned WebSub subscriber workflow examples.

These examples are deliberately ordinary Django project code. They show how a
host can wire django-indieweb's WebSub subscriber helpers into a queue, worker,
lease-renewal task, and delivery-attempt retention policy without making
django-indieweb own a scheduler, feed parser, feed-entry store, retry policy,
or queue dependency.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from django.utils import timezone

from indieweb.models import WebSubDeliveryAttempt, WebSubSubscription
from indieweb.websub import (
    WebSubSubscriptionRequestResult,
    get_websub_renewal_candidates,
    request_websub_subscription,
)


@dataclass(frozen=True)
class WebSubDeliveryPayload:
    """Small queue payload for later host-owned feed processing."""

    subscription_id: int
    hub_url: str
    topic_url: str
    body: bytes
    headers: dict[str, str]


class WebSubDeliveryQueue(Protocol):
    """Host queue adapter boundary; implementations may wrap Celery, RQ, etc."""

    def enqueue_websub_delivery(self, payload: WebSubDeliveryPayload) -> None:
        """Schedule delivery processing in the host application's worker system."""


def get_host_delivery_queue() -> WebSubDeliveryQueue:
    """Return the host queue adapter for ``websub_delivery_hook``.

    In a real project this function would import your Celery/RQ/task adapter
    or resolve a dependency from your application container. The example keeps
    it as an explicit host-owned adapter so importing this module starts no
    worker and performs no network or queue operations.
    """

    raise NotImplementedError("Configure this example to return your host delivery queue adapter")


def queue_websub_delivery(
    *,
    subscription_id: int,
    hub_url: str,
    topic_url: str,
    body: bytes,
    headers: Mapping[str, str],
    queue: WebSubDeliveryQueue,
) -> WebSubDeliveryPayload:
    """Build a compact delivery payload and hand it to a host queue adapter."""

    payload = WebSubDeliveryPayload(
        subscription_id=subscription_id,
        hub_url=hub_url,
        topic_url=topic_url,
        body=body,
        headers=dict(headers),
    )
    queue.enqueue_websub_delivery(payload)
    return payload


def websub_delivery_hook(
    *,
    subscription_id: int,
    hub_url: str,
    topic_url: str,
    body: bytes,
    headers: Mapping[str, str],
) -> None:
    """Example shape for ``INDIEWEB_WEBSUB_DELIVERY_HOOK``.

    Configure the dotted path to this kind of function from ``settings.py``.
    The callback path should stay small: django-indieweb has already validated
    the delivery and recorded metadata, while host code queues parsing and
    persistence work for a worker.

    Copy this shape into your project rather than configuring this example
    dotted path directly; ``get_host_delivery_queue()`` is intentionally a
    placeholder for host-owned queue setup.
    """

    queue_websub_delivery(
        subscription_id=subscription_id,
        hub_url=hub_url,
        topic_url=topic_url,
        body=body,
        headers=headers,
        queue=get_host_delivery_queue(),
    )


class HostFeedDeliveryProcessor(Protocol):
    """Host-owned feed parser and persistence boundary."""

    def process_delivery(
        self,
        *,
        subscription: WebSubSubscription,
        body: bytes,
        headers: Mapping[str, str],
    ) -> None:
        """Parse the feed body and persist entries according to host policy."""


@dataclass(frozen=True)
class WebSubDeliveryProcessingResult:
    """Operator-facing outcome from one queued delivery payload."""

    subscription_id: int
    processed: bool
    error: str = ""


def process_queued_websub_delivery(
    payload: WebSubDeliveryPayload,
    *,
    processor: HostFeedDeliveryProcessor,
) -> WebSubDeliveryProcessingResult:
    """Process a queued delivery by delegating feed semantics to host code."""

    try:
        subscription = WebSubSubscription.objects.get(pk=payload.subscription_id)
    except WebSubSubscription.DoesNotExist:
        return WebSubDeliveryProcessingResult(
            subscription_id=payload.subscription_id,
            processed=False,
            error="subscription no longer exists",
        )

    processor.process_delivery(subscription=subscription, body=payload.body, headers=payload.headers)
    return WebSubDeliveryProcessingResult(subscription_id=payload.subscription_id, processed=True)


class WebSubSubscriptionRequester(Protocol):
    """Callable boundary around the helper that sends explicit hub requests."""

    def __call__(
        self,
        topic_url: str,
        hub_url: str,
        *,
        callback_base_url: str | None = None,
        lease_seconds: int | None = None,
        secret: str | None = None,
    ) -> WebSubSubscriptionRequestResult:
        """Request subscribe/renewal for one subscription."""


SecretPolicy = Callable[[WebSubSubscription], str | None]


@dataclass(frozen=True)
class WebSubRenewalAttempt:
    """Summary for one explicit lease-renewal attempt."""

    subscription_id: int
    hub_url: str
    topic_url: str
    success: bool
    status_code: int | None = None
    error: str = ""


def renew_websub_candidates(
    *,
    callback_base_url: str,
    within: timedelta = timedelta(days=1),
    lease_seconds: int | None = None,
    secret_for_subscription: SecretPolicy | None = None,
    now: datetime | None = None,
    requester: WebSubSubscriptionRequester = request_websub_subscription,
) -> list[WebSubRenewalAttempt]:
    """Renew subscriptions selected by ``get_websub_renewal_candidates()``.

    This function performs hub network calls only when host code explicitly
    invokes it. A cron job, Django management command, Celery beat task, or
    manual operator action should own that schedule. Secret-policy failures and
    request failures are captured as per-subscription attempts so later
    candidates can still run.
    """

    attempts: list[WebSubRenewalAttempt] = []
    subscriptions = get_websub_renewal_candidates(within=within, now=now)
    for subscription in subscriptions:
        try:
            secret = secret_for_subscription(subscription) if secret_for_subscription is not None else None
            result = requester(
                subscription.topic_url,
                subscription.hub_url,
                callback_base_url=callback_base_url,
                lease_seconds=lease_seconds,
                secret=secret,
            )
        except Exception as exc:
            attempts.append(
                WebSubRenewalAttempt(
                    subscription_id=subscription.pk,
                    hub_url=subscription.hub_url,
                    topic_url=subscription.topic_url,
                    success=False,
                    error=str(exc),
                )
            )
            continue

        attempts.append(
            WebSubRenewalAttempt(
                subscription_id=subscription.pk,
                hub_url=subscription.hub_url,
                topic_url=subscription.topic_url,
                success=result.success,
                status_code=result.status_code,
                error=result.error,
            )
        )
    return attempts


@dataclass(frozen=True)
class WebSubDeliveryAttemptPruneResult:
    """Summary for a host-owned delivery-attempt retention run."""

    retention_days: int
    cutoff: datetime
    deleted_count: int


def prune_websub_delivery_attempts(
    *,
    retention_days: int,
    now: datetime | None = None,
) -> WebSubDeliveryAttemptPruneResult:
    """Delete metadata-only delivery attempts older than a host retention window.

    Returns the number of pruned ``WebSubDeliveryAttempt`` rows.
    """

    if retention_days < 0:
        raise ValueError("retention_days must be non-negative")

    reference_time = now or timezone.now()
    cutoff = reference_time - timedelta(days=retention_days)
    deleted_count, _deleted_by_model = WebSubDeliveryAttempt.objects.filter(received_at__lt=cutoff).delete()
    return WebSubDeliveryAttemptPruneResult(
        retention_days=retention_days,
        cutoff=cutoff,
        deleted_count=deleted_count,
    )
