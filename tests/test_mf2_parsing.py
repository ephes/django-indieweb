"""Bounded microformats parsing and linear link verification for fetched HTML."""

import json
import random
import time

import httpx
import mf2py
import pytest
from bs4 import BeautifulSoup
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

    assert mf2_parsing.parse_microformats(html, SOURCE_URL) is None


def test_markup_only_property_nesting_is_not_expanded():
    html = '<div class="h-entry">' + '<i class="e-x">' * 150 + "</i>" * 150 + "</div>"

    with override_settings(INDIEWEB_MF2_MAX_EXPANSION_BYTES=100_000):
        assert mf2_parsing.parse_microformats(html, SOURCE_URL) is None


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

    assert mf2_parsing.parse_microformats(html, SOURCE_URL) is None


@pytest.mark.parametrize(
    "depth, payload_bytes",
    [(1, 900_000), (2, 250_000), (4, 20_000)],
)
def test_accepted_documents_stay_within_the_expansion_limit(depth, payload_bytes):
    html = nested_embedded_document(depth=depth, payload_bytes=payload_bytes)

    parsed = mf2_parsing.parse_microformats(html, SOURCE_URL)

    assert parsed["items"], "document is expected to be within the limit"
    assert serialized_size(parsed) <= mf2_parsing.DEFAULT_MF2_MAX_EXPANSION_BYTES


def expansion_estimate(html):
    """Return the smallest limit under which ``html`` is accepted."""
    soup = BeautifulSoup(html, "html.parser")
    low, high = 1, 1 << 60
    while low < high:
        middle = (low + high) // 2
        if mf2_parsing.within_parse_limits(soup, SOURCE_URL, middle):
            high = middle
        else:
            low = middle + 1
    return low


def unbounded_parse_size(html):
    return serialized_size(mf2py.parse(doc=BeautifulSoup(html, "html.parser"), url=SOURCE_URL))


LONG_BASE = '<base href="https://example.com/' + "b" * 3000 + '/">'
ESTIMATE_CASES = {
    "microformat nested once per property class": (
        '<div class="h-entry">' + '<div class="p-a p-b h-cite">' * 10 + "x" + "</div>" * 11
    ),
    "embedded nested microformats": (
        '<div class="h-entry">' + '<div class="e-content h-cite p-x">' * 6 + "z" * 3000 + "</div>" * 7
    ),
    "links resolved against a long base": (
        LONG_BASE + '<div class="h-entry">' + '<a class="u-x" href="a">l</a>' * 300 + "</div>"
    ),
    "url text resolved against a long base": (
        LONG_BASE + '<div class="h-entry">' + '<span class="u-x">l</span>' * 300 + "</div>"
    ),
    "embedded images resolved against a long base": (
        LONG_BASE + '<div class="h-entry"><div class="e-content">' + '<img src="a" alt="">' * 300 + "</div></div>"
    ),
    "srcset candidates": (
        LONG_BASE
        + '<div class="h-entry">'
        + ('<img class="u-photo" srcset="' + ",".join(f"a{n} {n + 1}x" for n in range(50)) + '">') * 20
        + "</div>"
    ),
    "many relations on one link": (
        ('<a rel="' + " ".join(f"r{n}" for n in range(300)) + '" href="/' + "u" * 2000 + '">t</a>') * 5
    ),
    "classic nested authors": (
        '<div class="hentry">' + '<div class="author vcard entry-content">' * 6 + "x" * 2000 + "</div>" * 7
    ),
    "classic relations": (
        '<div class="hentry">' + '<a rel="bookmark tag" href="/x">' * 8 + "y" * 2000 + "</a>" * 8 + "</div>"
    ),
    "implied properties": (
        ('<a class="h-card" href="/' + "h" * 3000 + '"><img src="/' + "i" * 3000 + '" alt="' + "a" * 3000 + '"></a>')
        * 10
    ),
    "language repeated per value": (
        '<html lang="' + "l" * 3000 + '"><div class="h-entry">' + '<p class="e-x">t</p>' * 200 + "</div></html>"
    ),
    "image alternatives in text": (
        '<div class="h-entry">'
        + '<p class="p-a p-b">' * 5
        + ('<img alt="' + "q" * 3000 + '" src="s">') * 10
        + "</p>" * 5
        + "</div>"
    ),
    "element ids": '<div class="h-entry">' + ('<div class="h-cite" id="' + "i" * 2000 + '"></div>') * 50 + "</div>",
}


@pytest.mark.parametrize("html", ESTIMATE_CASES.values(), ids=ESTIMATE_CASES.keys())
def test_estimate_is_an_upper_bound_of_the_parse_result(html):
    assert expansion_estimate(html) >= unbounded_parse_size(html)


def random_document(rng):
    classes = [
        "h-entry", "h-cite", "h-card", "p-name", "p-author", "p-comment", "u-url", "u-photo", "e-content",
        "dt-published", "hentry", "vcard", "author", "entry-content", "entry-title", "fn", "url", "plain",
    ]  # fmt: skip
    parts = ['<base href="/base/' + "b" * rng.randint(0, 40) + '/">'] if rng.random() < 0.3 else []
    open_tags = []
    for _ in range(rng.randint(5, 60)):
        action = rng.random()
        if action < 0.45 and len(open_tags) < 12:
            name = rng.choice(["div", "span", "a", "p", "time", "article"])
            attributes = ""
            if rng.random() < 0.8:
                attributes += ' class="' + " ".join(rng.sample(classes, rng.randint(1, 3))) + '"'
            if name == "a":
                attributes += ' href="' + rng.choice(["/x", "y", "https://o.example/z"]) + '"'
                if rng.random() < 0.3:
                    attributes += ' rel="' + rng.choice(["me", "bookmark tag", "author"]) + '"'
            if rng.random() < 0.1:
                attributes += ' lang="en-' + "x" * rng.randint(0, 20) + '"'
            parts.append(f"<{name}{attributes}>")
            open_tags.append(name)
        elif action < 0.7 and open_tags:
            parts.append(f"</{open_tags.pop()}>")
        elif action < 0.8:
            parts.append('<img src="i.png" alt="' + "alt " * rng.randint(0, 5) + '">')
        else:
            parts.append("text " * rng.randint(1, 30))
    parts.extend(f"</{name}>" for name in reversed(open_tags))
    return "".join(parts)


def test_estimate_is_an_upper_bound_for_random_documents():
    rng = random.Random(20261012)
    checked = 0
    for _ in range(1500):
        html = random_document(rng)
        estimate = expansion_estimate(html)
        if estimate > 2_000_000:
            continue  # parsing it without the bound is what the bound exists to avoid
        checked += 1
        assert estimate >= unbounded_parse_size(html), html
    assert checked > 100


def test_ordinary_articles_are_within_the_default_limit():
    classic = (
        '<article class="post hentry category-x"><h1 class="entry-title">Title</h1><div class="entry-content">'
        '<div class="wp-block-group alignwide"><div class="wp-block-columns has-background">'
        + '<p class="has-text-color has-large-font-size">paragraph text here</p>' * 2000
        + '</div></div></div><span class="author vcard"><a class="url fn n" href="/a">A</a></span></article>'
    )
    modern = (
        '<div class="h-feed"><article class="h-entry"><h1 class="p-name">Title</h1><div class="e-content">'
        + '<p class="lead">paragraph <a href="/x">link</a> text text text text</p>' * 4000
        + '</div><a class="p-author h-card" href="/a"><img class="u-photo" src="/p.jpg" alt="">A</a></article></div>'
    )

    for html in (classic, modern):
        parsed = mf2_parsing.parse_microformats(html, SOURCE_URL)
        assert parsed is not None
        assert parsed["items"]


def test_parse_result_over_the_limit_is_discarded_even_when_the_estimate_passes(monkeypatch):
    html = '<div class="h-entry"><p class="p-name">' + "n" * 5000 + "</p></div>"
    monkeypatch.setattr(mf2_parsing, "within_parse_limits", lambda soup, url, max_bytes: True)

    with override_settings(INDIEWEB_MF2_MAX_EXPANSION_BYTES=2000):
        assert mf2_parsing.parse_microformats(html, SOURCE_URL) is None


def test_unknown_classic_rules_count_every_token(monkeypatch):
    html = '<div class="hentry"><div class="anything other">' + "t" * 1000 + "</div></div>"
    known = expansion_estimate(html)
    monkeypatch.setattr(mf2_parsing, "_classic_rules", lambda: None)

    assert expansion_estimate(html) > known


def test_malformed_classic_rules_count_every_token(monkeypatch):
    monkeypatch.setattr(mf2_parsing.backcompat, "_CLASSIC_MAP", {"hentry": {"properties": None}})
    mf2_parsing._classic_rules.cache_clear()
    try:
        assert mf2_parsing._classic_rules() is None
    finally:
        monkeypatch.undo()
        mf2_parsing._classic_rules.cache_clear()


def test_expansion_limit_is_configurable():
    html = nested_embedded_document(depth=3, payload_bytes=10_000)

    assert mf2_parsing.parse_microformats(html, SOURCE_URL)["items"]
    with override_settings(INDIEWEB_MF2_MAX_EXPANSION_BYTES=20_000):
        assert mf2_parsing.parse_microformats(html, SOURCE_URL) is None


@pytest.mark.parametrize("value", [0, -1, "big", None, True])
def test_invalid_expansion_limit_falls_back_to_the_default(value):
    with override_settings(INDIEWEB_MF2_MAX_EXPANSION_BYTES=value):
        assert mf2_parsing.mf2_max_expansion_bytes() == mf2_parsing.DEFAULT_MF2_MAX_EXPANSION_BYTES


def test_nesting_depth_is_limited():
    entry = '<div class="h-entry"><p class="p-name">Deep</p></div>'
    allowed = "<div>" * (mf2_parsing.MF2_MAX_NESTING_DEPTH - 5) + entry
    too_deep = "<div>" * (mf2_parsing.MF2_MAX_NESTING_DEPTH + 5) + entry

    assert mf2_parsing.parse_microformats(allowed, SOURCE_URL)["items"][0]["properties"]["name"] == ["Deep"]
    assert mf2_parsing.parse_microformats(too_deep, SOURCE_URL) is None


def test_very_deep_document_is_rejected_quickly():
    html = "<div>" * 50_000 + '<a class="h-entry" href="/x">x</a>'

    started = time.process_time()
    parsed = mf2_parsing.parse_microformats(html, SOURCE_URL)

    assert parsed is None
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


@pytest.mark.django_db
def test_reprocessing_with_a_source_over_the_limits_resets_parsed_fields():
    reply = (
        f'<article class="h-entry"><a class="u-in-reply-to" href="{TARGET_URL}">re</a>'
        '<div class="e-content">A real reply</div>'
        '<a class="p-author h-card" href="https://example.com/"><img class="u-photo" src="/me.png" alt="">Author</a>'
        '<time class="dt-published" datetime="2026-01-02T03:04:05+00:00">then</time></article>'
    )
    too_deep = "<div>" * (mf2_parsing.MF2_MAX_NESTING_DEPTH + 5) + reply
    responses = iter([reply, too_deep])
    processor = WebmentionProcessor()
    processor._injected_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=next(responses))
        )
    )

    first = processor.process_webmention(SOURCE_URL, TARGET_URL)
    assert (first.mention_type, first.author_name, first.content) == ("reply", "Author", "A real reply")
    assert first.published is not None

    processor.process_webmention(SOURCE_URL, TARGET_URL)

    webmention = Webmention.objects.get(pk=first.pk)
    assert webmention.status == "verified"
    assert webmention.mention_type == "mention"
    assert (webmention.author_name, webmention.author_url, webmention.author_photo) == ("", "", "")
    assert (webmention.content, webmention.content_html) == ("", "")
    assert webmention.published is None
    assert webmention.source_snapshot.parsed_h_entry == {}
