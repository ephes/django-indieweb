"""Normalization work is bounded for model input and bypass-written legacy rows."""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from indieweb.h_card import normalize_h_card, normalize_property_names, parse_h_card, validate_h_card
from indieweb.models import Profile
from indieweb.templatetags.indieweb_tags import h_card


def nested_card(depth):
    data = {"custom-key": ["Synthetic"]}
    for _ in range(depth):
        data = {"extension": [data]}
    return data


@pytest.fixture(params=["deep", "wide", "nested_lists"])
def oversized_card(request):
    if request.param == "deep":
        return nested_card(1500)
    if request.param == "wide":
        return {"extension": ["Synthetic"] * 10001}
    data = "Synthetic"
    for _ in range(1500):
        data = [data]
    return {"extension": data}


@pytest.mark.parametrize("normalize", [normalize_property_names, normalize_h_card])
def test_normalization_rejects_exhausted_work_budget(normalize, oversized_card):
    with pytest.raises(ValidationError) as caught:
        normalize(oversized_card)
    assert caught.value.code == "invalid_h_card"


def test_boolean_validator_refuses_oversized_cards(oversized_card):
    assert not validate_h_card(oversized_card)


@pytest.mark.parametrize("operation", ["clean", "save"])
@pytest.mark.django_db
def test_profile_budget_precedes_json_field_serialization(oversized_card, operation):
    profile = Profile(user=get_user_model().objects.create_user(username="budget-profile"), h_card=oversized_card)
    with pytest.raises(ValidationError) as caught:
        profile.full_clean() if operation == "clean" else profile.save()
    assert caught.value.error_dict["h_card"][0].code == "invalid_h_card"
    assert not Profile.objects.filter(user=profile.user).exists()


@pytest.mark.parametrize("data", [nested_card(100), {"extension": ["Synthetic"] * 10001}])
@pytest.mark.django_db
def test_legacy_oversized_card_renders_empty(data):
    profile = Profile.objects.create(user=get_user_model().objects.create_user(username="legacy-budget"))
    Profile.objects.filter(pk=profile.pk).update(h_card=data)
    profile.refresh_from_db()
    assert h_card(profile) == ""


def test_parser_budget_applies_to_extracted_properties(monkeypatch):
    monkeypatch.setattr(
        "indieweb.h_card.mf2py.parse",
        lambda **kwargs: {"items": [{"type": ["h-card"], "properties": nested_card(100)}]},
    )
    with pytest.raises(ValidationError) as caught:
        parse_h_card("<div class='h-card'></div>")
    assert caught.value.code == "invalid_h_card"


def test_ordinary_nested_card_is_preserved():
    data = {"adr": [{"street-address": "Invented Street"}], "org": [{"contact-info": {"postal-code": "12345"}}]}
    assert normalize_property_names(data) == {
        "adr": [{"street_address": "Invented Street"}],
        "org": [{"contact_info": {"postal_code": "12345"}}],
    }
    assert validate_h_card(data)


@pytest.mark.parametrize("key", [7, None])
def test_non_string_property_names_raise_validation_error(key):
    with pytest.raises(ValidationError) as caught:
        normalize_property_names({"extension": [{key: ["Synthetic"]}]})
    assert caught.value.code == "invalid_h_card"


def test_node_budget_is_shared_across_siblings():
    data = {"first": ["Synthetic"] * 6000, "second": ["Synthetic"] * 6000}
    with pytest.raises(ValidationError) as caught:
        normalize_property_names(data)
    assert caught.value.code == "invalid_h_card"


def test_exact_node_budget_is_admitted():
    # Root mapping + property list + 9,998 scalar items = 10,000 nodes.
    data = {"extension": ["Synthetic"] * 9998}
    assert normalize_property_names(data) == data
    data["extension"].append("One too many")
    with pytest.raises(ValidationError, match="work limits"):
        normalize_property_names(data)


def test_exact_depth_budget_is_admitted():
    data = "Synthetic"
    for _ in range(32):
        data = {"custom_key": data}
    assert normalize_property_names(data) == data
    with pytest.raises(ValidationError, match="work limits"):
        normalize_property_names({"custom_key": data})


def test_cyclic_in_memory_input_is_refused():
    data = {}
    data["extension"] = [data]
    with pytest.raises(ValidationError) as caught:
        normalize_property_names(data)
    assert caught.value.code == "invalid_h_card"
