"""H-card parsing, validation, and processing functions."""

from typing import Any

import mf2py
from django.core.exceptions import ValidationError

H_CARD_MAX_DEPTH = 32
H_CARD_MAX_NODES = 10_000


def normalize_property_names(data: dict[str, Any]) -> dict[str, Any]:
    """Copy and normalize names within a shared depth/node budget."""
    if not isinstance(data, dict):
        raise ValidationError("H-card properties must be a mapping", code="invalid_h_card")
    nodes = 0

    def normalize(value: Any, depth: int) -> Any:
        nonlocal nodes
        nodes += 1
        if depth > H_CARD_MAX_DEPTH or nodes > H_CARD_MAX_NODES:
            raise ValidationError("H-card exceeds normalization work limits", code="invalid_h_card")
        if isinstance(value, dict):
            normalized: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValidationError("H-card property names must be strings", code="invalid_h_card")
                new_key = key.replace("-", "_")
                if new_key in normalized:
                    raise ValidationError(
                        "H-card property name collision after normalization", code="property_name_collision"
                    )
                normalized[new_key] = normalize(item, depth + 1)
            return normalized
        if isinstance(value, list):
            return [normalize(item, depth + 1) for item in value]
        return value

    result: dict[str, Any] = normalize(data, 0)
    return result


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

    try:
        normalize_property_names(h_card)
        validate_h_card_properties(h_card)
    except ValidationError:
        return False

    return True


def validate_h_card_properties(h_card: dict[str, Any]) -> None:
    """Require list containers and supported items before deriving profile fields."""
    if not isinstance(h_card, dict):
        raise ValidationError("H-card properties must be a mapping", code="invalid_h_card")
    for key, value in h_card.items():
        if not isinstance(key, str):
            raise ValidationError("H-card property names must be strings", code="invalid_h_card")
        if not isinstance(value, list):
            raise ValidationError(f"H-card {key} must be a list", code="invalid_h_card")
        for item in value:
            valid = True
            if key in ("name", "url", "email"):
                valid = isinstance(item, str)
            elif key == "photo":
                valid = isinstance(item, str) or (
                    isinstance(item, dict)
                    and isinstance(item.get("value"), str)
                    and ("alt" not in item or isinstance(item["alt"], str))
                )
            elif key in ("adr", "org"):
                valid = isinstance(item, dict)
            if not valid:
                raise ValidationError(f"Unsupported item in h-card {key}", code="invalid_h_card")


def normalize_h_card(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize h-card data to ensure all properties are lists and names are normalized."""
    # First normalize property names
    data = normalize_property_names(data)

    normalized = {}

    for key, value in data.items():
        if isinstance(value, list):
            normalized[key] = value
        else:
            normalized[key] = [value]

    return normalized
