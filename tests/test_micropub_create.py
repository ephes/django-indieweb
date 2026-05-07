#!/usr/bin/env python

"""
test_micropub_create
--------------------

Tests for Micropub content creation functionality.
"""

import json
from urllib.parse import urlparse

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from indieweb import models
from indieweb.handlers import InMemoryMicropubHandler


@pytest.fixture
def user(db):
    return User.objects.create_user(username="testuser", email="test@example.org", password="password")


@pytest.fixture
def token(user):
    return models.Token.objects.create(
        me="https://example.org", client_id="https://client.example.org", scope="post", owner=user
    )


@pytest.fixture
def micropub_url():
    return reverse("indieweb:micropub")


class TestMicropubCreate:
    """Test Micropub content creation."""

    @pytest.mark.django_db
    def test_create_simple_note(self, client, token, micropub_url):
        """Test creating a simple note with form-encoded data."""
        auth_header = f"Bearer {token.key}"
        data = {
            "h": "entry",
            "content": "Hello, IndieWeb!",
        }

        response = client.post(micropub_url, data=data, Authorization=auth_header)

        assert response.status_code == 201
        assert "Location" in response
        location = response["Location"]
        assert location.startswith("http")
        assert "/entries/" in location

    @pytest.mark.django_db
    def test_create_note_with_categories(self, client, token, micropub_url):
        """Test creating a note with categories."""
        auth_header = f"Bearer {token.key}"
        data = {
            "h": "entry",
            "content": "A categorized post",
            "category": "indieweb,micropub,test",
        }

        response = client.post(micropub_url, data=data, Authorization=auth_header)

        assert response.status_code == 201
        assert "Location" in response

    @pytest.mark.django_db
    def test_create_article(self, client, token, micropub_url):
        """Test creating an article with name and content."""
        auth_header = f"Bearer {token.key}"
        data = {
            "h": "entry",
            "name": "My First Article",
            "content": "This is the content of my article.",
            "category": "articles,indieweb",
        }

        response = client.post(micropub_url, data=data, Authorization=auth_header)

        assert response.status_code == 201
        assert "Location" in response

    @pytest.mark.django_db
    def test_create_with_json_simple(self, client, token, micropub_url):
        """Test creating content with simple JSON format."""
        auth_header = f"Bearer {token.key}"
        data = {
            "type": "h-entry",
            "properties": {
                "content": ["Hello from JSON!"],
                "category": ["json", "test"],
            },
        }

        response = client.post(
            micropub_url, data=json.dumps(data), content_type="application/json", Authorization=auth_header
        )

        assert response.status_code == 201
        assert "Location" in response

    @pytest.mark.django_db
    def test_create_with_json_flat(self, client, token, micropub_url):
        """Test creating content with flat JSON format."""
        auth_header = f"Bearer {token.key}"
        data = {
            "content": "Flat JSON content",
            "name": "Flat JSON Post",
            "category": ["json", "flat"],
        }

        response = client.post(
            micropub_url, data=json.dumps(data), content_type="application/json", Authorization=auth_header
        )

        assert response.status_code == 201
        assert "Location" in response

    @pytest.mark.django_db
    def test_location_header_format(self, client, token, micropub_url):
        """Test that Location header returns absolute URL."""
        auth_header = f"Bearer {token.key}"
        data = {
            "h": "entry",
            "content": "Testing location header",
        }

        response = client.post(micropub_url, data=data, Authorization=auth_header)

        assert response.status_code == 201
        location = response["Location"]
        parsed = urlparse(location)
        assert parsed.scheme in ["http", "https"]
        assert parsed.netloc != ""
        assert parsed.path != ""

    @pytest.mark.django_db
    def test_create_with_location(self, client, token, micropub_url):
        """Test creating a post with location data."""
        auth_header = f"Bearer {token.key}"
        data = {
            "h": "entry",
            "content": "Posted from San Francisco!",
            "location": "geo:37.786971,-122.399677",
        }

        response = client.post(micropub_url, data=data, Authorization=auth_header)

        assert response.status_code == 201

    @pytest.mark.django_db
    def test_create_reply(self, client, token, micropub_url):
        """Test creating a reply post."""
        auth_header = f"Bearer {token.key}"
        data = {
            "h": "entry",
            "content": "Great post!",
            "in-reply-to": "https://example.com/some-post",
        }

        response = client.post(micropub_url, data=data, Authorization=auth_header)

        assert response.status_code == 201

    @pytest.mark.django_db
    def test_create_with_photo_url(self, client, token, micropub_url):
        """Test creating a post with photo URL."""
        auth_header = f"Bearer {token.key}"
        data = {
            "h": "entry",
            "content": "Check out this photo!",
            "photo": "https://example.com/photo.jpg",
        }

        response = client.post(micropub_url, data=data, Authorization=auth_header)

        assert response.status_code == 201

    @pytest.mark.django_db
    def test_handler_receives_photo_url_property(self, client, token, micropub_url, monkeypatch):
        """Test that URL-valued photo properties are still forwarded unchanged."""
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())
        auth_header = f"Bearer {token.key}"
        data = {
            "h": "entry",
            "content": "Check out this photo!",
            "photo": "https://example.com/photo.jpg",
        }

        response = client.post(micropub_url, data=data, Authorization=auth_header)

        assert response.status_code == 201
        assert received_properties is not None
        assert received_properties["photo"] == ["https://example.com/photo.jpg"]

    @pytest.mark.django_db
    def test_query_config(self, client, token, micropub_url):
        """Test querying Micropub configuration."""
        auth_header = f"Bearer {token.key}"

        response = client.get(f"{micropub_url}?q=config", Authorization=auth_header)

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"

        config = json.loads(response.content)
        assert "post-types" in config
        assert isinstance(config["post-types"], list)
        assert config["post-types"] == [
            {"type": "note", "name": "Note", "properties": ["content"]},
            {"type": "article", "name": "Article", "properties": ["name", "content"]},
            {"type": "photo", "name": "Photo", "properties": ["photo", "content", "category"]},
            {"type": "audio", "name": "Audio", "properties": ["audio", "content", "category"]},
            {"type": "video", "name": "Video", "properties": ["video", "content", "category"]},
            {"type": "reply", "name": "Reply", "properties": ["in-reply-to", "content"]},
            {"type": "bookmark", "name": "Bookmark", "properties": ["bookmark-of", "name", "content"]},
            {"type": "like", "name": "Like", "properties": ["like-of"]},
            {"type": "repost", "name": "Repost", "properties": ["repost-of"]},
            {
                "type": "event",
                "name": "Event",
                "properties": [
                    "name",
                    "summary",
                    "description",
                    "start",
                    "end",
                    "location",
                    "category",
                    "url",
                    "published",
                ],
            },
            {"type": "rsvp", "name": "RSVP", "properties": ["rsvp", "in-reply-to", "name", "content"]},
        ]

    @pytest.mark.django_db
    def test_query_syndicate_to(self, client, token, micropub_url):
        """Test querying syndication targets."""
        auth_header = f"Bearer {token.key}"

        response = client.get(f"{micropub_url}?q=syndicate-to", Authorization=auth_header)

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"

        data = json.loads(response.content)
        assert "syndicate-to" in data
        assert isinstance(data["syndicate-to"], list)

    @pytest.mark.django_db
    def test_missing_scope(self, client, user, micropub_url):
        """Test that a token without create/post scope returns 403."""
        # Create token without the create scope or legacy post alias
        token = models.Token.objects.create(
            me="https://example.org", client_id="https://client.example.org", scope="read", owner=user
        )

        auth_header = f"Bearer {token.key}"
        data = {
            "h": "entry",
            "content": "Should fail",
        }

        response = client.post(micropub_url, data=data, Authorization=auth_header)

        assert response.status_code == 403

    @pytest.mark.django_db
    def test_handler_receives_normalized_properties(self, client, token, micropub_url, monkeypatch):
        """Test that handler receives properly normalized properties."""
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        # Monkey patch the handler getter
        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())

        auth_header = f"Bearer {token.key}"
        data = {
            "h": "entry",
            "content": "Test content",
            "category": "test,micropub",
        }

        response = client.post(micropub_url, data=data, Authorization=auth_header)

        assert response.status_code == 201
        assert received_properties is not None
        assert "content" in received_properties
        assert isinstance(received_properties["content"], list)
        assert received_properties["content"] == ["Test content"]
        assert "category" in received_properties
        assert isinstance(received_properties["category"], list)
        assert received_properties["category"] == ["test", "micropub"]

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("payload", "expected_properties"),
        [
            (
                {"h": "entry", "bookmark-of": "https://example.com/bookmarked", "name": "Worth reading"},
                {"bookmark-of": ["https://example.com/bookmarked"], "name": ["Worth reading"]},
            ),
            ({"h": "entry", "like-of": "https://example.com/liked"}, {"like-of": ["https://example.com/liked"]}),
            (
                {"h": "entry", "repost-of": "https://example.com/reposted"},
                {"repost-of": ["https://example.com/reposted"]},
            ),
            (
                {"h": "entry", "audio": "https://example.com/audio.mp3", "video": "https://example.com/video.mp4"},
                {"audio": ["https://example.com/audio.mp3"], "video": ["https://example.com/video.mp4"]},
            ),
        ],
    )
    def test_form_create_forwards_additional_post_type_properties(
        self, client, token, micropub_url, monkeypatch, payload, expected_properties
    ):
        """Test that form-encoded create forwards advertised post-type properties."""
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())

        response = client.post(micropub_url, data=payload, Authorization=f"Bearer {token.key}")

        assert response.status_code == 201
        assert received_properties is not None
        for property_name, values in expected_properties.items():
            assert received_properties[property_name] == values

    @pytest.mark.django_db
    def test_form_create_forwards_array_media_properties(self, client, token, micropub_url, monkeypatch):
        """Test that array notation works for URL-valued media properties."""
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())

        response = client.post(
            micropub_url,
            data={
                "h": "entry",
                "audio[]": ["https://example.com/one.mp3", "https://example.com/two.mp3"],
                "video[]": ["https://example.com/one.mp4", "https://example.com/two.mp4"],
            },
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 201
        assert received_properties is not None
        assert received_properties["audio"] == ["https://example.com/one.mp3", "https://example.com/two.mp3"]
        assert received_properties["video"] == ["https://example.com/one.mp4", "https://example.com/two.mp4"]

    @pytest.mark.django_db
    def test_form_create_forwards_single_command_properties(self, client, token, micropub_url, monkeypatch):
        """Test that single-value command properties are forwarded as arrays without execution."""
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())

        response = client.post(
            micropub_url,
            data={
                "h": "entry",
                "content": "Publish later",
                "photo": "https://example.com/photo.jpg",
                "mp-slug": "my-suggested-slug",
                "mp-channel": "notes",
                "mp-photo-alt": "A text alternative",
                "mp-syndicate-to": "https://social.example/@user",
                "post-status": "draft",
            },
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 201
        assert received_properties == {
            "content": ["Publish later"],
            "photo": ["https://example.com/photo.jpg"],
            "mp-slug": ["my-suggested-slug"],
            "mp-channel": ["notes"],
            "mp-photo-alt": ["A text alternative"],
            "mp-syndicate-to": ["https://social.example/@user"],
            "post-status": ["draft"],
        }
        assert "slug" not in received_properties
        assert "channel" not in received_properties
        assert "syndication" not in received_properties

    @pytest.mark.django_db
    def test_form_create_sanitizes_mp_slug_before_handler(self, client, token, micropub_url, monkeypatch):
        """Path separators, controls, and leading dots are stripped from submitted slug hints."""
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())

        response = client.post(
            micropub_url,
            data={"h": "entry", "content": "Slug test", "mp-slug": "../bad/path\x1fname"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 201
        assert received_properties is not None
        assert received_properties["mp-slug"] == ["badpathname"]

    @pytest.mark.django_db
    def test_form_create_omits_empty_sanitized_mp_slug(self, client, token, micropub_url, monkeypatch):
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())

        response = client.post(
            micropub_url,
            data={"h": "entry", "content": "Slug test", "mp-slug": "../\x1f"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 201
        assert received_properties is not None
        assert "mp-slug" not in received_properties

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "property_name",
        ["photo", "audio", "video", "in-reply-to", "like-of", "repost-of", "bookmark-of", "syndication"],
    )
    def test_form_create_rejects_invalid_url_properties_before_handler(
        self, client, token, micropub_url, monkeypatch, property_name
    ):
        create_called = False

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal create_called
                create_called = True
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())

        response = client.post(
            micropub_url,
            data={"h": "entry", "content": "Bad URL", property_name: "javascript:alert(1)"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content == b"invalid_request"
        assert create_called is False

    @pytest.mark.django_db
    def test_form_create_forwards_valid_url_properties(self, client, token, micropub_url, monkeypatch):
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())
        payload = {
            "h": "entry",
            "photo": "https://media.example/photo.jpg",
            "audio": "https://media.example/audio.mp3",
            "video": "https://media.example/video.mp4",
            "in-reply-to": "https://example.com/reply",
            "like-of": "https://example.com/liked",
            "repost-of": "https://example.com/reposted",
            "bookmark-of": "https://example.com/bookmarked",
            "syndication": "https://social.example/post/1",
        }

        response = client.post(micropub_url, data=payload, Authorization=f"Bearer {token.key}")

        assert response.status_code == 201
        assert received_properties == {key: [value] for key, value in payload.items() if key != "h"}

    @pytest.mark.django_db
    def test_form_create_forwards_array_command_properties(self, client, token, micropub_url, monkeypatch):
        """Test that array notation works for list-shaped command properties."""
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())

        response = client.post(
            micropub_url,
            data={
                "h": "entry",
                "mp-channel[]": ["notes", "articles"],
                "mp-photo-alt[]": ["First alt", "Second alt"],
                "mp-syndicate-to[]": ["https://social.example/@user", "https://news.example/list"],
            },
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 201
        assert received_properties == {
            "mp-channel": ["notes", "articles"],
            "mp-photo-alt": ["First alt", "Second alt"],
            "mp-syndicate-to": ["https://social.example/@user", "https://news.example/list"],
        }

    @pytest.mark.django_db
    def test_json_create_preserves_additional_post_type_properties(self, client, token, micropub_url, monkeypatch):
        """Test that JSON create keeps the additional h-entry properties unchanged."""
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())
        payload = {
            "type": ["h-entry"],
            "properties": {
                "bookmark-of": ["https://example.com/bookmarked"],
                "like-of": ["https://example.com/liked"],
                "repost-of": ["https://example.com/reposted"],
            },
        }

        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 201
        assert received_properties == payload["properties"]

    @pytest.mark.django_db
    def test_json_create_preserves_command_properties_and_post_status(self, client, token, micropub_url, monkeypatch):
        """Test that Microformats2 JSON command properties remain handler-owned."""
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())
        payload = {
            "type": ["h-entry"],
            "properties": {
                "content": ["Publish later"],
                "photo": ["https://example.com/photo.jpg"],
                "mp-slug": ["my-suggested-slug"],
                "mp-channel": ["notes"],
                "mp-photo-alt": ["A text alternative"],
                "mp-syndicate-to": ["https://social.example/@user"],
                "post-status": ["draft"],
            },
        }

        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 201
        assert received_properties == payload["properties"]
        assert "slug" not in received_properties
        assert "channel" not in received_properties
        assert "syndication" not in received_properties

    @pytest.mark.django_db
    def test_json_create_accepts_content_type_with_charset(self, client, token, micropub_url, monkeypatch):
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())
        payload = {"type": ["h-entry"], "properties": {"content": ["JSON charset"]}}

        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json; charset=utf-8",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 201
        assert received_properties == payload["properties"]

    @pytest.mark.django_db
    def test_json_create_sanitizes_mp_slug_before_handler(self, client, token, micropub_url, monkeypatch):
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())
        payload = {"type": ["h-entry"], "properties": {"content": ["Slug"], "mp-slug": ["../bad\\path"]}}

        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 201
        assert received_properties is not None
        assert received_properties["mp-slug"] == ["badpath"]

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "property_name",
        ["photo", "audio", "video", "in-reply-to", "like-of", "repost-of", "bookmark-of", "syndication"],
    )
    def test_json_create_rejects_invalid_url_properties_before_handler(
        self, client, token, micropub_url, monkeypatch, property_name
    ):
        create_called = False

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal create_called
                create_called = True
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())
        payload = {"type": ["h-entry"], "properties": {property_name: ["notaurl"]}}

        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content == b"invalid_request"
        assert create_called is False

    @pytest.mark.django_db
    def test_json_create_preserves_empty_url_property_arrays(self, client, token, micropub_url, monkeypatch):
        """Empty Microformats2 arrays remain valid; only submitted URL values are validated."""
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())
        payload = {
            "type": ["h-entry"],
            "properties": {
                "content": ["No photo yet"],
                "photo": [],
            },
        }

        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 201
        assert received_properties == payload["properties"]

    @pytest.mark.django_db
    @pytest.mark.parametrize("property_name", ["uid", "author"])
    def test_json_create_rejects_server_managed_properties(
        self, client, token, micropub_url, monkeypatch, property_name
    ):
        """JSON create must not let clients submit properties owned by the server."""
        create_called = False

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal create_called
                create_called = True
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())
        payload = {
            "type": ["h-entry"],
            "properties": {
                "content": ["Client content"],
                property_name: ["client-supplied"],
            },
        }

        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content == b"invalid_request"
        assert create_called is False

    @pytest.mark.django_db
    def test_json_flat_create_rejects_server_managed_property(self, client, token, micropub_url, monkeypatch):
        """The simple JSON create shape gets the same server-managed property gate."""
        create_called = False

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal create_called
                create_called = True
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())
        payload = {"content": "Client content", "uid": "client-supplied"}

        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content == b"invalid_request"
        assert create_called is False

    @pytest.mark.django_db
    @pytest.mark.parametrize("property_name", ["uid", "author", "uid[]", "author[]"])
    def test_form_create_rejects_server_managed_properties(
        self, client, token, micropub_url, monkeypatch, property_name
    ):
        """Form creates cannot bypass the server-managed property deny-list."""
        create_called = False

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal create_called
                create_called = True
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())

        response = client.post(
            micropub_url,
            data={"h": "entry", "content": "Client content", property_name: "client-supplied"},
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 400
        assert response.content == b"invalid_request"
        assert create_called is False

    @pytest.mark.django_db
    def test_form_create_forwards_event_properties(self, client, token, micropub_url, monkeypatch):
        """Test that form-encoded h-event fields are forwarded as property arrays."""
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())

        response = client.post(
            micropub_url,
            data={
                "h": "event",
                "name": "IndieWeb Meetup",
                "summary": "Monthly meetup",
                "description": "Talks and demos",
                "start": "2026-06-01T18:00:00+02:00",
                "end": "2026-06-01T20:00:00+02:00",
                "location": "https://example.org/venue",
                "category": "indieweb,events",
                "url": "https://example.org/events/meetup",
                "published": "2026-05-03T12:00:00+02:00",
                "content": "Bring questions.",
            },
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 201
        assert received_properties == {
            "content": ["Bring questions."],
            "name": ["IndieWeb Meetup"],
            "summary": ["Monthly meetup"],
            "description": ["Talks and demos"],
            "category": ["indieweb", "events"],
            "location": ["https://example.org/venue"],
            "start": ["2026-06-01T18:00:00+02:00"],
            "end": ["2026-06-01T20:00:00+02:00"],
            "url": ["https://example.org/events/meetup"],
            "published": ["2026-05-03T12:00:00+02:00"],
        }

    @pytest.mark.django_db
    def test_form_create_forwards_rsvp_properties(self, client, token, micropub_url, monkeypatch):
        """Test that form-encoded RSVP fields are forwarded as property arrays."""
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())

        response = client.post(
            micropub_url,
            data={
                "h": "entry",
                "rsvp": "yes",
                "in-reply-to": "https://events.example.org/meetup",
                "name": "RSVP to IndieWeb Meetup",
                "content": "I will be there.",
                "category": "events,indieweb",
                "published": "2026-05-03T12:00:00+02:00",
            },
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 201
        assert received_properties == {
            "content": ["I will be there."],
            "name": ["RSVP to IndieWeb Meetup"],
            "category": ["events", "indieweb"],
            "in-reply-to": ["https://events.example.org/meetup"],
            "rsvp": ["yes"],
            "published": ["2026-05-03T12:00:00+02:00"],
        }

    @pytest.mark.django_db
    def test_json_create_preserves_h_event_payload(self, client, token, micropub_url, monkeypatch):
        """Test that JSON h-event create keeps properties untouched for the handler."""
        received_properties = None

        class TestHandler(InMemoryMicropubHandler):
            def create_entry(self, properties, user):
                nonlocal received_properties
                received_properties = properties
                return super().create_entry(properties, user)

        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: TestHandler())
        payload = {
            "type": ["h-event"],
            "properties": {
                "name": ["IndieWeb Meetup"],
                "start": ["2026-06-01T18:00:00+02:00"],
                "location": [{"type": ["h-card"], "properties": {"name": ["Venue"]}}],
            },
        }

        response = client.post(
            micropub_url,
            data=json.dumps(payload),
            content_type="application/json",
            Authorization=f"Bearer {token.key}",
        )

        assert response.status_code == 201
        assert received_properties == payload["properties"]


class TestInMemoryHandler:
    """Test the in-memory Micropub handler."""

    def test_create_entry(self):
        """Test creating an entry with the in-memory handler."""
        handler = InMemoryMicropubHandler()
        user = None  # In-memory handler doesn't use user

        properties = {
            "content": ["Hello, world!"],
            "category": ["test", "hello"],
        }

        entry = handler.create_entry(properties, user)

        assert entry.url == "/entries/1/"
        assert entry.properties == properties
        assert entry.type == ["h-entry"]

    def test_get_entry(self):
        """Test retrieving an entry."""
        handler = InMemoryMicropubHandler()
        user = None

        # Create an entry
        properties = {"content": ["Test"]}
        entry = handler.create_entry(properties, user)

        # Retrieve it
        retrieved = handler.get_entry(entry.url, user)

        assert retrieved is not None
        assert retrieved.url == entry.url
        assert retrieved.properties == properties

    def test_update_entry_replace(self):
        """Test updating an entry with replace operation."""
        handler = InMemoryMicropubHandler()
        user = None

        # Create an entry
        properties = {
            "content": ["Original content"],
            "category": ["original"],
        }
        entry = handler.create_entry(properties, user)

        # Update it
        updates = {
            "replace": {
                "content": ["Updated content"],
            }
        }
        updated = handler.update_entry(entry.url, updates, user)

        assert updated.properties["content"] == ["Updated content"]
        assert updated.properties["category"] == ["original"]  # Unchanged

    def test_update_entry_add(self):
        """Test updating an entry with add operation."""
        handler = InMemoryMicropubHandler()
        user = None

        # Create an entry
        properties = {
            "content": ["Original content"],
            "category": ["original"],
        }
        entry = handler.create_entry(properties, user)

        # Update it
        updates = {
            "add": {
                "category": ["new-tag"],
            }
        }
        updated = handler.update_entry(entry.url, updates, user)

        assert updated.properties["category"] == ["original", "new-tag"]

    def test_delete_and_undelete(self):
        """Test deleting and undeleting entries."""
        handler = InMemoryMicropubHandler()
        user = None

        # Create an entry
        properties = {"content": ["Test"]}
        entry = handler.create_entry(properties, user)
        url = entry.url

        # Delete it
        handler.delete_entry(url, user)
        assert handler.get_entry(url, user) is None

        # Undelete it
        restored = handler.undelete_entry(url, user)
        assert restored.url == url
        assert handler.get_entry(url, user) is not None

    def test_entry_helper_methods(self):
        """Test MicropubEntry helper methods."""
        handler = InMemoryMicropubHandler()
        user = None

        properties = {
            "content": ["First content", "Second content"],
            "name": ["Test Post"],
            "category": ["tag1", "tag2", "tag3"],
        }
        entry = handler.create_entry(properties, user)

        # Test get_property (returns first value)
        assert entry.get_property("content") == "First content"
        assert entry.get_property("name") == "Test Post"
        assert entry.get_property("missing") is None
        assert entry.get_property("missing", "default") == "default"

        # Test get_properties (returns all values)
        assert entry.get_properties("content") == ["First content", "Second content"]
        assert entry.get_properties("category") == ["tag1", "tag2", "tag3"]
        assert entry.get_properties("missing") == []
