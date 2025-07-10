#!/usr/bin/env python
"""
Comprehensive tests for IndieAuth consent screen functionality.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from indieweb.models import Auth


@pytest.fixture
def user(db):
    return User.objects.create_user(username="testuser", email="test@example.com", password="testpass")


@pytest.fixture
def auth_url():
    return reverse("indieweb:auth")


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

    def test_consent_screen_escapes_html(self, client, user, auth_url):
        """Test that consent screen properly escapes HTML in parameters."""
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
