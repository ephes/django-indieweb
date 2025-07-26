from indieweb.h_card import parse_h_card, validate_h_card


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


def test_validate_h_card():
    """Test h-card validation."""
    valid_h_card = {"name": ["Test User"], "url": ["https://example.com"]}
    assert validate_h_card(valid_h_card) is True

    invalid_h_card = {
        "name": "Not a list"  # Should be a list
    }
    assert validate_h_card(invalid_h_card) is False
