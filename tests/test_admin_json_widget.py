import json

import pytest
from django.contrib.auth import get_user_model

from indieweb.admin import ProfileAdminForm
from indieweb.models import Profile

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_superuser("admin", "admin@example.com", "password")


def test_json_widget_formats_data_correctly(user):
    """Test that the JSON widget formats h_card data for display."""
    h_card_data = {"name": ["Test User"], "url": ["https://example.com"], "email": ["test@example.com"]}

    profile = Profile.objects.create(user=user, name="Test User", h_card=h_card_data)

    form = ProfileAdminForm(instance=profile)

    # Check that the h_card field contains formatted JSON
    h_card_value = form.initial.get("h_card")
    assert h_card_value is not None

    # It should be a formatted JSON string
    assert isinstance(h_card_value, str)

    # Parse it back to verify it's valid JSON
    parsed = json.loads(h_card_value)
    assert parsed == h_card_data

    # Check that it's pretty-printed (has newlines and indentation)
    assert "\n" in h_card_value
    assert "  " in h_card_value  # indentation


def test_json_widget_handles_form_submission(user):
    """Test that the form correctly parses JSON input."""
    json_input = """{
  "name": ["New Name"],
  "photo": ["https://example.com/photo.jpg"],
  "url": ["https://example.com/new"]
}"""

    form_data = {"user": user.id, "name": "New Name", "h_card": json_input, "photo_url": "", "url": ""}

    form = ProfileAdminForm(data=form_data)
    assert form.is_valid(), form.errors

    # Check that clean_h_card returns a dict
    cleaned_h_card = form.cleaned_data["h_card"]
    assert isinstance(cleaned_h_card, dict)
    assert cleaned_h_card["name"] == ["New Name"]
    assert cleaned_h_card["photo"] == ["https://example.com/photo.jpg"]


def test_json_widget_handles_invalid_json(user):
    """Test that the form shows error for invalid JSON."""
    form_data = {"user": user.id, "name": "Test", "h_card": "{invalid json}", "photo_url": "", "url": ""}

    form = ProfileAdminForm(data=form_data)
    assert not form.is_valid()
    assert "h_card" in form.errors
    assert "Invalid JSON" in str(form.errors["h_card"])


def test_json_widget_handles_empty_input(user):
    """Test that empty JSON input is handled correctly."""
    form_data = {"user": user.id, "name": "Test", "h_card": "", "photo_url": "", "url": ""}

    form = ProfileAdminForm(data=form_data)
    assert form.is_valid()
    assert form.cleaned_data["h_card"] == {}


def test_json_widget_validates_h_card_structure(user):
    """Test that h-card structure validation works."""
    # Invalid h-card (properties not in lists)
    invalid_json = """{
  "name": "Should be in a list",
  "url": "https://example.com"
}"""

    form_data = {"user": user.id, "name": "Test", "h_card": invalid_json, "photo_url": "", "url": ""}

    form = ProfileAdminForm(data=form_data)
    assert not form.is_valid()
    assert "h_card" in form.errors
    assert "Invalid h-card structure" in str(form.errors["h_card"])
