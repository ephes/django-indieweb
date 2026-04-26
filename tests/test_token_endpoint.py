#!/usr/bin/env python

"""
test_django-indieweb
------------

Tests for `django-indieweb` auth endpoint.
"""

from datetime import timedelta
from urllib.parse import parse_qs, unquote

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from indieweb import models


@pytest.fixture
def user(db):
    return User.objects.create_user(username="foo", email="foo@example.org", password="password")


@pytest.fixture
def auth(user):
    return models.Auth.objects.create(
        owner=user,
        key="authkey",
        state=1234567890,
        me="http://example.org",
        scope="post",
        client_id="https://webapp.example.org",
    )


@pytest.fixture
def token_payload(auth):
    return {
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "code": auth.key,
        "state": auth.state,
        "me": auth.me,
        "scope": auth.scope,
        "client_id": auth.client_id,
    }


@pytest.fixture
def token_endpoint_url():
    return reverse("indieweb:token")


@pytest.mark.django_db
def test_wrong_auth_code(client, token_endpoint_url, token_payload):
    """Assert we can't get a token with the wrong auth code."""
    token_payload["code"] = "wrong_key"
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 400
    assert "invalid_grant" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_correct_auth_code(client, token_endpoint_url, token_payload):
    """Assert we get a token when the auth code is correct."""
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert "access_token" in data


@pytest.mark.django_db
def test_auth_code_timeout(client, auth, token_endpoint_url, token_payload):
    """Assert we can't get a token when the auth code is outdated."""
    timeout = getattr(settings, "INDIWEB_AUTH_CODE_TIMEOUT", 60)
    to_old_delta = timedelta(seconds=(timeout + 1))
    auth.created = auth.created - to_old_delta
    auth.save()
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 400
    assert "invalid_grant" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_token_exchange_without_me_parameter(client, auth, token_endpoint_url):
    """Test that token exchange works without the optional 'me' parameter."""
    # IndieAuth spec says 'me' is optional in token exchange
    token_payload = {
        "code": auth.key,
        "client_id": auth.client_id,
        # 'me' parameter intentionally omitted
    }
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert "access_token" in data
    assert data["me"][0] == auth.me  # Should get 'me' from auth object


@pytest.mark.django_db
def test_auth_code_timeout_multi_day(client, auth, token_endpoint_url, token_payload):
    """Auth codes older than one day must be rejected even when seconds-of-day is small."""
    # timedelta.seconds wraps at one day; total_seconds() must be used.
    auth.created = auth.created - timedelta(days=2, seconds=5)
    auth.save()
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 400
    assert "invalid_grant" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_token_response_advertises_configured_lifetime(client, settings, token_endpoint_url, token_payload):
    """Token response expires_in should reflect the configured token lifetime."""
    settings.INDIEWEB_TOKEN_EXPIRES_IN = 3600
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    expires_in = int(data["expires_in"][0])
    # Allow tiny clock drift in the round trip.
    assert 3590 <= expires_in <= 3600


@pytest.mark.django_db
def test_token_row_gets_expires_at(client, settings, token_endpoint_url, token_payload):
    """Token rows must persist an expires_at consistent with the configured lifetime."""
    settings.INDIEWEB_TOKEN_EXPIRES_IN = 3600
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    token = models.Token.objects.get(key=data["access_token"][0])
    assert token.expires_at is not None
    delta = token.expires_at - timezone.now()
    # Allow tiny clock drift in the round trip.
    assert timedelta(seconds=3590) <= delta <= timedelta(seconds=3600)


@pytest.mark.django_db
def test_token_reissue_resets_expires_at(client, settings, token_endpoint_url, token_payload, user):
    """Reissuing a token (same client/scope/me) refreshes expires_at."""
    settings.INDIEWEB_TOKEN_EXPIRES_IN = 3600
    # Pre-create a token row that is about to expire.
    stale = models.Token.objects.create(
        owner=user,
        client_id=token_payload["client_id"],
        me=token_payload["me"],
        scope=token_payload["scope"],
        expires_at=timezone.now() + timedelta(seconds=5),
    )
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 200
    stale.refresh_from_db()
    assert stale.expires_at is not None
    delta = stale.expires_at - timezone.now()
    assert delta >= timedelta(seconds=3590)
