"""Persisted h-card and quick-access values stay synchronized on partial saves."""

import pytest
from django.contrib.auth import get_user_model

from indieweb.models import Profile


@pytest.fixture
def profile(db):
    return Profile.objects.create(
        user=get_user_model().objects.create_user(username="synthetic-profile"),
        h_card={"name": ["Old"], "url": ["https://old.example/"], "photo": ["https://old.example/photo"]},
    )


@pytest.mark.parametrize(
    "key,field,value",
    [
        ("name", "name", "New"),
        ("url", "url", "https://new.example/"),
        ("photo", "photo_url", {"value": "https://new.example/photo"}),
    ],
)
def test_hcard_partial_save_persists_derived_fields(profile, key, field, value):
    profile.h_card[key] = [value]
    profile.save(update_fields=["h_card"])
    profile.refresh_from_db()
    assert getattr(profile, field) == (value["value"] if isinstance(value, dict) else value)


def test_unrelated_partial_save_does_not_publish_unsaved_hcard(profile):
    original = profile.h_card.copy()
    profile.h_card = {"name": ["Unsaved"], "url": ["https://unsaved.example/"]}
    profile.name = "Independent"
    profile.save(update_fields=["name"])
    profile.refresh_from_db()
    assert profile.name == "Independent"
    assert profile.url == "https://old.example/"
    assert profile.h_card == original


def test_empty_update_fields_is_noop_before_sync_and_validation(profile, django_assert_num_queries):
    profile.h_card = {"url": ["javascript:invalid"]}
    with django_assert_num_queries(0):
        profile.save(update_fields=[])
    assert profile.url == "https://old.example/"


@pytest.mark.parametrize("partial", [False, True])
def test_explicit_empty_arrays_clear_all_derived_fields(profile, partial):
    profile.h_card = {"name": [], "url": [], "photo": []}
    profile.save(**({"update_fields": ["h_card"]} if partial else {}))
    profile.refresh_from_db()
    assert (profile.name, profile.url, profile.photo_url) == ("", "", "")


@pytest.mark.parametrize("partial", [False, True])
def test_omitted_keys_preserve_independent_fields(profile, partial):
    profile.h_card = {"photo": [{"value": "https://new.example/photo"}]}
    profile.name = "Unsaved independent name" if partial else "Saved independent name"
    profile.save(**({"update_fields": ["h_card"]} if partial else {}))
    profile.refresh_from_db()
    assert profile.name == ("Old" if partial else "Saved independent name")
    assert profile.url == "https://old.example/"
    assert profile.photo_url == "https://new.example/photo"
