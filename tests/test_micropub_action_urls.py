"""Locality gate and URL policy for Micropub update/delete/undelete action URLs."""

import json

import pytest
from django.contrib.auth.models import User
from django.test import RequestFactory
from django.urls import reverse

from indieweb import checks, micropub_urls, models
from indieweb.handlers import InMemoryMicropubHandler, MicropubEntry

ACTIONS = ["update", "delete", "undelete"]


@pytest.fixture
def user(db):
    return User.objects.create_user(username="action-url-user")


@pytest.fixture
def recording_handler(monkeypatch):
    class RecordingHandler(InMemoryMicropubHandler):
        calls: list[tuple[str, str]] = []

        def update_entry(self, url, updates, user):
            self.calls.append(("update", url))
            return MicropubEntry(url=url, properties={})

        def delete_entry(self, url, user):
            self.calls.append(("delete", url))

        def undelete_entry(self, url, user):
            self.calls.append(("undelete", url))
            return MicropubEntry(url=url, properties={})

    handler = RecordingHandler()
    handler.calls = []
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler)
    return handler


@pytest.fixture
def post_action(client, user):
    token = models.Token.objects.create(
        owner=user, me="https://example.org/", client_id="https://client.example/", scope="update delete undelete"
    )

    def post(action, url, **extra):
        payload = {"action": action, "url": url}
        if action == "update":
            payload["replace"] = {"content": ["x"]}
        return client.post(
            reverse("indieweb:micropub"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
            **extra,
        )

    return post


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize(
    "url",
    [
        "../../etc/passwd",
        "entries/1/",
        "./entries/1/",
        "//attacker.example/entries/1/",
        "/entries/../../secret/",
        "/entries/%2e%2e/%2e%2e/secret/",
        "/entries/%252e%252e/secret/",
        "/entries/..%2fsecret/",
        "/entries\\..\\secret/",
        "/entries/1/\nforged",
        "http://testserver/entries/../secret/",
        "http://user:pw@testserver/entries/1/",
        "ftp://testserver/entries/1/",
        "http://attacker.example/entries/1/",
    ],
)
def test_action_rejects_non_local_or_traversal_urls_before_handler(post_action, recording_handler, action, url):
    response = post_action(action, url)

    assert response.status_code == 400
    assert recording_handler.calls == []


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("url", ["/entries/1/", "/entries/1/?draft=1", "http://testserver/entries/1/"])
def test_action_accepts_local_urls(post_action, recording_handler, action, url):
    response = post_action(action, url)

    assert response.status_code == 204
    assert recording_handler.calls == [(action, url)]


@pytest.mark.parametrize("action", ACTIONS)
def test_canonical_origins_replace_request_host_comparison(settings, post_action, recording_handler, action):
    settings.ALLOWED_HOSTS = ["testserver", "attacker.example"]
    settings.INDIEWEB_MICROPUB_CANONICAL_ORIGINS = ["https://example.org"]

    spoofed = post_action(action, "http://attacker.example/entries/1/", HTTP_HOST="attacker.example")
    request_host = post_action(action, "http://testserver/entries/1/")
    canonical = post_action(action, "https://example.org:443/entries/1/")
    wrong_scheme = post_action(action, "http://example.org/entries/1/")
    relative = post_action(action, "/entries/2/", HTTP_HOST="attacker.example")

    assert spoofed.status_code == 400
    assert request_host.status_code == 400
    assert canonical.status_code == 204
    assert wrong_scheme.status_code == 400
    assert relative.status_code == 204
    assert recording_handler.calls == [(action, "https://example.org:443/entries/1/"), (action, "/entries/2/")]


@pytest.mark.parametrize("action", ACTIONS)
def test_invalid_canonical_origins_fail_closed(settings, post_action, recording_handler, action):
    settings.INDIEWEB_MICROPUB_CANONICAL_ORIGINS = "https://example.org/blog/"

    response = post_action(action, "http://testserver/entries/1/")

    assert response.status_code == 400
    assert recording_handler.calls == []


@pytest.mark.parametrize("action", ACTIONS)
def test_url_policy_gates_action_urls_with_entry_kind(settings, post_action, recording_handler, monkeypatch, action):
    seen = []

    def policy(url, kind, request):
        seen.append((url, kind))
        return False

    monkeypatch.setattr("tests.micropub_policies.reject_all", policy)
    settings.INDIEWEB_MICROPUB_URL_POLICY = "tests.micropub_policies.reject_all"

    response = post_action(action, "/entries/1/")

    assert response.status_code == 400
    assert response.content == b"invalid_request: url not permitted by policy"
    assert seen == [("/entries/1/", "entry")]
    assert recording_handler.calls == []


@pytest.mark.parametrize("action", ACTIONS)
def test_url_policy_failure_fails_closed_for_actions(settings, post_action, recording_handler, action):
    settings.INDIEWEB_MICROPUB_URL_POLICY = "tests.micropub_policies.raise_runtime"

    response = post_action(action, "/entries/1/")

    assert response.status_code == 500
    assert recording_handler.calls == []


@pytest.mark.parametrize("action", ACTIONS)
def test_url_policy_allow_reaches_handler(settings, post_action, recording_handler, action):
    settings.INDIEWEB_MICROPUB_URL_POLICY = "tests.micropub_policies.allow_all"

    response = post_action(action, "/entries/1/")

    assert response.status_code == 204
    assert recording_handler.calls == [(action, "/entries/1/")]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://example.org", (("https", "example.org", None),)),
        ("https://example.org/", (("https", "example.org", None),)),
        (
            ("https://example.org", "http://localhost:8000"),
            (("https", "example.org", None), ("http", "localhost", 8000)),
        ),
        (["HTTPS://Example.ORG:443"], (("https", "example.org", None),)),
    ],
)
def test_parse_canonical_origins_accepts_origins(value, expected):
    assert micropub_urls.parse_canonical_origins(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "example.org",
        "ftp://example.org",
        "https://user@example.org",
        "https://example.org/path",
        "https://example.org?x=1",
        "https://example.org:99999",
        [],
        42,
        [None],
    ],
)
def test_parse_canonical_origins_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        micropub_urls.parse_canonical_origins(value)


def test_absolute_url_without_canonical_origins_compares_request_host(settings):
    request = RequestFactory().get("/", HTTP_HOST="testserver")

    assert micropub_urls.absolute_url_is_local(request, "https://testserver/a/")
    assert not micropub_urls.absolute_url_is_local(request, "https://other.example/a/")
    assert not micropub_urls.absolute_url_is_local(request, "https://[::1/a/")


def test_system_check_reports_invalid_canonical_origins(settings):
    settings.INDIEWEB_MICROPUB_CANONICAL_ORIGINS = ["https://example.org/blog"]

    messages = checks.check_micropub_canonical_origins()

    assert [message.id for message in messages] == ["indieweb.E001"]


@pytest.mark.parametrize("value", ["", [], ()])
def test_empty_canonical_origins_fail_closed(settings, rf, value):
    settings.INDIEWEB_MICROPUB_CANONICAL_ORIGINS = value
    request = rf.get("/", HTTP_HOST="testserver")

    assert micropub_urls.configured_canonical_origins() == ()
    assert not micropub_urls.absolute_url_is_local(request, "http://testserver/entries/1/")
    assert [message.id for message in checks.check_micropub_canonical_origins()] == ["indieweb.E001"]


def test_system_check_accepts_valid_canonical_origins(settings):
    settings.INDIEWEB_MICROPUB_CANONICAL_ORIGINS = "https://example.org"

    assert checks.check_micropub_canonical_origins() == []
