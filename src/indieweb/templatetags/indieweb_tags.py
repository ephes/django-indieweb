"""Template tags for IndieWeb functionality."""

from typing import Any

from django import template
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string

from indieweb.h_card import normalize_property_names
from indieweb.models import Profile

register = template.Library()
User = get_user_model()


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
