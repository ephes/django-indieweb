#!/usr/bin/env python

"""
test_django-indieweb
------------

Tests for `django-indieweb` micropub endpoint.
"""

from urllib.parse import unquote

import pytest
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
    )


@pytest.fixture
def token(user):
    return models.Token.objects.create(
        me="http://example.org", client_id="https://webapp.example.org", scope="post", owner=user
    )


@pytest.fixture
def micropub_endpoint_url():
    return reverse("indieweb:micropub")


@pytest.fixture
def micropub_payload():
    return {"content": "foobar", "h": "entry"}


@pytest.mark.django_db
def test_no_token(client, micropub_endpoint_url, micropub_payload):
    """Assert we can't post to the endpoint without token."""
    response = client.post(micropub_endpoint_url, data=micropub_payload)
    assert response.status_code == 401
    assert "error" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_wrong_token(client, micropub_endpoint_url, micropub_payload):
    """Assert we can't post to the endpoint without the right token."""
    auth_header = "Bearer wrongtoken"
    response = client.post(micropub_endpoint_url, data=micropub_payload, Authorization=auth_header)
    assert response.status_code == 401
    assert "error" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_correct_token_header(client, token, micropub_endpoint_url, micropub_payload):
    """
    Assert we can post to the endpoint with the right token
    submitted in the requests header.
    """
    auth_header = f"Bearer {token.key}"
    response = client.post(micropub_endpoint_url, data=micropub_payload, Authorization=auth_header)
    assert response.status_code == 201
    assert "Location" in response  # Should return Location header


@pytest.mark.django_db
def test_correct_token_body(client, token, micropub_endpoint_url, micropub_payload):
    """
    Assert we can post to the endpoint with the right token
    submitted in the requests body.
    """
    auth_body = f"Bearer {token.key}"
    micropub_payload["Authorization"] = auth_body
    response = client.post(micropub_endpoint_url, data=micropub_payload)
    assert response.status_code == 201
    assert "Location" in response  # Should return Location header


@pytest.mark.django_db
def test_not_authorized(client, token, micropub_endpoint_url, micropub_payload):
    """Assure we cant post if we don't have the right scope."""
    auth_body = f"Bearer {token.key}"
    old_scope = token.scope
    token.scope = "foo"
    token.save()
    micropub_payload["Authorization"] = auth_body
    response = client.post(micropub_endpoint_url, data=micropub_payload)
    assert response.status_code == 403
    assert "error" in response.content.decode("utf-8")
    # Restore scope for cleanup
    token.scope = old_scope
    token.save()


# Property tests removed - parsing logic is now tested via integration tests in test_micropub_create.py


@pytest.mark.django_db
def test_token_verification_on_get(client, token, micropub_endpoint_url):
    """
    Test authentication tokens via get request to micropub endpoint.
    """
    auth_header = f"Bearer {token.key}"
    response = client.get(micropub_endpoint_url, Authorization=auth_header)
    response_text = unquote(response.content.decode("utf-8"))
    assert response.status_code == 200
    assert token.me in response_text


@pytest.mark.django_db
def test_token_verification_on_get_wrong(client, micropub_endpoint_url):
    """
    Test wrong authentication tokens via get request to micropub endpoint.
    """
    auth_header = "Bearer wrong_token"
    response = client.get(micropub_endpoint_url, Authorization=auth_header)
    assert response.status_code == 401


@pytest.mark.django_db
def test_create_scope_authorization(client, user, micropub_endpoint_url, micropub_payload):
    """Test that tokens with 'create' scope (standard Micropub) are authorized."""
    # Create token with 'create' scope instead of 'post'
    token = models.Token.objects.create(
        me="http://example.org", client_id="https://webapp.example.org", scope="create", owner=user
    )

    auth_header = f"Bearer {token.key}"
    response = client.post(micropub_endpoint_url, data=micropub_payload, Authorization=auth_header)
    assert response.status_code == 201
    assert "Location" in response


@pytest.mark.django_db
def test_multiple_scopes_authorization(client, user, micropub_endpoint_url, micropub_payload):
    """Test that tokens with multiple scopes including 'create' are authorized."""
    # Create token with multiple scopes as sent by Quill
    token = models.Token.objects.create(
        me="http://example.org", client_id="https://quill.p3k.io/", scope="profile create update media", owner=user
    )

    auth_header = f"Bearer {token.key}"
    response = client.post(micropub_endpoint_url, data=micropub_payload, Authorization=auth_header)
    assert response.status_code == 201
    assert "Location" in response
