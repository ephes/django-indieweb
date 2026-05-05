#!/usr/bin/env python

"""Tests for Micropub category/channel queries and query discovery."""

import json

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from indieweb import models
from indieweb.handlers import InMemoryMicropubHandler


@pytest.fixture
def user(db):
    return User.objects.create_user(username="queryuser", email="query@example.org", password="password")


@pytest.fixture
def token(user):
    return models.Token.objects.create(
        me="https://example.org",
        client_id="https://client.example.org",
        scope="create",
        owner=user,
    )


@pytest.fixture
def micropub_url():
    return reverse("indieweb:micropub")


def _make_token(user, scope: str | None) -> "models.Token":
    return models.Token.objects.create(
        me="https://example.org",
        client_id="https://client.example.org",
        scope=scope,
        owner=user,
    )


def _patch_handler(monkeypatch, handler_cls):
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler_cls())


class _CategoriesHandler(InMemoryMicropubHandler):
    def get_config(self, user):
        config = super().get_config(user)
        config["categories"] = ["indieweb", "Micropub", "django", "test"]
        return config


class _ChannelsHandler(InMemoryMicropubHandler):
    def get_config(self, user):
        config = super().get_config(user)
        config["channels"] = [
            {"uid": "notes", "name": "Notes"},
            {"uid": "articles", "name": "Articles"},
            {"uid": "photos", "name": "Photos"},
        ]
        return config


class _NoListsHandler(InMemoryMicropubHandler):
    def get_config(self, user):
        return {
            "media-endpoint": None,
            "syndicate-to": [],
            "post-types": [],
        }


@pytest.mark.django_db
class TestQueryDiscovery:
    """Verify ``q=config`` advertises supported query names and default lists."""

    def test_config_advertises_supported_q_list(self, client, token, micropub_url):
        response = client.get(f"{micropub_url}?q=config", Authorization=f"Bearer {token.key}")
        assert response.status_code == 200
        config = json.loads(response.content)
        assert "q" in config
        assert isinstance(config["q"], list)
        assert set(config["q"]) == {"config", "source", "syndicate-to", "category", "channel"}

    def test_config_does_not_advertise_unimplemented_query_names(self, client, token, micropub_url):
        response = client.get(f"{micropub_url}?q=config", Authorization=f"Bearer {token.key}")
        config = json.loads(response.content)
        assert "media-endpoint" not in config["q"]
        assert "post-types" not in config["q"]

    def test_config_advertises_default_categories_and_channels(self, client, token, micropub_url):
        response = client.get(f"{micropub_url}?q=config", Authorization=f"Bearer {token.key}")
        config = json.loads(response.content)
        assert config.get("categories") == []
        assert config.get("channels") == []

    def test_config_does_not_mutate_handler_owned_config(self, client, token, micropub_url, monkeypatch):
        """A custom handler that reuses one config dict must not receive injected view-owned keys."""
        cached: dict = {
            "media-endpoint": None,
            "syndicate-to": [],
            "post-types": [],
            "categories": ["a"],
            "channels": [],
        }

        class CachedHandler(InMemoryMicropubHandler):
            def get_config(self, user):
                return cached

        _patch_handler(monkeypatch, CachedHandler)
        client.get(f"{micropub_url}?q=config", Authorization=f"Bearer {token.key}")
        assert "q" not in cached
        assert cached["media-endpoint"] is None


@pytest.mark.django_db
class TestCategoryQuery:
    """Verify ``q=category`` returns the handler's ``categories`` list."""

    def test_default_handler_returns_empty_categories(self, client, token, micropub_url):
        response = client.get(f"{micropub_url}?q=category", Authorization=f"Bearer {token.key}")
        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
        body = json.loads(response.content)
        assert body == {"categories": []}

    def test_custom_handler_categories_are_returned(self, client, token, micropub_url, monkeypatch):
        _patch_handler(monkeypatch, _CategoriesHandler)
        response = client.get(f"{micropub_url}?q=category", Authorization=f"Bearer {token.key}")
        assert response.status_code == 200
        body = json.loads(response.content)
        assert body == {"categories": ["indieweb", "Micropub", "django", "test"]}

    def test_missing_categories_key_returns_empty(self, client, token, micropub_url, monkeypatch):
        _patch_handler(monkeypatch, _NoListsHandler)
        response = client.get(f"{micropub_url}?q=category", Authorization=f"Bearer {token.key}")
        assert response.status_code == 200
        assert json.loads(response.content) == {"categories": []}

    def test_filter_is_case_insensitive_substring(self, client, token, micropub_url, monkeypatch):
        _patch_handler(monkeypatch, _CategoriesHandler)
        response = client.get(
            f"{micropub_url}?q=category&filter=micro",
            Authorization=f"Bearer {token.key}",
        )
        assert json.loads(response.content) == {"categories": ["Micropub"]}

    def test_limit_truncates_after_filter(self, client, token, micropub_url, monkeypatch):
        _patch_handler(monkeypatch, _CategoriesHandler)
        response = client.get(
            f"{micropub_url}?q=category&limit=2",
            Authorization=f"Bearer {token.key}",
        )
        assert json.loads(response.content) == {"categories": ["indieweb", "Micropub"]}

    def test_offset_skips_items(self, client, token, micropub_url, monkeypatch):
        _patch_handler(monkeypatch, _CategoriesHandler)
        response = client.get(
            f"{micropub_url}?q=category&offset=2",
            Authorization=f"Bearer {token.key}",
        )
        assert json.loads(response.content) == {"categories": ["django", "test"]}

    def test_limit_and_offset_combine(self, client, token, micropub_url, monkeypatch):
        _patch_handler(monkeypatch, _CategoriesHandler)
        response = client.get(
            f"{micropub_url}?q=category&offset=1&limit=2",
            Authorization=f"Bearer {token.key}",
        )
        assert json.loads(response.content) == {"categories": ["Micropub", "django"]}

    @pytest.mark.parametrize(
        "params",
        [
            "limit=abc",
            "limit=-1",
            "offset=abc",
            "offset=-1",
            "limit=1.5",
        ],
    )
    def test_malformed_limit_or_offset_returns_invalid_request(self, client, token, micropub_url, monkeypatch, params):
        _patch_handler(monkeypatch, _CategoriesHandler)
        response = client.get(
            f"{micropub_url}?q=category&{params}",
            Authorization=f"Bearer {token.key}",
        )
        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
class TestChannelQuery:
    """Verify ``q=channel`` returns the handler's ``channels`` list."""

    def test_default_handler_returns_empty_channels(self, client, token, micropub_url):
        response = client.get(f"{micropub_url}?q=channel", Authorization=f"Bearer {token.key}")
        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
        assert json.loads(response.content) == {"channels": []}

    def test_custom_handler_channels_are_returned(self, client, token, micropub_url, monkeypatch):
        _patch_handler(monkeypatch, _ChannelsHandler)
        response = client.get(f"{micropub_url}?q=channel", Authorization=f"Bearer {token.key}")
        assert response.status_code == 200
        body = json.loads(response.content)
        assert body == {
            "channels": [
                {"uid": "notes", "name": "Notes"},
                {"uid": "articles", "name": "Articles"},
                {"uid": "photos", "name": "Photos"},
            ]
        }

    def test_missing_channels_key_returns_empty(self, client, token, micropub_url, monkeypatch):
        _patch_handler(monkeypatch, _NoListsHandler)
        response = client.get(f"{micropub_url}?q=channel", Authorization=f"Bearer {token.key}")
        assert response.status_code == 200
        assert json.loads(response.content) == {"channels": []}

    def test_filter_matches_dict_uid_or_name(self, client, token, micropub_url, monkeypatch):
        _patch_handler(monkeypatch, _ChannelsHandler)
        response = client.get(
            f"{micropub_url}?q=channel&filter=notes",
            Authorization=f"Bearer {token.key}",
        )
        body = json.loads(response.content)
        assert body == {"channels": [{"uid": "notes", "name": "Notes"}]}

    def test_limit_and_offset(self, client, token, micropub_url, monkeypatch):
        _patch_handler(monkeypatch, _ChannelsHandler)
        response = client.get(
            f"{micropub_url}?q=channel&offset=1&limit=1",
            Authorization=f"Bearer {token.key}",
        )
        assert json.loads(response.content) == {"channels": [{"uid": "articles", "name": "Articles"}]}


@pytest.mark.django_db
@pytest.mark.parametrize("q", ["category", "channel"])
@pytest.mark.parametrize("scope", ["create", "post", "update", "delete", "undelete", "read", "", None])
def test_category_channel_queries_have_no_scope_gate(client, user, micropub_url, q, scope):
    """``q=category`` and ``q=channel`` are token-required only; no operation scope is required."""
    token = _make_token(user, scope)
    response = client.get(f"{micropub_url}?q={q}", Authorization=f"Bearer {token.key}")
    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("q", ["category", "channel"])
def test_category_channel_queries_require_a_token(client, micropub_url, q):
    response = client.get(f"{micropub_url}?q={q}")
    assert response.status_code == 401
