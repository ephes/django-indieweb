"""Synthetic h-card shape admission precedes derived fields and database writes."""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from indieweb.h_card import validate_h_card
from indieweb.models import Profile


@pytest.fixture
def profile(db):
    return Profile.objects.create(
        user=get_user_model().objects.create_user(username="shape-profile"),
        h_card={"name": ["Original"], "url": ["https://person.example/"]},
    )


@pytest.mark.parametrize("field", ["name", "photo", "url", "email"])
@pytest.mark.parametrize("value", [7, True, None, "scalar", {}, {"value": "mapping"}, [7], [None], [{}], [["nested"]]])
@pytest.mark.parametrize("operation", ["clean", "save", "partial"])
def test_malformed_profile_property_is_field_scoped_and_never_written(profile, field, value, operation):
    original = Profile.objects.values().get(pk=profile.pk)
    profile.h_card = {"name": ["Replacement"], field: value}
    with pytest.raises(ValidationError) as caught:
        if operation == "clean":
            profile.full_clean()
        else:
            profile.save(**({"update_fields": ["h_card"]} if operation == "partial" else {}))
    assert "h_card" in caught.value.error_dict
    assert Profile.objects.values().get(pk=profile.pk) == original
    assert profile.name == "Original"
    assert not validate_h_card(profile.h_card)


@pytest.mark.parametrize("value", [{"value": 7}, {"value": []}, {"value": "https://photo.example/", "alt": 7}])
def test_malformed_structured_photo_is_rejected(profile, value):
    profile.h_card = {"photo": [value]}
    with pytest.raises(ValidationError) as caught:
        profile.save()
    assert "h_card" in caught.value.error_dict
    assert not validate_h_card(profile.h_card)


@pytest.mark.parametrize("field", ["extension", "adr", "org"])
def test_all_profile_properties_require_lists(profile, field):
    profile.h_card = {field: {"name": "Synthetic"}}
    with pytest.raises(ValidationError) as caught:
        profile.save()
    assert "h_card" in caught.value.error_dict


@pytest.mark.parametrize("field", ["adr", "org"])
def test_nested_profile_properties_require_mappings(profile, field):
    profile.h_card = {field: [7]}
    with pytest.raises(ValidationError) as caught:
        profile.save()
    assert "h_card" in caught.value.error_dict


@pytest.mark.parametrize("field,value", [("url", "invalid"), ("photo", "invalid"), ("email", "invalid")])
def test_invalid_profile_values_are_field_scoped(profile, field, value):
    profile.h_card = {field: [value]}
    with pytest.raises(ValidationError) as caught:
        profile.save()
    assert "h_card" in caught.value.error_dict


def test_supported_shapes_preserve_data_and_derive_fields(profile):
    data = {
        "name": ["Synthetic Person"],
        "url": ["https://person.example/"],
        "photo": [{"value": "https://photo.example/", "alt": "Portrait"}],
        "email": ["person@example.com"],
        "org": [{"name": "Organization", "url": "https://org.example/"}],
        "adr": [{"street-address": "Invented Street"}],
        "extension": [{"custom-key": ["value"]}],
    }
    profile.h_card = data
    profile.save(update_fields=["h_card"])
    profile.refresh_from_db()
    assert profile.h_card == data
    assert (profile.name, profile.url, profile.photo_url) == (
        "Synthetic Person",
        "https://person.example/",
        "https://photo.example/",
    )
    assert validate_h_card(data)
