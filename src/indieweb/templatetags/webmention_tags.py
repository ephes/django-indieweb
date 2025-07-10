"""Template tags for displaying webmentions."""

from typing import Any

from django import template
from django.urls import reverse
from django.utils.safestring import SafeString, mark_safe

from indieweb.models import Webmention

register = template.Library()


@register.simple_tag
def webmention_endpoint_link(endpoint_url: str | None = None) -> SafeString:
    """
    Return a link tag for the webmention endpoint.

    Usage:
        {% webmention_endpoint_link %}
        {% webmention_endpoint_link "https://custom.endpoint/webmention" %}
    """
    if endpoint_url is None:
        endpoint_url = reverse("indieweb:webmention")

    link_tag = f'<link rel="webmention" href="{endpoint_url}" />'
    return mark_safe(link_tag)


@register.inclusion_tag("indieweb/webmentions.html")
def show_webmentions(target_url: str, mention_type: str | None = None) -> dict[str, Any]:
    """
    Display webmentions for a given URL.

    Usage:
        {% show_webmentions target_url %}
        {% show_webmentions target_url "like" %}
    """
    if not target_url:
        return {"webmentions": [], "target_url": target_url}

    # Filter for verified webmentions
    webmentions = Webmention.objects.filter(target_url=target_url, status="verified")

    if mention_type:
        webmentions = webmentions.filter(mention_type=mention_type)

    # Order by published date (newest first) or created if published is not set
    webmentions = webmentions.order_by("-published", "-created")

    return {"webmentions": webmentions, "target_url": target_url, "mention_type": mention_type}


@register.simple_tag
def webmention_count(target_url: str, mention_type: str | None = None, as_var: str | None = None) -> str | int:
    """
    Get count of webmentions for a URL.

    Usage:
        {% webmention_count target_url %}
        {% webmention_count target_url "reply" %}
        {% webmention_count target_url as count %}
    """
    if not target_url:
        count = 0
    else:
        # Count only verified webmentions
        webmentions = Webmention.objects.filter(target_url=target_url, status="verified")

        if mention_type:
            webmentions = webmentions.filter(mention_type=mention_type)

        count = webmentions.count()

    if as_var:
        return count

    return str(count)
