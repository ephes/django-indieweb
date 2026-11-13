"""Template tags for displaying webmentions."""

from collections.abc import Mapping, Sequence
from typing import Any, cast

from django import template
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

    # All direct sources participate in suppression, even for a type-filtered
    # render. Load them and their children in the same SQL statement so a
    # concurrent moderation commit cannot mix read generations.
    all_webmentions = _display_webmention_snapshot(target_url)
    direct_source_urls = {row.source_url for row in all_webmentions}
    webmentions = [
        _prepare_webmention_for_display(row)
        for row in all_webmentions
        if not mention_type or row.mention_type == mention_type
    ]
    return {
        "webmentions": _attach_displayable_nested_responses(webmentions, direct_source_urls),
        "target_url": target_url,
        "mention_type": mention_type,
    }


def _display_webmention_snapshot(target_url: str) -> list[Webmention]:
    """Materialize parents and children from one portable joined SELECT.

    SQL collation equality is only a candidate filter. Exact URL, status and
    type identity is decided in Python before display preparation. Large
    ingestion-only payloads stay deferred on the returned model instances.
    """
    parent_deferred = {
        "spam_check_result",
        "status_token",
        "vouch_url",
        "verified_at",
        "vouch_verified_at",
        "last_received_at",
    }
    parent_fields = [
        field.attname for field in Webmention._meta.concrete_fields if field.attname not in parent_deferred
    ]
    child_fields = [
        field.attname
        for field in WebmentionNestedResponse._meta.concrete_fields
        if field.attname not in {"parsed_h_entry", "content_digest"}
    ]
    rows = (
        Webmention.objects.filter(target_url=target_url, status="verified")
        .order_by(
            "-published",
            "-created",
            "pk",
            Coalesce("nested_responses__published", "nested_responses__first_seen_at").desc(),
            "-nested_responses__first_seen_at",
            "-nested_responses__created",
            "nested_responses__pk",
        )
        .values(*parent_fields, *(f"nested_responses__{field}" for field in child_fields))
    )
    parents: dict[int, Webmention] = {}
    for row in rows:
        if row["target_url"] != target_url or row["status"] != "verified":
            continue
        parent = parents.get(row["id"])
        if parent is None:
            parent = Webmention.from_db(rows.db, parent_fields, [row[field] for field in parent_fields])
            cast(Any, parent)._verified_nested_responses = []
            parents[parent.pk] = parent
        if row["nested_responses__id"] is not None and row["nested_responses__status"] == "verified":
            child = WebmentionNestedResponse.from_db(
                rows.db, child_fields, [row[f"nested_responses__{field}"] for field in child_fields]
            )
            cast(Any, parent)._verified_nested_responses.append(child)
    return list(parents.values())


@register.simple_tag
def prepare_webmention_counts(target_urls: Sequence[str]) -> dict[str, dict[str, int]]:
    """Count exact URL/type strings for one page; assign as ``webmention_counts``."""
    counts: dict[str, dict[str, int]] = {url: {} for url in target_urls if url}
    if counts:
        rows = (
            Webmention.objects.filter(target_url__in=counts, status="verified")
            .order_by()
            .values_list("target_url", "mention_type", "status")
            .iterator()
        )
        # SQL is only a candidate filter: collations may equate distinct URLs,
        # types or statuses. Never group or compare these strings in the DB.
        for url, kind, status in rows:
            if url in counts and status == "verified":
                by_type = counts[url]
                by_type[kind] = by_type.get(kind, 0) + 1
    return counts


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

    counts = context.get("webmention_counts")
    if isinstance(counts, Mapping):
        by_type = counts.get(target_url)
        if isinstance(by_type, Mapping) and all(type(value) is int for value in by_type.values()):
            typed_counts = cast(Mapping[str, int], by_type)
            return typed_counts.get(mention_type, 0) if mention_type else sum(typed_counts.values())

    by_type = prepare_webmention_counts([target_url])[target_url]
    return by_type.get(mention_type, 0) if mention_type else sum(by_type.values())
