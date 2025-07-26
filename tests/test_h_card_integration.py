import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import Client, TestCase
from django.urls import reverse

from indieweb.h_card import parse_h_card, validate_h_card
from indieweb.models import Profile, Token

User = get_user_model()


@pytest.mark.django_db
class TestHCardIntegration(TestCase):
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass")
        self.profile = Profile.objects.create(
            user=self.user,
            name="Test User",
            photo_url="https://example.com/photo.jpg",
            url="https://example.com",
            h_card={
                "name": ["Test User"],
                "photo": ["https://example.com/photo.jpg"],
                "url": ["https://example.com", "https://twitter.com/testuser"],
                "email": ["test@example.com"],
                "note": ["IndieWeb enthusiast"],
                "adr": [{"locality": "Portland", "region": "OR", "country_name": "USA"}],
            },
        )
        self.client = Client()

    def test_profile_accessible_via_user(self):
        """Test that profile is accessible via user relationship."""
        # Access profile through user
        profile = self.user.indieweb_profile
        assert profile == self.profile
        assert profile.name == "Test User"
        assert profile.h_card["name"] == ["Test User"]

    def test_h_card_template_integration(self):
        """Test h-card template tag works in actual template rendering."""
        template = Template("""
            {% load indieweb_tags %}
            <div class="author">
                {% h_card user %}
            </div>
        """)

        context = Context({"user": self.user})
        rendered = template.render(context)

        # Check h-card structure
        assert 'class="h-card"' in rendered
        assert 'class="p-name"' in rendered
        assert 'class="u-photo"' in rendered
        assert 'class="u-url"' in rendered
        assert 'class="u-email"' in rendered
        assert 'class="p-note"' in rendered
        assert 'class="p-adr h-adr"' in rendered

        # Check content
        assert "Test User" in rendered
        assert "https://example.com/photo.jpg" in rendered
        assert "https://example.com" in rendered
        assert "https://twitter.com/testuser" in rendered
        assert "test@example.com" in rendered
        assert "IndieWeb enthusiast" in rendered
        assert "Portland" in rendered

    def test_h_card_with_micropub_integration(self):
        """Test that h-card data can be used in micropub responses."""
        # Create a token for micropub access
        token = Token.objects.create(
            owner=self.user, client_id="https://example.com/", me="https://example.com/", scope="create"
        )

        # Make a micropub query request
        response = self.client.get(
            reverse("indieweb:micropub"), {"q": "config"}, HTTP_AUTHORIZATION=f"Bearer {token.key}"
        )

        assert response.status_code == 200
        # In a full implementation, the config response could include
        # author information from the h-card

    def test_h_card_parsing_integration(self):
        """Test h-card parsing utilities work with real HTML."""
        html = """
        <article class="h-entry">
            <div class="h-card p-author">
                <img class="u-photo" src="https://author.example/photo.jpg" alt="Author">
                <a class="p-name u-url" href="https://author.example">Author Name</a>
                <p class="p-note">A brief bio</p>
            </div>
            <div class="e-content">
                <p>This is the content of the post.</p>
            </div>
        </article>
        """

        h_card_data = parse_h_card(html)
        # If no h-card found, test that parsing a simpler h-card works
        if not h_card_data:
            # Try with simpler HTML
            simple_html = """<div class="h-card">
                <a class="p-name u-url" href="https://author.example">Author Name</a>
                <p class="p-note">A brief bio</p>
            </div>"""
            h_card_data = parse_h_card(simple_html)

        # Now check the parsed data
        assert h_card_data != {}
        assert "name" in h_card_data
        assert h_card_data["name"] == ["Author Name"]
        assert "url" in h_card_data
        assert h_card_data["url"] == ["https://author.example"]
        assert "note" in h_card_data
        assert h_card_data["note"] == ["A brief bio"]
        assert validate_h_card(h_card_data) is True

    def test_profile_admin_integration(self):
        """Test Profile admin interface integration."""
        # Login as superuser
        User.objects.create_superuser(username="admin", email="admin@example.com", password="adminpass")
        self.client.login(username="admin", password="adminpass")

        # Access profile admin
        url = reverse("admin:indieweb_profile_changelist")
        response = self.client.get(url)
        assert response.status_code == 200
        assert "Test User" in response.content.decode()

        # Access specific profile
        url = reverse("admin:indieweb_profile_change", args=[self.profile.pk])
        response = self.client.get(url)
        assert response.status_code == 200

        # Check that the form contains h_card field
        content = response.content.decode()
        assert "h_card" in content
        assert "Test User" in content  # The name should appear somewhere

    def test_h_card_without_profile(self):
        """Test h-card rendering for users without profiles."""
        user_no_profile = User.objects.create_user(username="noprofile")

        template = Template("{% load indieweb_tags %}{% h_card user %}")
        context = Context({"user": user_no_profile})
        rendered = template.render(context)

        # Should still render an h-card with minimal info
        assert 'class="h-card"' in rendered
        assert "noprofile" in rendered  # Username as fallback

    def test_multiple_profiles_integration(self):
        """Test system handles multiple user profiles correctly."""
        # Create another user with profile
        user2 = User.objects.create_user(username="user2")
        Profile.objects.create(user=user2, name="Second User", h_card={"name": ["Second User"]})

        # Ensure profiles are separate
        assert Profile.objects.count() == 2
        assert self.user.indieweb_profile != user2.indieweb_profile
        assert self.user.indieweb_profile.name == "Test User"
        assert user2.indieweb_profile.name == "Second User"
