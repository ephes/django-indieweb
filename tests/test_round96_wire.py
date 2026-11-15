"""Raw Link and JSON protocol grammar regressions."""

from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from indieweb.models import Token
from indieweb.views import _load_micropub_json_object
from indieweb.websub import delivery_topic_link_allowed


@pytest.mark.parametrize(
    "target",
    [
        "https://example.test/a;b?x=1,2",
        "https://example.test/a,b",
        "https://example.test/a;b",
    ],
)
def test_link_target_delimiters_preserve_exact_topic(target):
    link = f'<https://other.test/>; rel="hub"; title="a,b;c", <{target}>; rel="alternate self"'
    assert delivery_topic_link_allowed({"Link": link}, target)
    assert not delivery_topic_link_allowed({"Link": link}, target + "x")


@pytest.mark.parametrize(
    "link",
    [
        '<https://example.test/a;b?x=1,2; rel="self"',
        '<https://example.test/>; rel="self',
        '<<https://example.test/>>; rel="self"',
        'https://example.test/>; rel="self"',
        '<https://example.test/>; title="unclosed; rel=self',
    ],
)
def test_malformed_link_delimiters_are_not_authority(link):
    assert not delivery_topic_link_allowed({"Link": link}, "https://example.test/")


@pytest.fixture
def wire_token(db):
    user = User.objects.create_user(username="wire")
    return Token.objects.create(
        owner=user, me="https://example.test/", client_id="https://client.test/", scope="create update delete media"
    )


@pytest.mark.parametrize("endpoint", ["micropub", "media"])
@pytest.mark.parametrize(
    "body",
    [
        b'{"action":"delete","action":"undelete","url":"https://testserver/post"}',
        b'{"action":"delete","url":"https://testserver/a","url":"https://testserver/b"}',
        b'{"type":["h-entry"],"properties":{},"properties":{"content":["changed"]}}',
        b'{"type":["h-entry"],"properties":{"content":[{"text":"a","text":"b"}]}}',
        b'{"type":["h-entry"],"properties":{"content":[{"html":"<p>a</p>","html":"<p>b</p>"}]}}',
    ],
)
def test_duplicate_json_members_rejected_before_host_work(client, wire_token, endpoint, body):
    with patch("indieweb.views.get_micropub_handler") as handler, patch("indieweb.views.default_storage") as storage:
        response = client.post(
            reverse(f"indieweb:{endpoint}"),
            data=body,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {wire_token.key}",
        )
    assert response.status_code == 400
    assert response.content == b"invalid_request"
    handler.assert_not_called()
    assert not storage.mock_calls


def test_json_arrays_can_repeat_values_and_decode_is_cached(rf):
    request = rf.post("/", data=b'{"properties":{"category":["same","same"]}}', content_type="application/json")
    payload = _load_micropub_json_object(request)
    assert payload == {"properties": {"category": ["same", "same"]}}
    with patch("indieweb.views.json.loads", side_effect=AssertionError("decoded twice")):
        assert _load_micropub_json_object(request) is payload
