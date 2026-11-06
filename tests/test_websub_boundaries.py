"""Synthetic regressions for WebSub input and preflight boundaries."""

import hashlib
import hmac

import httpx
import pytest
from django.urls import reverse

from indieweb.models import WebSubSubscription
from indieweb.websub import notify_hubs, request_websub_subscription
from tests import websub_hooks


@pytest.mark.django_db
@pytest.mark.parametrize("digest", ["é", "a" * 63, "g" * 64, "a" * 65])
def test_malformed_digest_is_forbidden(client, settings, digest):
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"
    websub_hooks.reset()
    row = WebSubSubscription.objects.create(
        hub_url="https://hub.example/", topic_url="https://topic.example/", state="active"
    )
    row.set_secret("synthetic-secret-value-20x")
    row.save()
    response = client.post(
        reverse("indieweb:websub-callback", args=[row.callback_token]),
        data=b"body",
        content_type="application/octet-stream",
        HTTP_LINK=f'<{row.topic_url}>; rel="self"',
        HTTP_X_HUB_SIGNATURE_256=f"sha256={digest}",
    )
    assert response.status_code == 403
    assert websub_hooks.DELIVERIES == []


@pytest.mark.django_db
def test_valid_strongest_among_malformed_signatures(client, settings):
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"
    websub_hooks.reset()
    row = WebSubSubscription.objects.create(
        hub_url="https://hub.example/", topic_url="https://topic.example/", state="active"
    )
    secret = "synthetic-secret-value-20x"
    row.set_secret(secret)
    row.save()
    digest = hmac.new(secret.encode(), b"body", hashlib.sha256).hexdigest()
    response = client.post(
        reverse("indieweb:websub-callback", args=[row.callback_token]),
        data=b"body",
        content_type="application/octet-stream",
        HTTP_LINK=f'<{row.topic_url}>; rel="self"',
        HTTP_X_HUB_SIGNATURE_256=f"sha256=é, sha256={digest}",
    )
    assert response.status_code == 204
    assert len(websub_hooks.DELIVERIES) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize(
    "kwargs",
    [
        {"callback_base_url": "invalid"},
        {"timeout": float("nan")},
        {"timeout": float("inf")},
        {"timeout": -1},
        {"hub_url": "http://hub.example/", "secret": "synthetic-secret-value-20x"},
    ],
)
def test_invalid_preflight_never_writes(existing, kwargs):
    args = dict(
        topic_url="https://topic.example/",
        hub_url="https://hub.example/",
        callback_base_url="https://callback.example/",
    )
    args.update(kwargs)
    if existing:
        WebSubSubscription.objects.create(hub_url=args["hub_url"], topic_url=args["topic_url"], state="active")
    before = list(WebSubSubscription.objects.values())
    calls = []
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(202))
    ) as c:
        with pytest.raises(ValueError):
            request_websub_subscription(**args, client=c)
    assert calls == []
    assert list(WebSubSubscription.objects.values()) == before


@pytest.mark.parametrize("operation", ["publish", "subscribe"])
@pytest.mark.django_db
def test_total_budget_expires_trickle_and_next_hub_runs(monkeypatch, operation):
    clock = [0.0]
    monkeypatch.setattr("indieweb.http_client.time.monotonic", lambda: clock[0])
    calls = []

    class Trickle(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(3):
                clock[0] += 0.6
                yield b"x"

    def handler(request):
        calls.append(str(request.url))
        if request.url.host == "slow.example":
            return httpx.Response(200, stream=Trickle())
        return httpx.Response(202)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        if operation == "publish":
            results = notify_hubs(
                "https://topic.example/", hubs=["https://slow.example/", "https://fast.example/"], timeout=1, client=c
            )
            assert [r.success for r in results] == [False, True]
            assert len(calls) == 2
        else:
            result = request_websub_subscription(
                "https://topic.example/",
                "https://slow.example/",
                callback_base_url="https://callback.example/",
                timeout=1,
                client=c,
            )
            assert not result.success
            assert result.subscription.state == WebSubSubscription.STATE_DENIED


@pytest.mark.django_db
def test_callback_construction_failure_rolls_back_preparation(monkeypatch):
    def fail(*args):
        assert WebSubSubscription.objects.filter(pending_mode="subscribe").exists()
        raise ValueError("synthetic callback failure")

    monkeypatch.setattr("indieweb.websub.build_websub_callback_url", fail)
    with pytest.raises(ValueError, match="synthetic callback"):
        request_websub_subscription(
            "https://topic.example/", "https://hub.example/", callback_base_url="https://callback.example/"
        )
    assert not WebSubSubscription.objects.exists()


@pytest.mark.django_db(databases=["default", "other"])
def test_routed_callback_failure_rolls_back_preparation(monkeypatch, settings):
    class SubscriptionRouter:
        def db_for_read(self, model, **hints):
            return "other" if model is WebSubSubscription else None

        db_for_write = db_for_read

    settings.DATABASE_ROUTERS = [SubscriptionRouter()]

    def fail(*args):
        assert WebSubSubscription.objects.using("other").filter(pending_mode="subscribe").exists()
        raise ValueError("synthetic callback failure")

    monkeypatch.setattr("indieweb.websub.build_websub_callback_url", fail)
    with pytest.raises(ValueError, match="synthetic callback"):
        request_websub_subscription(
            "https://topic.example/", "https://hub.example/", callback_base_url="https://callback.example/"
        )
    assert not WebSubSubscription.objects.using("other").exists()
    assert not WebSubSubscription.objects.using("default").exists()
