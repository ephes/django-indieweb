from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.urls import reverse

from indieweb import models
from indieweb.rate_limit import get_rate_limit_config
from indieweb.views import TokenAuthMixin


@pytest.fixture(autouse=True)
def clear_rate_limit_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="ratelimit", email="ratelimit@example.org", password="password")


@pytest.fixture
def token(user):
    return models.Token.objects.create(
        me="https://example.org",
        client_id="https://client.example.org",
        scope="create media update",
        owner=user,
    )


@pytest.fixture
def auth(user):
    return models.Auth.objects.create(
        owner=user,
        key="rateauthkey",
        state="state",
        me="https://example.org",
        scope="create",
        client_id="https://client.example.org",
        redirect_uri="https://client.example.org/callback",
    )


def _valid_webmention_payload() -> dict[str, str]:
    site = Site.objects.get_current()
    return {
        "source": "https://source.example.org/reply",
        "target": f"https://{site.domain}/post",
    }


@pytest.mark.django_db
def test_rate_limiting_is_disabled_by_default(client):
    url = reverse("indieweb:token")

    first = client.post(url, data={"code": "wrong", "client_id": "https://client.example.org"})
    second = client.post(url, data={"code": "wrong", "client_id": "https://client.example.org"})

    assert first.status_code == 400
    assert second.status_code == 400
    assert "Retry-After" not in second


@pytest.mark.django_db
def test_configured_token_limit_returns_429_with_retry_after(client, settings):
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": 1, "window": 60}}
    url = reverse("indieweb:token")

    allowed = client.post(url, data={"code": "wrong", "client_id": "https://client.example.org"})
    limited = client.post(url, data={"code": "wrong", "client_id": "https://client.example.org"})

    assert allowed.status_code == 400
    assert limited.status_code == 429
    assert limited.content.decode("utf-8") == "rate limit exceeded"
    assert 1 <= int(limited["Retry-After"]) <= 60


@pytest.mark.django_db
def test_successful_token_request_under_limit_keeps_existing_response(client, settings, auth):
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": 2, "window": 60}}
    url = reverse("indieweb:token")

    response = client.post(
        url,
        data={
            "code": auth.key,
            "client_id": auth.client_id,
            "redirect_uri": auth.redirect_uri,
        },
    )

    assert response.status_code == 201
    assert response["Content-Type"] == "application/x-www-form-urlencoded"
    assert b"access_token=" in response.content


@pytest.mark.django_db
def test_limits_are_scoped_by_endpoint_key(client, settings, token):
    settings.INDIEWEB_RATE_LIMITS = {
        "token": {"limit": 1, "window": 60},
        "micropub": {"limit": 1, "window": 60},
    }
    token_url = reverse("indieweb:token")
    micropub_url = reverse("indieweb:micropub")

    token_response = client.post(token_url, data={"code": "wrong", "client_id": "https://client.example.org"})
    micropub_response = client.get(micropub_url, Authorization=f"Bearer {token.key}")
    limited_token_response = client.post(
        token_url,
        data={"code": "wrong", "client_id": "https://client.example.org"},
    )

    assert token_response.status_code == 400
    assert micropub_response.status_code == 200
    assert limited_token_response.status_code == 429


@pytest.mark.django_db
def test_limits_are_scoped_by_remote_addr(client, settings):
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": 1, "window": 60}}
    url = reverse("indieweb:token")
    payload = {"code": "wrong", "client_id": "https://client.example.org"}

    first = client.post(url, data=payload, REMOTE_ADDR="203.0.113.1")
    same_client = client.post(url, data=payload, REMOTE_ADDR="203.0.113.1")
    other_client = client.post(url, data=payload, REMOTE_ADDR="203.0.113.2")

    assert first.status_code == 400
    assert same_client.status_code == 429
    assert other_client.status_code == 400


@pytest.mark.django_db
def test_x_forwarded_for_is_not_trusted_by_default(client, settings):
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": 1, "window": 60}}
    url = reverse("indieweb:token")
    payload = {"code": "wrong", "client_id": "https://client.example.org"}

    first = client.post(
        url,
        data=payload,
        REMOTE_ADDR="203.0.113.1",
        HTTP_X_FORWARDED_FOR="198.51.100.1",
    )
    spoofed_forwarded_for = client.post(
        url,
        data=payload,
        REMOTE_ADDR="203.0.113.1",
        HTTP_X_FORWARDED_FOR="198.51.100.2",
    )

    assert first.status_code == 400
    assert spoofed_forwarded_for.status_code == 429


@pytest.mark.django_db
def test_malformed_rate_limit_config_is_ignored(client, settings):
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": "bad", "window": 60}}
    url = reverse("indieweb:token")

    first = client.post(url, data={"code": "wrong", "client_id": "https://client.example.org"})
    second = client.post(url, data={"code": "wrong", "client_id": "https://client.example.org"})

    assert get_rate_limit_config("token") is None
    assert first.status_code == 400
    assert second.status_code == 400


@pytest.mark.django_db
def test_micropub_limit_short_circuits_before_token_authentication(client, settings):
    settings.INDIEWEB_RATE_LIMITS = {"micropub": {"limit": 1, "window": 60}}
    url = reverse("indieweb:micropub")

    with patch.object(TokenAuthMixin, "authenticated", return_value=False) as authenticated:
        first = client.get(url, Authorization="Bearer wrong")
        second = client.get(url, Authorization="Bearer wrong")

    assert first.status_code == 401
    assert second.status_code == 429
    assert authenticated.call_count == 1


@pytest.mark.django_db
def test_webmention_limit_short_circuits_before_processing(client, settings):
    settings.INDIEWEB_RATE_LIMITS = {"webmention": {"limit": 1, "window": 60}}
    url = reverse("indieweb:webmention")
    payload = _valid_webmention_payload()

    with patch("indieweb.views.WebmentionProcessor") as processor_class:
        processor = MagicMock()
        processor_class.return_value = processor
        processor.process_webmention.return_value = models.Webmention(id=123)

        first = client.post(url, data=payload)
        second = client.post(url, data=payload)

    assert first.status_code == 201
    assert second.status_code == 429
    processor.process_webmention.assert_called_once_with(
        payload["source"],
        payload["target"],
        vouch_url=None,
    )


@pytest.mark.django_db
def test_auth_media_and_webmention_status_endpoint_keys_are_limited(client, settings):
    webmention = models.Webmention.objects.create(
        source_url="https://source.example.org/post",
        target_url="https://example.com/post",
        status="verified",
    )
    settings.INDIEWEB_RATE_LIMITS = {
        "auth": {"limit": 1, "window": 60},
        "media": {"limit": 1, "window": 60},
        "webmention_status": {"limit": 1, "window": 60},
    }
    auth_url = reverse("indieweb:auth")
    media_url = reverse("indieweb:media")
    status_url = reverse("indieweb:webmention-status", args=[webmention.pk])

    assert client.get(auth_url).status_code == 302
    assert client.get(auth_url).status_code == 429

    assert client.post(media_url, data={}).status_code == 401
    assert client.post(media_url, data={}).status_code == 429

    assert client.get(status_url).status_code == 200
    assert client.get(status_url).status_code == 429


@pytest.mark.django_db
def test_websub_callback_endpoint_key_is_limited(client, settings):
    subscription = models.WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=models.WebSubSubscription.STATE_ACTIVE,
    )
    settings.INDIEWEB_RATE_LIMITS = {"websub_callback": {"limit": 1, "window": 60}}
    url = reverse("indieweb:websub-callback", args=[subscription.callback_token])

    assert client.post(url, data=b"<feed/>", content_type="application/atom+xml").status_code == 204
    assert client.post(url, data=b"<feed/>", content_type="application/atom+xml").status_code == 429
