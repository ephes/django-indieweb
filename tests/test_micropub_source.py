"""Tests for the Micropub source query on the resource server."""

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from indieweb import models
from indieweb.handlers import InMemoryMicropubHandler, MicropubContentHandler, MicropubEntry, MicropubEntryList


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

    def test_empty_submitted_url_returns_400_invalid_request(self, client, user, micropub_url, shared_handler):
        token = _make_token(user, "update")
        response = client.get(
            micropub_url,
            data={"q": "source", "url": ""},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"

    def test_source_list_returns_items_and_paging(self, client, user, micropub_url, shared_handler):
        first = shared_handler.create_entry({"content": ["First source"], "category": ["notes"]}, user)
        second = shared_handler.create_entry({"content": ["Second source"], "name": ["Source title"]}, user)

        token = _make_token(user, "update")
        response = client.get(
            micropub_url,
            data={"q": "source"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
        assert response.json() == {
            "items": [
                {
                    "type": ["h-entry"],
                    "properties": {
                        "content": ["First source"],
                        "category": ["notes"],
                        "url": [first.url],
                    },
                },
                {
                    "type": ["h-entry"],
                    "properties": {
                        "content": ["Second source"],
                        "name": ["Source title"],
                        "url": [second.url],
                    },
                },
            ],
            "paging": {"limit": 20, "offset": 0, "total": 2},
        }

    def test_source_list_preserves_handler_url_property(self, client, user, micropub_url, shared_handler):
        shared_handler.create_entry(
            {
                "content": ["Linked source"],
                "url": ["https://example.org/posts/linked"],
            },
            user,
        )

        token = _make_token(user, "update")
        response = client.get(micropub_url, data={"q": "source"}, Authorization=f"Bearer {token.key}")

        assert response.status_code == 200
        assert response.json()["items"][0]["properties"]["url"] == ["https://example.org/posts/linked"]

    def test_source_list_preserves_handler_entry_type(self, client, user, micropub_url, shared_handler):
        entry = MicropubEntry(url="/events/1/", properties={"name": ["Launch"]}, type=["h-event"])
        shared_handler.entries[entry.url] = entry

        token = _make_token(user, "update")
        response = client.get(micropub_url, data={"q": "source"}, Authorization=f"Bearer {token.key}")

        assert response.status_code == 200
        assert response.json()["items"][0] == {
            "type": ["h-event"],
            "properties": {
                "name": ["Launch"],
                "url": ["/events/1/"],
            },
        }

    def test_source_list_empty_response(self, client, user, micropub_url, shared_handler):
        token = _make_token(user, "update")
        response = client.get(micropub_url, data={"q": "source"}, Authorization=f"Bearer {token.key}")

        assert response.status_code == 200
        assert response.json() == {"items": [], "paging": {"limit": 20, "offset": 0, "total": 0}}

    def test_source_list_limit_and_offset(self, client, user, micropub_url, shared_handler):
        shared_handler.create_entry({"content": ["First source"]}, user)
        second = shared_handler.create_entry({"content": ["Second source"]}, user)
        shared_handler.create_entry({"content": ["Third source"]}, user)

        token = _make_token(user, "update")
        response = client.get(
            micropub_url,
            data={"q": "source", "limit": "1", "offset": "1"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 200
        assert response.json() == {
            "items": [
                {
                    "type": ["h-entry"],
                    "properties": {
                        "content": ["Second source"],
                        "url": [second.url],
                    },
                }
            ],
            "paging": {"limit": 1, "offset": 1, "total": 3},
        }

    @pytest.mark.parametrize(
        "params",
        [
            {"limit": "abc"},
            {"limit": "-1"},
            {"limit": "1.5"},
            {"offset": "abc"},
            {"offset": "-1"},
        ],
    )
    def test_source_list_malformed_limit_or_offset_returns_invalid_request(
        self, client, user, micropub_url, shared_handler, params
    ):
        token = _make_token(user, "update")
        response = client.get(
            micropub_url,
            data={"q": "source", **params},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"

    def test_source_list_filter_is_case_insensitive_substring(self, client, user, micropub_url, shared_handler):
        match = shared_handler.create_entry({"content": ["Django Micropub source"]}, user)
        shared_handler.create_entry({"content": ["Unrelated note"]}, user)

        token = _make_token(user, "update")
        response = client.get(
            micropub_url,
            data={"q": "source", "filter": "micro"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 200
        assert response.json() == {
            "items": [
                {
                    "type": ["h-entry"],
                    "properties": {
                        "content": ["Django Micropub source"],
                        "url": [match.url],
                    },
                }
            ],
            "paging": {"limit": 20, "offset": 0, "total": 1},
        }

    def test_source_list_unsupported_handler_returns_501(self, client, user, micropub_url, monkeypatch):
        class UnsupportedListHandler(MicropubContentHandler):
            def create_entry(self, properties, user):
                return MicropubEntry(url="/entries/1/", properties=properties)

            def update_entry(self, url, updates, user):
                return MicropubEntry(url=url, properties={})

            def delete_entry(self, url, user):
                return None

            def undelete_entry(self, url, user):
                return MicropubEntry(url=url, properties={})

            def get_entry(self, url, user):
                return None

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: UnsupportedListHandler())

        token = _make_token(user, "update")
        response = client.get(micropub_url, data={"q": "source"}, Authorization=f"Bearer {token.key}")

        assert response.status_code == 501
        assert response.content.decode("utf-8") == "not_implemented"

    def test_source_list_custom_handler_result_can_omit_total(self, client, user, micropub_url, monkeypatch):
        calls = []

        class CustomListHandler(InMemoryMicropubHandler):
            def list_entries(self, user, *, limit=None, offset=0, filter=None):
                calls.append({"limit": limit, "offset": offset, "filter": filter})
                return MicropubEntryList(
                    entries=[MicropubEntry(url="/custom/1/", properties={"content": ["Custom source"]})]
                )

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: CustomListHandler())

        token = _make_token(user, "update")
        response = client.get(
            micropub_url,
            data={"q": "source", "limit": "5", "offset": "2", "filter": "custom"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 200
        assert calls == [{"limit": 5, "offset": 2, "filter": "custom"}]
        assert response.json() == {
            "items": [
                {
                    "type": ["h-entry"],
                    "properties": {
                        "content": ["Custom source"],
                        "url": ["/custom/1/"],
                    },
                }
            ],
            "paging": {"limit": 5, "offset": 2},
        }

    def test_source_list_empty_filter_is_forwarded_as_none(self, client, user, micropub_url, monkeypatch):
        calls = []

        class CustomListHandler(InMemoryMicropubHandler):
            def list_entries(self, user, *, limit=None, offset=0, filter=None):
                calls.append(filter)
                return MicropubEntryList(entries=[])

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: CustomListHandler())

        token = _make_token(user, "update")
        response = client.get(
            micropub_url,
            data={"q": "source", "filter": ""},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 200
        assert calls == [None]

    def test_source_list_value_error_returns_400_invalid_request(self, client, user, micropub_url, monkeypatch):
        class RejectingListHandler(InMemoryMicropubHandler):
            def list_entries(self, user, *, limit=None, offset=0, filter=None):
                raise ValueError("cannot enumerate")

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: RejectingListHandler())

        token = _make_token(user, "update")
        response = client.get(micropub_url, data={"q": "source"}, Authorization=f"Bearer {token.key}")

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"

    def test_source_list_unexpected_exception_returns_500(self, client, user, micropub_url, monkeypatch):
        class BrokenListHandler(InMemoryMicropubHandler):
            def list_entries(self, user, *, limit=None, offset=0, filter=None):
                raise RuntimeError("database is down")

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: BrokenListHandler())

        token = _make_token(user, "update")
        response = client.get(micropub_url, data={"q": "source"}, Authorization=f"Bearer {token.key}")

        assert response.status_code == 500
        assert response.content == b""

    def test_source_list_non_update_scope_rejected_before_handler_work(
        self, client, user, micropub_url, shared_handler, monkeypatch
    ):
        def fail_if_called():
            raise AssertionError("handler should not be loaded")

        monkeypatch.setattr("indieweb.views.get_micropub_handler", fail_if_called)

        token = _make_token(user, "create")
        response = client.get(micropub_url, data={"q": "source"}, Authorization=f"Bearer {token.key}")

        assert response.status_code == 403
        assert "authorization error" in response.content.decode("utf-8")

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
