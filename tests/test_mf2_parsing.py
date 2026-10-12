"""Bounded microformats parsing and linear link verification for fetched HTML."""

import json
import time

import httpx
import mf2py
import pytest
from django.test import override_settings

from indieweb import mf2_parsing
from indieweb.h_card import parse_h_card
from indieweb.models import Webmention
from indieweb.processors import WebmentionProcessor, _html_links_to_source_domain, _html_links_to_target

SOURCE_URL = "https://example.com/post"
TARGET_URL = "https://mysite.com/article"
MIB = 1024 * 1024


def nested_embedded_document(depth, payload_bytes):
    return (
        f'<article class="h-entry"><a class="u-in-reply-to" href="{TARGET_URL}">re</a>'
        + '<span class="e-content">' * depth
        + "A" * payload_bytes
        + "</span>" * depth
        + '<a class="p-author h-card" href="https://example.com/">Author</a></article>'
    )


def serialized_size(parsed):
    return len(json.dumps(parsed))


def test_ordinary_document_parses_like_mf2py():
    html = (
        '<article class="h-entry"><h1 class="p-name">Title</h1>'
        '<div class="e-content"><p>Hello <b>world</b></p>'
        '<blockquote class="h-cite"><a class="u-url p-name" href="/cited">Cited</a></blockquote></div>'
        '<a class="p-author h-card" href="https://example.com/">Author</a>'
        '<a rel="me" href="https://social.example/@author">me</a></article>'
    )

    parsed = mf2_parsing.parse_microformats(html, SOURCE_URL)

    assert parsed == mf2py.parse(doc=html, url=SOURCE_URL, html_parser="html.parser")
    assert parsed["items"][0]["properties"]["name"] == ["Title"]
    assert parsed["rels"]["me"] == ["https://social.example/@author"]


def test_nested_embedded_properties_are_not_expanded():
    html = nested_embedded_document(depth=80, payload_bytes=500_000)

    assert mf2_parsing.parse_microformats(html, SOURCE_URL) == mf2_parsing.empty_parse_result()


def test_markup_only_property_nesting_is_not_expanded():
    html = '<div class="h-entry">' + '<i class="e-x">' * 150 + "</i>" * 150 + "</div>"

    with override_settings(INDIEWEB_MF2_MAX_EXPANSION_BYTES=100_000):
        assert mf2_parsing.parse_microformats(html, SOURCE_URL)["items"] == []


@pytest.mark.parametrize(
    "html",
    [
        # classic microformats: plain class names become properties
        '<div class="hentry">' + '<div class="entry-content">' * 40 + "B" * 100_000 + "</div>" * 41,
        # link relations are returned with their text
        "".join(f'<a rel="me" href="/{n}">' for n in range(150)) + "C" * 100_000,
        # several property classes on one element
        '<div class="h-entry">' + '<div class="e-content p-a p-b u-c dt-d">' * 3 + "D" * 300_000 + "</div>" * 4,
    ],
    ids=["classic", "rels", "multiple-classes"],
)
def test_other_expanding_documents_are_not_parsed(html):
    assert len(html) < MIB

    assert mf2_parsing.parse_microformats(html, SOURCE_URL) == mf2_parsing.empty_parse_result()


@pytest.mark.parametrize(
    "depth, payload_bytes",
    [(1, 900_000), (8, 200_000), (30, 60_000)],
)
def test_accepted_documents_stay_within_the_expansion_limit(depth, payload_bytes):
    html = nested_embedded_document(depth=depth, payload_bytes=payload_bytes)

    parsed = mf2_parsing.parse_microformats(html, SOURCE_URL)

    assert parsed["items"], "document is expected to be within the limit"
    assert serialized_size(parsed) <= mf2_parsing.DEFAULT_MF2_MAX_EXPANSION_BYTES


def test_expansion_limit_is_configurable():
    html = nested_embedded_document(depth=3, payload_bytes=10_000)

    assert mf2_parsing.parse_microformats(html, SOURCE_URL)["items"]
    with override_settings(INDIEWEB_MF2_MAX_EXPANSION_BYTES=20_000):
        assert mf2_parsing.parse_microformats(html, SOURCE_URL)["items"] == []


@pytest.mark.parametrize("value", [0, -1, "big", None, True])
def test_invalid_expansion_limit_falls_back_to_the_default(value):
    with override_settings(INDIEWEB_MF2_MAX_EXPANSION_BYTES=value):
        assert mf2_parsing.mf2_max_expansion_bytes() == mf2_parsing.DEFAULT_MF2_MAX_EXPANSION_BYTES


def test_nesting_depth_is_limited():
    entry = '<div class="h-entry"><p class="p-name">Deep</p></div>'
    allowed = "<div>" * (mf2_parsing.MF2_MAX_NESTING_DEPTH - 5) + entry
    too_deep = "<div>" * (mf2_parsing.MF2_MAX_NESTING_DEPTH + 5) + entry

    assert mf2_parsing.parse_microformats(allowed, SOURCE_URL)["items"][0]["properties"]["name"] == ["Deep"]
    assert mf2_parsing.parse_microformats(too_deep, SOURCE_URL) == mf2_parsing.empty_parse_result()


def test_very_deep_document_is_rejected_quickly():
    html = "<div>" * 50_000 + '<a class="h-entry" href="/x">x</a>'

    started = time.process_time()
    parsed = mf2_parsing.parse_microformats(html, SOURCE_URL)

    assert parsed["items"] == []
    assert time.process_time() - started < 10


def test_open_formatting_elements_do_not_multiply_the_tree():
    # HTML5 error recovery re-creates the open formatting elements in every
    # following paragraph; the tree used here must not.
    html = (
        "<p>"
        + "".join(f"<b id=b{n}>" for n in range(100))
        + "</p><p>x" * 5000
        + '<div class="h-entry"><p class="p-name">Name</p></div>'
    )

    started = time.process_time()
    parsed = mf2_parsing.parse_microformats(html, SOURCE_URL)

    assert parsed["items"][0]["properties"]["name"] == ["Name"]
    assert time.process_time() - started < 10


def test_parse_h_card_uses_the_bounded_parser():
    html = '<div class="h-card">' + '<span class="e-note">' * 80 + "N" * 500_000 + "</span>" * 80 + "</div>"

    assert parse_h_card(html, "https://example.com/") == {}


def test_link_verification_is_linear_in_nesting():
    count = 30_000
    html = "<div>" * count + '<a href="https://other.example/">' * count

    started = time.process_time()
    assert _html_links_to_target(html, TARGET_URL) is False
    assert _html_links_to_source_domain(html, "https://source.example/post") is False

    # The ancestor walk this replaces needed minutes for this input.
    assert time.process_time() - started < 20


def test_links_in_nested_non_rendered_containers_do_not_verify():
    hidden = (
        "<template><div><noscript>"
        f'<a href="{TARGET_URL}">hidden</a>'
        "</noscript></div></template>"
        f'<noscript><p><a href="{TARGET_URL}">hidden</a></p></noscript>'
    )

    assert _html_links_to_target(hidden, TARGET_URL) is False
    assert _html_links_to_source_domain(hidden, TARGET_URL) is False
    assert _html_links_to_target(hidden + f'<a href="{TARGET_URL}">shown</a>', TARGET_URL) is True
    assert _html_links_to_source_domain(hidden + f'<a href="{TARGET_URL}">shown</a>', TARGET_URL) is True


@pytest.mark.django_db
def test_expanding_source_is_verified_as_a_plain_mention_with_a_small_snapshot():
    html = nested_embedded_document(depth=80, payload_bytes=500_000)
    processor = WebmentionProcessor()
    processor._injected_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=html)
        )
    )

    with override_settings(INDIEWEB_WEBMENTION_FETCH_MAX_BYTES=MIB):
        webmention = processor.process_webmention(SOURCE_URL, TARGET_URL)

    webmention = Webmention.objects.get(pk=webmention.pk)
    assert webmention.status == "verified"
    assert webmention.mention_type == "mention"
    assert webmention.content == ""
    assert webmention.content_html == ""
    assert webmention.nested_responses.count() == 0
    assert webmention.source_snapshot.parsed_h_entry == {}
