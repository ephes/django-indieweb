"""H-card parsing, validation, and processing functions."""

from typing import Any

import mf2py


def normalize_property_names(data: dict[str, Any]) -> dict[str, Any]:
    """Convert hyphenated property names to underscores for Django templates."""
    normalized: dict[str, Any] = {}

    for key, value in data.items():
        # Convert hyphens to underscores
        new_key = key.replace("-", "_")

        if isinstance(value, list):
            new_value: list[Any] = []
            for item in value:
                if isinstance(item, dict):
                    # Recursively normalize nested objects
                    new_value.append(normalize_property_names(item))
                else:
                    new_value.append(item)
            normalized[new_key] = new_value
        elif isinstance(value, dict):
            normalized[new_key] = normalize_property_names(value)
        else:
            normalized[new_key] = value

    return normalized


def parse_h_card(html: str, url: str = "") -> dict[str, Any]:
    """Parse h-card from HTML content."""
    parsed = mf2py.parse(doc=html, url=url)

    # Find first h-card
    for item in parsed.get("items", []):
        if "h-card" in item.get("type", []):
            properties = item.get("properties", {})
            # Normalize property names for Django
            return normalize_property_names(dict(properties))

    return {}


def validate_h_card(h_card: dict[str, Any]) -> bool:
    """
    Validate h-card structure.

    All property values should be lists per microformats2 spec.
    """
    if not isinstance(h_card, dict):
        return False

    # Check that all values are lists
    for key, value in h_card.items():
        if not isinstance(value, list):
            return False

        # For nested objects like adr and org
        if key in ["adr", "org"]:
            for item in value:
                if not isinstance(item, dict):
                    return False

    return True


def normalize_h_card(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize h-card data to ensure all properties are lists and names are normalized."""
    # First normalize property names
    data = normalize_property_names(data)

    normalized = {}

    for key, value in data.items():
        if isinstance(value, list):
            # Already a list, but check if items need normalization
            normalized_list = []
            for item in value:
                if isinstance(item, dict) and key in ["adr", "org"]:
                    # These should contain dictionaries, recurse
                    normalized_list.append(normalize_property_names(item))
                else:
                    normalized_list.append(item)
            normalized[key] = normalized_list
        else:
            # Convert to list
            if isinstance(value, dict) and key in ["adr", "org"]:
                normalized[key] = [normalize_property_names(value)]
            else:
                normalized[key] = [value]

    return normalized
