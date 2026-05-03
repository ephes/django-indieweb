"""Template tags for WebSub discovery."""

from django import template
from django.utils.html import format_html_join
from django.utils.safestring import SafeString

from indieweb.websub import build_websub_links

register = template.Library()


@register.simple_tag
def websub_link_tags(topic_url: str, *hubs: str) -> SafeString:
    """Return HTML ``link`` elements for WebSub hub and self discovery."""
    link_hubs = hubs or None
    links = build_websub_links(topic_url, link_hubs)
    return format_html_join("\n", '<link rel="{}" href="{}">', ((link.rel, link.url) for link in links))
