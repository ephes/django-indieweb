"""Query identity must agree across source proof, content proof and classification."""

from html import escape

import httpx
import pytest

from indieweb.processors import WebmentionProcessor
from indieweb.webmention_parse_worker import analyze_source, content_html_digest

SOURCE = "https://source.example/post"
TARGET = "https://target.example/post?"

QUERY_CASES = [
    ("key=%FF", "key=%FE", False),
    ("%FF=value", "%FE=value", False),
    ("key=%C3", "key=%EF%BF%BD", False),
    ("key=%FF", "key=%FF", True),
    ("key=%FF&a=1", "a=1&key=%FF", False),
    ("key=caf%C3%A9", "key=café", True),
    ("a=1&a=2", "a=2&a=1", False),
    ("a=&a=2", "a=2&a=", False),
    ("=1&=2", "=2&=1", False),
    ("a=1&b=2&a=3", "b=2&a=1&a=3", True),
    ("a=1&a=1", "a=1", False),
    ("a=1%26b%3D2", "a=1&b=2", False),
    ("a=1&b=2", "b=2&a=1", True),
]


@pytest.mark.parametrize("linked,submitted,matches", QUERY_CASES)
def test_source_query_identity(linked, submitted, matches):
    html = f'<a href="{escape(TARGET + linked, quote=True)}">target</a>'
    assert analyze_source(html, SOURCE, TARGET + submitted)["links_to_target"] is matches


@pytest.mark.parametrize("linked,submitted,matches", QUERY_CASES)
def test_embedded_content_query_identity(linked, submitted, matches):
    # A separate exact link admits the document; embedded proof must still match.
    content = f'<a href="{escape(TARGET + linked, quote=True)}">target</a>'
    html = (
        f'<a href="{escape(TARGET + submitted, quote=True)}">proof</a>'
        f'<article class="h-entry"><div class="e-content">{content}</div></article>'
    )
    result = analyze_source(html, SOURCE, TARGET + submitted)
    assert result["links_to_target"] is True
    stored = result["parsed"]["items"][0]["properties"]["content"][0]["html"]
    assert (content_html_digest(stored) in result["linking_content"]) is matches


@pytest.mark.django_db
@pytest.mark.parametrize("linked,submitted,matches", QUERY_CASES)
def test_query_identity_mention_classification(linked, submitted, matches):
    html = (
        f'<a href="{escape(TARGET + submitted, quote=True)}">proof</a>'
        '<article class="h-entry">'
        f'<a class="u-in-reply-to" href="{escape(TARGET + linked, quote=True)}">reply</a>'
        '<div class="e-content">Synthetic response</div></article>'
    )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=html)
        )
    ) as client:
        mention = WebmentionProcessor(client=client).process_webmention(SOURCE, TARGET + submitted)
    assert mention.status == "verified"
    assert mention.mention_type == ("reply" if matches else "mention")
