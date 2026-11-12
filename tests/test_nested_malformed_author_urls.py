"""Malformed nested author URLs must not discard a valid child, its siblings or the parent."""

import httpx
import pytest

from indieweb.processors import WebmentionProcessor

SOURCE = "https://source.example/post"
TARGET = "https://target.example/post"
BAD_URLS = ["https://[private.invalid/synthetic-secret", "//[private.invalid/synthetic-secret"]


def _children(bad_url: str) -> str:
    return (
        # String author that looks like a URL reference.
        '<article class="h-entry"><a class="u-url" href="/string-author">s</a>'
        f'<data class="p-author" value="{bad_url}">bad</data></article>'
        # Embedded h-card with a malformed u-url and a valid name.
        '<article class="h-entry"><a class="u-url" href="/card-url">c</a>'
        '<div class="p-author h-card"><span class="p-name">Card Name</span>'
        f'<data class="u-url" value="{bad_url}">bad</data>'
        '<img class="u-photo" src="/photo.png" alt=""></div></article>'
        # Embedded h-card with a malformed u-photo and a valid URL.
        '<article class="h-entry"><a class="u-url" href="/card-photo">p</a>'
        '<div class="p-author h-card"><a class="p-name u-url" href="/alice">Alice</a>'
        f'<data class="u-photo" value="{bad_url}">bad</data></div></article>'
        # Untouched sibling.
        '<article class="h-entry"><a class="u-url" href="/sibling">sibling</a></article>'
    )


@pytest.mark.django_db
@pytest.mark.parametrize("bad_url", BAD_URLS)
def test_nested_malformed_author_urls_keep_child_and_siblings(bad_url, caplog):
    document = (
        f'<article class="h-entry"><a class="u-in-reply-to" href="{TARGET}">parent</a>{_children(bad_url)}</article>'
    )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=document)
        )
    ) as client:
        mention = WebmentionProcessor(client=client).process_webmention(SOURCE, TARGET)

    assert mention.status == "verified"
    assert mention.mention_type == "reply"
    responses = {row.identity: row for row in mention.nested_responses.all()}
    assert set(responses) == {
        "https://source.example/string-author",
        "https://source.example/card-url",
        "https://source.example/card-photo",
        "https://source.example/sibling",
    }
    assert {row.status for row in responses.values()} == {"verified"}

    string_author = responses["https://source.example/string-author"]
    assert string_author.author_url == ""
    assert "private.invalid" not in string_author.author_name

    card_url = responses["https://source.example/card-url"]
    assert card_url.author_name == "Card Name"
    assert card_url.author_url == ""
    assert card_url.author_photo == "https://source.example/photo.png"

    card_photo = responses["https://source.example/card-photo"]
    assert card_photo.author_name == "Alice"
    assert card_photo.author_url == "https://source.example/alice"
    assert card_photo.author_photo == ""

    assert "synthetic-secret" not in caplog.text
    assert "private.invalid" not in caplog.text


@pytest.mark.django_db
@pytest.mark.parametrize("bad_url", BAD_URLS)
@pytest.mark.parametrize(
    "author_markup",
    [
        '<data class="p-author" value="{bad}">bad</data>',
        '<div class="p-author h-card"><span class="p-name">Bob</span><data class="u-url" value="{bad}">x</data></div>',
    ],
)
def test_parent_malformed_author_urls_keep_parent_verified(bad_url, author_markup, caplog):
    document = (
        f'<link rel="author" href="{bad_url}">'
        f'<article class="h-entry"><a class="u-in-reply-to" href="{TARGET}">parent</a>'
        f"{author_markup.format(bad=bad_url)}</article>"
    )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=document)
        )
    ) as client:
        mention = WebmentionProcessor(client=client).process_webmention(SOURCE, TARGET)

    assert mention.status == "verified"
    assert mention.author_url == ""
    assert "private.invalid" not in mention.author_name
    assert "synthetic-secret" not in caplog.text


@pytest.mark.django_db
@pytest.mark.parametrize("bad_url", BAD_URLS)
def test_rel_author_malformed_url_falls_back_to_page_h_card(bad_url):
    document = (
        f'<link rel="author" href="{bad_url}">'
        '<div class="h-card"><a class="p-name u-url" href="/me">Page Owner</a></div>'
        f'<article class="h-entry"><a class="u-in-reply-to" href="{TARGET}">parent</a></article>'
    )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=document)
        )
    ) as client:
        mention = WebmentionProcessor(client=client).process_webmention(SOURCE, TARGET)

    assert mention.status == "verified"
    assert mention.author_name == "Page Owner"
    assert mention.author_url == "https://source.example/me"
