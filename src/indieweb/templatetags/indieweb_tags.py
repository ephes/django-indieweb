"""Template tags for IndieWeb functionality."""

from typing import Any

from django import template
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string

from indieweb.h_card import normalize_property_names
from indieweb.models import Profile
from indieweb.sanitizers import sanitize_remote_webmention_url

register = template.Library()
User = get_user_model()


@register.filter(name="h_card_safe_url")
def h_card_safe_url(value: Any) -> str:
    """Return an absolute http(s) URL or an empty string.

    Defense-in-depth for h-card render: bypass paths (``bulk_update``,
    ``QuerySet.update``, raw SQL, fixtures) skip ``Profile.full_clean``, so the
    template still re-validates URL schemes before emitting ``href``/``src``.
    """
    if isinstance(value, dict) and "value" in value:
        value = value["value"]
    if not isinstance(value, str):
        return ""
    return sanitize_remote_webmention_url(value)


@register.filter(name="h_card_safe_urls")
def h_card_safe_urls(values: Any) -> list[str]:
    """Return a list of absolute http(s) URLs, dropping unsafe entries.

    Used in the bundled h-card template so that ``forloop.first`` keys off the
    first *emitted* safe URL rather than the first raw list item — preserves
    ``rel="me"`` on the first rendered profile link when an earlier raw entry
    was dropped by the sanitizer.
    """
    if not isinstance(values, (list, tuple)):
        return []
    safe: list[str] = []
    for value in values:
        candidate = h_card_safe_url(value)
        if candidate:
            safe.append(candidate)
    return safe


@register.simple_tag
def h_card(user_or_profile: Any, extra_classes: str | None = None) -> str:
    """
    Render an h-card for a user or profile.

    Usage:
        {% h_card user %}
        {% h_card profile %}
        {% h_card user "p-author" %}
    """
    if isinstance(user_or_profile, Profile):
        profile = user_or_profile
        user = profile.user
    elif isinstance(user_or_profile, User):
        user = user_or_profile
        try:
            profile = user.indieweb_profile
        except Profile.DoesNotExist:
            profile = None
    else:
        return ""

    # Normalize h_card data for template usage
    h_card_data = profile.h_card if profile else {}
    if h_card_data:
        h_card_data = normalize_property_names(h_card_data)

    # Render the template manually
    context = {"profile": profile, "user": user, "h_card": h_card_data, "extra_classes": extra_classes or ""}

    return render_to_string("indieweb/h-card.html", context)
