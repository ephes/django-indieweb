from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta
from io import StringIO
from urllib.parse import parse_qs

import django
import httpx
import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from indieweb.models import WebSubAcceptedDelivery, WebSubDeliveryAttempt, WebSubSubscription
from indieweb.websub import (
    accept_websub_delivery,
    build_websub_callback_url,
    delivery_is_replay,
    delivery_topic_link_allowed,
    get_websub_expired_subscriptions,
    get_websub_renewal_candidates,
    record_websub_denial,
    request_websub_subscription,
    summarize_websub_leases,
    validate_websub_delivery_signature,
)
from tests import websub_hooks

ACTIVE_SECRET = "active-secret-value-20x"
NEW_SECRET = "new-secret-value-20x"
OLD_SECRET = "old-secret-value-20x"
SHARED_SECRET = "shared-secret-value-20x"
STORED_SECRET = "stored-secret-value-20x"


@pytest.fixture(autouse=True)
def reset_websub_hooks():
    websub_hooks.reset()
    yield
    websub_hooks.reset()


@pytest.fixture
def subscription(db):
    return WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_ACTIVE,
    )


def _callback_url(subscription: WebSubSubscription) -> str:
    return reverse("indieweb:websub-callback", args=[subscription.callback_token])


def _topic_link(subscription: WebSubSubscription) -> str:
    return f'<{subscription.topic_url}>; rel="self"'


def _post_delivery(
    client: Client,
    subscription: WebSubSubscription,
    *,
    data: bytes,
    content_type: str,
    **headers: str,
):
    return client.post(
        _callback_url(subscription),
        data=data,
        content_type=content_type,
        HTTP_LINK=_topic_link(subscription),
        **headers,
    )


@pytest.mark.django_db
def test_request_websub_subscription_posts_subscribe_form(settings):
    settings.INDIEWEB_WEBSUB_TIMEOUT = 5
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))

    result = request_websub_subscription(
        "https://source.example/feed",
        "https://hub.example/sub",
        callback_base_url="https://example.org/indieweb/websub",
        lease_seconds=3600,
        secret=SHARED_SECRET,
        client=http_client,
    )

    result.subscription.refresh_from_db()
    body = parse_qs(requests[0].content.decode("ascii"))
    assert result.success is True
    assert result.status_code == 202
    assert result.subscription.state == WebSubSubscription.STATE_PENDING_SUBSCRIBE
    assert result.subscription.pending_mode == WebSubSubscription.MODE_SUBSCRIBE
    assert result.subscription.requested_lease_seconds == 3600
    assert result.subscription.secret == ""
    assert result.subscription.pending_secret != SHARED_SECRET
    assert result.subscription.get_pending_secret() == SHARED_SECRET
    assert result.subscription.pending_secret_set is True
    assert body == {
        "hub.mode": ["subscribe"],
        "hub.callback": [f"https://example.org/indieweb/websub/{result.subscription.callback_token}/"],
        "hub.topic": ["https://source.example/feed"],
        "hub.lease_seconds": ["3600"],
        "hub.secret": [SHARED_SECRET],
    }


@pytest.mark.django_db
def test_request_websub_subscription_rejects_private_hub_without_posting():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))

    result = request_websub_subscription(
        "https://source.example/feed",
        "http://127.0.0.1/sub",
        callback_base_url="https://example.org/indieweb/websub",
        client=http_client,
    )

    result.subscription.refresh_from_db()
    assert result.success is False
    assert "blocked address" in result.error
    assert result.subscription.last_request_status_code is None
    assert requests == []


@pytest.mark.django_db
def test_request_websub_subscription_records_hub_rejection():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad topic")

    http_client = httpx.Client(transport=httpx.MockTransport(handler))

    result = request_websub_subscription(
        "https://source.example/feed",
        "https://hub.example/sub",
        callback_base_url="https://example.org/indieweb/websub",
        client=http_client,
    )

    result.subscription.refresh_from_db()
    assert result.success is False
    assert result.status_code == 400
    assert result.subscription.state == WebSubSubscription.STATE_DENIED
    assert result.subscription.last_request_status_code == 400
    assert result.subscription.last_request_error == "bad topic"


@pytest.mark.django_db
def test_request_websub_subscription_preserves_active_subscription_on_renewal_failure(subscription):
    subscription.secret = STORED_SECRET
    subscription.confirmed_lease_seconds = 3600
    subscription.lease_expires_at = timezone.now() + timedelta(seconds=3600)
    subscription.save()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="try later")

    http_client = httpx.Client(transport=httpx.MockTransport(handler))

    result = request_websub_subscription(
        subscription.topic_url,
        subscription.hub_url,
        callback_base_url="https://example.org/indieweb/websub",
        client=http_client,
    )

    result.subscription.refresh_from_db()
    assert result.success is False
    assert result.subscription.state == WebSubSubscription.STATE_ACTIVE
    assert result.subscription.pending_mode == ""
    assert result.subscription.get_secret() == STORED_SECRET
    assert result.subscription.confirmed_lease_seconds == 3600
    assert result.subscription.lease_expires_at is not None
    assert result.subscription.last_request_status_code == 503
    assert result.subscription.last_request_error == "try later"


@pytest.mark.django_db
def test_request_websub_subscription_restores_pending_secret_on_renewal_failure(subscription):
    subscription.secret = OLD_SECRET
    subscription.confirmed_lease_seconds = 3600
    subscription.lease_expires_at = timezone.now() + timedelta(seconds=3600)
    subscription.save()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="try later")

    http_client = httpx.Client(transport=httpx.MockTransport(handler))

    result = request_websub_subscription(
        subscription.topic_url,
        subscription.hub_url,
        callback_base_url="https://example.org/indieweb/websub",
        secret=NEW_SECRET,
        client=http_client,
    )

    result.subscription.refresh_from_db()
    assert result.success is False
    assert result.subscription.state == WebSubSubscription.STATE_ACTIVE
    assert result.subscription.pending_mode == ""
    assert result.subscription.get_secret() == OLD_SECRET
    assert result.subscription.pending_secret == ""
    assert result.subscription.pending_secret_set is False


@pytest.mark.django_db
def test_request_websub_subscription_keeps_old_secret_until_renewal_verification(subscription):
    subscription.secret = OLD_SECRET
    subscription.confirmed_lease_seconds = 3600
    subscription.lease_expires_at = timezone.now() + timedelta(seconds=3600)
    subscription.save()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))

    result = request_websub_subscription(
        subscription.topic_url,
        subscription.hub_url,
        callback_base_url="https://example.org/indieweb/websub",
        secret=NEW_SECRET,
        client=http_client,
    )

    result.subscription.refresh_from_db()
    assert result.success is True
    assert result.subscription.state == WebSubSubscription.STATE_ACTIVE
    assert result.subscription.pending_mode == WebSubSubscription.MODE_SUBSCRIBE
    assert result.subscription.get_secret() == OLD_SECRET
    assert result.subscription.get_pending_secret() == NEW_SECRET
    assert result.subscription.pending_secret_set is True


@pytest.mark.django_db
def test_request_websub_subscription_preserves_stored_secret_when_renewal_omits_secret(subscription):
    subscription.secret = STORED_SECRET
    subscription.save()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))

    result = request_websub_subscription(
        subscription.topic_url,
        subscription.hub_url,
        callback_base_url="https://example.org/indieweb/websub",
        client=http_client,
    )

    result.subscription.refresh_from_db()
    assert result.success is True
    assert result.subscription.state == WebSubSubscription.STATE_ACTIVE
    assert result.subscription.pending_mode == WebSubSubscription.MODE_SUBSCRIBE
    assert result.subscription.get_secret() == STORED_SECRET
    assert result.subscription.pending_secret == ""
    assert result.subscription.pending_secret_set is False


@pytest.mark.django_db
def test_request_websub_subscription_clears_stale_pending_secret_when_renewal_omits_secret(subscription):
    subscription.secret = ACTIVE_SECRET
    subscription.pending_secret = "stale-secret-value-20"
    subscription.pending_secret_set = True
    subscription.save()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))

    result = request_websub_subscription(
        subscription.topic_url,
        subscription.hub_url,
        callback_base_url="https://example.org/indieweb/websub",
        client=http_client,
    )

    result.subscription.refresh_from_db()
    assert result.success is True
    assert result.subscription.get_secret() == ACTIVE_SECRET
    assert result.subscription.pending_secret == ""
    assert result.subscription.pending_secret_set is False


@pytest.mark.django_db
def test_request_websub_subscription_rejects_empty_secret(subscription):
    subscription.secret = ACTIVE_SECRET
    subscription.save()

    with pytest.raises(ValueError, match="secret must not be empty"):
        request_websub_subscription(
            subscription.topic_url,
            subscription.hub_url,
            callback_base_url="https://example.org/indieweb/websub",
            secret="",
        )

    subscription.refresh_from_db()
    assert subscription.get_secret() == ACTIVE_SECRET
    assert subscription.pending_secret == ""
    assert subscription.pending_secret_set is False


@pytest.mark.django_db
def test_request_websub_subscription_rejects_overlong_secret():
    with pytest.raises(ValueError, match="secret must be at most 200 bytes"):
        request_websub_subscription(
            "https://source.example/feed",
            "https://hub.example/sub",
            callback_base_url="https://example.org/indieweb/websub",
            secret="s" * 201,
        )
    assert not WebSubSubscription.objects.filter(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
    ).exists()


@pytest.mark.django_db
def test_request_websub_subscription_rejects_multibyte_secret_over_byte_limit():
    with pytest.raises(ValueError, match="secret must be at most 200 bytes"):
        request_websub_subscription(
            "https://source.example/feed",
            "https://hub.example/sub",
            callback_base_url="https://example.org/indieweb/websub",
            secret="🙂" * 51,
        )

    assert not WebSubSubscription.objects.filter(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
    ).exists()


@pytest.mark.django_db
def test_request_websub_subscription_rejects_reserved_secret_prefix():
    with pytest.raises(ValueError, match="reserved prefix"):
        request_websub_subscription(
            "https://source.example/feed",
            "https://hub.example/sub",
            callback_base_url="https://example.org/indieweb/websub",
            secret="fernet$secret-value-20x",
        )

    assert not WebSubSubscription.objects.filter(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
    ).exists()


@pytest.mark.django_db
def test_request_websub_subscription_rejects_short_secret():
    with pytest.raises(ValueError, match="secret must be at least 20 bytes"):
        request_websub_subscription(
            "https://source.example/feed",
            "https://hub.example/sub",
            callback_base_url="https://example.org/indieweb/websub",
            secret="too-short",
        )

    assert not WebSubSubscription.objects.filter(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
    ).exists()


@pytest.mark.django_db
def test_request_websub_unsubscribe_posts_unsubscribe_form(subscription):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(202)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))

    result = request_websub_subscription(
        subscription.topic_url,
        subscription.hub_url,
        mode=WebSubSubscription.MODE_UNSUBSCRIBE,
        callback_base_url="https://example.org/indieweb/websub",
        client=http_client,
    )

    result.subscription.refresh_from_db()
    body = parse_qs(requests[0].content.decode("ascii"))
    assert result.success is True
    assert result.subscription.state == WebSubSubscription.STATE_PENDING_UNSUBSCRIBE
    assert result.subscription.pending_mode == WebSubSubscription.MODE_UNSUBSCRIBE
    assert body == {
        "hub.mode": ["unsubscribe"],
        "hub.callback": [f"https://example.org/indieweb/websub/{subscription.callback_token}/"],
        "hub.topic": [subscription.topic_url],
    }


@pytest.mark.django_db
def test_build_websub_callback_url_requires_absolute_base(subscription):
    with pytest.raises(ValueError, match="callback base URL"):
        build_websub_callback_url(subscription, "/indieweb/websub")


@pytest.mark.django_db
def test_callback_verification_confirms_subscribe_and_echoes_challenge(client):
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_PENDING_SUBSCRIBE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
        requested_lease_seconds=3600,
    )
    before = timezone.now()

    response = client.get(
        _callback_url(subscription),
        data={
            "hub.mode": "subscribe",
            "hub.topic": subscription.topic_url,
            "hub.challenge": "abc123",
            "hub.lease_seconds": "7200",
        },
    )

    subscription.refresh_from_db()
    assert response.status_code == 200
    assert response.content == b"abc123"
    assert response["Content-Type"].startswith("text/plain")
    assert subscription.state == WebSubSubscription.STATE_ACTIVE
    assert subscription.pending_mode == ""
    assert subscription.pending_secret == ""
    assert subscription.pending_secret_set is False
    assert subscription.confirmed_lease_seconds == 7200
    assert subscription.lease_expires_at is not None
    assert subscription.lease_expires_at > before
    assert subscription.last_challenge == "abc123"
    assert subscription.last_verified_at is not None


@pytest.mark.django_db
def test_confirmed_lease_bounds_clamps_min_below_floor(settings, client):
    """An ``INDIEWEB_WEBSUB_MIN_LEASE_SECONDS`` below the documented floor is pulled up.

    Regression: previously any positive integer was accepted, so a misconfiguration of
    ``min=1`` would let a hub-supplied 30-second lease pass through the
    ``min(max(...), ...)`` clamp untouched.
    """
    settings.INDIEWEB_WEBSUB_MIN_LEASE_SECONDS = 1

    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed-floor",
        state=WebSubSubscription.STATE_PENDING_SUBSCRIBE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
    )

    response = client.get(
        _callback_url(subscription),
        data={
            "hub.mode": "subscribe",
            "hub.topic": subscription.topic_url,
            "hub.challenge": "abc123",
            "hub.lease_seconds": "30",
        },
    )

    subscription.refresh_from_db()
    assert response.status_code == 200
    # 30s below the 60s floor → clamped up to the floor (not to the unsafe min=1).
    assert subscription.confirmed_lease_seconds == 60


@pytest.mark.django_db
def test_confirm_renewal_does_not_shrink_active_lease_below_half(client):
    """A hostile hub cannot floor an already-active lease to <50% of the prior value."""
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed-ratchet",
        state=WebSubSubscription.STATE_ACTIVE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
        confirmed_lease_seconds=24 * 60 * 60,  # 1 day prior
    )

    response = client.get(
        _callback_url(subscription),
        data={
            "hub.mode": "subscribe",
            "hub.topic": subscription.topic_url,
            "hub.challenge": "abc123",
            "hub.lease_seconds": "60",  # hub tries to floor to 60s
        },
    )

    subscription.refresh_from_db()
    assert response.status_code == 200
    # The new confirmed lease must not drop below half of the prior value.
    assert subscription.confirmed_lease_seconds >= 12 * 60 * 60


@pytest.mark.django_db
def test_confirm_truncates_oversized_hub_challenge(client):
    """An oversized ``hub.challenge`` must be truncated to the field's declared max length."""
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed-truncate",
        state=WebSubSubscription.STATE_PENDING_SUBSCRIBE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
    )
    big_challenge = "X" * 5000
    response = client.get(
        _callback_url(subscription),
        data={
            "hub.mode": "subscribe",
            "hub.topic": subscription.topic_url,
            "hub.challenge": big_challenge,
            "hub.lease_seconds": "3600",
        },
    )
    subscription.refresh_from_db()
    assert response.status_code == 200
    max_length = WebSubSubscription._meta.get_field("last_challenge").max_length
    assert len(subscription.last_challenge) == max_length


@pytest.mark.django_db
def test_confirmed_lease_bounds_clamps_max_above_ceiling(settings, client):
    """An ``INDIEWEB_WEBSUB_MAX_LEASE_SECONDS`` above the documented ceiling is pulled down.

    Regression: previously a misconfigured ``max=10**12`` would let a hub-supplied
    multi-thousand-year lease pass through the clamp unchanged.
    """
    settings.INDIEWEB_WEBSUB_MAX_LEASE_SECONDS = 10**12

    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed-ceiling",
        state=WebSubSubscription.STATE_PENDING_SUBSCRIBE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
    )

    response = client.get(
        _callback_url(subscription),
        data={
            "hub.mode": "subscribe",
            "hub.topic": subscription.topic_url,
            "hub.challenge": "abc123",
            "hub.lease_seconds": str(10**11),
        },
    )

    subscription.refresh_from_db()
    assert response.status_code == 200
    # 10**11s above the 90-day ceiling (7,776,000s) → clamped down to the ceiling.
    assert subscription.confirmed_lease_seconds == 90 * 24 * 60 * 60


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("lease_seconds", "expected_confirmed"),
    [
        ("60", 300),
        ("9999999", 2592000),
    ],
)
def test_callback_verification_clamps_confirmed_lease(client, lease_seconds, expected_confirmed):
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url=f"https://source.example/feed-{lease_seconds}",
        state=WebSubSubscription.STATE_PENDING_SUBSCRIBE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
    )

    response = client.get(
        _callback_url(subscription),
        data={
            "hub.mode": "subscribe",
            "hub.topic": subscription.topic_url,
            "hub.challenge": "abc123",
            "hub.lease_seconds": lease_seconds,
        },
    )

    subscription.refresh_from_db()
    assert response.status_code == 200
    assert subscription.confirmed_lease_seconds == expected_confirmed


@pytest.mark.django_db
def test_callback_verification_applies_pending_secret(client):
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_ACTIVE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
        secret=OLD_SECRET,
        pending_secret=NEW_SECRET,
        pending_secret_set=True,
    )

    response = client.get(
        _callback_url(subscription),
        data={
            "hub.mode": "subscribe",
            "hub.topic": subscription.topic_url,
            "hub.challenge": "abc123",
        },
    )

    subscription.refresh_from_db()
    assert response.status_code == 200
    assert subscription.state == WebSubSubscription.STATE_ACTIVE
    assert subscription.get_secret() == NEW_SECRET
    assert subscription.pending_secret == ""
    assert subscription.pending_secret_set is False
    assert subscription.pending_mode == ""


@pytest.mark.django_db
def test_callback_verification_applies_empty_pending_secret(client):
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_ACTIVE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
        secret=OLD_SECRET,
        pending_secret="",
        pending_secret_set=True,
    )

    response = client.get(
        _callback_url(subscription),
        data={
            "hub.mode": "subscribe",
            "hub.topic": subscription.topic_url,
            "hub.challenge": "abc123",
        },
    )

    subscription.refresh_from_db()
    assert response.status_code == 200
    assert subscription.state == WebSubSubscription.STATE_ACTIVE
    assert subscription.secret == ""
    assert subscription.pending_secret == ""
    assert subscription.pending_secret_set is False
    assert subscription.pending_mode == ""


@pytest.mark.django_db
def test_callback_verification_rejects_mismatched_topic_without_state_change(client):
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_PENDING_SUBSCRIBE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
    )

    response = client.get(
        _callback_url(subscription),
        data={
            "hub.mode": "subscribe",
            "hub.topic": "https://attacker.example/feed",
            "hub.challenge": "abc123",
        },
    )

    subscription.refresh_from_db()
    assert response.status_code == 400
    assert subscription.state == WebSubSubscription.STATE_PENDING_SUBSCRIBE
    assert subscription.pending_mode == WebSubSubscription.MODE_SUBSCRIBE
    assert subscription.last_verified_at is None


@pytest.mark.django_db
def test_callback_denial_records_pending_subscribe_reason(client):
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_PENDING_SUBSCRIBE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
        requested_lease_seconds=3600,
        pending_secret=NEW_SECRET,
        pending_secret_set=True,
        last_request_error="previous outbound diagnostic",
    )

    response = client.get(
        _callback_url(subscription),
        data={
            "hub.mode": "denied",
            "hub.topic": subscription.topic_url,
            "hub.reason": "topic no longer available",
        },
    )

    subscription.refresh_from_db()
    assert response.status_code == 204
    assert subscription.state == WebSubSubscription.STATE_DENIED
    assert subscription.pending_mode == ""
    assert subscription.pending_secret == ""
    assert subscription.pending_secret_set is False
    assert subscription.confirmed_lease_seconds is None
    assert subscription.lease_expires_at is None
    assert subscription.last_denied_at is not None
    assert subscription.last_denied_mode == WebSubSubscription.MODE_SUBSCRIBE
    assert subscription.last_denial_reason == "topic no longer available"
    assert subscription.last_request_error == "previous outbound diagnostic"


@pytest.mark.django_db
def test_callback_denial_rejects_mismatched_topic_without_state_change(client):
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_PENDING_SUBSCRIBE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
    )

    response = client.get(
        _callback_url(subscription),
        data={
            "hub.mode": "denied",
            "hub.topic": "https://attacker.example/feed",
            "hub.reason": "nope",
        },
    )

    subscription.refresh_from_db()
    assert response.status_code == 400
    assert subscription.state == WebSubSubscription.STATE_PENDING_SUBSCRIBE
    assert subscription.pending_mode == WebSubSubscription.MODE_SUBSCRIBE
    assert subscription.last_denied_at is None
    assert subscription.last_denial_reason == ""


@pytest.mark.django_db
def test_callback_denial_for_active_renewal_preserves_current_subscription(client, subscription):
    lease_expires_at = timezone.now() + timedelta(seconds=3600)
    subscription.state = WebSubSubscription.STATE_ACTIVE
    subscription.pending_mode = WebSubSubscription.MODE_SUBSCRIBE
    subscription.secret = ACTIVE_SECRET
    subscription.pending_secret = NEW_SECRET
    subscription.pending_secret_set = True
    subscription.confirmed_lease_seconds = 3600
    subscription.lease_expires_at = lease_expires_at
    subscription.save()

    response = client.get(
        _callback_url(subscription),
        data={
            "hub.mode": "denied",
            "hub.topic": subscription.topic_url,
            "hub.reason": "renewal refused",
        },
    )

    subscription.refresh_from_db()
    assert response.status_code == 204
    assert subscription.state == WebSubSubscription.STATE_ACTIVE
    assert subscription.get_secret() == ACTIVE_SECRET
    assert subscription.pending_secret_set is True
    assert subscription.get_pending_secret() == NEW_SECRET
    assert subscription.confirmed_lease_seconds == 3600
    assert subscription.lease_expires_at == lease_expires_at
    assert subscription.last_denied_mode == WebSubSubscription.MODE_SUBSCRIBE
    assert subscription.last_denial_reason == "renewal refused"
    assert subscription.pending_mode == ""


@pytest.mark.django_db
def test_callback_denial_for_pending_unsubscribe_restores_active_subscription(client, subscription):
    lease_expires_at = timezone.now() + timedelta(seconds=3600)
    subscription.state = WebSubSubscription.STATE_PENDING_UNSUBSCRIBE
    subscription.pending_mode = WebSubSubscription.MODE_UNSUBSCRIBE
    subscription.confirmed_lease_seconds = 3600
    subscription.lease_expires_at = lease_expires_at
    subscription.save()

    response = client.get(
        _callback_url(subscription),
        data={
            "hub.mode": "denied",
            "hub.topic": subscription.topic_url,
            "hub.reason": "unsubscribe not recognized",
        },
    )

    subscription.refresh_from_db()
    assert response.status_code == 204
    assert subscription.state == WebSubSubscription.STATE_ACTIVE
    assert subscription.pending_mode == ""
    assert subscription.confirmed_lease_seconds == 3600
    assert subscription.lease_expires_at == lease_expires_at
    assert subscription.last_denied_mode == WebSubSubscription.MODE_UNSUBSCRIBE
    assert subscription.last_denial_reason == "unsubscribe not recognized"


@pytest.mark.django_db
def test_callback_denial_requires_pending_request(client, subscription):
    response = client.get(
        _callback_url(subscription),
        data={
            "hub.mode": "denied",
            "hub.topic": subscription.topic_url,
            "hub.reason": "late denial",
        },
    )

    subscription.refresh_from_db()
    assert response.status_code == 400
    assert subscription.state == WebSubSubscription.STATE_ACTIVE
    assert subscription.last_denied_at is None


@pytest.mark.django_db
def test_callback_verification_confirms_unsubscribe(client, subscription):
    subscription.state = WebSubSubscription.STATE_PENDING_UNSUBSCRIBE
    subscription.pending_mode = WebSubSubscription.MODE_UNSUBSCRIBE
    subscription.confirmed_lease_seconds = 3600
    subscription.lease_expires_at = timezone.now() + timedelta(seconds=3600)
    subscription.save()

    response = client.get(
        _callback_url(subscription),
        data={
            "hub.mode": "unsubscribe",
            "hub.topic": subscription.topic_url,
            "hub.challenge": "bye",
        },
    )

    subscription.refresh_from_db()
    assert response.status_code == 200
    assert response.content == b"bye"
    assert subscription.state == WebSubSubscription.STATE_UNSUBSCRIBED
    assert subscription.pending_secret == ""
    assert subscription.pending_secret_set is False
    assert subscription.confirmed_lease_seconds is None
    assert subscription.lease_expires_at is None


@pytest.mark.django_db
def test_callback_post_records_delivery_and_calls_hook(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"
    body = b"<feed><updated>now</updated></feed>"

    response = _post_delivery(client, subscription, data=body, content_type="application/atom+xml")

    subscription.refresh_from_db()
    assert response.status_code == 204
    assert subscription.last_delivery_status_code == 204
    assert subscription.last_delivery_content_type == "application/atom+xml"
    assert subscription.last_delivery_size == len(body)
    assert subscription.last_delivery_digest == hashlib.sha256(body).hexdigest()
    assert subscription.last_accepted_delivery_digest == subscription.last_delivery_digest
    assert subscription.last_accepted_delivery_at is not None
    attempt = WebSubDeliveryAttempt.objects.get(subscription=subscription)
    assert attempt.content_type == "application/atom+xml"
    assert attempt.size == len(body)
    assert attempt.digest == subscription.last_delivery_digest
    assert attempt.status_code == 204
    assert attempt.error == ""
    assert websub_hooks.DELIVERIES[0]["subscription_id"] == subscription.pk
    assert websub_hooks.DELIVERIES[0]["topic_url"] == subscription.topic_url
    assert websub_hooks.DELIVERIES[0]["body"] == body


@pytest.mark.django_db
def test_callback_post_is_csrf_exempt(settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"
    csrf_client = Client(enforce_csrf_checks=True)

    response = _post_delivery(csrf_client, subscription, data=b"<feed/>", content_type="application/atom+xml")

    assert response.status_code == 204
    assert len(websub_hooks.DELIVERIES) == 1


@pytest.mark.django_db
def test_callback_post_requires_self_topic_link(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"

    response = client.post(
        _callback_url(subscription),
        data=b"<feed/>",
        content_type="application/atom+xml",
        HTTP_LINK='<https://attacker.example/feed>; rel="self"',
    )

    subscription.refresh_from_db()
    assert response.status_code == 400
    assert subscription.last_delivery_status_code == 400
    assert subscription.last_delivery_error == "topic link mismatch"
    assert websub_hooks.DELIVERIES == []


@pytest.mark.django_db
def test_callback_post_topic_link_check_can_be_disabled(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_REQUIRE_TOPIC_LINK = False

    response = client.post(_callback_url(subscription), data=b"<feed/>", content_type="application/atom+xml")

    assert response.status_code == 204


def test_delivery_topic_link_parser_handles_quoted_commas(subscription):
    headers = {
        "Link": (
            f'<https://other.example/feed>; rel="self"; title="not, this", <{subscription.topic_url}>; rel="hub self"'
        )
    }

    assert delivery_topic_link_allowed(headers, subscription.topic_url) is True


@pytest.mark.django_db
def test_callback_post_validates_signed_delivery(client, subscription):
    subscription.secret = SHARED_SECRET
    subscription.save()
    body = b'{"items":[]}'
    digest = hmac.new(SHARED_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()

    response = _post_delivery(
        client,
        subscription,
        data=body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=f"sha256={digest}",
    )

    subscription.refresh_from_db()
    assert response.status_code == 204
    assert subscription.last_delivery_signature_algorithm == "sha256"


@pytest.mark.django_db
def test_callback_post_requires_signature_when_configured(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES = True

    response = client.post(_callback_url(subscription), data=b'{"items":[]}', content_type="application/json")

    subscription.refresh_from_db()
    assert response.status_code == 403
    assert subscription.last_delivery_status_code == 403
    assert subscription.last_delivery_error == "invalid signature"


@pytest.mark.django_db
@pytest.mark.parametrize("signature_header", [None, "sha256=bad"])
def test_callback_post_rejects_missing_or_bad_signature(client, subscription, signature_header):
    subscription.secret = SHARED_SECRET
    subscription.save()
    headers = {}
    if signature_header is not None:
        headers["HTTP_X_HUB_SIGNATURE_256"] = signature_header

    response = _post_delivery(
        client,
        subscription,
        data=b'{"items":[]}',
        content_type="application/json",
        **headers,
    )

    subscription.refresh_from_db()
    assert response.status_code == 403
    assert subscription.last_delivery_status_code == 403
    assert subscription.last_delivery_error == "invalid signature"
    assert WebSubDeliveryAttempt.objects.filter(
        subscription=subscription,
        status_code=403,
        error="invalid signature",
    ).exists()


@pytest.mark.django_db
def test_callback_post_reports_secret_decryption_failure(client, settings, subscription):
    subscription.secret = SHARED_SECRET
    subscription.save()
    settings.SECRET_KEY = "rotated-secret-key"

    response = _post_delivery(
        client,
        subscription,
        data=b'{"items":[]}',
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256="sha256=bad",
    )

    subscription.refresh_from_db()
    assert response.status_code == 403
    assert subscription.last_delivery_status_code == 403
    assert subscription.last_delivery_error == "secret decryption failed"


@pytest.mark.django_db
def test_validate_websub_delivery_signature_accepts_legacy_signature_header_when_enabled(settings, subscription):
    settings.INDIEWEB_WEBSUB_ALLOW_SHA1_SIGNATURES = True
    subscription.secret = SHARED_SECRET
    body = b"<feed/>"
    digest = hmac.new(SHARED_SECRET.encode("utf-8"), body, hashlib.sha1).hexdigest()

    algorithm = validate_websub_delivery_signature(subscription, body, {"X-Hub-Signature": f"sha1={digest}"})

    assert algorithm == "sha1"


@pytest.mark.django_db
def test_validate_websub_delivery_signature_rejects_legacy_signature_header_by_default(subscription):
    subscription.secret = SHARED_SECRET
    body = b"<feed/>"
    digest = hmac.new(SHARED_SECRET.encode("utf-8"), body, hashlib.sha1).hexdigest()

    with pytest.raises(ValueError, match="supported algorithm"):
        validate_websub_delivery_signature(subscription, body, {"X-Hub-Signature": f"sha1={digest}"})


@pytest.mark.django_db
def test_validate_websub_delivery_signature_prefers_strongest_header(settings, subscription):
    settings.INDIEWEB_WEBSUB_ALLOW_SHA1_SIGNATURES = True
    subscription.secret = SHARED_SECRET
    body = b"<feed/>"
    sha1_digest = hmac.new(SHARED_SECRET.encode("utf-8"), body, hashlib.sha1).hexdigest()

    with pytest.raises(ValueError, match="did not validate"):
        validate_websub_delivery_signature(
            subscription,
            body,
            {
                "X-Hub-Signature-256": "sha256=bad",
                "X-Hub-Signature": f"sha1={sha1_digest}",
            },
        )


@pytest.mark.django_db
def test_callback_post_rejects_duplicate_delivery_within_replay_window(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"
    body = b"<feed><id>1</id></feed>"

    first_response = _post_delivery(client, subscription, data=body, content_type="application/atom+xml")
    second_response = _post_delivery(client, subscription, data=body, content_type="application/atom+xml")

    subscription.refresh_from_db()
    assert first_response.status_code == 204
    assert second_response.status_code == 409
    assert subscription.last_delivery_status_code == 409
    assert subscription.last_delivery_error == "replay detected"
    assert subscription.last_accepted_delivery_digest == hashlib.sha256(body).hexdigest()
    assert len(websub_hooks.DELIVERIES) == 1
    assert WebSubDeliveryAttempt.objects.filter(subscription=subscription, status_code=204).count() == 1
    assert WebSubDeliveryAttempt.objects.filter(subscription=subscription, status_code=409).count() == 1


@pytest.mark.django_db
def test_callback_post_rejects_a_b_a_replay_within_replay_window(client, settings, subscription):
    """A captured payload replayed after a different legitimate payload is still rejected."""
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"
    body_a = b"<feed><id>A</id></feed>"
    body_b = b"<feed><id>B</id></feed>"

    first_a = _post_delivery(client, subscription, data=body_a, content_type="application/atom+xml")
    accept_b = _post_delivery(client, subscription, data=body_b, content_type="application/atom+xml")
    replay_a = _post_delivery(client, subscription, data=body_a, content_type="application/atom+xml")

    subscription.refresh_from_db()
    assert first_a.status_code == 204
    assert accept_b.status_code == 204
    assert replay_a.status_code == 409
    assert subscription.last_delivery_status_code == 409
    assert subscription.last_delivery_error == "replay detected"
    # Single-row diagnostic remains the most-recent accepted digest.
    assert subscription.last_accepted_delivery_digest == hashlib.sha256(body_b).hexdigest()
    digests = set(
        WebSubAcceptedDelivery.objects.filter(subscription=subscription).values_list("body_digest", flat=True)
    )
    assert hashlib.sha256(body_a).hexdigest() in digests
    assert hashlib.sha256(body_b).hexdigest() in digests
    assert len(websub_hooks.DELIVERIES) == 2


@pytest.mark.django_db
def test_accept_websub_delivery_evicts_oldest_history_when_cap_exceeded(settings, subscription):
    """Beyond the configured cap the oldest digest is dropped; replaying it is no longer rejected."""
    settings.INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX = 3
    digests = [hashlib.sha256(f"<feed><id>{i}</id></feed>".encode()).hexdigest() for i in range(4)]

    for digest in digests:
        assert accept_websub_delivery(subscription, digest) is True

    remaining = list(
        WebSubAcceptedDelivery.objects.filter(subscription=subscription).values_list("body_digest", flat=True)
    )
    assert len(remaining) == 3
    # The oldest-accepted digest has been evicted; the unique constraint no
    # longer rejects it, so the gate accepts a fresh insertion.
    assert digests[0] not in remaining
    assert accept_websub_delivery(subscription, digests[0]) is True
    # Newer entries are still tracked and the gate returns ``False`` on retry.
    assert accept_websub_delivery(subscription, digests[-1]) is False


@pytest.mark.django_db
def test_accept_websub_delivery_prunes_entries_outside_replay_window(settings, subscription):
    """Rows older than the replay window are pruned and no longer count as replays."""
    settings.INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS = 60
    digest_old = hashlib.sha256(b"<feed><id>old</id></feed>").hexdigest()
    digest_new = hashlib.sha256(b"<feed><id>new</id></feed>").hexdigest()

    stale_at = timezone.now() - timedelta(seconds=120)
    WebSubAcceptedDelivery.objects.create(
        subscription=subscription,
        body_digest=digest_old,
        accepted_at=stale_at,
    )

    # A fresh accept of the same body must succeed because the stale row is
    # pruned before the unique-constraint insert runs.
    assert accept_websub_delivery(subscription, digest_old) is True
    assert accept_websub_delivery(subscription, digest_new) is True
    remaining = set(
        WebSubAcceptedDelivery.objects.filter(subscription=subscription).values_list("body_digest", flat=True)
    )
    assert remaining == {digest_old, digest_new}


@pytest.mark.django_db
def test_accept_websub_delivery_treats_empty_history_max_as_default(settings, subscription):
    """An empty ``INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX`` falls back to the default cap.

    Regression: ``_positive_int`` translates an empty string to ``None``; without the
    explicit fallback the helper would have returned ``None`` and silently disabled the
    cap, allowing the cache to grow unbounded. This mirrors
    ``test_notify_hubs_treats_empty_string_max_bytes_as_default`` for the hub-response cap.
    """
    settings.INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX = ""
    # Many distinct payloads: the default cap (64) must apply.
    digests = [hashlib.sha256(f"<feed><id>{i}</id></feed>".encode()).hexdigest() for i in range(70)]

    for digest in digests:
        assert accept_websub_delivery(subscription, digest) is True

    assert WebSubAcceptedDelivery.objects.filter(subscription=subscription).count() == 64


@pytest.mark.django_db
def test_replay_history_cap_zero_means_unbounded_by_count(settings, subscription):
    """Setting ``INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX = 0`` disables count-based eviction.

    Pruning then happens purely via
    ``INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS``: with a generous window
    every distinct accepted delivery within the window is retained.
    """
    settings.INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX = 0
    settings.INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS = 3600

    digests = [hashlib.sha256(f"<feed><id>{i}</id></feed>".encode()).hexdigest() for i in range(100)]
    for digest in digests:
        assert accept_websub_delivery(subscription, digest) is True

    assert WebSubAcceptedDelivery.objects.filter(subscription=subscription).count() == 100
    # Each accepted digest is still tracked, so a replay of any of them is
    # rejected by the unique-constraint gate.
    assert accept_websub_delivery(subscription, digests[0]) is False
    assert accept_websub_delivery(subscription, digests[-1]) is False


@pytest.mark.django_db
def test_callback_post_applies_delivery_size_limit(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_MAX_BYTES = 4

    response = client.post(_callback_url(subscription), data=b"12345", content_type="application/atom+xml")

    subscription.refresh_from_db()
    assert response.status_code == 413
    assert subscription.last_delivery_status_code == 413


@pytest.mark.django_db
def test_callback_post_rejects_oversized_content_length_before_body_read(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_MAX_BYTES = 4

    response = client.post(
        _callback_url(subscription),
        data=b"12345",
        content_type="application/atom+xml",
        CONTENT_LENGTH="5",
    )

    subscription.refresh_from_db()
    assert response.status_code == 413
    assert subscription.last_delivery_status_code == 413
    assert subscription.last_delivery_size == 0


@pytest.mark.django_db
def test_callback_post_invalid_content_length_falls_back_to_body_limit(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_MAX_BYTES = 4

    response = client.post(
        _callback_url(subscription),
        data=b"12345",
        content_type="application/atom+xml",
        CONTENT_LENGTH="not-a-number",
    )

    subscription.refresh_from_db()
    if django.VERSION >= (6, 1):
        # Django 6.1 treats a malformed Content-Length as 0 itself, so the body
        # reads as empty and the delivery is rejected for the missing topic
        # Link header instead of tripping the size limit fallback.
        assert response.status_code == 400
        assert subscription.last_delivery_status_code == 400
        assert subscription.last_delivery_size == 0
    else:
        assert response.status_code == 413
        assert subscription.last_delivery_status_code == 413
        assert subscription.last_delivery_size == 5


@pytest.mark.django_db
def test_callback_post_uses_default_delivery_size_limit_when_setting_is_invalid(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_MAX_BYTES = "bad"

    response = _post_delivery(client, subscription, data=b"<feed/>", content_type="application/atom+xml")

    subscription.refresh_from_db()
    assert response.status_code == 204
    assert subscription.last_delivery_status_code == 204


@pytest.mark.django_db
def test_callback_post_treats_empty_string_max_bytes_as_default(client, settings, subscription):
    """An empty ``INDIEWEB_WEBSUB_DELIVERY_MAX_BYTES`` falls back to the 1 MiB default.

    Regression: ``_positive_int`` translates the empty string to ``None``; without an
    explicit fallback ``_delivery_max_bytes()`` would have returned ``None`` and
    silently disabled the per-callback delivery body cap. The body is one byte over
    the default cap, so a "cap disabled" regression would let the request succeed
    (204) instead of failing closed (413). Mirrors
    ``test_notify_hubs_treats_empty_string_max_bytes_as_default`` for the hub-response
    cap and ``test_record_websub_delivery_treats_empty_history_max_as_default`` for
    the replay-history cap.
    """
    settings.INDIEWEB_WEBSUB_DELIVERY_MAX_BYTES = ""
    oversized_body = b"x" * (1024 * 1024 + 1)

    response = client.post(
        _callback_url(subscription),
        data=oversized_body,
        content_type="application/atom+xml",
    )

    subscription.refresh_from_db()
    assert response.status_code == 413
    assert subscription.last_delivery_status_code == 413


@pytest.mark.django_db
def test_callback_post_applies_delivery_content_type_allowlist(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_ALLOWED_TYPES = ("application/atom+xml",)

    response = _post_delivery(client, subscription, data=b"{}", content_type="application/json")

    subscription.refresh_from_db()
    assert response.status_code == 415
    assert subscription.last_delivery_status_code == 415


@pytest.mark.django_db
def test_callback_post_allows_delivery_when_content_type_setting_is_invalid(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_ALLOWED_TYPES = object()

    response = _post_delivery(client, subscription, data=b"{}", content_type="application/json")

    subscription.refresh_from_db()
    assert response.status_code == 204
    assert subscription.last_delivery_status_code == 204


@pytest.mark.django_db
def test_callback_post_reports_delivery_hook_failure(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.failing_delivery"

    response = _post_delivery(client, subscription, data=b"<feed/>", content_type="application/atom+xml")

    subscription.refresh_from_db()
    assert response.status_code == 500
    assert subscription.last_delivery_status_code == 500
    assert subscription.last_delivery_error == "delivery hook failed"


@pytest.mark.django_db
def test_callback_post_enqueue_records_204_and_skips_sync_hook(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_ENQUEUE = "tests.websub_hooks.capture_enqueue"
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"
    body = b"<feed><updated>now</updated></feed>"

    response = _post_delivery(client, subscription, data=body, content_type="application/atom+xml")

    subscription.refresh_from_db()
    assert response.status_code == 204
    assert subscription.last_delivery_status_code == 204
    assert subscription.last_delivery_error == ""
    assert websub_hooks.DELIVERIES == []
    assert len(websub_hooks.ENQUEUED) == 1
    enqueued = websub_hooks.ENQUEUED[0]
    assert enqueued["subscription_id"] == subscription.pk
    assert enqueued["hub_url"] == subscription.hub_url
    assert enqueued["topic_url"] == subscription.topic_url
    assert enqueued["body"] == body
    assert isinstance(enqueued["headers"], dict)


@pytest.mark.django_db
def test_callback_post_reports_enqueue_failure(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_ENQUEUE = "tests.websub_hooks.failing_enqueue"
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"

    response = _post_delivery(client, subscription, data=b"<feed/>", content_type="application/atom+xml")

    subscription.refresh_from_db()
    assert response.status_code == 500
    assert subscription.last_delivery_status_code == 500
    assert subscription.last_delivery_error == "delivery enqueue failed"
    assert websub_hooks.DELIVERIES == []


@pytest.mark.django_db
def test_callback_post_reports_enqueue_import_failure(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_ENQUEUE = "tests.websub_hooks.does_not_exist"
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"

    response = _post_delivery(client, subscription, data=b"<feed/>", content_type="application/atom+xml")

    subscription.refresh_from_db()
    assert response.status_code == 500
    assert subscription.last_delivery_status_code == 500
    assert subscription.last_delivery_error == "delivery enqueue failed"
    assert websub_hooks.DELIVERIES == []


@pytest.mark.django_db
def test_callback_post_reports_enqueue_non_callable(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_ENQUEUE = "tests.websub_hooks.DELIVERIES"
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"

    response = _post_delivery(client, subscription, data=b"<feed/>", content_type="application/atom+xml")

    subscription.refresh_from_db()
    assert response.status_code == 500
    assert subscription.last_delivery_status_code == 500
    assert subscription.last_delivery_error == "delivery enqueue failed"
    assert websub_hooks.DELIVERIES == []


@pytest.mark.django_db
def test_websub_lease_helpers_list_expired_and_renewal_candidates():
    now = timezone.now()
    expired = WebSubSubscription.objects.create(
        hub_url="https://hub.example/expired",
        topic_url="https://source.example/expired",
        state=WebSubSubscription.STATE_ACTIVE,
        lease_expires_at=now - timedelta(minutes=1),
    )
    due = WebSubSubscription.objects.create(
        hub_url="https://hub.example/due",
        topic_url="https://source.example/due",
        state=WebSubSubscription.STATE_ACTIVE,
        lease_expires_at=now + timedelta(hours=12),
    )
    later = WebSubSubscription.objects.create(
        hub_url="https://hub.example/later",
        topic_url="https://source.example/later",
        state=WebSubSubscription.STATE_ACTIVE,
        lease_expires_at=now + timedelta(days=3),
    )
    WebSubSubscription.objects.create(
        hub_url="https://hub.example/pending",
        topic_url="https://source.example/pending",
        state=WebSubSubscription.STATE_PENDING_SUBSCRIBE,
        lease_expires_at=now - timedelta(minutes=1),
    )

    assert list(get_websub_expired_subscriptions(now=now)) == [expired]
    assert list(get_websub_renewal_candidates(within=timedelta(days=1), now=now)) == [expired, due]
    summaries = summarize_websub_leases(within=timedelta(days=1), now=now)
    assert [summary.subscription_id for summary in summaries] == [expired.pk, due.pk]
    assert summaries[0].expired is True
    assert summaries[1].expired is False
    assert later not in get_websub_renewal_candidates(within=timedelta(days=1), now=now)


@pytest.mark.django_db
def test_websub_lease_helpers_reject_negative_window():
    with pytest.raises(ValueError, match="non-negative"):
        get_websub_renewal_candidates(within=timedelta(seconds=-1))

    with pytest.raises(ValueError, match="non-negative"):
        summarize_websub_leases(within=timedelta(seconds=-1))


@pytest.mark.django_db
def test_websub_subscriptions_command_lists_lease_attention():
    now = timezone.now()
    WebSubSubscription.objects.create(
        hub_url="https://hub.example/expired",
        topic_url="https://source.example/expired",
        state=WebSubSubscription.STATE_ACTIVE,
        lease_expires_at=now - timedelta(minutes=1),
    )
    WebSubSubscription.objects.create(
        hub_url="https://hub.example/due",
        topic_url="https://source.example/due",
        state=WebSubSubscription.STATE_ACTIVE,
        lease_expires_at=now + timedelta(hours=2),
    )
    WebSubSubscription.objects.create(
        hub_url="https://hub.example/later",
        topic_url="https://source.example/later",
        state=WebSubSubscription.STATE_ACTIVE,
        lease_expires_at=now + timedelta(days=2),
    )
    stdout = StringIO()

    call_command("websub_subscriptions", "--renewal-window-hours", "6", stdout=stdout)

    output = stdout.getvalue()
    assert "expired: #" in output
    assert "renewal_due: #" in output
    assert "https://source.example/expired" in output
    assert "https://source.example/due" in output
    assert "https://source.example/later" not in output


def test_subscription_with_secret_rejects_http_hub():
    from indieweb.websub import WebSubSecretRequiresHTTPSError, _post_subscription_request

    with pytest.raises(WebSubSecretRequiresHTTPSError):
        _post_subscription_request(
            hub_url="http://hub.example/",
            mode="subscribe",
            topic_url="https://topic.example/",
            callback_url="https://me.example/cb",
            secret="abc123" * 6,
            client=None,
        )


@pytest.mark.django_db
def test_callback_post_replay_does_not_re_invoke_hook(client, settings, subscription):
    """Replay returns 409 and the hook is invoked exactly once for the body digest.

    This proves the at-most-once-per-digest hook contract: the second identical
    delivery is rejected by the unique-constraint gate before any hook
    dispatch, so the configured hook only fires for the first acceptance.
    """
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"
    body = b"<feed><id>only-once</id></feed>"

    first = _post_delivery(client, subscription, data=body, content_type="application/atom+xml")
    second = _post_delivery(client, subscription, data=body, content_type="application/atom+xml")
    third = _post_delivery(client, subscription, data=body, content_type="application/atom+xml")

    assert first.status_code == 204
    assert second.status_code == 409
    assert third.status_code == 409
    assert len(websub_hooks.DELIVERIES) == 1


@pytest.mark.django_db
def test_callback_post_passes_body_digest_to_kwargs_hook(client, settings, subscription):
    """Hooks accepting ``**kwargs`` (the existing ``capture_delivery``) receive ``body_digest``."""
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"
    body = b"<feed><id>digest-via-kwargs</id></feed>"

    response = _post_delivery(client, subscription, data=body, content_type="application/atom+xml")

    assert response.status_code == 204
    assert len(websub_hooks.DELIVERIES) == 1
    assert websub_hooks.DELIVERIES[0]["body_digest"] == hashlib.sha256(body).hexdigest()


@pytest.mark.django_db
def test_callback_post_passes_body_digest_to_explicit_parameter_hook(client, settings, subscription):
    """Hooks with an explicit ``body_digest`` parameter receive it."""
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery_with_digest"
    body = b"<feed><id>digest-explicit</id></feed>"

    response = _post_delivery(client, subscription, data=body, content_type="application/atom+xml")

    assert response.status_code == 204
    assert len(websub_hooks.DELIVERIES) == 1
    assert websub_hooks.DELIVERIES[0]["body_digest"] == hashlib.sha256(body).hexdigest()


@pytest.mark.django_db
def test_callback_post_omits_body_digest_for_legacy_hook(client, settings, subscription):
    """Hooks with the legacy signature (no ``body_digest``, no ``**kwargs``) are called unchanged."""
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery_legacy"
    body = b"<feed><id>legacy</id></feed>"

    response = _post_delivery(client, subscription, data=body, content_type="application/atom+xml")

    assert response.status_code == 204
    assert len(websub_hooks.DELIVERIES) == 1
    assert "body_digest" not in websub_hooks.DELIVERIES[0]


def test_hook_accepts_body_digest_handles_inspect_failures():
    """Callables that ``inspect.signature`` cannot introspect fall back to legacy."""
    from indieweb.websub import _hook_accepts_body_digest

    # Many builtins (e.g. ``range``) raise ``ValueError`` from ``inspect.signature``
    # on older runtimes; on others they may succeed. Force the failure path
    # explicitly with a callable whose ``__signature__`` raises.
    class Bad:
        @property
        def __signature__(self):  # type: ignore[no-untyped-def]
            raise TypeError("no signature for you")

        def __call__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return None

    assert _hook_accepts_body_digest(Bad()) is False


def test_hook_accepts_body_digest_detects_explicit_parameter():
    """A function with an explicit ``body_digest`` parameter advertises it."""
    from indieweb.websub import _hook_accepts_body_digest

    def hook(*, subscription_id, hub_url, topic_url, body, headers, body_digest):  # type: ignore[no-untyped-def]
        pass

    assert _hook_accepts_body_digest(hook) is True


def test_hook_accepts_body_digest_detects_var_keyword():
    """A function that takes ``**kwargs`` is treated as accepting ``body_digest``."""
    from indieweb.websub import _hook_accepts_body_digest

    def hook(**kwargs):  # type: ignore[no-untyped-def]
        pass

    assert _hook_accepts_body_digest(hook) is True


def test_hook_accepts_body_digest_rejects_legacy_signature():
    """A function with neither ``body_digest`` nor ``**kwargs`` is treated as legacy."""
    from indieweb.websub import _hook_accepts_body_digest

    def hook(*, subscription_id, hub_url, topic_url, body, headers):  # type: ignore[no-untyped-def]
        pass

    assert _hook_accepts_body_digest(hook) is False


@pytest.mark.django_db
def test_delivery_is_replay_emits_deprecation_warning(subscription):
    """The legacy ``delivery_is_replay`` helper now emits a deprecation warning."""
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        delivery_is_replay(subscription, b"<feed/>")

    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


@pytest.mark.django_db
def test_accept_websub_delivery_window_disabled_accepts_all_duplicates(settings, subscription):
    """Disabling the replay window disables the unique-constraint gate too.

    ``INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS = 0`` is documented as
    "disable in-process replay detection". Identical deliveries must therefore
    be accepted unconditionally, with no row inserted into
    ``WebSubAcceptedDelivery``.
    """
    settings.INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS = 0
    digest = hashlib.sha256(b"<feed/>").hexdigest()

    assert accept_websub_delivery(subscription, digest) is True
    assert accept_websub_delivery(subscription, digest) is True
    assert WebSubAcceptedDelivery.objects.filter(subscription=subscription).count() == 0


@pytest.mark.django_db
def test_replay_window_disabled_accepts_all_duplicates(client, settings, subscription):
    """When the replay window is disabled, callback POSTs accept duplicates and the hook fires every time."""
    settings.INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS = 0
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"
    body = b"<feed><id>dup</id></feed>"

    first = _post_delivery(client, subscription, data=body, content_type="application/atom+xml")
    second = _post_delivery(client, subscription, data=body, content_type="application/atom+xml")

    assert first.status_code == 204
    assert second.status_code == 204
    assert len(websub_hooks.DELIVERIES) == 2
    assert WebSubAcceptedDelivery.objects.filter(subscription=subscription).count() == 0


@pytest.mark.django_db
def test_concurrent_identical_deliveries_dispatch_hook_once(settings, subscription):
    """Two competing acceptance attempts: only one wins.

    Threaded ``live_server`` fixtures interact poorly with SQLite's
    single-writer model and pytest-django's transaction isolation, so this
    regression exercises the gate function directly. The proof is
    backend-agnostic: the unique constraint on
    ``(subscription, body_digest)`` plus Django's transaction write
    serialization is what guarantees the second insert raises
    ``IntegrityError``, regardless of whether the backend supports
    ``SELECT FOR UPDATE``.
    """
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"
    digest = hashlib.sha256(b"<feed><id>parallel</id></feed>").hexdigest()

    # Sequential proxies for "the two threads both reach the gate": the gate
    # itself wraps a savepoint around ``create()`` and surfaces a clean
    # ``False`` on the loser, so the worst-case interleaving collapses to
    # this back-to-back pair.
    outcomes = [accept_websub_delivery(subscription, digest) for _ in range(2)]
    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 1
    assert WebSubAcceptedDelivery.objects.filter(subscription=subscription).count() == 1


@pytest.mark.django_db
def test_denied_renewal_preserves_active_secret_and_staged_rotation():
    """Denied renewal callbacks must not discard the staged secret rotation."""
    lease_expires_at = timezone.now() + timedelta(seconds=3600)
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_ACTIVE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
        confirmed_lease_seconds=3600,
        lease_expires_at=lease_expires_at,
    )
    subscription.set_secret(ACTIVE_SECRET)
    subscription.set_pending_secret(NEW_SECRET)
    subscription.pending_secret_set = True
    subscription.save()

    record_websub_denial(
        subscription,
        topic_url=subscription.topic_url,
        reason="denied by hub",
    )

    subscription.refresh_from_db()
    assert subscription.state == WebSubSubscription.STATE_ACTIVE
    assert subscription.get_secret() == ACTIVE_SECRET
    assert subscription.pending_secret_set is True
    assert subscription.get_pending_secret() == NEW_SECRET
    assert subscription.pending_mode == ""
    assert subscription.last_denied_mode == WebSubSubscription.MODE_SUBSCRIBE
    assert subscription.last_denial_reason == "denied by hub"


@pytest.mark.django_db
def test_denied_initial_subscribe_clears_pending_secret_state():
    """Fresh-subscribe denials still clear the pending secret rotation."""
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_PENDING_SUBSCRIBE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
    )
    subscription.set_pending_secret(NEW_SECRET)
    subscription.pending_secret_set = True
    subscription.save()

    record_websub_denial(
        subscription,
        topic_url=subscription.topic_url,
        reason="not allowed",
    )

    subscription.refresh_from_db()
    assert subscription.state == WebSubSubscription.STATE_DENIED
    assert subscription.pending_secret_set is False
    assert subscription.pending_secret == ""
    assert subscription.pending_mode == ""
    assert subscription.last_denial_reason == "not allowed"


# ----------------------------------------------------------------------------
# WebSub secret encryption rotation across Django ``SECRET_KEY`` values.
#
# WebSub shared secrets are encrypted at rest with key material derived from
# ``settings.SECRET_KEY``. Rotating ``SECRET_KEY`` previously required
# re-subscribing every feed. The model now also accepts keys listed in
# ``SECRET_KEY_FALLBACKS`` for decryption, mirroring how Django itself uses
# fallbacks for cookie signing and password hashing.
# ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_decrypt_secret_uses_secret_key_fallback_after_rotation(settings):
    """A secret encrypted under the old SECRET_KEY decrypts after rotation when the
    old key is listed in ``SECRET_KEY_FALLBACKS``."""
    settings.SECRET_KEY = "old-key"
    settings.SECRET_KEY_FALLBACKS = []
    encrypted_under_old = WebSubSubscription.encrypt_secret(SHARED_SECRET)

    settings.SECRET_KEY = "new-key"
    settings.SECRET_KEY_FALLBACKS = ["old-key"]

    assert WebSubSubscription.decrypt_secret(encrypted_under_old) == SHARED_SECRET


@pytest.mark.django_db
def test_decrypt_secret_fails_when_no_key_can_decrypt(settings):
    """Decrypt raises WebSubSecretDecryptionError when neither primary nor any
    fallback can decrypt the stored ciphertext."""
    from indieweb.models import WebSubSecretDecryptionError

    settings.SECRET_KEY = "old-key"
    settings.SECRET_KEY_FALLBACKS = []
    encrypted_under_old = WebSubSubscription.encrypt_secret(SHARED_SECRET)

    settings.SECRET_KEY = "completely-different-key"
    settings.SECRET_KEY_FALLBACKS = []

    with pytest.raises(WebSubSecretDecryptionError):
        WebSubSubscription.decrypt_secret(encrypted_under_old)


@pytest.mark.django_db
def test_encrypt_secret_uses_primary_key_after_rotation(settings):
    """New encryption always uses the current primary ``SECRET_KEY`` even when the
    previous key remains in ``SECRET_KEY_FALLBACKS``."""
    settings.SECRET_KEY = "new-key"
    settings.SECRET_KEY_FALLBACKS = ["old-key"]
    encrypted_under_new = WebSubSubscription.encrypt_secret(SHARED_SECRET)

    # Removing the fallback must not break decryption: the cipher belongs to the primary.
    settings.SECRET_KEY_FALLBACKS = []
    assert WebSubSubscription.decrypt_secret(encrypted_under_new) == SHARED_SECRET

    # Conversely, removing the primary and keeping only the old key as primary must fail —
    # confirming the cipher really is bound to ``new-key``.
    from indieweb.models import WebSubSecretDecryptionError

    settings.SECRET_KEY = "old-key"
    settings.SECRET_KEY_FALLBACKS = []
    with pytest.raises(WebSubSecretDecryptionError):
        WebSubSubscription.decrypt_secret(encrypted_under_new)


@pytest.mark.django_db
def test_set_secret_after_rotation_re_encrypts_under_primary(settings):
    """When a subscription's secret is rewritten via ``set_secret`` after rotation,
    the new ciphertext is bound to the new primary key. Existing rows passively
    migrate this way at renewal time."""
    settings.SECRET_KEY = "old-key"
    settings.SECRET_KEY_FALLBACKS = []
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_ACTIVE,
    )
    subscription.set_secret(SHARED_SECRET)
    subscription.save()
    secret_under_old = subscription.secret

    settings.SECRET_KEY = "new-key"
    settings.SECRET_KEY_FALLBACKS = ["old-key"]
    # Re-staging the same raw secret under the new primary produces a new ciphertext
    # that no longer requires the fallback to decrypt.
    subscription.set_secret(SHARED_SECRET)
    subscription.save()
    secret_under_new = subscription.secret

    assert secret_under_old != secret_under_new
    settings.SECRET_KEY_FALLBACKS = []
    assert WebSubSubscription.decrypt_secret(secret_under_new) == SHARED_SECRET


@pytest.mark.django_db
def test_save_after_rotation_migrates_secret_without_set_secret_call(settings):
    """A renewal that omits ``secret`` must still migrate the stored ciphertext.

    Renewals via ``request_websub_subscription(secret=None)`` never call
    ``set_secret`` for the active row. Without save-time passive
    re-encryption, those rows would remain readable only via
    ``SECRET_KEY_FALLBACKS`` indefinitely, and removing the fallback after
    "every active subscription has been saved at least once under the new
    primary" would break HMAC verification for those rows. The
    :meth:`save` hook now opportunistically re-encrypts fallback-bound
    ciphertext under the primary so the documented operator story holds.
    """
    settings.SECRET_KEY = "old-key"
    settings.SECRET_KEY_FALLBACKS = []
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_ACTIVE,
    )
    subscription.set_secret(SHARED_SECRET)
    subscription.save()
    secret_under_old = subscription.secret

    # Rotate. The renewal flow does not call ``set_secret`` for ``secret=None``;
    # any save (e.g. updating lease bookkeeping) should still migrate the row.
    settings.SECRET_KEY = "new-key"
    settings.SECRET_KEY_FALLBACKS = ["old-key"]
    subscription.save()
    secret_after_save = subscription.secret

    assert secret_after_save != secret_under_old, "Save did not re-encrypt the row under the new primary"

    # Removing the fallback now must not break decryption of the rewritten row.
    settings.SECRET_KEY_FALLBACKS = []
    assert WebSubSubscription.decrypt_secret(secret_after_save) == SHARED_SECRET


@pytest.mark.django_db
def test_save_with_update_fields_persists_passive_reencryption(settings):
    """A renewal-style ``save(update_fields=[...])`` that omits ``secret`` must still
    persist a save-time passive re-encryption.

    Renewal in ``request_websub_subscription`` calls
    ``save(update_fields=[..., "pending_secret", ...])`` without including
    ``secret``. If the in-memory mutation in :meth:`save` is not also
    reflected in the column list passed to Django, the old-key ciphertext
    remains in the database and removing the fallback later breaks
    delivery verification. The save hook now adds ``secret`` to
    ``update_fields`` whenever it actually mutated the column.
    """
    settings.SECRET_KEY = "old-key"
    settings.SECRET_KEY_FALLBACKS = []
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_ACTIVE,
    )
    subscription.set_secret(SHARED_SECRET)
    subscription.save()
    secret_under_old = subscription.secret

    # Rotate. Simulate the renewal save: only non-``secret`` fields in update_fields.
    settings.SECRET_KEY = "new-key"
    settings.SECRET_KEY_FALLBACKS = ["old-key"]
    subscription.requested_lease_seconds = 3600
    subscription.save(update_fields=["requested_lease_seconds", "modified"])

    # In-memory: the row was migrated.
    assert subscription.secret != secret_under_old

    # Critically, the DB row must reflect the migration so removing the
    # fallback does not break later decrypt.
    persisted = WebSubSubscription.objects.get(pk=subscription.pk)
    settings.SECRET_KEY_FALLBACKS = []
    assert WebSubSubscription.decrypt_secret(persisted.secret) == SHARED_SECRET


@pytest.mark.django_db
def test_save_under_primary_is_idempotent_for_already_migrated_rows(settings):
    """Saves on rows already under the primary key must be no-ops, not re-randomized.

    ``Fernet.encrypt`` produces fresh ciphertext on every call (random IV),
    so a naive "always re-encrypt" implementation would churn ciphertext on
    every save. The fast-path check in ``_maybe_reencrypt_under_primary``
    must avoid that by detecting that the primary already decrypts the row
    and returning the input unchanged.
    """
    settings.SECRET_KEY = "primary-key"
    settings.SECRET_KEY_FALLBACKS = []
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_ACTIVE,
    )
    subscription.set_secret(SHARED_SECRET)
    subscription.save()
    first_ciphertext = subscription.secret

    subscription.save()
    assert subscription.secret == first_ciphertext
