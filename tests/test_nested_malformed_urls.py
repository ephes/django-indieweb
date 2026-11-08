"""Malformed child identity URLs must not discard a verified parent or siblings."""

import httpx
import pytest

from indieweb.processors import WebmentionProcessor

SOURCE = "https://source.example/post"
TARGET = "https://target.example/post"
BAD_URL = "https://[private.invalid/synthetic-secret"


@pytest.mark.django_db
@pytest.mark.parametrize("bad_url", [BAD_URL, "//[private.invalid/synthetic-secret"])
def test_nested_malformed_urls_skip_only_unusable_identities(bad_url, caplog):
    current = '<article class="h-entry"><a class="u-url" href="/existing">existing</a></article>'
    parent = f'<article class="h-entry"><a class="u-in-reply-to" href="{TARGET}">parent</a>{{}}</article>'
    documents = [
        parent.format(current),
        parent.format(
            current
            + f'<article class="h-entry"><data class="p-uid" value="{bad_url}">bad</data></article>'
            + f'<article class="h-entry"><data class="p-uid" value="{bad_url}">bad</data>'
            + '<a class="u-url" href="/fallback">fallback</a></article>'
            + f'<article class="h-entry"><data class="p-url" value="{bad_url}">bad</data>'
            + '<data class="p-url" value="/later">later candidate</data></article>'
            + f'<article class="h-entry" id="child"><data class="p-url" value="{bad_url}">id fallback</data></article>'
            + '<article class="h-entry"><a class="u-url" href="/sibling">sibling</a></article>'
        ),
    ]
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=documents.pop(0))
        )
    ) as client:
        processor = WebmentionProcessor(client=client)
        mention = processor.process_webmention(SOURCE, TARGET)
        assert mention.status == "verified"
        existing = mention.nested_responses.get()
        refreshed = processor.process_webmention(SOURCE, TARGET)

    assert refreshed.pk == mention.pk
    assert refreshed.status == "verified"
    assert refreshed.mention_type == "reply"
    expected = {
        SOURCE + "#child",
        "https://source.example/existing",
        "https://source.example/fallback",
        "https://source.example/later",
        "https://source.example/sibling",
    }
    assert set(refreshed.nested_responses.values_list("identity", flat=True)) == expected
    assert set(refreshed.nested_responses.values_list("status", flat=True)) == {"verified"}
    assert set(refreshed.source_snapshot.nested_response_identities) == expected
    existing.refresh_from_db()
    assert existing.status == "verified"
    assert "synthetic-secret" not in caplog.text
    assert "private.invalid" not in caplog.text
