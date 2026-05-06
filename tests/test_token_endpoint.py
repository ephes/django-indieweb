#!/usr/bin/env python

"""
test_django-indieweb
------------

Tests for `django-indieweb` auth endpoint.
"""

import logging
from datetime import timedelta
from urllib.parse import parse_qs, unquote

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from indieweb import models
from indieweb.views import _authorization_bearer_token


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


@pytest.fixture
def token_introspection_endpoint_url():
    return reverse("indieweb:token-introspection")


@pytest.mark.django_db
def test_wrong_auth_code(client, token_endpoint_url, token_payload):
    """Assert we can't get a token with the wrong auth code."""
    token_payload["code"] = "wrong_key"
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 400
    assert "invalid_grant" in response.content.decode("utf-8")
    assert models.Auth.objects.filter(key="authkey").exists()
    assert models.Token.objects.count() == 0


@pytest.mark.django_db
def test_correct_auth_code(client, auth, token_endpoint_url, token_payload):
    """Assert we get a token when the auth code is correct."""
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert "access_token" in data
    assert data["token_type"] == ["Bearer"]
    assert not models.Auth.objects.filter(pk=auth.pk).exists()


@pytest.mark.django_db
def test_token_exchange_accepts_grant_type_authorization_code(client, token_endpoint_url, token_payload):
    """Token POST accepts the current IndieAuth authorization_code grant_type."""
    token_payload["grant_type"] = "authorization_code"
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert data["token_type"] == ["Bearer"]


@pytest.mark.django_db
def test_token_exchange_accepts_omitted_grant_type_for_legacy_clients(client, token_endpoint_url, token_payload):
    """Token POST keeps accepting legacy requests that omit grant_type."""
    token_payload.pop("grant_type", None)
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert "access_token" in data


@pytest.mark.django_db
def test_token_exchange_rejects_invalid_grant_type_without_token(client, token_endpoint_url, token_payload):
    """Token POST rejects present grant_type values other than authorization_code."""
    token_payload["grant_type"] = "client_credentials"
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 400
    assert response["Content-Type"] == "application/x-www-form-urlencoded"
    assert response.content == b"invalid_request"
    assert models.Token.objects.count() == 0


@pytest.mark.django_db
def test_token_exchange_without_scope_uses_stored_auth_scope(client, auth, token_endpoint_url):
    """Omitting scope at token exchange issues the scope stored with the auth code."""
    auth.scope = "create update"
    auth.save()
    response = client.post(
        token_endpoint_url,
        data={
            "code": auth.key,
            "client_id": auth.client_id,
        },
    )
    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert data["scope"] == ["create update"]
    token = models.Token.objects.get(key=data["access_token"][0])
    assert token.scope == "create update"


@pytest.mark.django_db
def test_token_exchange_returns_json_when_requested(client, auth, token_endpoint_url):
    """Token POST returns JSON when the client explicitly prefers JSON."""
    auth.scope = "create update"
    auth.save()
    response = client.post(
        token_endpoint_url,
        data={
            "grant_type": "authorization_code",
            "code": auth.key,
            "client_id": auth.client_id,
        },
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 201
    assert response["Content-Type"] == "application/json"
    data = response.json()
    assert data["access_token"]
    assert data["token_type"] == "Bearer"
    assert data["expires_in"] >= 0
    assert data["scope"] == "create update"
    assert data["me"] == auth.me


@pytest.mark.django_db
def test_token_exchange_keeps_default_form_response_for_wildcard_accept(client, auth, token_endpoint_url):
    """Wildcard Accept headers do not switch legacy token responses to JSON."""
    response = client.post(
        token_endpoint_url,
        data={
            "code": auth.key,
            "client_id": auth.client_id,
        },
        HTTP_ACCEPT="*/*",
    )
    assert response.status_code == 201
    assert response["Content-Type"] == "application/x-www-form-urlencoded"
    data = parse_qs(response.content.decode("utf-8"), keep_blank_values=True)
    assert data["token_type"] == ["Bearer"]


@pytest.mark.django_db
def test_token_reissue_json_response_keeps_status_and_token_type(
    client, settings, token_endpoint_url, token_payload, user
):
    """Reissued token JSON responses keep 200 semantics while rotating the bearer key."""
    settings.INDIEWEB_TOKEN_EXPIRES_IN = 3600
    existing = models.Token.objects.create(
        owner=user,
        client_id=token_payload["client_id"],
        me=token_payload["me"],
        scope=token_payload["scope"],
        expires_at=timezone.now() + timedelta(seconds=5),
    )
    response = client.post(token_endpoint_url, data=token_payload, HTTP_ACCEPT="application/json")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response.json()["access_token"] != existing.key
    assert response.json()["token_type"] == "Bearer"


@pytest.mark.django_db
def test_token_exchange_without_scope_allows_no_scope_auth_code(client, auth, token_endpoint_url):
    """Omitting scope at token exchange works for a no-scope auth code."""
    auth.scope = None
    auth.save()
    response = client.post(
        token_endpoint_url,
        data={
            "code": auth.key,
            "client_id": auth.client_id,
        },
    )
    assert response.status_code == 201
    data = parse_qs(response.content.decode("utf-8"), keep_blank_values=True)
    assert data["scope"] == [""]
    token = models.Token.objects.get(key=data["access_token"][0])
    assert token.scope is None


@pytest.mark.django_db
def test_token_exchange_with_matching_scope_succeeds(client, auth, token_endpoint_url):
    """A submitted scope matching the auth-code scope is accepted."""
    auth.scope = "create update"
    auth.save()
    response = client.post(
        token_endpoint_url,
        data={
            "code": auth.key,
            "client_id": auth.client_id,
            "scope": "create update",
        },
    )
    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert data["scope"] == ["create update"]


@pytest.mark.django_db
def test_token_exchange_with_equivalent_normalized_scope_succeeds(client, auth, token_endpoint_url):
    """Whitespace and duplicate differences are normalized before scope comparison."""
    auth.scope = "create update"
    auth.save()
    response = client.post(
        token_endpoint_url,
        data={
            "code": auth.key,
            "client_id": auth.client_id,
            "scope": " create  update create ",
        },
    )
    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert data["scope"] == ["create update"]


@pytest.mark.django_db
def test_token_exchange_rejects_different_scope_without_token(client, auth, token_endpoint_url):
    """A token request cannot broaden or replace the approved scope."""
    auth.scope = "create"
    auth.save()
    response = client.post(
        token_endpoint_url,
        data={
            "code": auth.key,
            "client_id": auth.client_id,
            "scope": "create delete",
        },
    )
    assert response.status_code == 400
    assert response["Content-Type"] == "application/x-www-form-urlencoded"
    assert "invalid_grant" in response.content.decode("utf-8")
    assert models.Token.objects.count() == 0
    assert not models.Auth.objects.filter(pk=auth.pk).exists()

    replay = client.post(
        token_endpoint_url,
        data={
            "code": auth.key,
            "client_id": auth.client_id,
            "scope": "create",
        },
    )
    assert replay.status_code == 400
    assert "invalid_grant" in replay.content.decode("utf-8")
    assert models.Token.objects.count() == 0


@pytest.mark.django_db
def test_token_exchange_rejects_different_scope_without_reissue(client, settings, auth, token_endpoint_url, user):
    """A mismatched scope does not refresh an existing token row."""
    settings.INDIEWEB_TOKEN_EXPIRES_IN = 3600
    auth.scope = "create"
    auth.save()
    stale_expires_at = timezone.now() + timedelta(seconds=5)
    token = models.Token.objects.create(
        owner=user,
        client_id=auth.client_id,
        me=auth.me,
        scope="create",
        expires_at=stale_expires_at,
    )
    response = client.post(
        token_endpoint_url,
        data={
            "code": auth.key,
            "client_id": auth.client_id,
            "scope": "delete",
        },
    )
    assert response.status_code == 400
    token.refresh_from_db()
    assert token.expires_at == stale_expires_at
    assert models.Token.objects.count() == 1
    assert not models.Auth.objects.filter(pk=auth.pk).exists()


@pytest.mark.django_db
def test_token_exchange_rejects_empty_scope_parameter_for_scoped_auth_code(client, auth, token_endpoint_url):
    """An explicitly empty scope parameter normalizes to no scope and must still match."""
    auth.scope = "create"
    auth.save()
    response = client.post(
        token_endpoint_url,
        data={
            "code": auth.key,
            "client_id": auth.client_id,
            "scope": "",
        },
    )
    assert response.status_code == 400
    assert response["Content-Type"] == "application/x-www-form-urlencoded"
    assert "invalid_grant" in response.content.decode("utf-8")
    assert models.Token.objects.count() == 0
    assert not models.Auth.objects.filter(pk=auth.pk).exists()


@pytest.mark.django_db
def test_token_exchange_accepts_empty_scope_parameter_for_no_scope_auth_code(client, auth, token_endpoint_url):
    """An explicitly empty scope parameter is equivalent to no scope for a no-scope auth code."""
    auth.scope = None
    auth.save()
    response = client.post(
        token_endpoint_url,
        data={
            "code": auth.key,
            "client_id": auth.client_id,
            "scope": "",
        },
    )
    assert response.status_code == 201
    data = parse_qs(response.content.decode("utf-8"), keep_blank_values=True)
    assert data["scope"] == [""]
    token = models.Token.objects.get(key=data["access_token"][0])
    assert token.scope is None


@pytest.mark.django_db
def test_token_exchange_cannot_override_no_scope_auth_code(client, auth, token_endpoint_url):
    """An auth code issued without scope cannot be exchanged for a scoped token."""
    auth.scope = None
    auth.save()
    response = client.post(
        token_endpoint_url,
        data={
            "code": auth.key,
            "client_id": auth.client_id,
            "scope": "create",
        },
    )
    assert response.status_code == 400
    assert response["Content-Type"] == "application/x-www-form-urlencoded"
    assert "invalid_grant" in response.content.decode("utf-8")
    assert models.Token.objects.count() == 0
    assert not models.Auth.objects.filter(pk=auth.pk).exists()


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
    assert not models.Auth.objects.filter(pk=auth.pk).exists()


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
    assert not models.Auth.objects.filter(pk=auth.pk).exists()


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
@pytest.mark.parametrize(
    "bad_redirect_uri",
    [
        "https://webapp.example.org/auth/callback#section",
        "https://webapp.example.org/auth/callback#",
        "https://User:Pass@webapp.example.org/auth/callback",
        "ftp://webapp.example.org/auth/callback",
        "javascript:alert(1)",
        "not a url",
    ],
)
def test_token_rejects_invalid_redirect_uri(client, token_endpoint_url, token_payload, bad_redirect_uri):
    """Token endpoint rejects malformed submitted redirect_uri with invalid_grant."""
    token_payload["redirect_uri"] = bad_redirect_uri
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 400
    assert "invalid_grant" in response.content.decode("utf-8")
    assert models.Auth.objects.filter(key=token_payload["code"]).exists()
    assert models.Token.objects.count() == 0


@pytest.mark.django_db
def test_token_rejects_omitted_redirect_uri_when_auth_code_has_one(client, auth, token_endpoint_url):
    """A redirect_uri-bound auth code must be redeemed with redirect_uri."""
    auth.redirect_uri = "https://webapp.example.org/auth/callback"
    auth.save()

    response = client.post(
        token_endpoint_url,
        data={
            "code": auth.key,
            "client_id": auth.client_id,
        },
    )

    assert response.status_code == 400
    assert response["Content-Type"] == "application/x-www-form-urlencoded"
    assert response.content == b"invalid_grant"
    assert models.Token.objects.count() == 0
    assert not models.Auth.objects.filter(pk=auth.pk).exists()

    replay = client.post(
        token_endpoint_url,
        data={
            "code": auth.key,
            "client_id": auth.client_id,
            "redirect_uri": auth.redirect_uri,
        },
    )
    assert replay.status_code == 400
    assert replay.content == b"invalid_grant"


@pytest.mark.django_db
def test_token_does_not_delete_unrelated_auth_on_malformed_redirect_uri(client, user, token_endpoint_url):
    """Malformed submitted redirect_uri is rejected before any auth-code lookup/deletion."""
    other = models.Auth.objects.create(
        owner=user,
        client_id="https://other.example.org",
        redirect_uri="https://other.example.org/callback",
        state="other",
        me="https://example.org",
    )

    response = client.post(
        token_endpoint_url,
        data={
            "code": "not-a-real-code",
            "client_id": "https://webapp.example.org",
            "redirect_uri": "https://webapp.example.org/callback#fragment",
        },
    )

    assert response.status_code == 400
    assert response["Content-Type"] == "application/x-www-form-urlencoded"
    assert response.content == b"invalid_grant"
    assert models.Auth.objects.filter(pk=other.pk).exists()
    assert models.Token.objects.count() == 0


@pytest.mark.django_db
def test_token_consumes_auth_with_pathological_stored_redirect_uri(client, auth, token_endpoint_url, token_payload):
    """Historical stored redirect_uri values that fail IDNA normalization do not 500."""
    auth.redirect_uri = "http://../callback"
    auth.save()

    response = client.post(token_endpoint_url, data=token_payload)

    assert response.status_code == 400
    assert response["Content-Type"] == "application/x-www-form-urlencoded"
    assert response.content == b"invalid_grant"
    assert models.Token.objects.count() == 0
    assert not models.Auth.objects.filter(pk=auth.pk).exists()


@pytest.mark.django_db
def test_token_accepts_exact_redirect_uri_match(client, auth, token_endpoint_url, token_payload):
    """Submitted redirect_uri matching the stored auth-code value is accepted."""
    auth.redirect_uri = "https://webapp.example.org/auth/callback"
    auth.save()
    token_payload["redirect_uri"] = auth.redirect_uri

    response = client.post(token_endpoint_url, data=token_payload)

    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert "access_token" in data


@pytest.mark.django_db
def test_token_accepts_case_only_difference_in_redirect_uri(client, auth, token_endpoint_url, token_payload):
    """Submitted redirect_uri matching stored value only by scheme/host case is accepted."""
    auth.redirect_uri = "https://webapp.example.org/auth/callback"
    auth.save()
    token_payload["redirect_uri"] = "HTTPS://WebApp.Example.ORG/auth/callback"
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert "access_token" in data


@pytest.mark.django_db
def test_token_accepts_default_port_difference_in_redirect_uri(client, auth, token_endpoint_url, token_payload):
    """Default HTTP(S) ports are collapsed before redirect_uri comparison."""
    auth.redirect_uri = "https://webapp.example.org/auth/callback"
    auth.save()
    token_payload["redirect_uri"] = "https://webapp.example.org:443/auth/callback"

    response = client.post(token_endpoint_url, data=token_payload)

    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert "access_token" in data


@pytest.mark.django_db
def test_token_accepts_idna_equivalent_redirect_uri(client, auth, token_endpoint_url, token_payload):
    """Unicode and IDNA-encoded host forms compare equivalent."""
    auth.redirect_uri = "https://bücher.example/auth/callback"
    auth.save()
    token_payload["redirect_uri"] = "https://xn--bcher-kva.example/auth/callback"

    response = client.post(token_endpoint_url, data=token_payload)

    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert "access_token" in data


@pytest.mark.django_db
def test_token_accepts_percent_triplet_case_difference_in_redirect_uri(
    client, auth, token_endpoint_url, token_payload
):
    """Percent-encoded triplet case is normalized before redirect_uri comparison."""
    auth.redirect_uri = "https://webapp.example.org/auth/%7Ecallback?next=%2Fhome"
    auth.save()
    token_payload["redirect_uri"] = "https://webapp.example.org/auth/%7ecallback?next=%2fhome"

    response = client.post(token_endpoint_url, data=token_payload)

    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert "access_token" in data


@pytest.mark.django_db
def test_token_accepts_root_empty_path_equivalent_redirect_uri(client, auth, token_endpoint_url, token_payload):
    """A root redirect_uri with no path is equivalent to the same URL with ``/``."""
    auth.redirect_uri = "https://webapp.example.org"
    auth.save()
    token_payload["redirect_uri"] = "https://webapp.example.org/"

    response = client.post(token_endpoint_url, data=token_payload)

    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert "access_token" in data


@pytest.mark.django_db
def test_token_rejects_non_default_port_difference_in_redirect_uri(client, auth, token_endpoint_url, token_payload):
    """Non-default ports remain semantically significant."""
    auth.redirect_uri = "https://webapp.example.org:8443/auth/callback"
    auth.save()
    token_payload["redirect_uri"] = "https://webapp.example.org/auth/callback"

    response = client.post(token_endpoint_url, data=token_payload)

    assert response.status_code == 400
    assert response.content == b"invalid_grant"
    assert not models.Auth.objects.filter(pk=auth.pk).exists()


@pytest.mark.django_db
def test_token_rejects_path_only_difference_in_redirect_uri(client, auth, token_endpoint_url, token_payload):
    """Submitted redirect_uri whose path differs is rejected as invalid_grant."""
    auth.redirect_uri = "https://webapp.example.org/auth/callback"
    auth.save()
    token_payload["redirect_uri"] = "https://webapp.example.org/auth/other"
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 400
    assert "invalid_grant" in response.content.decode("utf-8")
    assert not models.Auth.objects.filter(pk=auth.pk).exists()

    token_payload["redirect_uri"] = auth.redirect_uri
    replay = client.post(token_endpoint_url, data=token_payload)
    assert replay.status_code == 400
    assert "invalid_grant" in replay.content.decode("utf-8")
    assert models.Token.objects.count() == 0


@pytest.mark.django_db
def test_token_rejects_query_difference_in_redirect_uri(client, auth, token_endpoint_url, token_payload):
    """Query differences remain semantically significant."""
    auth.redirect_uri = "https://webapp.example.org/auth/callback?next=/one"
    auth.save()
    token_payload["redirect_uri"] = "https://webapp.example.org/auth/callback?next=/two"

    response = client.post(token_endpoint_url, data=token_payload)

    assert response.status_code == 400
    assert response.content == b"invalid_grant"
    assert models.Token.objects.count() == 0
    assert not models.Auth.objects.filter(pk=auth.pk).exists()


PKCE_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
PKCE_S256_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


@pytest.mark.django_db
def test_token_legacy_no_pkce_round_trip(client, auth, token_endpoint_url, token_payload):
    """Auth code with no stored challenge accepts a token request with no verifier (legacy)."""
    assert auth.code_challenge in (None, "")
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert "access_token" in data


@pytest.mark.django_db
def test_token_rejects_missing_verifier_when_challenge_stored(client, auth, token_endpoint_url, token_payload):
    """If the auth row has a code_challenge, a missing code_verifier is invalid_grant."""
    auth.code_challenge = PKCE_S256_CHALLENGE
    auth.code_challenge_method = "S256"
    auth.save()
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 400
    assert "invalid_grant" in response.content.decode("utf-8")
    # PKCE failure deletes the auth row to preserve one-time-use semantics.
    assert not models.Auth.objects.filter(pk=auth.pk).exists()

    token_payload["code_verifier"] = PKCE_VERIFIER
    replay = client.post(token_endpoint_url, data=token_payload)
    assert replay.status_code == 400
    assert "invalid_grant" in replay.content.decode("utf-8")
    assert models.Token.objects.count() == 0


@pytest.mark.django_db
def test_token_rejects_verifier_when_no_challenge_stored(client, auth, token_endpoint_url, token_payload):
    """If no challenge is stored, submitting a verifier is invalid_grant."""
    token_payload["code_verifier"] = PKCE_VERIFIER
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 400
    assert "invalid_grant" in response.content.decode("utf-8")
    assert not models.Auth.objects.filter(pk=auth.pk).exists()


@pytest.mark.django_db
def test_token_accepts_correct_s256_verifier(client, auth, token_endpoint_url, token_payload):
    """A correct S256 verifier matches the stored S256 challenge."""
    auth.code_challenge = PKCE_S256_CHALLENGE
    auth.code_challenge_method = "S256"
    auth.save()
    token_payload["code_verifier"] = PKCE_VERIFIER
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert "access_token" in data


@pytest.mark.django_db
def test_token_accepts_correct_plain_verifier(client, auth, token_endpoint_url, token_payload):
    """A correct plain verifier matches the stored plain challenge."""
    auth.code_challenge = PKCE_VERIFIER
    auth.code_challenge_method = "plain"
    auth.save()
    token_payload["code_verifier"] = PKCE_VERIFIER
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert "access_token" in data


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["plain", "S256"])
def test_token_rejects_wrong_verifier(client, auth, token_endpoint_url, token_payload, method):
    """Mismatched verifier is rejected for both methods."""
    auth.code_challenge = PKCE_S256_CHALLENGE if method == "S256" else PKCE_VERIFIER
    auth.code_challenge_method = method
    auth.save()
    token_payload["code_verifier"] = "WRONGverifierWRONGverifierWRONGverifierWRONG"  # 44 chars
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 400
    assert "invalid_grant" in response.content.decode("utf-8")
    assert not models.Auth.objects.filter(pk=auth.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "bad_verifier",
    [
        "short",  # below RFC minimum 43
        "a" * 42,  # exactly below minimum
        "a" * 129,  # above RFC maximum 128
        "abc!" + "a" * 40,  # disallowed character
        "abc def" + "a" * 36,  # whitespace
        "abc/def" + "a" * 36,  # slash not in unreserved
    ],
)
def test_token_rejects_malformed_verifier(client, auth, token_endpoint_url, token_payload, bad_verifier):
    """Verifiers outside the RFC unreserved set or length bounds are rejected."""
    auth.code_challenge = PKCE_VERIFIER
    auth.code_challenge_method = "plain"
    auth.save()
    token_payload["code_verifier"] = bad_verifier
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 400
    assert "invalid_grant" in response.content.decode("utf-8")
    assert not models.Auth.objects.filter(pk=auth.pk).exists()


@pytest.mark.django_db
def test_token_exchange_logs_redact_full_authorization_code(client, caplog, token_endpoint_url):
    """Token exchange failure logs must not disclose full authorization codes."""
    submitted_code = "authorization-code-secret-for-logs"

    with caplog.at_level(logging.ERROR, logger="indieweb.views"):
        response = client.post(
            token_endpoint_url,
            data={
                "code": submitted_code,
                "client_id": "https://webapp.example.org",
            },
        )

    assert response.status_code == 400
    assert "invalid_grant" in response.content.decode("utf-8")
    assert submitted_code not in caplog.text
    assert "author..." in caplog.text


@pytest.mark.django_db
def test_token_exchange_success_logs_redact_full_authorization_code(client, auth, caplog, token_endpoint_url):
    """Successful token exchange logs must not disclose the full authorization code."""
    auth.key = "success-code-secret-1234567890"
    auth.save()

    with caplog.at_level(logging.INFO, logger="indieweb.views"):
        response = client.post(
            token_endpoint_url,
            data={
                "code": auth.key,
                "client_id": auth.client_id,
            },
        )

    assert response.status_code == 201
    data = parse_qs(unquote(response.content.decode("utf-8")))
    assert "access_token" in data
    assert auth.key not in caplog.text
    assert "succes..." in caplog.text


@pytest.mark.django_db
def test_token_exchange_missing_parameter_logs_redact_full_authorization_code(client, caplog, token_endpoint_url):
    """Missing-parameter logs must redact a submitted authorization code."""
    submitted_code = "missing-code-secret-for-logs"

    with caplog.at_level(logging.ERROR, logger="indieweb.views"):
        response = client.post(
            token_endpoint_url,
            data={
                "code": submitted_code,
            },
        )

    assert response.status_code == 400
    assert response.content == b"invalid_request"
    assert submitted_code not in caplog.text
    assert "missin..." in caplog.text


BAD_CLIENT_IDS = [
    "not a url",
    "ftp://webapp.example.org",
    "https://webapp.example.org#frag",
    "https://webapp.example.org#",
    "https://User:Pass@webapp.example.org",
    "javascript:alert(1)",
]


@pytest.mark.django_db
@pytest.mark.parametrize("bad_client_id", BAD_CLIENT_IDS)
def test_token_rejects_invalid_client_id(client, token_endpoint_url, token_payload, bad_client_id):
    """Token endpoint rejects malformed client_id with invalid_request before any Auth lookup."""
    token_payload["client_id"] = bad_client_id
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 400
    assert "invalid_request" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_token_rejects_disallowed_client_id_via_validator(client, settings, token_endpoint_url, token_payload):
    """Configured validator returning False blocks token issuance with invalid_request."""
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.client_id_validators.deny_all"
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 400
    assert "invalid_request" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_token_accepts_allowed_client_id_via_validator(client, settings, token_endpoint_url, token_payload):
    """Configured validator returning True does not block token issuance."""
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.client_id_validators.allow_all"
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 201


@pytest.mark.django_db
def test_token_rejects_when_validator_misconfigured(client, settings, token_endpoint_url, token_payload):
    """A dotted path that fails to import is fail-closed at the token endpoint."""
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.does_not_exist.nope"
    response = client.post(token_endpoint_url, data=token_payload)
    assert response.status_code == 400
    assert "invalid_request" in response.content.decode("utf-8")


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


@pytest.mark.django_db
def test_token_reissue_rotates_key_and_reuses_existing_row(client, settings, token_endpoint_url, token_payload, user):
    """Reissuing the same token tuple rotates the bearer key without creating a second row."""
    settings.INDIEWEB_TOKEN_EXPIRES_IN = 3600
    stale = models.Token.objects.create(
        owner=user,
        client_id=token_payload["client_id"],
        me=token_payload["me"],
        scope=token_payload["scope"],
        expires_at=timezone.now() + timedelta(seconds=5),
    )
    old_key = stale.key

    response = client.post(token_endpoint_url, data=token_payload)

    assert response.status_code == 200
    data = parse_qs(response.content.decode("utf-8"), keep_blank_values=True)
    new_key = data["access_token"][0]
    assert new_key != old_key
    stale.refresh_from_db()
    assert stale.key == new_key
    assert models.Token.objects.count() == 1


@pytest.mark.django_db
def test_reissued_old_token_stops_authenticating_and_new_token_authenticates(
    client, settings, token_endpoint_url, token_payload, user
):
    """Only the rotated key should authenticate after a reissue."""
    settings.INDIEWEB_TOKEN_EXPIRES_IN = 3600
    existing = models.Token.objects.create(
        owner=user,
        client_id=token_payload["client_id"],
        me=token_payload["me"],
        scope=token_payload["scope"],
        expires_at=timezone.now() + timedelta(seconds=5),
    )
    old_key = existing.key

    response = client.post(token_endpoint_url, data=token_payload)
    new_key = parse_qs(response.content.decode("utf-8"), keep_blank_values=True)["access_token"][0]

    micropub_url = reverse("indieweb:micropub")
    old_response = client.get(micropub_url, Authorization=f"Bearer {old_key}")
    new_response = client.get(micropub_url, Authorization=f"Bearer {new_key}")
    assert old_response.status_code == 401
    assert new_response.status_code == 200


@pytest.mark.django_db
def test_token_introspection_returns_active_token_metadata(client, user, token_introspection_endpoint_url):
    """Valid tokens introspect to stable resource-server metadata without exposing secrets."""
    expires_at = timezone.now() + timedelta(hours=1)
    token = models.Token.objects.create(
        owner=user,
        key="activetokensecret",
        client_id="https://webapp.example.org",
        me="https://example.org/",
        scope="create update",
        expires_at=expires_at,
    )

    response = client.post(token_introspection_endpoint_url, data={"token": token.key})

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    data = response.json()
    assert data == {
        "active": True,
        "me": "https://example.org/",
        "client_id": "https://webapp.example.org",
        "scope": "create update",
        "iat": int(token.created.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    assert token.key not in response.content.decode("utf-8")


@pytest.mark.django_db
def test_token_introspection_accepts_bearer_header_as_token_input(client, user, token_introspection_endpoint_url):
    """The endpoint can introspect the bearer token supplied in the Authorization header."""
    token = models.Token.objects.create(
        owner=user,
        key="bearerintrospectionsecret",
        client_id="https://webapp.example.org",
        me="https://example.org/",
        scope=None,
        expires_at=timezone.now() + timedelta(hours=1),
    )

    response = client.post(token_introspection_endpoint_url, HTTP_AUTHORIZATION=f"Bearer {token.key}")

    assert response.status_code == 200
    assert response.json()["active"] is True
    assert response.json()["scope"] == ""


@pytest.mark.django_db
def test_token_introspection_accepts_case_insensitive_bearer_scheme(client, user, token_introspection_endpoint_url):
    """Bearer scheme matching remains case-insensitive."""
    token = models.Token.objects.create(
        owner=user,
        key="lowercasebearersecret",
        client_id="https://webapp.example.org",
        me="https://example.org/",
        scope=None,
        expires_at=timezone.now() + timedelta(hours=1),
    )

    response = client.post(token_introspection_endpoint_url, HTTP_AUTHORIZATION=f"bearer {token.key}")

    assert response.status_code == 200
    assert response.json()["active"] is True


@pytest.mark.parametrize(
    "auth_header",
    [
        "Bearer one two",
        "Basic token",
        "Bearer",
        "Bearer   ",
        "   ",
    ],
)
def test_authorization_bearer_token_rejects_malformed_headers(rf, auth_header):
    """The shared bearer parser accepts only exactly two Bearer header parts."""
    request = rf.post("/indieweb/token/introspect/", HTTP_AUTHORIZATION=auth_header)

    assert _authorization_bearer_token(request) is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "auth_header",
    [
        "Bearer one two",
        "Basic token",
        "Bearer",
        "Bearer   ",
        "   ",
    ],
)
def test_token_introspection_returns_inactive_for_malformed_bearer_headers(
    client, token_introspection_endpoint_url, auth_header
):
    """Malformed bearer headers are treated as absent token input."""
    response = client.post(token_introspection_endpoint_url, HTTP_AUTHORIZATION=auth_header)

    assert response.status_code == 200
    assert response.json() == {"active": False}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("payload", "headers"),
    [
        ({}, {}),
        ({"token": ""}, {}),
        ({"token": "unknown-token"}, {}),
    ],
)
def test_token_introspection_returns_inactive_for_missing_or_unknown_token(
    client, token_introspection_endpoint_url, payload, headers
):
    """Missing and unknown token inputs do not disclose detail."""
    response = client.post(token_introspection_endpoint_url, data=payload, **headers)

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response.json() == {"active": False}


@pytest.mark.django_db
def test_token_exchange_rejects_duplicate_auth_code_lookup_without_issuing_token(
    client, auth, monkeypatch, token_endpoint_url, token_payload
):
    """Defensive duplicate Auth-key handling returns invalid_grant instead of a 500."""

    def duplicate_auth(*args, **kwargs):
        raise models.Auth.MultipleObjectsReturned

    monkeypatch.setattr(models.Auth.objects, "get", duplicate_auth)

    response = client.post(token_endpoint_url, data=token_payload)

    assert response.status_code == 400
    assert response["Content-Type"] == "application/x-www-form-urlencoded"
    assert response.content == b"invalid_grant"
    assert models.Token.objects.count() == 0
    assert not models.Auth.objects.filter(pk=auth.pk).exists()


@pytest.mark.django_db
def test_token_introspection_rejects_duplicate_token_key_lookup_without_500(
    client, monkeypatch, token_introspection_endpoint_url
):
    """Defensive duplicate Token-key handling returns the stable inactive response."""

    class DuplicateTokenQuery:
        def get(self, *args, **kwargs):
            raise models.Token.MultipleObjectsReturned

    monkeypatch.setattr(models.Token.objects, "select_related", lambda *args, **kwargs: DuplicateTokenQuery())

    response = client.post(token_introspection_endpoint_url, data={"token": "duplicatetokensecret"})

    assert response.status_code == 200
    assert response.json() == {"active": False}


@pytest.mark.django_db
def test_token_introspection_returns_inactive_for_expired_token(client, user, token_introspection_endpoint_url):
    token = models.Token.objects.create(
        owner=user,
        key="expiredtokensecret",
        client_id="https://webapp.example.org",
        me="https://example.org/",
        scope="create",
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    response = client.post(token_introspection_endpoint_url, data={"token": token.key})

    assert response.status_code == 200
    assert response.json() == {"active": False}


@pytest.mark.django_db
def test_token_introspection_returns_inactive_for_deleted_token(client, user, token_introspection_endpoint_url):
    token = models.Token.objects.create(
        owner=user,
        key="deletedtokensecret",
        client_id="https://webapp.example.org",
        me="https://example.org/",
        scope="create",
        expires_at=timezone.now() + timedelta(hours=1),
    )
    token_key = token.key
    token.delete()

    response = client.post(token_introspection_endpoint_url, data={"token": token_key})

    assert response.status_code == 200
    assert response.json() == {"active": False}


@pytest.mark.django_db
def test_token_introspection_returns_inactive_for_inactive_owner(client, user, token_introspection_endpoint_url):
    user.is_active = False
    user.save()
    token = models.Token.objects.create(
        owner=user,
        key="inactiveownersecret",
        client_id="https://webapp.example.org",
        me="https://example.org/",
        scope="create",
        expires_at=timezone.now() + timedelta(hours=1),
    )

    response = client.post(token_introspection_endpoint_url, data={"token": token.key})

    assert response.status_code == 200
    assert response.json() == {"active": False}


@pytest.mark.django_db
def test_token_introspection_returns_inactive_for_disallowed_client_id(
    client, settings, user, token_introspection_endpoint_url
):
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.client_id_validators.deny_all"
    token = models.Token.objects.create(
        owner=user,
        key="disallowedclientsecret",
        client_id="https://webapp.example.org",
        me="https://example.org/",
        scope="create",
        expires_at=timezone.now() + timedelta(hours=1),
    )

    response = client.post(token_introspection_endpoint_url, data={"token": token.key})

    assert response.status_code == 200
    assert response.json() == {"active": False}


@pytest.mark.django_db
def test_token_introspection_does_not_mutate_token_rows(client, user, token_introspection_endpoint_url):
    expires_at = timezone.now() + timedelta(hours=1)
    token = models.Token.objects.create(
        owner=user,
        key="immutabletokensecret",
        client_id="https://webapp.example.org",
        me="https://example.org/",
        scope="create",
        expires_at=expires_at,
    )
    original_modified = token.modified
    original_count = models.Token.objects.count()

    response = client.post(token_introspection_endpoint_url, data={"token": token.key})

    assert response.status_code == 200
    token.refresh_from_db()
    assert models.Token.objects.count() == original_count
    assert token.expires_at == expires_at
    assert token.modified == original_modified
