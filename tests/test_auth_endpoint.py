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
def test_authenticated_shows_consent_screen(client, user, auth_endpoint_url):
    """Assure we see the consent screen when authenticated."""
    client.login(username=user.username, password="password")
    response = client.get(auth_endpoint_url)
    assert response.status_code == 200

    # Verify the consent template was used
    assert hasattr(response, "templates"), "Response should have templates attribute"
    template_names = [t.name for t in response.templates]
    assert "indieweb/consent.html" in template_names, f"Expected consent.html template, got: {template_names}"

    # Verify context data
    assert hasattr(response, "context"), "Response should have context attribute"
    assert response.context["client_id"] == "https://webapp.example.org"
    assert response.context["redirect_uri"] == "https://webapp.example.org/auth/callback"
    assert response.context["state"] == "1234567890"
    assert response.context["me"] == "http://example.org"
    assert response.context["scope"] == "post"
    assert response.context["scope_list"] == ["post"]


@pytest.mark.django_db
def test_consent_approval(client, user):
    """Test approving consent creates auth code and redirects."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")

    # Submit approval form
    form_data = {
        "action": "approve",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "me": "http://example.org",
        "scope": "post",
    }
    response = client.post(base_url, data=form_data)

    # Should redirect with auth code
    assert response.status_code == 302
    assert "code" in response.url
    assert "state=1234567890" in response.url
    assert "me=http%3A%2F%2Fexample.org" in response.url

    # Auth object should be created
    auth = Auth.objects.get(client_id="https://webapp.example.org", me="http://example.org")
    assert auth.owner == user
    assert auth.scope == "post"


@pytest.mark.django_db
def test_consent_denial(client, user):
    """Test denying consent redirects with error."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")

    # Submit denial form
    form_data = {
        "action": "deny",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "me": "http://example.org",
        "scope": "post",
    }
    response = client.post(base_url, data=form_data)

    # Should redirect with error
    assert response.status_code == 302
    assert "error=access_denied" in response.url
    assert "state=1234567890" in response.url

    # No Auth object should be created
    assert Auth.objects.filter(client_id="https://webapp.example.org", me="http://example.org").count() == 0


@pytest.mark.django_db
def test_get_or_create(client, user):
    """Test get or create logic for Auth object."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")

    # First approval
    form_data = {
        "action": "approve",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "me": "http://example.org",
        "scope": "post",
    }

    for _i in range(2):
        response = client.post(base_url, data=form_data)
        assert response.status_code == 302
        assert "code" in response.url
        # Should only have one Auth object
        assert Auth.objects.filter(client_id="https://webapp.example.org", me="http://example.org").count() == 1


@pytest.mark.django_db
def test_auth_timeout_reset(client, user):
    """Test timeout is reset on new authentication."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")

    # First approval
    form_data = {
        "action": "approve",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "me": "http://example.org",
        "scope": "post",
    }
    response = client.post(base_url, data=form_data)
    data = parse_qs(urlparse(response.url).query)
    auth = Auth.objects.get(owner=user, me=data["me"][0])
    timeout = getattr(settings, "INDIWEB_AUTH_CODE_TIMEOUT", 60)
    auth.created = auth.created - timedelta(seconds=timeout + 10)
    auth.save()

    # Second approval should reset timeout
    response = client.post(base_url, data=form_data)
    auth = Auth.objects.get(owner=user, me=data["me"][0])
    assert (datetime.now(timezone.utc) - auth.created).seconds <= timeout


@pytest.mark.django_db
def test_post_verify_auth_code(client, user):
    """Test POST request to verify auth code."""
    client.login(username=user.username, password="password")

    # Create an auth code
    auth = Auth.objects.create(
        owner=user,
        client_id="https://webapp.example.org",
        redirect_uri="https://webapp.example.org/auth/callback",
        state="1234567890",
        scope="post",
        me="http://example.org",
    )

    # Verify the auth code
    base_url = reverse("indieweb:auth")
    verify_data = {
        "code": auth.key,
        "client_id": "https://webapp.example.org",
    }
    response = client.post(base_url, data=verify_data)

    assert response.status_code == 200
    assert "me=http%3A%2F%2Fexample.org" in response.content.decode("utf-8")
