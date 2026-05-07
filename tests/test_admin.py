import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.urls import reverse

from indieweb.models import Auth, Token, Webmention

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def superuser():
    return User.objects.create_superuser(username="admin", email="admin@example.com", password="adminpass")


@pytest.fixture
def logged_admin_client(client, superuser):
    client.force_login(superuser)
    return client


@pytest.fixture
def webmention():
    return Webmention.objects.create(
        source_url="https://example.com/post1",
        target_url="https://mysite.com/post2",
        status="verified",
        mention_type="reply",
        author_name="Test Author",
        content="Great post!",
    )


@pytest.fixture
def token(superuser):
    return Token.objects.create(
        owner=superuser,
        client_id="https://client.example.com",
        me="https://mysite.com/",
        scope="create update",
    )


@pytest.fixture
def auth(superuser):
    return Auth.objects.create(
        owner=superuser,
        state="teststate123",
        client_id="https://client.example.com",
        redirect_uri="https://client.example.com/callback",
        me="https://mysite.com/",
    )


def test_webmention_admin_registered():
    """Test that Webmention model is registered in admin."""
    assert Webmention in admin.site._registry


def test_token_admin_registered():
    """Test that Token model is registered in admin."""
    assert Token in admin.site._registry


def test_auth_admin_registered():
    """Test that Auth model is registered in admin."""
    assert Auth in admin.site._registry


def test_webmention_changelist_view(logged_admin_client, webmention):
    """Test webmention changelist view loads correctly."""
    url = reverse("admin:indieweb_webmention_changelist")
    response = logged_admin_client.get(url)

    assert response.status_code == 200
    assert webmention.source_url in response.content.decode()


def test_webmention_list_display(logged_admin_client, webmention):
    """Test webmention list display columns."""
    url = reverse("admin:indieweb_webmention_changelist")
    response = logged_admin_client.get(url)
    content = response.content.decode()

    assert response.status_code == 200
    assert "Source url" in content
    assert "Target url" in content
    assert "Status" in content
    assert "Mention type" in content
    assert "Author name" in content


def test_webmention_filters():
    """Test webmention admin filters."""
    modeladmin = admin.site._registry[Webmention]

    assert "status" in modeladmin.list_filter
    assert "mention_type" in modeladmin.list_filter
    assert "created" in modeladmin.list_filter


def test_webmention_search(logged_admin_client, webmention):
    """Test webmention search functionality."""
    url = reverse("admin:indieweb_webmention_changelist")
    response = logged_admin_client.get(url, {"q": "example.com"})

    assert response.status_code == 200
    assert webmention.source_url in response.content.decode()


def test_webmention_detail_view(logged_admin_client, webmention):
    """Test webmention detail/change view."""
    url = reverse("admin:indieweb_webmention_change", args=[webmention.pk])
    response = logged_admin_client.get(url)

    assert response.status_code == 200
    assert webmention.source_url in response.content.decode()


def test_token_changelist_view(logged_admin_client, token):
    """Test token changelist view loads correctly."""
    url = reverse("admin:indieweb_token_changelist")
    response = logged_admin_client.get(url)

    assert response.status_code == 200
    assert token.client_id in response.content.decode()


def test_token_readonly_fields(token):
    """Test that token fields are read-only."""
    modeladmin = admin.site._registry[Token]
    readonly_fields = modeladmin.get_readonly_fields(None, token)

    # Most fields should be read-only for security
    expected_readonly = {"masked_key", "owner", "client_id", "me", "scope", "created", "modified"}
    assert expected_readonly.issubset(set(readonly_fields))


def test_token_admin_masks_key(token):
    """Test that token admin exposes only a masked key representation."""
    modeladmin = admin.site._registry[Token]
    raw_key = token.key
    token.refresh_from_db()

    assert modeladmin.masked_key(token) == "hmac-sha256$..."
    assert raw_key not in modeladmin.masked_key(token)


def test_token_no_add_permission():
    """Test that tokens cannot be added via admin."""
    modeladmin = admin.site._registry[Token]

    assert not modeladmin.has_add_permission(None)


def test_auth_changelist_view(logged_admin_client, auth):
    """Test auth changelist view loads correctly."""
    url = reverse("admin:indieweb_auth_changelist")
    response = logged_admin_client.get(url)

    assert response.status_code == 200
    assert auth.client_id in response.content.decode()


def test_auth_readonly_all_fields(auth):
    """Test that all auth fields are read-only."""
    modeladmin = admin.site._registry[Auth]
    readonly_fields = modeladmin.get_readonly_fields(None, auth)

    # All fields should be read-only
    model_fields = [f.name for f in Auth._meta.fields]
    assert set(readonly_fields) == set(model_fields)


def test_auth_admin_does_not_search_state():
    """Test that transient auth state is not part of admin search fields."""
    modeladmin = admin.site._registry[Auth]

    assert "state" not in modeladmin.search_fields


def test_auth_no_add_permission():
    """Test that auth records cannot be added via admin."""
    modeladmin = admin.site._registry[Auth]

    assert not modeladmin.has_add_permission(None)
