import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.urls import reverse

from indieweb.models import Profile

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
def user():
    return User.objects.create_user(username="testuser")


@pytest.fixture
def profile(user):
    return Profile.objects.create(user=user, name="Test User", h_card={"name": ["Test User"]})


def test_profile_admin_registered():
    """Test that Profile model is registered in admin."""
    assert Profile in admin.site._registry


def test_profile_changelist(logged_admin_client, profile):
    """Test profile changelist view."""
    url = reverse("admin:indieweb_profile_changelist")
    response = logged_admin_client.get(url)

    assert response.status_code == 200
    assert "Test User" in response.content.decode()


def test_profile_change_view(logged_admin_client, profile):
    """Test profile change view."""
    url = reverse("admin:indieweb_profile_change", args=[profile.pk])
    response = logged_admin_client.get(url)

    assert response.status_code == 200
    assert "Test User" in response.content.decode()


def test_profile_add_view(logged_admin_client):
    """Test profile add view."""
    url = reverse("admin:indieweb_profile_add")
    response = logged_admin_client.get(url)

    assert response.status_code == 200


def test_json_field_widget(logged_admin_client, profile):
    """Test that h_card field uses appropriate widget."""
    url = reverse("admin:indieweb_profile_change", args=[profile.pk])
    response = logged_admin_client.get(url)

    assert response.status_code == 200
    assert "h_card" in response.content.decode()
    # Should use JSONField widget for nice formatting
