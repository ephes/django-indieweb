"""H-card parsing, validation, and processing functions."""

from typing import Any

import mf2py
from django.core.exceptions import ValidationError

H_CARD_MAX_DEPTH = 32
H_CARD_MAX_NODES = 10_000
H_CARD_MAX_BYTES = 262_144
H_CARD_MAX_HTML_BYTES = 1_048_576


def _text_byte_size(value: str, remaining: int) -> int:
    """Count UTF-8 bytes without encoding an unbounded string."""
    if len(value) > remaining:
        raise ValidationError("H-card exceeds byte limits", code="invalid_h_card")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValidationError("H-card contains invalid UTF-8 text", code="invalid_h_card") from exc
    if size > remaining:
        raise ValidationError("H-card exceeds byte limits", code="invalid_h_card")
    return size


def _admit_properties(data: dict[str, Any]) -> None:
    """Check the complete depth/node/byte envelope before copying or normalizing."""
    nodes = 0
    remaining = H_CARD_MAX_BYTES

    def visit(value: Any, depth: int) -> None:
        nonlocal nodes, remaining
        nodes += 1
        if depth > H_CARD_MAX_DEPTH or nodes > H_CARD_MAX_NODES:
            raise ValidationError("H-card exceeds normalization work limits", code="invalid_h_card")
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValidationError("H-card property names must be strings", code="invalid_h_card")
                remaining -= _text_byte_size(key, remaining)
                visit(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                visit(item, depth + 1)
        elif isinstance(value, str):
            remaining -= _text_byte_size(value, remaining)
        elif value is None or isinstance(value, bool | int | float):
            remaining -= _text_byte_size(_scalar_text(value), remaining)

    visit(data, 0)


def _scalar_text(value: bool | int | float | None) -> str:
    try:
        return str(value) if value is not None else "null"
    except ValueError as exc:
        raise ValidationError("H-card exceeds scalar limits", code="invalid_h_card") from exc


def normalize_property_names(data: dict[str, Any]) -> dict[str, Any]:
    """Admit the full resource envelope, then copy and normalize property names."""
    if not isinstance(data, dict):
        raise ValidationError("H-card properties must be a mapping", code="invalid_h_card")
    _admit_properties(data)

    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            normalized: dict[str, Any] = {}
            for key, item in value.items():
                new_key = key.replace("-", "_")
                if new_key in normalized:
                    raise ValidationError(
                        "H-card property name collision after normalization", code="property_name_collision"
                    )
                normalized[new_key] = normalize(item)
            return normalized
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value

    result: dict[str, Any] = normalize(data)
    return result


def parse_h_card(html: str, url: str = "") -> dict[str, Any]:
    """Admit raw HTML bytes before parsing and applying the property budgets."""
    _text_byte_size(html, H_CARD_MAX_HTML_BYTES)
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
