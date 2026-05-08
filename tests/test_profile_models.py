import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from indieweb.models import Profile

User = get_user_model()


@pytest.mark.django_db
class TestProfileHCardURLSchemes:
    @pytest.mark.parametrize(
        "scheme_value",
        [
            "ftp://example.com/file",
            "ftps://example.com/file",
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "file:///etc/passwd",
        ],
    )
    def test_h_card_url_field_rejects_non_http_schemes(self, scheme_value):
        user = User.objects.create_user(username="schemes-url")
        with pytest.raises(ValidationError):
            Profile.objects.create(user=user, h_card={"url": [scheme_value]})

    @pytest.mark.parametrize(
        "scheme_value",
        [
            "ftp://example.com/photo.jpg",
            "javascript:alert(1)",
            "data:image/svg+xml,<svg onload=alert(1)>",
        ],
    )
    def test_h_card_photo_rejects_non_http_schemes(self, scheme_value):
        user = User.objects.create_user(username="schemes-photo")
        with pytest.raises(ValidationError):
            Profile.objects.create(user=user, h_card={"photo": [scheme_value]})

    def test_h_card_org_url_rejects_non_http_schemes(self):
        user = User.objects.create_user(username="schemes-org")
        with pytest.raises(ValidationError):
            Profile.objects.create(
                user=user,
                h_card={"org": [{"name": "Example", "url": "ftp://example.com/"}]},
            )

    def test_profile_url_field_rejects_non_http_schemes(self):
        user = User.objects.create_user(username="schemes-quick-url")
        with pytest.raises(ValidationError):
            Profile.objects.create(user=user, url="ftp://example.com/")

    def test_profile_photo_url_field_rejects_non_http_schemes(self):
        user = User.objects.create_user(username="schemes-quick-photo")
        with pytest.raises(ValidationError):
            Profile.objects.create(user=user, photo_url="ftp://example.com/photo.jpg")

    def test_h_card_url_accepts_http_and_https(self):
        user = User.objects.create_user(username="schemes-ok")
        profile = Profile.objects.create(
            user=user,
            h_card={
                "url": ["http://example.com", "https://example.com"],
                "photo": ["https://example.com/photo.jpg"],
            },
        )
        assert profile.url == "http://example.com"


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
