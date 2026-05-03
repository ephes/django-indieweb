from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.urls import reverse

from indieweb import models
from indieweb.rate_limit import check_rate_limit
from indieweb.views import TokenAuthMixin
from tests import webmention_enqueue_hooks

ALLOWED_ORIGIN = "https://app.example.org"
OTHER_ORIGIN = "https://other.example.org"


@pytest.fixture
def user(db):
    return User.objects.create_user(username="cors", email="cors@example.org", password="password")


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
        key="corsauthkey",
        state="state",
        me="https://example.org",
        scope="create",
        client_id="https://client.example.org",
        redirect_uri="https://client.example.org/callback",
    )


@pytest.fixture
def webmention(db):
    return models.Webmention.objects.create(
        source_url="https://source.example.org/post",
        target_url="https://example.org/post",
        status="pending",
    )


@pytest.fixture
def websub_subscription(db):
    return models.WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=models.WebSubSubscription.STATE_ACTIVE,
    )


def _preflight(client, url: str, method: str = "POST", origin: str = ALLOWED_ORIGIN):
    return client.options(
        url,
        HTTP_ORIGIN=origin,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD=method,
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="Authorization, Content-Type",
    )


def _valid_webmention_payload() -> dict[str, str]:
    site = Site.objects.get_current()
    return {
        "source": "https://source.example.org/reply",
        "target": f"https://{site.domain}/post",
    }


@pytest.mark.django_db
def test_cors_is_disabled_by_default(client):
    url = reverse("indieweb:token")

    response = client.post(
        url,
        data={"code": "wrong", "client_id": "https://client.example.org"},
        HTTP_ORIGIN=ALLOWED_ORIGIN,
    )

    assert response.status_code == 400
    assert response.content == b"invalid_grant"
    assert response["Content-Type"] == "application/x-www-form-urlencoded"
    assert "Access-Control-Allow-Origin" not in response


@pytest.mark.django_db
def test_allowed_origin_gets_cors_headers_on_actual_response(client, settings, token):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = (ALLOWED_ORIGIN,)
    url = reverse("indieweb:micropub")

    response = client.get(url, Authorization=f"Bearer {token.key}", HTTP_ORIGIN=ALLOWED_ORIGIN)

    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert response["Vary"] == "Origin"
    assert "me=https%3A%2F%2Fexample.org" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_disallowed_origin_gets_no_cors_headers_on_actual_response(client, settings, token):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = (ALLOWED_ORIGIN,)
    url = reverse("indieweb:micropub")

    response = client.get(url, Authorization=f"Bearer {token.key}", HTTP_ORIGIN=OTHER_ORIGIN)

    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response
    assert "Vary" not in response


@pytest.mark.django_db
def test_configured_cors_only_changes_headers_on_existing_response(client, settings, auth):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = (ALLOWED_ORIGIN,)
    url = reverse("indieweb:token")

    response = client.post(
        url,
        data={"code": auth.key, "client_id": auth.client_id, "redirect_uri": auth.redirect_uri},
        HTTP_ORIGIN=ALLOWED_ORIGIN,
    )

    assert response.status_code == 201
    assert response["Content-Type"] == "application/x-www-form-urlencoded"
    assert b"access_token=" in response.content
    assert response["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN


@pytest.mark.django_db
def test_allowed_origin_gets_cors_headers_on_rate_limited_response(client, settings):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = (ALLOWED_ORIGIN,)
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": 1, "window": 60}}
    url = reverse("indieweb:token")
    payload = {"code": "wrong", "client_id": "https://client.example.org"}

    first = client.post(url, data=payload, HTTP_ORIGIN=ALLOWED_ORIGIN, REMOTE_ADDR="203.0.113.42")
    limited = client.post(url, data=payload, HTTP_ORIGIN=ALLOWED_ORIGIN, REMOTE_ADDR="203.0.113.42")

    assert first.status_code == 400
    assert limited.status_code == 429
    assert limited.content == b"rate limit exceeded"
    assert limited["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert limited["Vary"] == "Origin"


@pytest.mark.django_db
def test_allowed_origin_gets_cors_headers_on_authentication_failure(client, settings):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = (ALLOWED_ORIGIN,)
    url = reverse("indieweb:micropub")

    response = client.get(url, Authorization="Bearer wrong", HTTP_ORIGIN=ALLOWED_ORIGIN)

    assert response.status_code == 401
    assert response.content == b"authentication error"
    assert response["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert response["Vary"] == "Origin"


@pytest.mark.django_db
def test_wildcard_origin_uses_star_without_credentials(client, settings, token):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = "*"
    url = reverse("indieweb:micropub")

    response = client.get(url, Authorization=f"Bearer {token.key}", HTTP_ORIGIN=ALLOWED_ORIGIN)

    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == "*"
    assert "Access-Control-Allow-Credentials" not in response
    assert "Vary" not in response


@pytest.mark.django_db
def test_wildcard_with_credentials_echoes_origin(client, settings, token):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = "*"
    settings.INDIEWEB_CORS_ALLOW_CREDENTIALS = True
    url = reverse("indieweb:micropub")

    response = client.get(url, Authorization=f"Bearer {token.key}", HTTP_ORIGIN=ALLOWED_ORIGIN)

    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert response["Access-Control-Allow-Credentials"] == "true"
    assert response["Vary"] == "Origin"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("endpoint_name", "method", "args"),
    [
        ("auth", "GET", ()),
        ("auth", "POST", ()),
        ("token", "POST", ()),
        ("micropub", "GET", ()),
        ("micropub", "POST", ()),
        ("media", "POST", ()),
        ("webmention", "GET", ()),
        ("webmention", "POST", ()),
        ("webmention-status", "GET", ("webmention",)),
    ],
)
def test_preflight_works_for_protocol_endpoints(client, settings, webmention, endpoint_name, method, args):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = (ALLOWED_ORIGIN,)
    settings.INDIEWEB_CORS_ALLOWED_HEADERS = ("Authorization", "Content-Type", "Accept")
    settings.INDIEWEB_CORS_MAX_AGE = 600
    url_args = [webmention.pk] if args else []
    url = reverse(f"indieweb:{endpoint_name}", args=url_args)

    response = _preflight(client, url, method=method)

    assert response.status_code == 204
    assert response.content == b""
    assert response["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert response["Access-Control-Allow-Methods"]
    assert method in response["Access-Control-Allow-Methods"]
    assert response["Access-Control-Allow-Headers"] == "Authorization, Content-Type, Accept"
    assert response["Access-Control-Max-Age"] == "600"
    assert response["Vary"] == "Origin"


@pytest.mark.django_db
def test_disallowed_origin_preflight_gets_no_cors_headers(client, settings):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = (ALLOWED_ORIGIN,)
    url = reverse("indieweb:token")

    response = _preflight(client, url, origin=OTHER_ORIGIN)

    assert response.status_code == 405
    assert "Access-Control-Allow-Origin" not in response


@pytest.mark.django_db
def test_preflight_short_circuits_before_rate_limiting_and_token_auth(client, settings):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = (ALLOWED_ORIGIN,)
    settings.INDIEWEB_RATE_LIMITS = {"micropub": {"limit": 1, "window": 60}}
    url = reverse("indieweb:micropub")

    with (
        patch("indieweb.rate_limit.check_rate_limit", wraps=check_rate_limit) as rate_limit,
        patch.object(TokenAuthMixin, "authenticated", return_value=False) as authenticated,
    ):
        response = _preflight(client, url)

    assert response.status_code == 204
    rate_limit.assert_not_called()
    authenticated.assert_not_called()


@pytest.mark.django_db
def test_micropub_preflight_short_circuits_before_handler_work(client, settings):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = (ALLOWED_ORIGIN,)
    url = reverse("indieweb:micropub")

    with patch("indieweb.views.get_micropub_handler") as handler:
        response = _preflight(client, url)

    assert response.status_code == 204
    handler.assert_not_called()


@pytest.mark.django_db
def test_media_preflight_short_circuits_before_auth_and_storage(client, settings):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = (ALLOWED_ORIGIN,)
    url = reverse("indieweb:media")

    with (
        patch.object(TokenAuthMixin, "authenticated", return_value=False) as authenticated,
        patch("indieweb.views.default_storage.save") as storage_save,
    ):
        response = _preflight(client, url)

    assert response.status_code == 204
    authenticated.assert_not_called()
    storage_save.assert_not_called()


@pytest.mark.django_db
def test_websub_callback_is_excluded_from_cors_even_when_cors_is_configured(client, settings, websub_subscription):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = (ALLOWED_ORIGIN,)
    url = reverse("indieweb:websub-callback", args=[websub_subscription.callback_token])

    post_response = client.post(
        url,
        data=b"<feed/>",
        content_type="application/atom+xml",
        HTTP_ORIGIN=ALLOWED_ORIGIN,
    )
    options_response = _preflight(client, url, method="POST")

    assert post_response.status_code == 204
    assert "Access-Control-Allow-Origin" not in post_response
    assert options_response.status_code == 200
    assert "Access-Control-Allow-Origin" not in options_response


@pytest.mark.django_db
def test_webmention_preflight_short_circuits_before_processing_or_enqueue(client, settings):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = (ALLOWED_ORIGIN,)
    settings.INDIEWEB_WEBMENTION_ENQUEUE = "tests.webmention_enqueue_hooks.capture_webmention_id"
    webmention_enqueue_hooks.reset()
    url = reverse("indieweb:webmention")

    with patch("indieweb.views.WebmentionProcessor") as processor_class:
        response = _preflight(client, url)

    assert response.status_code == 204
    processor_class.assert_not_called()
    assert webmention_enqueue_hooks.ENQUEUED_WEBMENTION_IDS == []
    assert models.Webmention.objects.count() == 0


@pytest.mark.django_db
def test_actual_webmention_response_gets_headers_without_changing_processing(client, settings):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = (ALLOWED_ORIGIN,)
    url = reverse("indieweb:webmention")
    payload = _valid_webmention_payload()

    with patch("indieweb.views.WebmentionProcessor") as processor_class:
        processor = processor_class.return_value
        processor.process_webmention.return_value = models.Webmention(id=123)
        response = client.post(url, data=payload, HTTP_ORIGIN=ALLOWED_ORIGIN)

    assert response.status_code == 201
    assert response["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    processor.process_webmention.assert_called_once_with(
        payload["source"],
        payload["target"],
        vouch_url=None,
    )


@pytest.mark.django_db
def test_browser_token_management_ui_is_excluded_from_cors(client, settings, user):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = (ALLOWED_ORIGIN,)
    client.force_login(user)
    list_url = reverse("indieweb:tokens")
    token = models.Token.objects.create(
        owner=user,
        me="https://example.org",
        client_id="https://client.example.org",
        scope="create",
    )
    revoke_url = reverse("indieweb:token-revoke", args=[token.pk])

    list_response = client.get(list_url, HTTP_ORIGIN=ALLOWED_ORIGIN)
    revoke_response = client.options(
        revoke_url,
        HTTP_ORIGIN=ALLOWED_ORIGIN,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
    )

    assert list_response.status_code == 200
    assert "Access-Control-Allow-Origin" not in list_response
    assert revoke_response.status_code == 200
    assert "Access-Control-Allow-Origin" not in revoke_response
