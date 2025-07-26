import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import TestCase

from indieweb.models import Profile

User = get_user_model()


@pytest.mark.django_db
class TestHCardTemplateTags(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com")
        self.profile = Profile.objects.create(
            user=self.user,
            name="Test User",
            photo_url="https://example.com/photo.jpg",
            url="https://example.com",
            h_card={
                "name": ["Test User"],
                "photo": ["https://example.com/photo.jpg"],
                "url": ["https://example.com", "https://social.example/@testuser"],
                "email": ["test@example.com"],
                "note": ["Software developer"],
                "nickname": ["testuser"],
            },
        )

    def test_h_card_tag_with_user(self):
        """Test h_card tag renders correctly with user object."""
        template = Template("{% load indieweb_tags %}{% h_card user %}")
        context = Context({"user": self.user})
        rendered = template.render(context)

        assert "h-card" in rendered
        assert "Test User" in rendered
        assert "https://example.com/photo.jpg" in rendered
        assert "p-name" in rendered
        assert "u-photo" in rendered

    def test_h_card_tag_with_profile(self):
        """Test h_card tag renders correctly with profile object."""
        template = Template("{% load indieweb_tags %}{% h_card profile %}")
        context = Context({"profile": self.profile})
        rendered = template.render(context)

        assert "h-card" in rendered
        assert "Test User" in rendered

    def test_h_card_tag_handles_missing_profile(self):
        """Test h_card tag handles users without profiles gracefully."""
        user_without_profile = User.objects.create_user(username="nocard")
        template = Template("{% load indieweb_tags %}{% h_card user %}")
        context = Context({"user": user_without_profile})
        rendered = template.render(context)

        assert "h-card" in rendered
        assert "nocard" in rendered  # Should show username as fallback

    def test_h_card_renders_multiple_urls(self):
        """Test that multiple URLs are rendered correctly."""
        template = Template("{% load indieweb_tags %}{% h_card user %}")
        context = Context({"user": self.user})
        rendered = template.render(context)

        assert "https://example.com" in rendered
        assert "https://social.example/@testuser" in rendered

    def test_h_card_renders_address(self):
        """Test address rendering in h-card."""
        self.profile.h_card["adr"] = [{"locality": "Portland", "region": "OR", "country_name": "USA"}]
        self.profile.save()

        template = Template("{% load indieweb_tags %}{% h_card user %}")
        context = Context({"user": self.user})
        rendered = template.render(context)

        assert "p-adr" in rendered
        assert "p-locality" in rendered
        assert "Portland" in rendered
