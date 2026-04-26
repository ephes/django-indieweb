"""Tests for the Micropub source query on the resource server."""

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from indieweb import models
from indieweb.handlers import InMemoryMicropubHandler


@pytest.fixture
def user(db):
    return User.objects.create_user(username="sourceuser", email="source@example.org", password="password")


@pytest.fixture
def micropub_url():
    return reverse("indieweb:micropub")


@pytest.fixture
def shared_handler(monkeypatch):
    """Inject a single shared in-memory handler so source requests see seeded entries."""
    handler = InMemoryMicropubHandler()
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler)
    return handler


def _make_token(user, scope: str) -> "models.Token":
    return models.Token.objects.create(
        me="https://example.org",
        client_id="https://client.example.org",
        scope=scope,
        owner=user,
    )


@pytest.mark.django_db
class TestMicropubSourceQuery:
    def test_full_source_returns_type_and_all_properties(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry(
            {"content": ["Hello source"], "name": ["Source title"], "category": ["indieweb"]}, user
        )

        token = _make_token(user, "update")
        response = client.get(
            micropub_url,
            data={"q": "source", "url": entry.url},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
        assert response.json() == {
            "type": ["h-entry"],
            "properties": {
                "content": ["Hello source"],
                "name": ["Source title"],
                "category": ["indieweb"],
            },
        }

    def test_selective_properties_returns_only_requested_properties(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry(
            {"content": ["Hello source"], "name": ["Source title"], "category": ["indieweb"]}, user
        )

        token = _make_token(user, "update")
        response = client.get(
            f"{micropub_url}?q=source&url={entry.url}&properties[]=content&properties[]=name",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 200
        assert response.json() == {
            "properties": {
                "content": ["Hello source"],
                "name": ["Source title"],
            }
        }
        assert "type" not in response.json()

    def test_missing_requested_properties_are_omitted(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Hello source"]}, user)

        token = _make_token(user, "update")
        response = client.get(
            f"{micropub_url}?q=source&url={entry.url}&properties[]=content&properties[]=summary",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 200
        assert response.json() == {"properties": {"content": ["Hello source"]}}

    def test_all_unknown_requested_properties_returns_empty_properties(
        self, client, user, micropub_url, shared_handler
    ):
        entry = shared_handler.create_entry({"content": ["Hello source"]}, user)

        token = _make_token(user, "update")
        response = client.get(
            f"{micropub_url}?q=source&url={entry.url}&properties[]=summary&properties[]=published",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 200
        assert response.json() == {"properties": {}}

    def test_multiple_properties_values_both_round_trip(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry(
            {"category": ["indieweb", "micropub"], "photo": ["https://example.org/photo.jpg"]}, user
        )

        token = _make_token(user, "update")
        response = client.get(
            f"{micropub_url}?q=source&url={entry.url}&properties[]=photo&properties[]=category",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 200
        assert response.json() == {
            "properties": {
                "photo": ["https://example.org/photo.jpg"],
                "category": ["indieweb", "micropub"],
            }
        }

    def test_unknown_url_returns_400_invalid_request(self, client, user, micropub_url, shared_handler):
        token = _make_token(user, "update")
        response = client.get(
            micropub_url,
            data={"q": "source", "url": "/entries/missing/"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"

    def test_missing_url_returns_400_invalid_request(self, client, user, micropub_url, shared_handler):
        token = _make_token(user, "update")
        response = client.get(
            micropub_url,
            data={"q": "source"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"

    def test_handler_value_error_returns_400_invalid_request(self, client, user, micropub_url, monkeypatch):
        class RejectingHandler(InMemoryMicropubHandler):
            def get_entry(self, url, user):
                raise ValueError("entry not found")

        handler = RejectingHandler()
        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler)

        token = _make_token(user, "update")
        response = client.get(
            micropub_url,
            data={"q": "source", "url": "/entries/1/"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"

    def test_unexpected_handler_exception_returns_500(self, client, user, micropub_url, monkeypatch):
        class BrokenHandler(InMemoryMicropubHandler):
            def get_entry(self, url, user):
                raise RuntimeError("database is down")

        handler = BrokenHandler()
        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler)

        token = _make_token(user, "update")
        response = client.get(
            micropub_url,
            data={"q": "source", "url": "/entries/1/"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 500
        assert response.content == b""
