"""Template tags for displaying webmentions."""

from collections.abc import Sequence
from typing import Any, cast

from django import template
from django.db.models import Prefetch
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

from indieweb.models import Webmention, WebmentionNestedResponse
from indieweb.sanitizers import sanitize_remote_webmention_url, sanitize_webmention_html

register = template.Library()


def _nested_response_keys(nested_response: WebmentionNestedResponse) -> set[str]:
    """Return stable URL-like keys that can identify a nested response in display."""
    keys = {nested_response.identity}
    if nested_response.response_url:
        keys.add(nested_response.response_url)
    return keys


def _attach_displayable_nested_responses(
    webmentions: Sequence[Webmention],
    direct_source_urls: set[str],
) -> list[Webmention]:
    """Attach template-ready nested responses while suppressing duplicate renders."""
    displayed_child_identities: set[str] = set()
    prepared_webmentions = []

    for webmention in webmentions:
        displayable_nested_responses = []
        prefetched_children = getattr(webmention, "_verified_nested_responses", [])

        if webmention.mention_type == "reply":
            for nested_response in prefetched_children:
                if _nested_response_keys(nested_response) & direct_source_urls:
                    continue
                if nested_response.identity in displayed_child_identities:
                    continue

                displayed_child_identities.add(nested_response.identity)
                displayable_nested_responses.append(_prepare_nested_response_for_display(nested_response))

        cast(Any, webmention).displayable_nested_responses = displayable_nested_responses
        prepared_webmentions.append(webmention)

    return prepared_webmentions


def _prepare_nested_response_for_display(nested_response: WebmentionNestedResponse) -> WebmentionNestedResponse:
    """Sanitize remote child response fields before bundled templates render them.

    ``identity`` and ``response_url`` flow into the bundled
    ``nested_response.html`` template as the ``href`` of the response link
    (via ``firstof response_url identity as nested_response_url``). The
    ingestion path already validates these values, but a display-time
    sanitizer guards against latent bad rows and any future code path
    that bypasses ingestion validation, in line with the same defensive
    treatment applied to ``author_url`` / ``author_photo``.
    """
    nested_response.author_url = sanitize_remote_webmention_url(nested_response.author_url)
    nested_response.author_photo = sanitize_remote_webmention_url(nested_response.author_photo)
    nested_response.identity = sanitize_remote_webmention_url(nested_response.identity)
    nested_response.response_url = sanitize_remote_webmention_url(nested_response.response_url)
    nested_response.content_html = sanitize_webmention_html(nested_response.content_html)
    return nested_response


def _prepare_webmention_for_display(webmention: Webmention) -> Webmention:
    """Sanitize remote Webmention fields before bundled templates render them."""
    webmention.author_url = sanitize_remote_webmention_url(webmention.author_url)
    webmention.author_photo = sanitize_remote_webmention_url(webmention.author_photo)
    webmention.content_html = sanitize_webmention_html(webmention.content_html)
    return webmention


@register.simple_tag
def webmention_endpoint_link(endpoint_url: str | None = None) -> SafeString:
    """
    Return a link tag for the webmention endpoint.

    Usage:
        {% webmention_endpoint_link %}
        {% webmention_endpoint_link "https://custom.endpoint/webmention" %}

    The optional override is rejected unless it is an absolute HTTP(S) URL
    or a same-origin path. Non-conforming arguments fall back to the
    reversed indieweb webmention endpoint so a templating mistake cannot
    smuggle a ``javascript:`` or ``data:`` href into the rendered link.
    """
    if endpoint_url is None or not _is_safe_endpoint_link_argument(endpoint_url):
        endpoint_url = reverse("indieweb:webmention")

    return format_html('<link rel="webmention" href="{}" />', endpoint_url)


def _is_safe_endpoint_link_argument(value: object) -> bool:
    """Return whether ``value`` is a safe href for the bundled webmention link tag."""
    if not isinstance(value, str) or not value:
        return False
    if value.startswith("/") and not value.startswith("//"):
        # Same-origin absolute paths are always safe to render.
        return True
    from urllib.parse import urlparse

    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


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

    nested_responses = WebmentionNestedResponse.objects.filter(
        status="verified",
        webmention__status="verified",
    ).order_by(
        Coalesce("published", "first_seen_at").desc(),
        "-first_seen_at",
        "-created",
        "pk",
    )

    # Filter for verified webmentions
    webmentions = Webmention.objects.filter(target_url=target_url, status="verified").prefetch_related(
        Prefetch("nested_responses", queryset=nested_responses, to_attr="_verified_nested_responses")
    )

    if mention_type:
        webmentions = webmentions.filter(mention_type=mention_type)

    # Order by published date (newest first) or created if published is not set
    webmentions = webmentions.order_by("-published", "-created")
    webmention_list = [_prepare_webmention_for_display(webmention) for webmention in webmentions]

    if mention_type:
        direct_source_urls = set(
            Webmention.objects.filter(target_url=target_url, status="verified").values_list("source_url", flat=True)
        )
    else:
        direct_source_urls = {webmention.source_url for webmention in webmention_list}

    return {
        "webmentions": _attach_displayable_nested_responses(webmention_list, direct_source_urls),
        "target_url": target_url,
        "mention_type": mention_type,
    }


@register.simple_tag(takes_context=True)
def webmention_count(context: dict[str, Any], target_url: str, mention_type: str | None = None) -> int:
    """
    Get count of webmentions for a URL.

    Always returns an integer for consistent template comparisons.

    Usage:
        {% webmention_count target_url %}
        {% webmention_count target_url "reply" %}
        {% webmention_count target_url as count %}
    """
    if not target_url:
        return 0

    # Count only verified webmentions
    webmentions = Webmention.objects.filter(target_url=target_url, status="verified")

    if mention_type:
        webmentions = webmentions.filter(mention_type=mention_type)

    return webmentions.count()
