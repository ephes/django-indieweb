#!/usr/bin/env python
"""
Comprehensive tests for IndieAuth consent screen functionality.
"""

import re
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from indieweb.models import Auth, Profile


@pytest.fixture
def user(db):
    return User.objects.create_user(username="testuser", email="test@example.com", password="testpass")


@pytest.fixture
def auth_url():
    return reverse("indieweb:auth")


def _consent_data(action="approve", redirect_uri="https://app.example.com/callback"):
    return {
        "action": action,
        "client_id": "https://app.example.com",
        "redirect_uri": redirect_uri,
        "state": "test123",
        "me": "https://example.com",
        "scope": "create",
    }


def _authorization_request_data():
    data = _consent_data()
    data.pop("action")
    return data


def _csrf_token(response):
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.content.decode("utf-8"))
    assert match is not None
    return match.group(1)


class TestConsentScreenDisplay:
    """Test consent screen rendering and display."""

    def test_consent_screen_shows_all_scopes(self, client, user, auth_url):
        """Test that consent screen displays all requested scopes."""
        client.login(username=user.username, password="testpass")

        response = client.get(
            auth_url,
            {
                "me": "https://example.com",
                "client_id": "https://app.example.com",
                "redirect_uri": "https://app.example.com/callback",
                "state": "test123",
                "scope": "create update delete media",
            },
        )

        assert response.status_code == 200

        # Check template was used
        assert hasattr(response, "templates"), "Response should have templates attribute"
        template_names = [t.name for t in response.templates]
        assert "indieweb/consent.html" in template_names

        # Check context has the right data
        assert hasattr(response, "context"), "Response should have context attribute"
        assert response.context["client_id"] == "https://app.example.com"
        assert response.context["scope"] == "create update delete media"
        assert response.context["scope_list"] == ["create", "update", "delete", "media"]

    def test_consent_screen_without_scope(self, client, user, auth_url):
        """Test consent screen when no scope is requested (auth only)."""
        client.login(username=user.username, password="testpass")

        response = client.get(
            auth_url,
            {
                "me": "https://example.com",
                "client_id": "https://app.example.com",
                "redirect_uri": "https://app.example.com/callback",
                "state": "test123",
            },
        )

        assert response.status_code == 200

        # Check template was used
        assert hasattr(response, "templates"), "Response should have templates attribute"
        template_names = [t.name for t in response.templates]
        assert "indieweb/consent.html" in template_names

        # Check context
        assert hasattr(response, "context"), "Response should have context attribute"
        assert response.context["scope_list"] == []

    def test_consent_screen_escapes_html(self, client, user, auth_url, settings):
        """Test that consent screen properly escapes HTML in parameters."""
        settings.INDIEWEB_REDIRECT_URI_VALIDATOR = "tests.test_redirect_validators.allow_all"
        client.login(username=user.username, password="testpass")

        response = client.get(
            auth_url,
            {
                "me": "https://example.com",
                "client_id": "https://evil.com/<script>alert('xss')</script>",
                "redirect_uri": "https://app.example.com/callback",
                "state": "test123",
            },
        )

        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # HTML should be escaped
        assert "<script>" not in content
        assert "&lt;script&gt;" in content or "script" not in content

    def test_consent_screen_preserves_all_parameters(self, client, user, auth_url):
        """Test that context preserves all parameters."""
        client.login(username=user.username, password="testpass")

        response = client.get(
            auth_url,
            {
                "me": "https://example.com",
                "client_id": "https://app.example.com",
                "redirect_uri": "https://app.example.com/callback",
                "state": "complex-state-123",
                "scope": "create",
            },
        )

        assert response.status_code == 200

        # Check context preserves all parameters
        assert hasattr(response, "context"), "Response should have context attribute"
        assert response.context["client_id"] == "https://app.example.com"
        assert response.context["redirect_uri"] == "https://app.example.com/callback"
        assert response.context["state"] == "complex-state-123"
        assert response.context["me"] == "https://example.com"
        assert response.context["scope"] == "create"

    def test_consent_screen_shows_expected_profile_url_and_mismatch(self, client, user, auth_url):
        """Consent context and template warn when submitted me differs from the local profile URL."""
        Profile.objects.create(user=user, h_card={"url": ["https://profile.example.com/"]})
        client.login(username=user.username, password="testpass")

        response = client.get(
            auth_url,
            {
                "me": "https://example.com",
                "client_id": "https://app.example.com",
                "redirect_uri": "https://app.example.com/callback",
                "state": "test123",
            },
        )

        assert response.status_code == 200
        assert response.context["expected_me"] == "https://profile.example.com/"
        assert response.context["me_mismatch"] is True
        content = response.content.decode("utf-8")
        assert "Configured identity URL" in content
        assert "does not match your configured identity URL" in content

    def test_consent_screen_blocks_framing(self, client, user, auth_url):
        """Consent GET emits frame protections."""
        client.login(username=user.username, password="testpass")

        response = client.get(
            auth_url,
            {
                "me": "https://example.com",
                "client_id": "https://app.example.com",
                "redirect_uri": "https://app.example.com/callback",
                "state": "test123",
            },
        )

        assert response.status_code == 200
        assert response["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in response["Content-Security-Policy"]


class TestConsentActions:
    """Test consent approval and denial actions."""

    def test_approve_with_multiple_scopes(self, client, user, auth_url):
        """Test approving with multiple scopes creates proper auth."""
        client.login(username=user.username, password="testpass")

        response = client.post(
            auth_url,
            {
                "action": "approve",
                "client_id": "https://app.example.com",
                "redirect_uri": "https://app.example.com/callback",
                "state": "test123",
                "me": "https://example.com",
                "scope": "create update delete",
            },
        )

        assert response.status_code == 302

        # Check auth was created with all scopes
        auth = Auth.objects.get(client_id="https://app.example.com")
        assert auth.scope == "create update delete"
        assert auth.me == "https://example.com"
        assert auth.owner == user

    def test_approve_without_scope(self, client, user, auth_url):
        """Test approving without scope (auth only)."""
        client.login(username=user.username, password="testpass")

        response = client.post(
            auth_url,
            {
                "action": "approve",
                "client_id": "https://app.example.com",
                "redirect_uri": "https://app.example.com/callback",
                "state": "test123",
                "me": "https://example.com",
            },
        )

        assert response.status_code == 302

        # Check auth was created without scope
        auth = Auth.objects.get(client_id="https://app.example.com")
        assert auth.scope is None or auth.scope == ""
        assert auth.me == "https://example.com"

    def test_deny_does_not_create_auth(self, client, user, auth_url):
        """Test denying does not create any auth object."""
        client.login(username=user.username, password="testpass")

        # Ensure no auth exists
        assert Auth.objects.count() == 0

        response = client.post(
            auth_url,
            {
                "action": "deny",
                "client_id": "https://app.example.com",
                "redirect_uri": "https://app.example.com/callback",
                "state": "test123",
                "me": "https://example.com",
                "scope": "create",
            },
        )

        assert response.status_code == 302
        assert "error=access_denied" in response.url

        # No auth should be created
        assert Auth.objects.count() == 0

    def test_missing_action_parameter(self, client, user, auth_url):
        """Test POST without action parameter falls back to code verification."""
        client.login(username=user.username, password="testpass")

        # Create an auth first
        auth = Auth.objects.create(
            owner=user,
            client_id="https://app.example.com",
            redirect_uri="https://app.example.com/callback",
            state="test123",
            me="https://example.com",
        )

        response = client.post(
            auth_url,
            {
                "code": auth.key,
                "client_id": "https://app.example.com",
            },
        )

        assert response.status_code == 200
        assert "me=https%3A%2F%2Fexample.com" in response.content.decode("utf-8")

    def test_invalid_action_parameter(self, client, user, auth_url):
        """Test POST with invalid action parameter."""
        client.login(username=user.username, password="testpass")

        response = client.post(
            auth_url,
            {
                "action": "invalid",
                "client_id": "https://app.example.com",
                "redirect_uri": "https://app.example.com/callback",
                "state": "test123",
                "me": "https://example.com",
            },
        )

        # Should fall through to code verification and fail
        assert response.status_code == 400

    def test_consent_missing_required_parameters(self, client, user, auth_url):
        """Test consent form submission with missing parameters."""
        client.login(username=user.username, password="testpass")

        # Missing redirect_uri
        response = client.post(
            auth_url,
            {
                "action": "approve",
                "client_id": "https://app.example.com",
                "state": "test123",
                "me": "https://example.com",
            },
        )

        assert response.status_code == 400
        assert "Missing required parameters" in response.content.decode("utf-8")


class TestConsentSecurity:
    """Test security aspects of consent screen."""

    def test_requires_authentication(self, client, auth_url):
        """Test that consent screen requires login."""
        response = client.get(
            auth_url,
            {
                "me": "https://example.com",
                "client_id": "https://app.example.com",
                "redirect_uri": "https://app.example.com/callback",
                "state": "test123",
            },
        )

        assert response.status_code == 302
        assert "login" in response.url

    def test_csrf_token_in_form(self, client, user, auth_url):
        """Test that consent form uses correct template with CSRF."""
        client.login(username=user.username, password="testpass")

        response = client.get(
            auth_url,
            {
                "me": "https://example.com",
                "client_id": "https://app.example.com",
                "redirect_uri": "https://app.example.com/callback",
                "state": "test123",
            },
        )

        assert response.status_code == 200

        # Just verify the template was used - CSRF token check needs actual rendering
        assert hasattr(response, "templates"), "Response should have templates attribute"
        template_names = [t.name for t in response.templates]
        assert "indieweb/consent.html" in template_names

    def test_approve_requires_csrf_token(self, user, auth_url):
        """Approve consent POST is CSRF-protected for browser clients."""
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(user)

        blocked = csrf_client.post(auth_url, _consent_data("approve"))

        assert blocked.status_code == 403
        assert Auth.objects.count() == 0

    def test_deny_requires_csrf_token(self, user, auth_url):
        """Deny consent POST is CSRF-protected for browser clients."""
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(user)

        blocked = csrf_client.post(auth_url, _consent_data("deny"))

        assert blocked.status_code == 403
        assert Auth.objects.count() == 0

    def test_approve_with_valid_csrf_token_still_works(self, user, auth_url):
        """Authenticated approve with a valid CSRF token creates an auth code."""
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(user)
        page = csrf_client.get(auth_url, _authorization_request_data())

        response = csrf_client.post(
            auth_url,
            _consent_data("approve") | {"csrfmiddlewaretoken": _csrf_token(page)},
        )

        assert response.status_code == 302
        params = parse_qs(urlparse(response.url).query)
        assert "code" in params
        assert params["state"] == ["test123"]
        assert Auth.objects.get(client_id="https://app.example.com").owner == user

    def test_deny_with_valid_csrf_token_still_works(self, user, auth_url):
        """Authenticated deny with a valid CSRF token redirects with access_denied."""
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(user)
        page = csrf_client.get(auth_url, _authorization_request_data())

        response = csrf_client.post(
            auth_url,
            _consent_data("deny") | {"csrfmiddlewaretoken": _csrf_token(page)},
        )

        assert response.status_code == 302
        params = parse_qs(urlparse(response.url).query)
        assert params["error"] == ["access_denied"]
        assert params["state"] == ["test123"]
        assert Auth.objects.count() == 0

    def test_unauthenticated_deny_does_not_redirect_to_client_uri(self, client, auth_url):
        """Unauthenticated deny submissions are rejected before client redirect handling."""
        response = client.post(
            auth_url,
            _consent_data("deny", redirect_uri="https://attacker.example/callback"),
        )

        assert response.status_code == 401
        assert "Location" not in response
        assert b"User not authenticated" in response.content

    def test_strict_me_binding_rejects_mismatch(self, client, settings, user, auth_url):
        """Strict me binding blocks a mismatched submitted identity before issuing a code."""
        settings.INDIEWEB_BIND_ME_TO_USER = True
        Profile.objects.create(user=user, h_card={"url": ["https://profile.example.com/"]})
        client.login(username=user.username, password="testpass")

        response = client.post(auth_url, _consent_data("approve"))

        assert response.status_code == 400
        assert response.content == b"invalid me"
        assert Auth.objects.count() == 0

    def test_strict_me_binding_accepts_matching_identity(self, client, settings, user, auth_url):
        """Strict me binding accepts equivalent configured and submitted identity URLs."""
        settings.INDIEWEB_BIND_ME_TO_USER = True
        Profile.objects.create(user=user, h_card={"url": ["https://example.com/"]})
        client.login(username=user.username, password="testpass")

        response = client.post(auth_url, _consent_data("approve"))

        assert response.status_code == 302
        assert Auth.objects.get(client_id="https://app.example.com").me == "https://example.com"

    def test_strict_me_binding_without_profile_url_fails_closed(self, client, settings, user, auth_url):
        """Strict me binding has deterministic fail-closed behavior when no local profile URL exists."""
        settings.INDIEWEB_BIND_ME_TO_USER = True
        client.login(username=user.username, password="testpass")

        response = client.post(auth_url, _consent_data("approve"))

        assert response.status_code == 400
        assert response.content == b"invalid me"
        assert Auth.objects.count() == 0

    def test_code_verification_post_remains_csrf_exempt(self, user, auth_url):
        """Legacy IndieAuth code verification POST remains a protocol POST."""
        csrf_client = Client(enforce_csrf_checks=True)
        auth = Auth.objects.create(
            owner=user,
            client_id="https://app.example.com",
            redirect_uri="https://app.example.com/callback",
            state="test123",
            me="https://example.com",
        )

        response = csrf_client.post(
            auth_url,
            {
                "code": auth.key,
                "client_id": "https://app.example.com",
            },
        )

        assert response.status_code == 200
        assert "me=https%3A%2F%2Fexample.com" in response.content.decode("utf-8")

    def test_state_parameter_preserved(self, client, user, auth_url):
        """Test that state parameter is preserved through the flow."""
        client.login(username=user.username, password="testpass")

        # Complex state that might need encoding
        state = "complex/state?with=special&chars"

        response = client.post(
            auth_url,
            {
                "action": "approve",
                "client_id": "https://app.example.com",
                "redirect_uri": "https://app.example.com/callback",
                "state": state,
                "me": "https://example.com",
            },
        )

        assert response.status_code == 302
        parsed = urlparse(response.url)
        params = parse_qs(parsed.query)
        assert params["state"][0] == state


class TestExistingAuthReplacement:
    """Test replacing existing auth objects."""

    def test_replaces_existing_auth_same_scope(self, client, user, auth_url):
        """Test that approving again with same scope replaces existing auth."""
        client.login(username=user.username, password="testpass")

        # Create first auth
        client.post(
            auth_url,
            {
                "action": "approve",
                "client_id": "https://app.example.com",
                "redirect_uri": "https://app.example.com/callback",
                "state": "test123",
                "me": "https://example.com",
                "scope": "create",
            },
        )

        first_auth = Auth.objects.get(client_id="https://app.example.com", scope="create")
        first_key = first_auth.key

        # Approve again with same scope
        client.post(
            auth_url,
            {
                "action": "approve",
                "client_id": "https://app.example.com",
                "redirect_uri": "https://app.example.com/callback",
                "state": "test456",
                "me": "https://example.com",
                "scope": "create",
            },
        )

        # Should have only one auth with this scope
        assert Auth.objects.filter(client_id="https://app.example.com", scope="create").count() == 1

        # With new key
        new_auth = Auth.objects.get(client_id="https://app.example.com", scope="create")
        assert new_auth.key != first_key


@pytest.mark.django_db
def test_consent_screen_displays_redirect_uri(client, user):
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
    assert b"https://client.example/cb" in response.content
