#!/usr/bin/env python

"""
test_django-indieweb
------------

Tests for `django-indieweb` auth endpoint.
"""

from datetime import datetime, timedelta, timezone  # noqa: E501
from urllib.parse import parse_qs, urlparse

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils.http import urlencode

from indieweb.models import Auth


@pytest.fixture
def user(db):
    return User.objects.create_user(username="foo", email="foo@example.org", password="password")


@pytest.fixture
def auth_endpoint_url():
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": 1234567890,
        "scope": "post",
    }
    return f"{base_url}?{urlencode(url_params)}"


@pytest.mark.django_db
def test_not_authenticated(client, auth_endpoint_url):
    """
    Assure we are redirected to login if we try to get an auth-code
    from the indieweb auth endpoint and are not yet logged in.
    """
    response = client.get(auth_endpoint_url)
    assert response.status_code == 302
    assert "login" in response.url


@pytest.mark.django_db
def test_authenticated_without_params(client, user):
    """Assure get without proper parameters raises an error."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    response = client.get(base_url)
    assert response.status_code == 404
    assert "missing" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_authenticated(client, user, auth_endpoint_url):
    """Assure we get back an auth code if we are authenticated."""
    client.login(username=user.username, password="password")
    response = client.get(auth_endpoint_url)
    assert response.status_code == 302
    assert "code" in response.url


@pytest.mark.django_db
def test_get_or_create(client, user, auth_endpoint_url):
    """Test get or create logic for Auth object."""
    client.login(username=user.username, password="password")
    for _i in range(2):
        response = client.get(auth_endpoint_url)
        assert response.status_code == 302
        assert "code" in response.url


@pytest.mark.django_db
def test_auth_timeout_reset(client, user, auth_endpoint_url):
    """Test timeout is reset on new authentication."""
    client.login(username=user.username, password="password")
    response = client.get(auth_endpoint_url)
    data = parse_qs(urlparse(response.url).query)
    auth = Auth.objects.get(owner=user, me=data["me"][0])
    timeout = getattr(settings, "INDIWEB_AUTH_CODE_TIMEOUT", 60)
    auth.created = auth.created - timedelta(seconds=timeout + 10)
    auth.save()
    response = client.get(auth_endpoint_url)
    auth = Auth.objects.get(owner=user, me=data["me"][0])
    assert (datetime.now(timezone.utc) - auth.created).seconds <= timeout
