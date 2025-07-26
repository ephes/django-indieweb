import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from indieweb.models import Profile

User = get_user_model()


@pytest.mark.django_db
class TestProfileModel:
    def test_profile_creation(self):
        """Test basic profile creation with h-card data."""
        user = User.objects.create_user(username="testuser", email="test@example.com")
        profile = Profile.objects.create(
            user=user,
            name="Test User",
            photo_url="https://example.com/photo.jpg",
            url="https://example.com",
            h_card={
                "name": ["Test User"],
                "photo": ["https://example.com/photo.jpg"],
                "url": ["https://example.com"],
                "email": ["test@example.com"],
                "note": ["Test bio"],
            },
        )
        assert profile.user == user
        assert profile.name == "Test User"
        assert profile.h_card["name"] == ["Test User"]

    def test_profile_str_method(self):
        """Test string representation of profile."""
        user = User.objects.create_user(username="testuser")
        profile = Profile.objects.create(user=user, name="Test User")
        assert str(profile) == "Profile for testuser"

    def test_profile_with_nested_h_card_data(self):
        """Test profile with complex nested h-card data."""
        user = User.objects.create_user(username="testuser")
        profile = Profile.objects.create(
            user=user,
            h_card={
                "name": ["Jane Doe"],
                "adr": [{"locality": "Portland", "region": "OR", "country_name": "USA"}],
                "org": [{"name": "Example Corp", "url": "https://example.corp"}],
            },
        )
        assert profile.h_card["adr"][0]["locality"] == "Portland"
        assert profile.h_card["org"][0]["name"] == "Example Corp"

    def test_profile_unique_per_user(self):
        """Test that each user can only have one profile."""
        user = User.objects.create_user(username="testuser")
        Profile.objects.create(user=user)
        from django.core.exceptions import ValidationError

        with pytest.raises((IntegrityError, ValidationError)):
            Profile.objects.create(user=user)
