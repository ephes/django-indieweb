"""Tests for the Micropub update/delete/undelete actions on the resource server."""

import json

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from indieweb import models
from indieweb.handlers import InMemoryMicropubHandler


@pytest.fixture
def user(db):
    return User.objects.create_user(username="actuser", email="act@example.org", password="password")


@pytest.fixture
def micropub_url():
    return reverse("indieweb:micropub")


@pytest.fixture
def shared_handler(monkeypatch):
    """Inject a single shared in-memory handler so create + action requests see the same state."""
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
class TestMicropubUpdate:
    def test_update_replace_returns_204_and_replaces_property(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Original"], "category": ["a"]}, user)

        token = _make_token(user, "update")
        payload = {"action": "update", "url": entry.url, "replace": {"content": ["Updated"]}}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 204
        assert response.content == b""
        stored = shared_handler.get_entry(entry.url, user)
        assert stored is not None
        assert stored.properties["content"] == ["Updated"]
        assert stored.properties["category"] == ["a"]

    def test_update_add_returns_204_and_appends_value(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Original"], "category": ["a"]}, user)

        token = _make_token(user, "update")
        payload = {"action": "update", "url": entry.url, "add": {"category": ["b"]}}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 204
        stored = shared_handler.get_entry(entry.url, user)
        assert stored is not None
        assert stored.properties["category"] == ["a", "b"]

    def test_update_delete_property_list_removes_property(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Original"], "category": ["a"]}, user)

        token = _make_token(user, "update")
        payload = {"action": "update", "url": entry.url, "delete": ["category"]}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 204
        stored = shared_handler.get_entry(entry.url, user)
        assert stored is not None
        assert "category" not in stored.properties
        assert stored.properties["content"] == ["Original"]

    def test_update_delete_specific_values_removes_only_those_values(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Original"], "category": ["a", "b"]}, user)

        token = _make_token(user, "update")
        payload = {"action": "update", "url": entry.url, "delete": {"category": ["a"]}}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 204
        stored = shared_handler.get_entry(entry.url, user)
        assert stored is not None
        assert stored.properties["category"] == ["b"]

    def test_update_combined_replace_add_delete(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Original"], "category": ["a", "b"], "extra": ["keep"]}, user)

        token = _make_token(user, "update")
        payload = {
            "action": "update",
            "url": entry.url,
            "replace": {"content": ["Replaced"]},
            "add": {"category": ["c"]},
            "delete": ["extra"],
        }
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 204
        stored = shared_handler.get_entry(entry.url, user)
        assert stored is not None
        assert stored.properties["content"] == ["Replaced"]
        assert stored.properties["category"] == ["a", "b", "c"]
        assert "extra" not in stored.properties

    def test_update_unknown_url_returns_400_invalid_request(self, client, user, micropub_url, shared_handler):
        token = _make_token(user, "update")
        payload = {"action": "update", "url": "/entries/missing/", "replace": {"content": ["x"]}}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"

    def test_update_missing_url_returns_400_invalid_request(self, client, user, micropub_url, shared_handler):
        token = _make_token(user, "update")
        payload = {"action": "update", "replace": {"content": ["x"]}}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"

    def test_update_form_encoded_returns_400_invalid_request(self, client, user, micropub_url, shared_handler):
        """Form-encoded updates are not supported by the spec; the endpoint requires JSON for action=update."""
        entry = shared_handler.create_entry({"content": ["Original"]}, user)

        token = _make_token(user, "update")
        response = client.post(
            micropub_url,
            data={"action": "update", "url": entry.url, "replace": "content"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"

    @pytest.mark.parametrize(
        "operation",
        [
            {"replace": {"uid": ["client-supplied"]}},
            {"replace": {"author": [{"type": ["h-card"], "properties": {"name": ["Client"]}}]}},
            {"add": {"uid": ["client-supplied"]}},
            {"add": {"author": [{"type": ["h-card"], "properties": {"name": ["Client"]}}]}},
            {"delete": ["uid"]},
            {"delete": ["author"]},
            {"delete": {"uid": ["client-supplied"]}},
            {"delete": {"author": [{"type": ["h-card"], "properties": {"name": ["Client"]}}]}},
        ],
    )
    def test_update_rejects_server_managed_properties_before_handler(
        self, client, user, micropub_url, monkeypatch, operation
    ):
        """Update replace/add/delete cannot mutate server-managed properties."""
        handler_called = False

        def get_handler():
            nonlocal handler_called
            handler_called = True
            return InMemoryMicropubHandler()

        monkeypatch.setattr("indieweb.views.get_micropub_handler", get_handler)

        token = _make_token(user, "update")
        payload = {"action": "update", "url": "/entries/1/", **operation}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"
        assert handler_called is False


@pytest.mark.django_db
class TestMicropubDelete:
    def test_delete_form_returns_204_and_removes_entry(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Doomed"]}, user)

        token = _make_token(user, "delete")
        response = client.post(
            micropub_url,
            data={"action": "delete", "url": entry.url},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 204
        assert response.content == b""
        assert shared_handler.get_entry(entry.url, user) is None

    def test_delete_json_returns_204_and_removes_entry(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Doomed"]}, user)

        token = _make_token(user, "delete")
        payload = {"action": "delete", "url": entry.url}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 204
        assert shared_handler.get_entry(entry.url, user) is None

    def test_delete_unknown_url_returns_400_invalid_request(self, client, user, micropub_url, shared_handler):
        token = _make_token(user, "delete")
        response = client.post(
            micropub_url,
            data={"action": "delete", "url": "/entries/missing/"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"

    def test_delete_missing_url_returns_400_invalid_request(self, client, user, micropub_url, shared_handler):
        token = _make_token(user, "delete")
        response = client.post(
            micropub_url,
            data={"action": "delete"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
class TestMicropubUndelete:
    def test_undelete_form_returns_204_and_restores_entry(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Doomed"]}, user)
        shared_handler.delete_entry(entry.url, user)

        token = _make_token(user, "undelete")
        response = client.post(
            micropub_url,
            data={"action": "undelete", "url": entry.url},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 204
        assert response.content == b""
        restored = shared_handler.get_entry(entry.url, user)
        assert restored is not None
        assert restored.properties["content"] == ["Doomed"]

    def test_undelete_json_returns_204_and_restores_entry(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Doomed"]}, user)
        shared_handler.delete_entry(entry.url, user)

        token = _make_token(user, "undelete")
        payload = {"action": "undelete", "url": entry.url}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 204
        restored = shared_handler.get_entry(entry.url, user)
        assert restored is not None

    def test_undelete_url_not_in_deleted_set_returns_400_invalid_request(
        self, client, user, micropub_url, shared_handler
    ):
        # Create but do not delete; undelete must reject because nothing is in the deleted set.
        entry = shared_handler.create_entry({"content": ["Alive"]}, user)

        token = _make_token(user, "undelete")
        response = client.post(
            micropub_url,
            data={"action": "undelete", "url": entry.url},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"

    def test_undelete_missing_url_returns_400_invalid_request(self, client, user, micropub_url, shared_handler):
        token = _make_token(user, "undelete")
        response = client.post(
            micropub_url,
            data={"action": "undelete"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
class TestMicropubMalformedJsonBody:
    """A POST with Content-Type: application/json and a body that isn't a JSON object must
    be rejected before scope/action dispatch — otherwise a malformed update body could fall
    through to the create path and silently create an empty entry."""

    def test_malformed_json_with_create_scope_returns_400_not_201(self, client, user, micropub_url, shared_handler):
        token = _make_token(user, "create")
        response = client.post(
            micropub_url,
            data='{"action":"update",',
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"
        assert shared_handler.entries == {}

    def test_malformed_json_with_create_update_scope_returns_400(self, client, user, micropub_url, shared_handler):
        token = _make_token(user, "create update")
        response = client.post(
            micropub_url,
            data='{"action":"update",',
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"
        assert shared_handler.entries == {}

    def test_json_array_body_returns_400(self, client, user, micropub_url, shared_handler):
        token = _make_token(user, "create update")
        response = client.post(
            micropub_url,
            data="[1, 2, 3]",
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"

    def test_json_string_body_returns_400(self, client, user, micropub_url, shared_handler):
        token = _make_token(user, "create update")
        response = client.post(
            micropub_url,
            data='"just a string"',
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"

    def test_invalid_utf8_bytes_body_returns_400(self, client, user, micropub_url, shared_handler):
        """Invalid UTF-8 bytes in an application/json body must not escape as a 500.

        ``json.loads`` decodes bytes as UTF-8 internally and raises ``UnicodeDecodeError``
        (a ``ValueError`` subclass, but distinct from ``json.JSONDecodeError``) on invalid
        sequences such as ``b"\\xff"``. The endpoint must catch that path explicitly.
        """
        token = _make_token(user, "create update")
        response = client.post(
            micropub_url,
            data=b"\xff",
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"
        assert shared_handler.entries == {}


@pytest.mark.django_db
class TestMicropubUpdateBodyValidation:
    """Per Micropub §3.4, an update body MUST contain at least one of replace/add/delete and
    values inside operations MUST be arrays. Spec violations must be rejected by the view
    rather than papered over by the handler's normalization."""

    def test_update_with_no_operations_returns_400(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Original"]}, user)
        original_props = dict(entry.properties)

        token = _make_token(user, "update")
        payload = {"action": "update", "url": entry.url}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"
        # And the entry was not touched.
        assert shared_handler.get_entry(entry.url, user).properties == original_props

    def test_update_replace_with_scalar_value_returns_400(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Original"]}, user)

        token = _make_token(user, "update")
        payload = {"action": "update", "url": entry.url, "replace": {"content": "scalar"}}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"
        assert shared_handler.get_entry(entry.url, user).properties["content"] == ["Original"]

    def test_update_add_with_scalar_value_returns_400(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Original"], "category": ["a"]}, user)

        token = _make_token(user, "update")
        payload = {"action": "update", "url": entry.url, "add": {"category": "b"}}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"
        assert shared_handler.get_entry(entry.url, user).properties["category"] == ["a"]

    def test_update_replace_not_dict_returns_400(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Original"]}, user)

        token = _make_token(user, "update")
        payload = {"action": "update", "url": entry.url, "replace": ["content"]}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"

    def test_update_delete_scalar_returns_400(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Original"], "category": ["a"]}, user)

        token = _make_token(user, "update")
        payload = {"action": "update", "url": entry.url, "delete": "category"}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"
        assert shared_handler.get_entry(entry.url, user).properties["category"] == ["a"]

    def test_update_delete_dict_with_scalar_values_returns_400(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Original"], "category": ["a", "b"]}, user)

        token = _make_token(user, "update")
        payload = {"action": "update", "url": entry.url, "delete": {"category": "a"}}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"
        assert shared_handler.get_entry(entry.url, user).properties["category"] == ["a", "b"]

    def test_update_delete_list_with_non_string_returns_400(self, client, user, micropub_url, shared_handler):
        entry = shared_handler.create_entry({"content": ["Original"]}, user)

        token = _make_token(user, "update")
        payload = {"action": "update", "url": entry.url, "delete": [123]}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
class TestMicropubActionUnexpectedHandlerExceptions:
    """Unexpected handler exceptions (database failures, handler bugs) are server errors and must
    return ``500``, not ``400``. ``ValueError`` (entry not found) stays as ``400 invalid_request``."""

    def test_update_unexpected_exception_returns_500(self, client, user, micropub_url, monkeypatch):
        class BrokenHandler(InMemoryMicropubHandler):
            def update_entry(self, url, updates, user):
                raise RuntimeError("database is down")

        handler = BrokenHandler()
        handler.create_entry({"content": ["x"]}, user)
        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler)

        token = _make_token(user, "update")
        payload = {"action": "update", "url": "/entries/1/", "replace": {"content": ["new"]}}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 500

    def test_delete_unexpected_exception_returns_500(self, client, user, micropub_url, monkeypatch):
        class BrokenHandler(InMemoryMicropubHandler):
            def delete_entry(self, url, user):
                raise RuntimeError("database is down")

        handler = BrokenHandler()
        handler.create_entry({"content": ["x"]}, user)
        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler)

        token = _make_token(user, "delete")
        response = client.post(
            micropub_url,
            data={"action": "delete", "url": "/entries/1/"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 500

    def test_undelete_unexpected_exception_returns_500(self, client, user, micropub_url, monkeypatch):
        class BrokenHandler(InMemoryMicropubHandler):
            def undelete_entry(self, url, user):
                raise RuntimeError("database is down")

        handler = BrokenHandler()
        handler.create_entry({"content": ["x"]}, user)
        handler.delete_entry("/entries/1/", user)
        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler)

        token = _make_token(user, "undelete")
        response = client.post(
            micropub_url,
            data={"action": "undelete", "url": "/entries/1/"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 500


@pytest.mark.django_db
class TestMicropubActionRelocation:
    """When an action returns an entry whose URL differs from the submitted URL, surface 201 + Location."""

    def test_update_returning_new_url_returns_201_with_location(self, client, user, micropub_url, monkeypatch):
        class RelocatingHandler(InMemoryMicropubHandler):
            def update_entry(self, url, updates, user):
                from indieweb.handlers import MicropubEntry

                return MicropubEntry(url="/entries/relocated/", properties={"content": ["new"]})

        handler = RelocatingHandler()
        # Pre-seed an entry so the URL maps to something in the handler when listed (not strictly needed
        # since update_entry above ignores it, but keeps the model honest)
        handler.create_entry({"content": ["x"]}, user)
        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler)

        token = _make_token(user, "update")
        payload = {"action": "update", "url": "/entries/1/", "replace": {"content": ["new"]}}
        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 201
        assert "Location" in response
        assert response["Location"].endswith("/entries/relocated/")
