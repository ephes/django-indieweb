import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from indieweb.models import Profile

User = get_user_model()


@pytest.mark.django_db
class TestProfileAdmin(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="adminpass"
        )
        self.client.force_login(self.superuser)

        self.user = User.objects.create_user(username="testuser")
        self.profile = Profile.objects.create(user=self.user, name="Test User", h_card={"name": ["Test User"]})

    def test_profile_admin_registered(self):
        """Test that Profile model is registered in admin."""
        self.assertIn(Profile, admin.site._registry)

    def test_profile_changelist(self):
        """Test profile changelist view."""
        url = reverse("admin:indieweb_profile_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test User")

    def test_profile_change_view(self):
        """Test profile change view."""
        url = reverse("admin:indieweb_profile_change", args=[self.profile.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test User")

    def test_profile_add_view(self):
        """Test profile add view."""
        url = reverse("admin:indieweb_profile_add")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_json_field_widget(self):
        """Test that h_card field uses appropriate widget."""
        url = reverse("admin:indieweb_profile_change", args=[self.profile.pk])
        response = self.client.get(url)
        self.assertContains(response, "h_card")
        # Should use JSONField widget for nice formatting
