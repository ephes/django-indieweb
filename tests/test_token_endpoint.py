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
    assert response.status_code == 401
    assert "error" in response.content.decode("utf-8")


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
    assert response.status_code == 401
    assert "error" in response.content.decode("utf-8")
