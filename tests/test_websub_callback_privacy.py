"""Capability-bearing verification URLs must always reach current state checks."""

import pytest
from django.core.cache import cache
from django.urls import reverse

from indieweb.models import WebSubSubscription


@pytest.fixture
def cached_callback(settings):
    settings.MIDDLEWARE = [
        "django.middleware.cache.UpdateCacheMiddleware",
        *settings.MIDDLEWARE,
        "django.middleware.cache.FetchFromCacheMiddleware",
    ]
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    cache.clear()
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_PENDING_SUBSCRIBE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
    )
    yield subscription, reverse("indieweb:websub-callback", args=[subscription.callback_token])
    cache.clear()


def assert_private_callback(response):
    assert {"private", "no-store", "no-cache", "max-age=0", "must-revalidate"} <= {
        part.strip() for part in response["Cache-Control"].split(",")
    }
    assert response["Referrer-Policy"] == "no-referrer"


@pytest.mark.django_db
@pytest.mark.parametrize("mode, status, body", [("subscribe", 200, b"synthetic-challenge"), ("denied", 204, b"")])
def test_verification_and_denial_are_not_replayed(client, cached_callback, mode, status, body):
    subscription, url = cached_callback
    query = {
        "hub.mode": mode,
        "hub.topic": subscription.topic_url,
        "hub.challenge": "synthetic-challenge",
        "hub.lease_seconds": "3600",
    }
    first = client.get(url, query)
    assert first.status_code == status
    assert first.content == body
    # The same URL is now stale; cached challenges must not skip the state check.
    second = client.get(url, query)
    assert second.status_code == 404
    assert second.content == b""
    assert_private_callback(first)
    assert_private_callback(second)


@pytest.mark.django_db
@pytest.mark.parametrize("failure", ["unknown", "stale", "missing", "topic", "mode", "lease"])
def test_callback_refusals_keep_capability_urls_private(client, cached_callback, failure):
    subscription, url = cached_callback
    query = {
        "hub.mode": "subscribe",
        "hub.topic": subscription.topic_url,
        "hub.challenge": "synthetic-challenge",
        "hub.lease_seconds": "3600",
    }
    if failure == "unknown":
        subscription.delete()
    elif failure == "stale":
        WebSubSubscription.objects.filter(pk=subscription.pk).update(pending_mode="")
    elif failure == "missing":
        del query["hub.challenge"]
    elif failure == "topic":
        query["hub.topic"] = "https://other.example/"
    elif failure == "mode":
        query["hub.mode"] = "invalid"
    else:
        query["hub.lease_seconds"] = "invalid"
    for _ in range(2):
        response = client.get(url, query)
        assert response.status_code == 404
        assert response.content == b""
        assert_private_callback(response)


@pytest.mark.django_db
def test_callback_rate_limit_refusal_is_private(client, settings, cached_callback):
    subscription, url = cached_callback
    settings.INDIEWEB_RATE_LIMITS = {"websub_callback": {"limit": 1, "window": 60}}
    first = client.get(url)
    limited = client.get(url)
    assert first.status_code == 404
    assert limited.status_code == 429
    assert_private_callback(first)
    assert_private_callback(limited)
