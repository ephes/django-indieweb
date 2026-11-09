"""Signed WebSub deliveries are required by default; unsigned subscriptions are made visible."""

from __future__ import annotations

import hashlib
import hmac
import logging

import httpx
import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse

from indieweb import checks
from indieweb.models import WebSubDeliveryAttempt, WebSubSubscription
from indieweb.websub import request_websub_subscription, websub_signed_deliveries_required
from tests import websub_hooks

SECRET = "signed-default-secret-20x"
SUBSCRIPTION_LOGGER = "indieweb.websub"


@pytest.fixture(autouse=True)
def reset_hooks():
    websub_hooks.reset()
    yield
    websub_hooks.reset()


@pytest.fixture
def active_subscription(db):
    return WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_ACTIVE,
    )


def _deliver(client, subscription, body=b"<feed/>", **headers):
    return client.post(
        reverse("indieweb:websub-callback", args=[subscription.callback_token]),
        data=body,
        content_type="application/atom+xml",
        HTTP_LINK=f'<{subscription.topic_url}>; rel="self"',
        **headers,
    )


def _hub_client():
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(202)))


def test_signed_deliveries_are_required_by_default(settings):
    if hasattr(settings, "INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES"):
        del settings.INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES

    assert websub_signed_deliveries_required() is True


@pytest.mark.django_db
def test_unsigned_delivery_without_secret_is_rejected_by_default(client, settings, active_subscription):
    if hasattr(settings, "INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES"):
        del settings.INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"

    response = _deliver(client, active_subscription)

    assert response.status_code == 403
    assert websub_hooks.DELIVERIES == []
    assert WebSubDeliveryAttempt.objects.get(subscription=active_subscription).error == "invalid signature"


@pytest.mark.django_db
def test_unsigned_delivery_is_accepted_after_opt_out(client, settings, active_subscription):
    settings.INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES = False
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"

    response = _deliver(client, active_subscription)

    assert response.status_code == 204
    assert len(websub_hooks.DELIVERIES) == 1


@pytest.mark.django_db
def test_signed_delivery_is_accepted_by_default(client, settings, active_subscription):
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"
    active_subscription.secret = SECRET
    active_subscription.save()
    body = b"<feed><entry/></feed>"
    digest = hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()

    response = _deliver(client, active_subscription, body=body, HTTP_X_HUB_SIGNATURE_256=f"sha256={digest}")

    assert response.status_code == 204
    assert len(websub_hooks.DELIVERIES) == 1


@pytest.mark.django_db
def test_subscribing_without_secret_warns_that_deliveries_will_be_rejected(caplog):
    with caplog.at_level(logging.WARNING, logger=SUBSCRIPTION_LOGGER):
        result = request_websub_subscription(
            "https://source.example/feed",
            "https://hub.example/sub",
            callback_base_url="https://example.org/indieweb/websub",
            client=_hub_client(),
        )

    assert result.success is True
    messages = [record.getMessage() for record in caplog.records if record.name == SUBSCRIPTION_LOGGER]
    assert len(messages) == 1
    assert "has no hub.secret" in messages[0]
    assert "rejected with 403" in messages[0]
    assert "INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES = False" in messages[0]


@pytest.mark.django_db
def test_subscribing_without_secret_after_opt_out_warns_about_unsigned_content(settings, caplog):
    settings.INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES = False

    with caplog.at_level(logging.WARNING, logger=SUBSCRIPTION_LOGGER):
        request_websub_subscription(
            "https://source.example/feed",
            "https://hub.example/sub",
            callback_base_url="https://example.org/indieweb/websub",
            client=_hub_client(),
        )

    messages = [record.getMessage() for record in caplog.records if record.name == SUBSCRIPTION_LOGGER]
    assert len(messages) == 1
    assert "unsigned deliveries will be accepted" in messages[0]


@pytest.mark.django_db
def test_subscribing_with_secret_does_not_warn(caplog):
    with caplog.at_level(logging.WARNING, logger=SUBSCRIPTION_LOGGER):
        request_websub_subscription(
            "https://source.example/feed",
            "https://hub.example/sub",
            callback_base_url="https://example.org/indieweb/websub",
            secret=SECRET,
            client=_hub_client(),
        )

    assert not [record for record in caplog.records if record.name == SUBSCRIPTION_LOGGER]


@pytest.mark.django_db
def test_renewal_that_keeps_stored_secret_does_not_warn(active_subscription, caplog):
    active_subscription.secret = SECRET
    active_subscription.save()

    with caplog.at_level(logging.WARNING, logger=SUBSCRIPTION_LOGGER):
        request_websub_subscription(
            active_subscription.topic_url,
            active_subscription.hub_url,
            callback_base_url="https://example.org/indieweb/websub",
            client=_hub_client(),
        )

    assert not [record for record in caplog.records if record.name == SUBSCRIPTION_LOGGER]


@pytest.mark.django_db
def test_unsubscribe_without_secret_does_not_warn(active_subscription, caplog):
    with caplog.at_level(logging.WARNING, logger=SUBSCRIPTION_LOGGER):
        request_websub_subscription(
            active_subscription.topic_url,
            active_subscription.hub_url,
            mode=WebSubSubscription.MODE_UNSUBSCRIBE,
            callback_base_url="https://example.org/indieweb/websub",
            client=_hub_client(),
        )

    assert not [record for record in caplog.records if record.name == SUBSCRIPTION_LOGGER]


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({}, []),
        ({"INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES": False}, []),
        (
            {
                "INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES": False,
                "INDIEWEB_WEBSUB_DELIVERY_HOOK": "tests.websub_hooks.capture_delivery",
            },
            ["indieweb.W001"],
        ),
        (
            {
                "INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES": False,
                "INDIEWEB_WEBSUB_DELIVERY_ENQUEUE": "tests.websub_hooks.capture_enqueue",
            },
            ["indieweb.W001"],
        ),
        (
            {
                "INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES": True,
                "INDIEWEB_WEBSUB_DELIVERY_HOOK": "tests.websub_hooks.capture_delivery",
            },
            [],
        ),
    ],
)
def test_unsigned_delivery_system_check(settings, overrides, expected):
    for name in (
        "INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES",
        "INDIEWEB_WEBSUB_DELIVERY_HOOK",
        "INDIEWEB_WEBSUB_DELIVERY_ENQUEUE",
    ):
        if hasattr(settings, name):
            delattr(settings, name)
    for name, value in overrides.items():
        setattr(settings, name, value)

    assert [message.id for message in checks.check_websub_unsigned_deliveries()] == expected


@pytest.mark.django_db
def test_admin_shows_and_filters_signed_subscriptions(active_subscription):
    signed = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/other-feed",
        state=WebSubSubscription.STATE_ACTIVE,
        secret=SECRET,
    )
    modeladmin = admin.site._registry[WebSubSubscription]
    request = RequestFactory().get("/")

    assert "has_secret" in modeladmin.list_display
    assert modeladmin.has_secret(signed) is True
    assert modeladmin.has_secret(active_subscription) is False

    list_filter = modeladmin.list_filter[1]
    queryset = WebSubSubscription.objects.all()
    with_secret = list_filter(request, {"has_secret": ["yes"]}, WebSubSubscription, modeladmin)
    without_secret = list_filter(request, {"has_secret": ["no"]}, WebSubSubscription, modeladmin)
    assert list(with_secret.queryset(request, queryset)) == [signed]
    assert list(without_secret.queryset(request, queryset)) == [active_subscription]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "secret,headers,reason",
    [
        (None, {}, "unsigned, and the subscription has no stored secret"),
        (SECRET, {"HTTP_X_HUB_SIGNATURE": "md5=" + "0" * 32}, "no supported algorithm in the delivery signature"),
        (
            SECRET,
            {"HTTP_X_HUB_SIGNATURE_256": "sha256=" + "0" * 64},
            "the HMAC did not validate against the stored secret",
        ),
    ],
)
def test_rejected_delivery_log_keeps_reason(client, settings, caplog, active_subscription, secret, headers, reason):
    # WebSubRejection messages are fixed sentences, so the reason is logged.
    if hasattr(settings, "INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES"):
        del settings.INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES
    settings.INDIEWEB_LOG_REDACTION = "passthrough"
    if secret:
        active_subscription.set_secret(secret)
        active_subscription.save()

    with caplog.at_level(logging.WARNING, logger="indieweb.views"):
        response = _deliver(client, active_subscription, **headers)

    assert response.status_code == 403
    assert f"WebSub delivery rejected: {reason}" in caplog.text


@pytest.mark.django_db
def test_hub_denial_reason_is_stored_as_a_fingerprint(client):
    password = "".join(("Vq3z", "pw"))
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_PENDING_SUBSCRIBE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
    )

    response = client.get(
        reverse("indieweb:websub-callback", args=[subscription.callback_token]),
        {
            "hub.mode": "denied",
            "hub.topic": subscription.topic_url,
            "hub.reason": f"denied for https://user:{password}@hub.example/x\nINFO forged",
        },
    )

    subscription.refresh_from_db()
    assert response.status_code == 204
    assert subscription.last_denial_reason.startswith("hub.reason ")
    assert subscription.last_denial_reason.endswith(f"bytes, digest {subscription.last_denial_reason[-12:]}")
    for private in (password, "denied for", "forged"):
        assert private not in subscription.last_denial_reason
