import pytest

from indieweb.h_card import normalize_h_card, normalize_property_names, parse_h_card, validate_h_card


def test_normalize_property_names_recurses_through_nested_data():
    """Test hyphenated h-card properties normalize in nested dicts and list items."""
    result = normalize_property_names(
        {
            "street-address": "123 Main St",
            "photo": [
                {"value": "https://example.com/photo.jpg", "alt-text": "Portrait"},
                "https://example.com/backup.jpg",
            ],
            "adr": [
                {
                    "country-name": "USA",
                    "geo": {"latitude-value": "45.5", "longitude-value": "-122.6"},
                    "labels": ["home", {"postal-code": "97201"}],
                }
            ],
        }
    )

    assert result == {
        "street_address": "123 Main St",
        "photo": [
            {"value": "https://example.com/photo.jpg", "alt_text": "Portrait"},
            "https://example.com/backup.jpg",
        ],
        "adr": [
            {
                "country_name": "USA",
                "geo": {"latitude_value": "45.5", "longitude_value": "-122.6"},
                "labels": ["home", {"postal_code": "97201"}],
            }
        ],
    }


def test_normalize_h_card_wraps_scalars_and_normalizes_nested_adr_org():
    """Test normalize_h_card converts scalar values to lists and normalizes nested h-card objects."""
    result = normalize_h_card(
        {
            "name": "Alice",
            "url": "https://example.com/alice",
            "adr": {"street-address": "123 Main St", "country-name": "USA"},
            "org": [{"organization-name": "Example Corp", "contact-info": {"postal-code": "97201"}}],
        }
    )

    assert result == {
        "name": ["Alice"],
        "url": ["https://example.com/alice"],
        "adr": [{"street_address": "123 Main St", "country_name": "USA"}],
        "org": [{"organization_name": "Example Corp", "contact_info": {"postal_code": "97201"}}],
    }


def test_normalize_h_card_wraps_non_adr_org_dict_values():
    """Test non-adr/org dictionaries are normalized and wrapped without flattening."""
    result = normalize_h_card({"geo": {"latitude-value": "45.5", "longitude-value": "-122.6"}})

    assert result == {"geo": [{"latitude_value": "45.5", "longitude_value": "-122.6"}]}


def test_parse_h_card_from_html():
    """Test parsing h-card from HTML."""
    html = """
    <div class="h-card">
        <img class="u-photo" src="https://example.com/photo.jpg" alt="Jane">
        <a class="p-name u-url" href="https://example.com">Jane Doe</a>
        <p class="p-note">Developer</p>
    </div>
    """
    result = parse_h_card(html)
    assert result["name"] == ["Jane Doe"]
    assert len(result["photo"]) == 1

    # Handle both string and object photo formats
    photo = result["photo"][0]
    if isinstance(photo, dict):
        assert photo["value"] == "https://example.com/photo.jpg"
    else:
        assert photo == "https://example.com/photo.jpg"

    assert result["url"] == ["https://example.com"]
    assert result["note"] == ["Developer"]


def test_parse_h_card_returns_empty_dict_when_no_h_card_is_found():
    """Test parser returns an empty dict when HTML has no top-level h-card."""
    assert parse_h_card("<article class='h-entry'><p class='p-name'>Entry</p></article>") == {}


def test_parse_h_card_returns_first_top_level_h_card():
    """Test parser returns the first top-level h-card item."""
    html = """
    <div class="h-card"><p class="p-name">First Person</p></div>
    <div class="h-card"><p class="p-name">Second Person</p></div>
    """

    assert parse_h_card(html) == {"name": ["First Person"]}


def test_parse_h_card_resolves_relative_urls_against_base_url():
    """Test parser passes the supplied base URL through to mf2py."""
    html = '<div class="h-card"><a class="p-name u-url" href="/alice">Alice</a></div>'

    result = parse_h_card(html, url="https://example.com/people/")

    assert result["name"] == ["Alice"]
    assert result["url"][0].startswith("https://example.com/")
    assert result["url"][0].endswith("/alice")


def test_parse_h_card_normalizes_nested_h_adr_property_names():
    """Test parser normalizes hyphenated property names in nested h-adr values."""
    html = """
    <div class="h-card">
        <p class="p-name">Alice</p>
        <div class="p-adr h-adr">
            <span class="p-street-address">123 Main St</span>
            <span class="p-country-name">USA</span>
        </div>
    </div>
    """

    result = parse_h_card(html)

    assert result["adr"][0]["type"] == ["h-adr"]
    assert result["adr"][0]["properties"] == {"street_address": ["123 Main St"], "country_name": ["USA"]}


def test_validate_h_card():
    """Test h-card validation."""
    valid_h_card = {"name": ["Test User"], "url": ["https://example.com"]}
    assert validate_h_card(valid_h_card) is True

    invalid_h_card = {
        "name": "Not a list"  # Should be a list
    }
    assert validate_h_card(invalid_h_card) is False


def test_validate_h_card_accepts_valid_nested_adr_and_org_items():
    """Test adr and org properties accept dictionary list items."""
    h_card = {"adr": [{"locality": "Portland"}], "org": [{"name": "Example Corp"}]}

    assert validate_h_card(h_card) is True


@pytest.mark.parametrize("h_card", [None, [], "not a dict"])
def test_validate_h_card_rejects_non_dict_input(h_card):
    """Test validator rejects non-dict top-level input."""
    assert validate_h_card(h_card) is False


@pytest.mark.parametrize(
    "h_card",
    [
        {"adr": ["Portland, OR"]},
        {"org": ["Example Corp"]},
        {"adr": [{"locality": "Portland"}, "Portland, OR"]},
        {"org": [{"name": "Example Corp"}, "Example Corp"]},
    ],
)
def test_validate_h_card_rejects_non_dict_adr_and_org_items(h_card):
    """Test adr and org list items must be dictionaries."""
    assert validate_h_card(h_card) is False
