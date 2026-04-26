#!/usr/bin/env python

"""
test_django-indieweb
------------

Tests for `django-indieweb` micropub endpoint.
"""

from datetime import timedelta
from urllib.parse import unquote

import pytest
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


@pytest.mark.django_db
def test_http_authorization_header(client, token, micropub_endpoint_url, micropub_payload):
    """Test that HTTP_AUTHORIZATION header format (used by real HTTP requests) works."""
    # Django's RequestFactory and real HTTP requests use HTTP_AUTHORIZATION
    auth_header = f"Bearer {token.key}"
    response = client.post(micropub_endpoint_url, data=micropub_payload, HTTP_AUTHORIZATION=auth_header)
    assert response.status_code == 201
    assert "Location" in response


@pytest.mark.django_db
def test_unexpired_token_is_accepted(client, user, micropub_endpoint_url, micropub_payload):
    """Tokens with a future expires_at should authenticate normally."""
    token = models.Token.objects.create(
        me="http://example.org",
        client_id="https://webapp.example.org",
        scope="post",
        owner=user,
        expires_at=timezone.now() + timedelta(hours=1),
    )
    auth_header = f"Bearer {token.key}"
    response = client.post(micropub_endpoint_url, data=micropub_payload, Authorization=auth_header)
    assert response.status_code == 201


@pytest.mark.django_db
def test_expired_token_is_rejected(client, user, micropub_endpoint_url, micropub_payload):
    """Tokens whose expires_at is in the past must be rejected with 401."""
    token = models.Token.objects.create(
        me="http://example.org",
        client_id="https://webapp.example.org",
        scope="post",
        owner=user,
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    auth_header = f"Bearer {token.key}"
    response = client.post(micropub_endpoint_url, data=micropub_payload, Authorization=auth_header)
    assert response.status_code == 401


@pytest.mark.django_db
def test_legacy_null_expiry_token_is_accepted(client, token, micropub_endpoint_url, micropub_payload):
    """Tokens with expires_at=None remain valid (backwards compatible)."""
    assert token.expires_at is None
    auth_header = f"Bearer {token.key}"
    response = client.post(micropub_endpoint_url, data=micropub_payload, Authorization=auth_header)
    assert response.status_code == 201


@pytest.mark.django_db
def test_micropub_rejects_disallowed_client_id_via_validator(
    client, settings, token, micropub_endpoint_url, micropub_payload
):
    """Resource server rejects an existing token whose client_id is no longer allowed."""
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.client_id_validators.deny_all"
    auth_header = f"Bearer {token.key}"
    response = client.post(micropub_endpoint_url, data=micropub_payload, Authorization=auth_header)
    assert response.status_code == 403
    assert "invalid_client" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_micropub_accepts_allowed_client_id_via_validator(
    client, settings, token, micropub_endpoint_url, micropub_payload
):
    """Resource server still accepts a token whose client_id passes the validator."""
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.client_id_validators.allow_all"
    auth_header = f"Bearer {token.key}"
    response = client.post(micropub_endpoint_url, data=micropub_payload, Authorization=auth_header)
    assert response.status_code == 201


@pytest.mark.django_db
def test_micropub_rejects_when_validator_misconfigured(
    client, settings, token, micropub_endpoint_url, micropub_payload
):
    """A misconfigured validator fails closed at the resource server."""
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.does_not_exist.nope"
    auth_header = f"Bearer {token.key}"
    response = client.post(micropub_endpoint_url, data=micropub_payload, Authorization=auth_header)
    assert response.status_code == 403
    assert "invalid_client" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_both_authorization_formats(client, token, micropub_endpoint_url):
    """Test that both Authorization and HTTP_AUTHORIZATION formats work for GET requests."""
    # Test with Authorization (test client format)
    auth_header = f"Bearer {token.key}"
    response1 = client.get(micropub_endpoint_url, Authorization=auth_header)
    assert response1.status_code == 200

    # Test with HTTP_AUTHORIZATION (real HTTP format)
    response2 = client.get(micropub_endpoint_url, HTTP_AUTHORIZATION=auth_header)
    assert response2.status_code == 200

    # Both should return the same content
    assert response1.content == response2.content


def _make_token(user, scope: str | None) -> "models.Token":
    return models.Token.objects.create(
        me="http://example.org",
        client_id="https://webapp.example.org",
        scope=scope,
        owner=user,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ["create", "post", "create update delete", "profile create"])
def test_post_create_accepts_create_or_post_scope(client, user, micropub_endpoint_url, micropub_payload, scope):
    """A POST entry create succeeds for ``create`` (standard) or ``post`` (legacy alias)."""
    token = _make_token(user, scope)
    auth_header = f"Bearer {token.key}"
    response = client.post(micropub_endpoint_url, data=micropub_payload, Authorization=auth_header)
    assert response.status_code == 201
    assert "Location" in response


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ["update", "delete", "undelete", "read", "", "createXYZ", "postscript"])
def test_post_create_rejects_other_scopes(client, user, micropub_endpoint_url, micropub_payload, scope):
    """A POST entry create requires exact ``create``/``post`` scope tokens; substrings must not satisfy it."""
    token = _make_token(user, scope)
    auth_header = f"Bearer {token.key}"
    response = client.post(micropub_endpoint_url, data=micropub_payload, Authorization=auth_header)
    assert response.status_code == 403
    assert "authorization error" in response.content.decode("utf-8")


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ["update", "create update", "update delete"])
def test_post_action_update_accepts_update_scope(client, user, micropub_endpoint_url, scope):
    """A POST with ``action=update`` requires the ``update`` scope and reaches the 501 stub."""
    token = _make_token(user, scope)
    auth_header = f"Bearer {token.key}"
    payload = {"action": "update", "url": "https://example.org/post/1"}
    response = client.post(micropub_endpoint_url, data=payload, Authorization=auth_header)
    assert response.status_code == 501


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ["create", "post", "delete", "undelete", "read", ""])
def test_post_action_update_rejects_non_update_scope(client, user, micropub_endpoint_url, scope):
    """``action=update`` must not be authorized by ``create``/``post``/``delete`` (regression)."""
    token = _make_token(user, scope)
    auth_header = f"Bearer {token.key}"
    payload = {"action": "update", "url": "https://example.org/post/1"}
    response = client.post(micropub_endpoint_url, data=payload, Authorization=auth_header)
    assert response.status_code == 403
    assert "authorization error" in response.content.decode("utf-8")


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ["delete", "create delete", "delete update"])
def test_post_action_delete_accepts_delete_scope(client, user, micropub_endpoint_url, scope):
    """A POST with ``action=delete`` requires the ``delete`` scope and reaches the 501 stub."""
    token = _make_token(user, scope)
    auth_header = f"Bearer {token.key}"
    payload = {"action": "delete", "url": "https://example.org/post/1"}
    response = client.post(micropub_endpoint_url, data=payload, Authorization=auth_header)
    assert response.status_code == 501


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ["create", "post", "update", "undelete", ""])
def test_post_action_delete_rejects_non_delete_scope(client, user, micropub_endpoint_url, scope):
    """``action=delete`` must not be authorized by ``create``/``post``/``update``/``undelete`` (regression)."""
    token = _make_token(user, scope)
    auth_header = f"Bearer {token.key}"
    payload = {"action": "delete", "url": "https://example.org/post/1"}
    response = client.post(micropub_endpoint_url, data=payload, Authorization=auth_header)
    assert response.status_code == 403
    assert "authorization error" in response.content.decode("utf-8")


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ["undelete", "delete undelete", "create undelete"])
def test_post_action_undelete_accepts_undelete_scope(client, user, micropub_endpoint_url, scope):
    """A POST with ``action=undelete`` requires the project-defined ``undelete`` scope."""
    token = _make_token(user, scope)
    auth_header = f"Bearer {token.key}"
    payload = {"action": "undelete", "url": "https://example.org/post/1"}
    response = client.post(micropub_endpoint_url, data=payload, Authorization=auth_header)
    assert response.status_code == 501


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ["create", "post", "update", "delete", ""])
def test_post_action_undelete_rejects_non_undelete_scope(client, user, micropub_endpoint_url, scope):
    """``action=undelete`` must not be authorized by ``create``/``post``/``update``/``delete``."""
    token = _make_token(user, scope)
    auth_header = f"Bearer {token.key}"
    payload = {"action": "undelete", "url": "https://example.org/post/1"}
    response = client.post(micropub_endpoint_url, data=payload, Authorization=auth_header)
    assert response.status_code == 403
    assert "authorization error" in response.content.decode("utf-8")


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ["create", "post", "update", "delete", "read", "", None])
def test_get_config_query_has_no_scope_gate(client, user, micropub_endpoint_url, scope):
    """``GET ?q=config`` is token-required only (no scope gate); historically returned 200 for any scope."""
    token = _make_token(user, scope)
    auth_header = f"Bearer {token.key}"
    response = client.get(f"{micropub_endpoint_url}?q=config", Authorization=auth_header)
    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ["create", "post", "update", "delete", "read", "", None])
def test_get_syndicate_to_query_has_no_scope_gate(client, user, micropub_endpoint_url, scope):
    """``GET ?q=syndicate-to`` is token-required only (no scope gate)."""
    token = _make_token(user, scope)
    auth_header = f"Bearer {token.key}"
    response = client.get(f"{micropub_endpoint_url}?q=syndicate-to", Authorization=auth_header)
    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ["create", "post", "update", "delete", "read", "", None])
def test_get_no_query_has_no_scope_gate(client, user, micropub_endpoint_url, scope):
    """``GET`` with no ``q`` returns the user's ``me`` URL for any authenticated token."""
    token = _make_token(user, scope)
    auth_header = f"Bearer {token.key}"
    response = client.get(micropub_endpoint_url, Authorization=auth_header)
    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ["update", "create update", "update delete"])
def test_get_source_query_accepts_update_scope(client, user, micropub_endpoint_url, scope):
    """``GET ?q=source`` requires ``update`` scope (typical use: read post for editing) and reaches the 501 stub."""
    token = _make_token(user, scope)
    auth_header = f"Bearer {token.key}"
    response = client.get(f"{micropub_endpoint_url}?q=source", Authorization=auth_header)
    assert response.status_code == 501


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ["create", "post", "delete", "undelete", "read", ""])
def test_get_source_query_rejects_non_update_scope(client, user, micropub_endpoint_url, scope):
    """``GET ?q=source`` must not be authorized by tokens that lack ``update``."""
    token = _make_token(user, scope)
    auth_header = f"Bearer {token.key}"
    response = client.get(f"{micropub_endpoint_url}?q=source", Authorization=auth_header)
    assert response.status_code == 403
    assert "authorization error" in response.content.decode("utf-8")
