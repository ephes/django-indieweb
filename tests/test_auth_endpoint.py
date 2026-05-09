#!/usr/bin/env python

"""
test_django-indieweb
------------

Tests for `django-indieweb` auth endpoint.
"""

import json
from datetime import datetime, timedelta, timezone  # noqa: E501
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils.http import urlencode

from indieweb.models import Auth
from indieweb.views import IndieAuthMetadataView
from tests import client_id_validators


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


def test_indieauth_metadata_endpoint_returns_public_json(client):
    """The reusable metadata endpoint is public and describes shipped capabilities only."""
    response = client.get(reverse("indieweb:auth-metadata"))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    data = response.json()
    assert data == {
        "issuer": "http://testserver/indieweb/",
        "authorization_endpoint": "http://testserver/indieweb/auth/",
        "token_endpoint": "http://testserver/indieweb/token/",
        "introspection_endpoint": "http://testserver/indieweb/token/introspect/",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["plain", "S256"],
        "scopes_supported": ["create", "update", "delete", "undelete", "media"],
        "service_documentation": "https://django-indieweb.readthedocs.io/en/latest/indieauth.html",
    }


def test_indieauth_metadata_reflects_s256_only_pkce_policy(client, settings):
    settings.INDIEWEB_REQUIRE_PKCE_S256 = True

    response = client.get(reverse("indieweb:auth-metadata"))

    assert response.status_code == 200
    assert response.json()["code_challenge_methods_supported"] == ["S256"]


def test_indieauth_metadata_omits_unimplemented_endpoints(client):
    """Discovery must not advertise endpoints django-indieweb does not implement yet."""
    response = client.get(reverse("indieweb:auth-metadata"))

    assert response.status_code == 200
    data = response.json()
    assert "revocation_endpoint" not in data
    assert "userinfo_endpoint" not in data


def test_indieauth_metadata_does_not_require_login_or_bearer_token(client):
    """Metadata discovery stays public even when the caller is not logged in."""
    response = client.get(reverse("indieweb:auth-metadata"), HTTP_AUTHORIZATION="Bearer wrong")

    assert response.status_code == 200
    assert response.json()["authorization_endpoint"] == "http://testserver/indieweb/auth/"


def test_indieauth_metadata_view_supports_host_well_known_route(rf):
    """Host projects can route the same reusable view at the root well-known path."""
    request = rf.get("/.well-known/oauth-authorization-server")
    response = IndieAuthMetadataView.as_view()(request)

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["issuer"] == "http://testserver/"
    assert data["authorization_endpoint"] == "http://testserver/indieweb/auth/"
    assert data["token_endpoint"] == "http://testserver/indieweb/token/"
    assert data["introspection_endpoint"] == "http://testserver/indieweb/token/introspect/"


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
def test_get_accepts_response_type_code(client, user):
    """Authorization GET accepts the current IndieAuth response_type value."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "scope": "post",
        "response_type": "code",
    }
    response = client.get(f"{base_url}?{urlencode(url_params)}")
    assert response.status_code == 200
    assert response.context["client_id"] == "https://webapp.example.org"


@pytest.mark.django_db
def test_get_rejects_invalid_response_type(client, user):
    """Authorization GET rejects present response_type values other than code."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "scope": "post",
        "response_type": "token",
    }
    response = client.get(f"{base_url}?{urlencode(url_params)}")
    assert response.status_code == 400
    assert response.content == b"invalid response_type"
    assert "indieweb/consent.html" not in [template.name for template in response.templates]


@pytest.mark.django_db
def test_get_accepts_omitted_response_type_for_legacy_clients(client, user, auth_endpoint_url):
    """Authorization GET keeps accepting legacy requests that omit response_type."""
    client.login(username=user.username, password="password")
    response = client.get(auth_endpoint_url)
    assert response.status_code == 200


@pytest.mark.django_db
def test_authenticated_normalizes_repeated_scope_tokens(client, user):
    """Authorization GET normalizes whitespace and repeated scopes for display."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "scope": " create  update create ",
    }
    response = client.get(f"{base_url}?{urlencode(url_params)}")
    assert response.status_code == 200
    assert response.context["scope"] == "create update"
    assert response.context["scope_list"] == ["create", "update"]


@pytest.mark.django_db
def test_authenticated_preserves_unknown_scope_tokens(client, user):
    """Authorization GET preserves extension-defined scopes after normalization."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "scope": "profile media site-specific profile",
    }
    response = client.get(f"{base_url}?{urlencode(url_params)}")
    assert response.status_code == 200
    assert response.context["scope"] == "profile media site-specific"
    assert response.context["scope_list"] == ["profile", "media", "site-specific"]


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
    data = parse_qs(urlparse(response.url).query)
    assert "code" in data
    assert data["state"] == ["1234567890"]
    assert data["me"] == ["http://example.org"]
    assert data["iss"] == ["http://testserver/indieweb/"]

    # Auth object should be created
    auth = Auth.objects.get(client_id="https://webapp.example.org", me="http://example.org")
    assert auth.owner == user
    assert auth.scope == "post"


@pytest.mark.django_db
def test_consent_approval_stores_normalized_scope(client, user):
    """Consent approval stores normalized scope on the Auth row."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    form_data = {
        "action": "approve",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "me": "http://example.org",
        "scope": " create  update create ",
    }
    response = client.post(base_url, data=form_data)
    assert response.status_code == 302
    auth = Auth.objects.get(client_id="https://webapp.example.org", me="http://example.org")
    assert auth.scope == "create update"


@pytest.mark.django_db
def test_consent_approval_preserves_unknown_scope_tokens(client, user):
    """Consent approval preserves unknown extension scopes after normalization."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    form_data = {
        "action": "approve",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "me": "http://example.org",
        "scope": "profile media site-specific profile",
    }
    response = client.post(base_url, data=form_data)
    assert response.status_code == 302
    auth = Auth.objects.get(client_id="https://webapp.example.org", me="http://example.org")
    assert auth.scope == "profile media site-specific"


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
def test_get_rejects_invalid_redirect_uri(client, user, bad_redirect_uri):
    """Authorization endpoint rejects redirect_uri with fragment/bad scheme/invalid syntax."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "https://webapp.example.org",
        "redirect_uri": bad_redirect_uri,
        "state": "1234567890",
        "scope": "post",
    }
    response = client.get(f"{base_url}?{urlencode(url_params)}")
    assert response.status_code == 400
    assert "redirect_uri" in response.content.decode("utf-8")


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
def test_consent_approval_rejects_invalid_redirect_uri(client, user, bad_redirect_uri):
    """Consent approval rejects invalid redirect_uri before creating an Auth row."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    form_data = {
        "action": "approve",
        "client_id": "https://webapp.example.org",
        "redirect_uri": bad_redirect_uri,
        "state": "1234567890",
        "me": "http://example.org",
        "scope": "post",
    }
    response = client.post(base_url, data=form_data)
    assert response.status_code == 400
    assert Auth.objects.filter(client_id="https://webapp.example.org").count() == 0


@pytest.mark.django_db
def test_consent_approval_merges_existing_query(client, user):
    """Approve must merge code/state into an existing redirect_uri query, not duplicate `?`."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    form_data = {
        "action": "approve",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback?next=/x",
        "state": "1234567890",
        "me": "http://example.org",
        "scope": "post",
    }
    response = client.post(base_url, data=form_data)
    assert response.status_code == 302
    parsed = urlparse(response.url)
    assert response.url.count("?") == 1, f"Expected one '?' separator, got: {response.url}"
    qs = parse_qs(parsed.query)
    assert qs["next"] == ["/x"]
    assert "code" in qs
    assert qs["state"] == ["1234567890"]
    assert qs["me"] == ["http://example.org"]
    assert qs["iss"] == ["http://testserver/indieweb/"]


@pytest.mark.django_db
def test_consent_denial_merges_existing_query(client, user):
    """Deny must merge error/state into an existing redirect_uri query, not duplicate `?`."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    form_data = {
        "action": "deny",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback?next=/x",
        "state": "1234567890",
        "me": "http://example.org",
        "scope": "post",
    }
    response = client.post(base_url, data=form_data)
    assert response.status_code == 302
    parsed = urlparse(response.url)
    assert response.url.count("?") == 1, f"Expected one '?' separator, got: {response.url}"
    qs = parse_qs(parsed.query)
    assert qs["next"] == ["/x"]
    assert qs["error"] == ["access_denied"]
    assert qs["state"] == ["1234567890"]
    assert "iss" not in qs


PKCE_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
PKCE_S256_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


@pytest.mark.django_db
@pytest.mark.parametrize("bad_method", ["MD5", "sha256", "S512", "PLAIN", " plain"])
def test_get_rejects_unsupported_pkce_method(client, user, bad_method):
    """Authorization GET rejects code_challenge_method values outside {plain, S256}."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "scope": "post",
        "code_challenge": PKCE_S256_CHALLENGE,
        "code_challenge_method": bad_method,
    }
    response = client.get(f"{base_url}?{urlencode(url_params)}")
    assert response.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize(
    "bad_challenge",
    [
        "",  # empty
        "short",  # too short for S256-style fingerprint but irrelevant — caught by length rule
        "a" * 129,  # too long
        "abc!def",  # disallowed character
        "abc def",  # whitespace
        "abc/def",  # slash not in unreserved
    ],
)
def test_get_rejects_invalid_pkce_challenge(client, user, bad_challenge):
    """Authorization GET rejects malformed code_challenge values."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "scope": "post",
        "code_challenge": bad_challenge,
        "code_challenge_method": "S256",
    }
    response = client.get(f"{base_url}?{urlencode(url_params)}")
    assert response.status_code == 400


@pytest.mark.django_db
def test_get_accepts_no_pkce_legacy(client, user, auth_endpoint_url):
    """Authorization GET still accepts a request without PKCE parameters (legacy clients)."""
    client.login(username=user.username, password="password")
    response = client.get(auth_endpoint_url)
    assert response.status_code == 200


@pytest.mark.django_db
def test_get_rejects_missing_pkce_when_required(client, settings, user, auth_endpoint_url):
    settings.INDIEWEB_REQUIRE_PKCE = True
    client.login(username=user.username, password="password")

    response = client.get(auth_endpoint_url)

    assert response.status_code == 400
    assert response.content == b"invalid_request"


@pytest.mark.django_db
def test_get_accepts_plain_pkce_when_pkce_required(client, settings, user):
    settings.INDIEWEB_REQUIRE_PKCE = True
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "scope": "post",
        "code_challenge": PKCE_VERIFIER,
        "code_challenge_method": "plain",
    }

    response = client.get(f"{base_url}?{urlencode(url_params)}")

    assert response.status_code == 200
    assert response.context["code_challenge_method"] == "plain"


@pytest.mark.django_db
def test_get_rejects_plain_pkce_when_s256_required(client, settings, user):
    settings.INDIEWEB_REQUIRE_PKCE_S256 = True
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "scope": "post",
        "code_challenge": PKCE_VERIFIER,
        "code_challenge_method": "plain",
    }

    response = client.get(f"{base_url}?{urlencode(url_params)}")

    assert response.status_code == 400
    assert response.content == b"invalid_request"


@pytest.mark.django_db
def test_get_accepts_s256_pkce_when_s256_required(client, settings, user):
    settings.INDIEWEB_REQUIRE_PKCE_S256 = True
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "scope": "post",
        "code_challenge": PKCE_S256_CHALLENGE,
        "code_challenge_method": "S256",
    }

    response = client.get(f"{base_url}?{urlencode(url_params)}")

    assert response.status_code == 200
    assert response.context["code_challenge_method"] == "S256"


@pytest.mark.django_db
def test_get_defaults_method_to_plain(client, user):
    """When only code_challenge is sent, the default method is ``plain`` per RFC 7636 §4.3."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "scope": "post",
        "code_challenge": PKCE_VERIFIER,  # any RFC-valid string
    }
    response = client.get(f"{base_url}?{urlencode(url_params)}")
    assert response.status_code == 200


@pytest.mark.django_db
def test_consent_approval_persists_pkce(client, user):
    """Consent approve stores code_challenge and effective code_challenge_method."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    form_data = {
        "action": "approve",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "me": "http://example.org",
        "scope": "post",
        "code_challenge": PKCE_S256_CHALLENGE,
        "code_challenge_method": "S256",
    }
    response = client.post(base_url, data=form_data)
    assert response.status_code == 302
    auth = Auth.objects.get(client_id="https://webapp.example.org", me="http://example.org")
    assert auth.code_challenge == PKCE_S256_CHALLENGE
    assert auth.code_challenge_method == "S256"


@pytest.mark.django_db
def test_consent_approval_defaults_method_to_plain(client, user):
    """Consent approve persists ``plain`` as the default method when none is sent."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    form_data = {
        "action": "approve",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "me": "http://example.org",
        "scope": "post",
        "code_challenge": PKCE_VERIFIER,
    }
    response = client.post(base_url, data=form_data)
    assert response.status_code == 302
    auth = Auth.objects.get(client_id="https://webapp.example.org", me="http://example.org")
    assert auth.code_challenge == PKCE_VERIFIER
    assert auth.code_challenge_method == "plain"


@pytest.mark.django_db
def test_consent_approval_rejects_bad_pkce(client, user):
    """Consent approve rejects malformed PKCE inputs before creating an Auth row."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    form_data = {
        "action": "approve",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "me": "http://example.org",
        "scope": "post",
        "code_challenge": "abc!def",
        "code_challenge_method": "S256",
    }
    response = client.post(base_url, data=form_data)
    assert response.status_code == 400
    assert Auth.objects.filter(client_id="https://webapp.example.org").count() == 0


@pytest.mark.django_db
def test_consent_approval_rejects_missing_pkce_when_required(client, settings, user):
    settings.INDIEWEB_REQUIRE_PKCE = True
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    form_data = {
        "action": "approve",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "me": "http://example.org",
        "scope": "post",
    }

    response = client.post(base_url, data=form_data)

    assert response.status_code == 400
    assert response.content == b"invalid_request"
    assert Auth.objects.filter(client_id="https://webapp.example.org").count() == 0


@pytest.mark.django_db
def test_get_renders_pkce_into_consent_context(client, user):
    """Authorization GET propagates PKCE values into the render context."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "scope": "post",
        "code_challenge": PKCE_S256_CHALLENGE,
        "code_challenge_method": "S256",
    }
    response = client.get(f"{base_url}?{urlencode(url_params)}")
    assert response.status_code == 200
    assert response.context["code_challenge"] == PKCE_S256_CHALLENGE
    assert response.context["code_challenge_method"] == "S256"


def test_consent_template_source_carries_pkce_hidden_inputs():
    """Bundled consent.html must render PKCE hidden inputs when a challenge is in context.

    This is a static check on the template source rather than a render assertion:
    the test base.html intentionally has no ``{% block content %}``, so block
    output is discarded by ``render_to_string`` here. Reading the source still
    catches the regression (template author dropped the hidden inputs).
    """
    from django.template.loader import get_template

    source = Path(get_template("indieweb/consent.html").origin.name).read_text()
    assert 'name="code_challenge"' in source
    assert 'name="code_challenge_method"' in source
    assert "{% if code_challenge %}" in source


@pytest.mark.django_db
def test_pkce_round_trip_through_consent_screen(client, user):
    """End-to-end: PKCE GET -> consent form submit -> token exchange with verifier."""
    client.login(username=user.username, password="password")
    auth_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "scope": "post",
        "code_challenge": PKCE_S256_CHALLENGE,
        "code_challenge_method": "S256",
    }
    get_resp = client.get(f"{auth_url}?{urlencode(url_params)}")
    assert get_resp.status_code == 200

    # Submit the consent form using only what the rendered template carries.
    ctx = get_resp.context
    form_data = {
        "action": "approve",
        "client_id": ctx["client_id"],
        "redirect_uri": ctx["redirect_uri"],
        "state": ctx["state"],
        "me": ctx["me"],
        "scope": ctx["scope"],
        "code_challenge": ctx["code_challenge"],
        "code_challenge_method": ctx["code_challenge_method"],
    }
    post_resp = client.post(auth_url, data=form_data)
    assert post_resp.status_code == 302

    auth = Auth.objects.get(client_id="https://webapp.example.org", me="http://example.org")
    assert auth.code_challenge == PKCE_S256_CHALLENGE
    assert auth.code_challenge_method == "S256"

    redirect_query = parse_qs(urlparse(post_resp["Location"]).query)
    issued_code = redirect_query["code"][0]
    assert issued_code != auth.key
    assert auth.key.startswith("hmac-sha256$")

    token_resp = client.post(
        reverse("indieweb:token"),
        data={
            "code": issued_code,
            "client_id": auth.client_id,
            "redirect_uri": auth.redirect_uri,
            "code_verifier": PKCE_VERIFIER,
        },
    )
    assert token_resp.status_code == 201


@pytest.mark.django_db
def test_consent_approval_rejects_unsupported_method(client, user):
    """Consent approve rejects code_challenge_method values outside {plain, S256}."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    form_data = {
        "action": "approve",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "me": "http://example.org",
        "scope": "post",
        "code_challenge": PKCE_S256_CHALLENGE,
        "code_challenge_method": "MD5",
    }
    response = client.post(base_url, data=form_data)
    assert response.status_code == 400
    assert Auth.objects.filter(client_id="https://webapp.example.org").count() == 0


BAD_CLIENT_IDS = [
    "",
    "not a url",
    "ftp://webapp.example.org",
    "https://webapp.example.org#frag",
    "https://webapp.example.org#",
    "https://User:Pass@webapp.example.org",
    "javascript:alert(1)",
]


@pytest.mark.django_db
@pytest.mark.parametrize("bad_client_id", BAD_CLIENT_IDS)
def test_get_rejects_invalid_client_id(client, user, bad_client_id):
    """Authorization endpoint rejects malformed client_id with HTTP 400."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": bad_client_id,
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "scope": "post",
    }
    response = client.get(f"{base_url}?{urlencode(url_params)}")
    # An empty client_id is reported as a missing parameter (404) by the
    # required-params check that runs first; everything else is structural 400.
    assert response.status_code in (400, 404)
    if response.status_code == 400:
        assert "client_id" in response.content.decode("utf-8")


@pytest.mark.django_db
@pytest.mark.parametrize("bad_client_id", [c for c in BAD_CLIENT_IDS if c])
def test_consent_approval_rejects_invalid_client_id(client, user, bad_client_id):
    """Consent approval rejects malformed client_id before creating an Auth row."""
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    form_data = {
        "action": "approve",
        "client_id": bad_client_id,
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "me": "http://example.org",
        "scope": "post",
    }
    response = client.post(base_url, data=form_data)
    assert response.status_code == 400
    assert Auth.objects.filter(client_id=bad_client_id).count() == 0


@pytest.mark.django_db
def test_get_rejects_disallowed_client_id_via_validator(client, settings, user, auth_endpoint_url):
    """Configured validator returning False blocks the authorization GET with HTTP 400."""
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.client_id_validators.deny_all"
    client.login(username=user.username, password="password")
    response = client.get(auth_endpoint_url)
    assert response.status_code == 400
    assert "invalid_client" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_get_accepts_allowed_client_id_via_validator(client, settings, user, auth_endpoint_url):
    """Configured validator returning True does not block a structurally-valid GET."""
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.client_id_validators.allow_all"
    client.login(username=user.username, password="password")
    response = client.get(auth_endpoint_url)
    assert response.status_code == 200


@pytest.mark.django_db
def test_get_passes_normalized_client_id_to_validator(client, settings, user):
    """Validator allowlists see normalized scheme/host and IDNA client IDs."""
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.client_id_validators.allow_only_normalized"
    settings.INDIEWEB_REDIRECT_URI_ALLOWLIST = {
        "HTTPS://Bücher.Example/Client?A=1": ["https://webapp.example.org/auth/callback"],
    }
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "HTTPS://Bücher.Example/Client?A=1",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
    }

    response = client.get(f"{base_url}?{urlencode(url_params)}")

    assert response.status_code == 200
    assert response.context["client_id"] == "HTTPS://Bücher.Example/Client?A=1"


@pytest.mark.django_db
def test_get_allowed_client_ids_setting_blocks_untrusted_client(client, settings, user, auth_endpoint_url):
    settings.INDIEWEB_ALLOWED_CLIENT_IDS = ("https://trusted.example.org",)
    client.login(username=user.username, password="password")

    response = client.get(auth_endpoint_url)

    assert response.status_code == 400
    assert response.content == b"invalid_client"


@pytest.mark.django_db
def test_get_allowed_client_ids_setting_accepts_normalized_client(client, settings, user):
    settings.INDIEWEB_ALLOWED_CLIENT_IDS = ("https://xn--bcher-kva.example/Client?A=1",)
    settings.INDIEWEB_REDIRECT_URI_ALLOWLIST = {
        "HTTPS://Bücher.Example/Client?A=1": ["https://webapp.example.org/auth/callback"],
    }
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "HTTPS://Bücher.Example/Client?A=1",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
    }

    response = client.get(f"{base_url}?{urlencode(url_params)}")

    assert response.status_code == 200


@pytest.mark.django_db
def test_get_client_id_validator_receives_normalized_value(client, settings, user):
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.client_id_validators.capture_and_allow"
    settings.INDIEWEB_REDIRECT_URI_ALLOWLIST = {
        "HTTPS://Bücher.Example/Client?A=1": ["https://webapp.example.org/auth/callback"],
    }
    client_id_validators.seen_client_ids.clear()
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    url_params = {
        "me": "http://example.org",
        "client_id": "HTTPS://Bücher.Example/Client?A=1",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
    }

    response = client.get(f"{base_url}?{urlencode(url_params)}")

    assert response.status_code == 200
    assert client_id_validators.seen_client_ids == ["https://xn--bcher-kva.example/Client?A=1"]


@pytest.mark.django_db
def test_consent_approval_rejects_disallowed_client_id_via_validator(client, settings, user):
    """Configured validator returning False blocks consent approval with HTTP 400."""
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.client_id_validators.deny_all"
    client.login(username=user.username, password="password")
    base_url = reverse("indieweb:auth")
    form_data = {
        "action": "approve",
        "client_id": "https://webapp.example.org",
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "state": "1234567890",
        "me": "http://example.org",
        "scope": "post",
    }
    response = client.post(base_url, data=form_data)
    assert response.status_code == 400
    assert Auth.objects.filter(client_id="https://webapp.example.org").count() == 0


@pytest.mark.django_db
def test_get_rejects_when_validator_misconfigured(client, settings, user, auth_endpoint_url):
    """A dotted path that fails to import is fail-closed at the auth endpoint."""
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.does_not_exist.nope"
    client.login(username=user.username, password="password")
    response = client.get(auth_endpoint_url)
    assert response.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("bad_client_id", [c for c in BAD_CLIENT_IDS if c])
def test_verify_auth_code_rejects_invalid_client_id(client, user, bad_client_id):
    """Code-verification POST rejects malformed client_id before any Auth lookup."""
    Auth.objects.create(
        owner=user,
        client_id=bad_client_id,
        redirect_uri="https://webapp.example.org/auth/callback",
        state="1234567890",
        me="http://example.org",
        key="legacykey",
    )
    base_url = reverse("indieweb:auth")
    response = client.post(base_url, data={"code": "legacykey", "client_id": bad_client_id})
    assert response.status_code == 400
    assert "client_id" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_verify_auth_code_rejects_disallowed_client_id_via_validator(client, settings, user):
    """Configured validator returning False blocks code verification with HTTP 400."""
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.client_id_validators.deny_all"
    auth = Auth.objects.create(
        owner=user,
        client_id="https://webapp.example.org",
        redirect_uri="https://webapp.example.org/auth/callback",
        state="1234567890",
        me="http://example.org",
    )
    base_url = reverse("indieweb:auth")
    response = client.post(base_url, data={"code": auth.key, "client_id": auth.client_id})
    assert response.status_code == 400
    assert "invalid_client" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_verify_auth_code_rejects_when_validator_misconfigured(client, settings, user):
    """A non-importable validator path is fail-closed at the code-verification POST."""
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.does_not_exist.nope"
    auth = Auth.objects.create(
        owner=user,
        client_id="https://webapp.example.org",
        redirect_uri="https://webapp.example.org/auth/callback",
        state="1234567890",
        me="http://example.org",
    )
    base_url = reverse("indieweb:auth")
    response = client.post(base_url, data={"code": auth.key, "client_id": auth.client_id})
    assert response.status_code == 400


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
    assert response["Content-Type"] == "application/x-www-form-urlencoded"
    assert "me=http%3A%2F%2Fexample.org" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_post_verify_auth_code_rejects_duplicate_auth_lookup(client, monkeypatch):
    """Duplicate auth-code lookup failures keep the legacy invalid-code response shape."""

    def duplicate_auth(*args, **kwargs):
        raise Auth.MultipleObjectsReturned

    monkeypatch.setattr(Auth.objects, "get", duplicate_auth)

    response = client.post(
        reverse("indieweb:auth"),
        data={
            "code": "duplicateauthsecret",
            "client_id": "https://webapp.example.org",
        },
    )

    assert response.status_code == 400
    assert response.content == b"Invalid authorization code"


@pytest.mark.django_db
def test_post_verify_auth_code_returns_json_when_requested(client, user):
    """Code verification returns JSON only when the client explicitly prefers it."""
    auth = Auth.objects.create(
        owner=user,
        client_id="https://webapp.example.org",
        redirect_uri="https://webapp.example.org/auth/callback",
        state="1234567890",
        scope="post",
        me="http://example.org",
    )
    response = client.post(
        reverse("indieweb:auth"),
        data={"code": auth.key, "client_id": auth.client_id},
        HTTP_ACCEPT="application/json",
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response.json() == {"me": "http://example.org"}


@pytest.mark.django_db
def test_post_verify_auth_code_keeps_default_form_response_for_wildcard_accept(client, user):
    """Wildcard Accept headers do not switch legacy code verification responses to JSON."""
    auth = Auth.objects.create(
        owner=user,
        client_id="https://webapp.example.org",
        redirect_uri="https://webapp.example.org/auth/callback",
        state="1234567890",
        scope="post",
        me="http://example.org",
    )
    response = client.post(
        reverse("indieweb:auth"),
        data={"code": auth.key, "client_id": auth.client_id},
        HTTP_ACCEPT="*/*",
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/x-www-form-urlencoded"
    assert parse_qs(response.content.decode("utf-8")) == {"me": ["http://example.org"]}


@pytest.mark.django_db
def test_post_verify_auth_code_rejects_expired_code(client, user):
    """Legacy code verification must apply ``INDIWEB_AUTH_CODE_TIMEOUT``.

    Token exchange has always rejected stale codes, but the verification POST
    previously returned ``me`` for any matching ``code`` / ``client_id`` pair
    regardless of age. An attacker with a leaked but expired code could
    therefore confirm the bound ``me`` indefinitely. The verification POST now
    enforces the same expiry window and deletes the row on failure so the
    code cannot be reused on either path.
    """
    auth = Auth.objects.create(
        owner=user,
        client_id="https://webapp.example.org",
        redirect_uri="https://webapp.example.org/auth/callback",
        state="1234567890",
        scope="post",
        me="http://example.org",
    )

    timeout = getattr(settings, "INDIWEB_AUTH_CODE_TIMEOUT", 60)
    auth.created = auth.created - timedelta(seconds=timeout + 1)
    auth.save()

    response = client.post(
        reverse("indieweb:auth"),
        data={"code": auth.key, "client_id": auth.client_id},
    )

    assert response.status_code == 400
    assert response.content == b"Invalid authorization code"
    assert not Auth.objects.filter(pk=auth.pk).exists()


@pytest.mark.django_db
def test_post_verify_auth_code_accepts_fresh_code_within_window(client, user):
    """A code aged within the expiry window still succeeds at verification."""
    auth = Auth.objects.create(
        owner=user,
        client_id="https://webapp.example.org",
        redirect_uri="https://webapp.example.org/auth/callback",
        state="1234567890",
        scope="post",
        me="http://example.org",
    )

    # Age the code to half the expiry window — still inside the window.
    timeout = getattr(settings, "INDIWEB_AUTH_CODE_TIMEOUT", 60)
    auth.created = auth.created - timedelta(seconds=timeout // 2)
    auth.save()

    response = client.post(
        reverse("indieweb:auth"),
        data={"code": auth.key, "client_id": auth.client_id},
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/x-www-form-urlencoded"
    assert "me=http%3A%2F%2Fexample.org" in response.content.decode("utf-8")
    # Verification is non-destructive on success — the row is consumed only
    # by token exchange.
    assert Auth.objects.filter(pk=auth.pk).exists()


@pytest.mark.django_db
def test_authorize_rejects_cross_origin_redirect_by_default(client, user):
    client.force_login(user)
    response = client.get(
        "/indieweb/auth/",
        {
            "client_id": "https://client.example/",
            "redirect_uri": "https://attacker.example/cb",
            "state": "abc",
            "me": "https://me.example/",
            "response_type": "code",
        },
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_authorize_accepts_same_origin_redirect(client, user):
    client.force_login(user)
    response = client.get(
        "/indieweb/auth/",
        {
            "client_id": "https://client.example/",
            "redirect_uri": "https://client.example/cb",
            "state": "abc",
            "me": "https://me.example/",
            "response_type": "code",
        },
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_authorize_allowlist_overrides_same_origin(client, settings, user):
    settings.INDIEWEB_REDIRECT_URI_ALLOWLIST = {
        "https://client.example/": ["https://callback.example/oauth/cb"],
    }
    client.force_login(user)
    response = client.get(
        "/indieweb/auth/",
        {
            "client_id": "https://client.example/",
            "redirect_uri": "https://callback.example/oauth/cb",
            "state": "abc",
            "me": "https://me.example/",
            "response_type": "code",
        },
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_authorize_allowlist_prefix_boundary(client, settings, user):
    settings.INDIEWEB_REDIRECT_URI_ALLOWLIST = {
        "https://client.example/": ["https://callback.example/oauth/"],
    }
    client.force_login(user)
    bad = client.get(
        "/indieweb/auth/",
        {
            "client_id": "https://client.example/",
            "redirect_uri": "https://callback.example/oauth.evil",
            "state": "abc",
            "me": "https://me.example/",
            "response_type": "code",
        },
    )
    assert bad.status_code == 400
    good = client.get(
        "/indieweb/auth/",
        {
            "client_id": "https://client.example/",
            "redirect_uri": "https://callback.example/oauth/cb",
            "state": "abc",
            "me": "https://me.example/",
            "response_type": "code",
        },
    )
    assert good.status_code == 200


@pytest.mark.django_db
def test_authorize_validator_hook_overrides_allowlist(client, settings, user):
    settings.INDIEWEB_REDIRECT_URI_VALIDATOR = "tests.test_redirect_validators.allow_all"
    settings.INDIEWEB_REDIRECT_URI_ALLOWLIST = {
        "https://client.example/": ["https://only-this.example/"],
    }
    client.force_login(user)
    response = client.get(
        "/indieweb/auth/",
        {
            "client_id": "https://client.example/",
            "redirect_uri": "https://anywhere.example/cb",
            "state": "abc",
            "me": "https://me.example/",
            "response_type": "code",
        },
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_authorize_validator_failure_fails_closed(client, settings, user):
    settings.INDIEWEB_REDIRECT_URI_VALIDATOR = "tests.test_redirect_validators.broken_path"
    client.force_login(user)
    response = client.get(
        "/indieweb/auth/",
        {
            "client_id": "https://client.example/",
            "redirect_uri": "https://client.example/cb",
            "state": "abc",
            "me": "https://me.example/",
            "response_type": "code",
        },
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_auth_get_rejects_overlong_state(client, user):
    """A ``state`` longer than the backing model max_length is rejected with 400."""
    client.force_login(user)
    response = client.get(
        reverse("indieweb:auth"),
        {
            "client_id": "https://c.example/",
            "redirect_uri": "https://c.example/cb",
            "state": "x" * 5000,
            "me": "https://me.example/",
            "response_type": "code",
        },
    )
    assert response.status_code == 400
    assert Auth.objects.count() == 0


@pytest.mark.django_db
def test_auth_get_rejects_overlong_client_id(client, user):
    """A ``client_id`` longer than the backing model max_length is rejected with 400."""
    client.force_login(user)
    response = client.get(
        reverse("indieweb:auth"),
        {
            "client_id": "https://c.example/" + ("a" * 5000),
            "redirect_uri": "https://c.example/cb",
            "state": "abc",
            "me": "https://me.example/",
            "response_type": "code",
        },
    )
    assert response.status_code == 400
    assert Auth.objects.count() == 0


@pytest.mark.django_db
def test_auth_get_rejects_overlong_redirect_uri(client, user):
    """A ``redirect_uri`` longer than the backing model max_length is rejected with 400."""
    client.force_login(user)
    response = client.get(
        reverse("indieweb:auth"),
        {
            "client_id": "https://c.example/",
            "redirect_uri": "https://c.example/" + ("a" * 5000),
            "state": "abc",
            "me": "https://me.example/",
            "response_type": "code",
        },
    )
    assert response.status_code == 400
    assert Auth.objects.count() == 0


@pytest.mark.django_db
def test_auth_get_rejects_overlong_me(client, user):
    """A ``me`` longer than the backing model max_length is rejected with 400."""
    client.force_login(user)
    response = client.get(
        reverse("indieweb:auth"),
        {
            "client_id": "https://c.example/",
            "redirect_uri": "https://c.example/cb",
            "state": "abc",
            "me": "https://me.example/" + ("a" * 5000),
            "response_type": "code",
        },
    )
    assert response.status_code == 400
    assert Auth.objects.count() == 0


@pytest.mark.django_db
def test_auth_get_rejects_overlong_scope(client, user):
    """An overlong ``scope`` is rejected with 400 before any DB write."""
    client.force_login(user)
    response = client.get(
        reverse("indieweb:auth"),
        {
            "client_id": "https://c.example/",
            "redirect_uri": "https://c.example/cb",
            "state": "abc",
            "me": "https://me.example/",
            "scope": "x" * 5000,
            "response_type": "code",
        },
    )
    assert response.status_code == 400
    assert Auth.objects.count() == 0


@pytest.mark.django_db
def test_auth_consent_post_rejects_overlong_state(client, user):
    """The consent POST path must reject overlong ``state`` before ``Auth.objects.create``."""
    client.force_login(user)
    response = client.post(
        reverse("indieweb:auth"),
        {
            "action": "approve",
            "client_id": "https://c.example/",
            "redirect_uri": "https://c.example/cb",
            "state": "x" * 5000,
            "me": "https://me.example/",
            "scope": "create",
        },
    )
    assert response.status_code == 400
    assert Auth.objects.count() == 0


@pytest.mark.django_db
def test_auth_consent_post_rejects_overlong_client_id(client, user):
    """The consent POST path must reject overlong ``client_id`` before ``Auth.objects.create``."""
    client.force_login(user)
    response = client.post(
        reverse("indieweb:auth"),
        {
            "action": "approve",
            "client_id": "https://c.example/" + ("a" * 5000),
            "redirect_uri": "https://c.example/cb",
            "state": "abc",
            "me": "https://me.example/",
            "scope": "create",
        },
    )
    assert response.status_code == 400
    assert Auth.objects.count() == 0


@pytest.mark.django_db
def test_auth_consent_post_rejects_overlong_redirect_uri(client, user):
    """The consent POST path must reject overlong ``redirect_uri`` before ``Auth.objects.create``."""
    client.force_login(user)
    response = client.post(
        reverse("indieweb:auth"),
        {
            "action": "approve",
            "client_id": "https://c.example/",
            "redirect_uri": "https://c.example/" + ("a" * 5000),
            "state": "abc",
            "me": "https://me.example/",
            "scope": "create",
        },
    )
    assert response.status_code == 400
    assert Auth.objects.count() == 0
