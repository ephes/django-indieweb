"""Test h_card template tag with extra_classes parameter."""

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import TestCase

from indieweb.models import Profile

User = get_user_model()


class HCardExtraClassesTest(TestCase):
    """Test the h_card template tag with extra classes."""

    def setUp(self):
        """Set up test user and profile."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
        )
        self.profile = Profile.objects.create(
            user=self.user,
            name="Test User",
            url="https://example.com/testuser",
            photo_url="https://example.com/photo.jpg",
        )

    def test_h_card_without_extra_classes(self):
        """Test h_card renders without extra classes."""
        template = Template("{% load indieweb_tags %}{% h_card user %}")
        html = template.render(Context({"user": self.user}))
        self.assertIn('class="h-card"', html)
        self.assertNotIn("p-author", html)

    def test_h_card_with_p_author_class(self):
        """Test h_card renders with p-author class."""
        template = Template('{% load indieweb_tags %}{% h_card user "p-author" %}')
        html = template.render(Context({"user": self.user}))
        self.assertIn('class="h-card p-author"', html)

    def test_h_card_with_multiple_extra_classes(self):
        """Test h_card renders with multiple extra classes."""
        template = Template('{% load indieweb_tags %}{% h_card user "p-author custom-class" %}')
        html = template.render(Context({"user": self.user}))
        self.assertIn('class="h-card p-author custom-class"', html)

    def test_h_card_profile_with_extra_classes(self):
        """Test h_card with profile object and extra classes."""
        template = Template('{% load indieweb_tags %}{% h_card profile "p-author" %}')
        html = template.render(Context({"profile": self.profile}))
        self.assertIn('class="h-card p-author"', html)
        self.assertIn("Test User", html)
        self.assertIn("https://example.com/testuser", html)
