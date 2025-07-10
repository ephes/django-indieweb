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
    def test_query_config(self, client, token, micropub_url):
        """Test querying Micropub configuration."""
        auth_header = f"Bearer {token.key}"

        response = client.get(f"{micropub_url}?q=config", Authorization=auth_header)

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"

        config = json.loads(response.content)
        assert "post-types" in config
        assert isinstance(config["post-types"], list)
        assert len(config["post-types"]) > 0

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
        """Test that missing 'post' scope returns 403."""
        # Create token without 'post' scope
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
