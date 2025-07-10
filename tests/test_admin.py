import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from indieweb.models import Auth, Token, Webmention

User = get_user_model()


@pytest.mark.django_db
class TestAdminRegistration(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="adminpass"
        )
        self.client.force_login(self.superuser)

    def test_webmention_admin_registered(self):
        """Test that Webmention model is registered in admin."""
        self.assertIn(Webmention, admin.site._registry)

    def test_token_admin_registered(self):
        """Test that Token model is registered in admin."""
        self.assertIn(Token, admin.site._registry)

    def test_auth_admin_registered(self):
        """Test that Auth model is registered in admin."""
        self.assertIn(Auth, admin.site._registry)


@pytest.mark.django_db
class TestWebmentionAdmin(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="adminpass"
        )
        self.client.force_login(self.superuser)

        # Create test webmention
        self.webmention = Webmention.objects.create(
            source_url="https://example.com/post1",
            target_url="https://mysite.com/post2",
            status="verified",
            mention_type="reply",
            author_name="Test Author",
            content="Great post!",
        )

    def test_webmention_changelist_view(self):
        """Test webmention changelist view loads correctly."""
        url = reverse("admin:indieweb_webmention_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://example.com/post1")

    def test_webmention_list_display(self):
        """Test webmention list display columns."""
        url = reverse("admin:indieweb_webmention_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Check for expected columns
        self.assertContains(response, "Source url")
        self.assertContains(response, "Target url")
        self.assertContains(response, "Status")
        self.assertContains(response, "Mention type")
        self.assertContains(response, "Author name")

    def test_webmention_filters(self):
        """Test webmention admin filters."""
        modeladmin = admin.site._registry[Webmention]
        self.assertIn("status", modeladmin.list_filter)
        self.assertIn("mention_type", modeladmin.list_filter)
        self.assertIn("created", modeladmin.list_filter)

    def test_webmention_search(self):
        """Test webmention search functionality."""
        url = reverse("admin:indieweb_webmention_changelist")
        response = self.client.get(url, {"q": "example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://example.com/post1")

    def test_webmention_detail_view(self):
        """Test webmention detail/change view."""
        url = reverse("admin:indieweb_webmention_change", args=[self.webmention.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://example.com/post1")


@pytest.mark.django_db
class TestTokenAdmin(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="adminpass"
        )
        self.client.force_login(self.superuser)

        # Create test token
        self.token = Token.objects.create(
            owner=self.superuser,
            client_id="https://client.example.com",
            me="https://mysite.com/",
            scope="create update",
        )

    def test_token_changelist_view(self):
        """Test token changelist view loads correctly."""
        url = reverse("admin:indieweb_token_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://client.example.com")

    def test_token_readonly_fields(self):
        """Test that token fields are read-only."""
        modeladmin = admin.site._registry[Token]
        readonly_fields = modeladmin.get_readonly_fields(None, self.token)

        # Most fields should be read-only for security
        expected_readonly = {"key", "owner", "client_id", "me", "scope", "created", "modified"}
        self.assertTrue(expected_readonly.issubset(set(readonly_fields)))

    def test_token_no_add_permission(self):
        """Test that tokens cannot be added via admin."""
        modeladmin = admin.site._registry[Token]
        self.assertFalse(modeladmin.has_add_permission(None))


@pytest.mark.django_db
class TestAuthAdmin(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="adminpass"
        )
        self.client.force_login(self.superuser)

        # Create test auth
        self.auth = Auth.objects.create(
            owner=self.superuser,
            state="teststate123",
            client_id="https://client.example.com",
            redirect_uri="https://client.example.com/callback",
            me="https://mysite.com/",
        )

    def test_auth_changelist_view(self):
        """Test auth changelist view loads correctly."""
        url = reverse("admin:indieweb_auth_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://client.example.com")

    def test_auth_readonly_all_fields(self):
        """Test that all auth fields are read-only."""
        modeladmin = admin.site._registry[Auth]
        readonly_fields = modeladmin.get_readonly_fields(None, self.auth)

        # All fields should be read-only
        model_fields = [f.name for f in Auth._meta.fields]
        self.assertEqual(set(readonly_fields), set(model_fields))

    def test_auth_no_add_permission(self):
        """Test that auth records cannot be added via admin."""
        modeladmin = admin.site._registry[Auth]
        self.assertFalse(modeladmin.has_add_permission(None))
