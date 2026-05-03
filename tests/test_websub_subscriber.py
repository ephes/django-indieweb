from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta
from urllib.parse import parse_qs

import httpx
import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from indieweb.models import WebSubSubscription
from indieweb.websub import (
    build_websub_callback_url,
    request_websub_subscription,
    validate_websub_delivery_signature,
)
from tests import websub_hooks


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
        secret="shared-secret",
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
    assert result.subscription.pending_secret == "shared-secret"
    assert result.subscription.pending_secret_set is True
    assert body == {
        "hub.mode": ["subscribe"],
        "hub.callback": [f"https://example.org/indieweb/websub/{result.subscription.callback_token}/"],
        "hub.topic": ["https://source.example/feed"],
        "hub.lease_seconds": ["3600"],
        "hub.secret": ["shared-secret"],
    }


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
    subscription.secret = "stored-secret"
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
    assert result.subscription.secret == "stored-secret"
    assert result.subscription.confirmed_lease_seconds == 3600
    assert result.subscription.lease_expires_at is not None
    assert result.subscription.last_request_status_code == 503
    assert result.subscription.last_request_error == "try later"


@pytest.mark.django_db
def test_request_websub_subscription_restores_pending_secret_on_renewal_failure(subscription):
    subscription.secret = "old-secret"
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
        secret="new-secret",
        client=http_client,
    )

    result.subscription.refresh_from_db()
    assert result.success is False
    assert result.subscription.state == WebSubSubscription.STATE_ACTIVE
    assert result.subscription.pending_mode == ""
    assert result.subscription.secret == "old-secret"
    assert result.subscription.pending_secret == ""
    assert result.subscription.pending_secret_set is False


@pytest.mark.django_db
def test_request_websub_subscription_keeps_old_secret_until_renewal_verification(subscription):
    subscription.secret = "old-secret"
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
        secret="new-secret",
        client=http_client,
    )

    result.subscription.refresh_from_db()
    assert result.success is True
    assert result.subscription.state == WebSubSubscription.STATE_ACTIVE
    assert result.subscription.pending_mode == WebSubSubscription.MODE_SUBSCRIBE
    assert result.subscription.secret == "old-secret"
    assert result.subscription.pending_secret == "new-secret"
    assert result.subscription.pending_secret_set is True


@pytest.mark.django_db
def test_request_websub_subscription_preserves_stored_secret_when_renewal_omits_secret(subscription):
    subscription.secret = "stored-secret"
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
    assert result.subscription.secret == "stored-secret"
    assert result.subscription.pending_secret == ""
    assert result.subscription.pending_secret_set is False


@pytest.mark.django_db
def test_request_websub_subscription_clears_stale_pending_secret_when_renewal_omits_secret(subscription):
    subscription.secret = "active-secret"
    subscription.pending_secret = "stale-secret"
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
    assert result.subscription.secret == "active-secret"
    assert result.subscription.pending_secret == ""
    assert result.subscription.pending_secret_set is False


@pytest.mark.django_db
def test_request_websub_subscription_can_stage_empty_secret_to_drop_signed_delivery(subscription):
    subscription.secret = "active-secret"
    subscription.save()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))

    result = request_websub_subscription(
        subscription.topic_url,
        subscription.hub_url,
        callback_base_url="https://example.org/indieweb/websub",
        secret="",
        client=http_client,
    )

    result.subscription.refresh_from_db()
    assert result.success is True
    assert result.subscription.secret == "active-secret"
    assert result.subscription.pending_secret == ""
    assert result.subscription.pending_secret_set is True


@pytest.mark.django_db
def test_request_websub_subscription_rejects_overlong_secret():
    with pytest.raises(ValueError, match="secret must be at most 200 characters"):
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
def test_callback_verification_applies_pending_secret(client):
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_ACTIVE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
        secret="old-secret",
        pending_secret="new-secret",
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
    assert subscription.secret == "new-secret"
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
        secret="old-secret",
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

    response = client.post(_callback_url(subscription), data=body, content_type="application/atom+xml")

    subscription.refresh_from_db()
    assert response.status_code == 204
    assert subscription.last_delivery_status_code == 204
    assert subscription.last_delivery_content_type == "application/atom+xml"
    assert subscription.last_delivery_size == len(body)
    assert subscription.last_delivery_digest == hashlib.sha256(body).hexdigest()
    assert websub_hooks.DELIVERIES[0]["subscription_id"] == subscription.pk
    assert websub_hooks.DELIVERIES[0]["topic_url"] == subscription.topic_url
    assert websub_hooks.DELIVERIES[0]["body"] == body


@pytest.mark.django_db
def test_callback_post_is_csrf_exempt(settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"
    csrf_client = Client(enforce_csrf_checks=True)

    response = csrf_client.post(_callback_url(subscription), data=b"<feed/>", content_type="application/atom+xml")

    assert response.status_code == 204
    assert len(websub_hooks.DELIVERIES) == 1


@pytest.mark.django_db
def test_callback_post_validates_signed_delivery(client, subscription):
    subscription.secret = "shared-secret"
    subscription.save()
    body = b'{"items":[]}'
    digest = hmac.new(subscription.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    response = client.post(
        _callback_url(subscription),
        data=body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=f"sha256={digest}",
    )

    subscription.refresh_from_db()
    assert response.status_code == 204
    assert subscription.last_delivery_signature_algorithm == "sha256"


@pytest.mark.django_db
@pytest.mark.parametrize("signature_header", [None, "sha256=bad"])
def test_callback_post_rejects_missing_or_bad_signature(client, subscription, signature_header):
    subscription.secret = "shared-secret"
    subscription.save()
    headers = {}
    if signature_header is not None:
        headers["HTTP_X_HUB_SIGNATURE_256"] = signature_header

    response = client.post(
        _callback_url(subscription),
        data=b'{"items":[]}',
        content_type="application/json",
        **headers,
    )

    subscription.refresh_from_db()
    assert response.status_code == 403
    assert subscription.last_delivery_status_code == 403
    assert subscription.last_delivery_error == "invalid signature"


@pytest.mark.django_db
def test_validate_websub_delivery_signature_accepts_legacy_signature_header(subscription):
    subscription.secret = "shared-secret"
    body = b"<feed/>"
    digest = hmac.new(subscription.secret.encode("utf-8"), body, hashlib.sha1).hexdigest()

    algorithm = validate_websub_delivery_signature(subscription, body, {"X-Hub-Signature": f"sha1={digest}"})

    assert algorithm == "sha1"


@pytest.mark.django_db
def test_callback_post_applies_delivery_size_limit(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_MAX_BYTES = 4

    response = client.post(_callback_url(subscription), data=b"12345", content_type="application/atom+xml")

    subscription.refresh_from_db()
    assert response.status_code == 413
    assert subscription.last_delivery_status_code == 413


@pytest.mark.django_db
def test_callback_post_uses_default_delivery_size_limit_when_setting_is_invalid(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_MAX_BYTES = "bad"

    response = client.post(_callback_url(subscription), data=b"<feed/>", content_type="application/atom+xml")

    subscription.refresh_from_db()
    assert response.status_code == 204
    assert subscription.last_delivery_status_code == 204


@pytest.mark.django_db
def test_callback_post_applies_delivery_content_type_allowlist(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_ALLOWED_TYPES = ("application/atom+xml",)

    response = client.post(_callback_url(subscription), data=b"{}", content_type="application/json")

    subscription.refresh_from_db()
    assert response.status_code == 415
    assert subscription.last_delivery_status_code == 415


@pytest.mark.django_db
def test_callback_post_allows_delivery_when_content_type_setting_is_invalid(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_ALLOWED_TYPES = object()

    response = client.post(_callback_url(subscription), data=b"{}", content_type="application/json")

    subscription.refresh_from_db()
    assert response.status_code == 204
    assert subscription.last_delivery_status_code == 204


@pytest.mark.django_db
def test_callback_post_reports_delivery_hook_failure(client, settings, subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.failing_delivery"

    response = client.post(_callback_url(subscription), data=b"<feed/>", content_type="application/atom+xml")

    subscription.refresh_from_db()
    assert response.status_code == 500
    assert subscription.last_delivery_status_code == 500
    assert subscription.last_delivery_error == "delivery hook failed"
