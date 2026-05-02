"""Test h_card template tag with extra_classes parameter."""

import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template

from indieweb.models import Profile

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    """Create a test user with profile data for h-card rendering."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
    )


@pytest.fixture
def profile(user):
    """Create profile data for h-card rendering."""
    return Profile.objects.create(
        user=user,
        name="Test User",
        url="https://example.com/testuser",
        photo_url="https://example.com/photo.jpg",
    )


def test_h_card_without_extra_classes(user, profile):
    """Test h_card renders without extra classes."""
    template = Template("{% load indieweb_tags %}{% h_card user %}")
    html = template.render(Context({"user": user}))

    assert 'class="h-card"' in html
    assert "p-author" not in html


def test_h_card_with_p_author_class(user, profile):
    """Test h_card renders with p-author class."""
    template = Template('{% load indieweb_tags %}{% h_card user "p-author" %}')
    html = template.render(Context({"user": user}))

    assert 'class="h-card p-author"' in html


def test_h_card_with_multiple_extra_classes(user, profile):
    """Test h_card renders with multiple extra classes."""
    template = Template('{% load indieweb_tags %}{% h_card user "p-author custom-class" %}')
    html = template.render(Context({"user": user}))

    assert 'class="h-card p-author custom-class"' in html


def test_h_card_profile_with_extra_classes(profile):
    """Test h_card with profile object and extra classes."""
    template = Template('{% load indieweb_tags %}{% h_card profile "p-author" %}')
    html = template.render(Context({"profile": profile}))

    assert 'class="h-card p-author"' in html
    assert "Test User" in html
    assert "https://example.com/testuser" in html
