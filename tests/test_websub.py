import httpx
import pytest
from django.http import HttpResponse

from indieweb.websub import (
    add_websub_link_header,
    build_websub_links,
    get_websub_hubs,
    notify_hubs,
    websub_link_header,
)


def test_get_websub_hubs_reads_and_validates_settings(settings):
    settings.INDIEWEB_WEBSUB_HUBS = ("https://hub.example/", "https://backup.example/websub")

    assert get_websub_hubs() == ("https://hub.example/", "https://backup.example/websub")


def test_get_websub_hubs_accepts_explicit_single_hub():
    assert get_websub_hubs("https://hub.example/") == ("https://hub.example/",)


@pytest.mark.parametrize(
    ("topic_url", "hubs", "message"),
    [
        ("not-a-url", ("https://hub.example/",), "topic URL must be a valid"),
        ("https://example.com/feed", ("ftp://hub.example/",), "hub URL must be a valid"),
        ("https://example.com/feed", (), "at least one WebSub hub URL is required"),
    ],
)
def test_build_websub_links_rejects_invalid_discovery_inputs(topic_url, hubs, message):
    with pytest.raises(ValueError, match=message):
        build_websub_links(topic_url, hubs)


def test_build_websub_links_returns_hub_links_and_exactly_one_self_link():
    links = build_websub_links(
        "https://example.com/feed",
        ("https://hub.example/", "https://backup.example/websub"),
    )

    assert [(link.rel, link.url) for link in links] == [
        ("hub", "https://hub.example/"),
        ("hub", "https://backup.example/websub"),
        ("self", "https://example.com/feed"),
    ]


def test_websub_link_header_combines_hubs_and_self():
    header = websub_link_header("https://example.com/feed", ("https://hub.example/",))

    assert header == '<https://hub.example/>; rel="hub", <https://example.com/feed>; rel="self"'


def test_add_websub_link_header_appends_to_existing_link_header():
    response = HttpResponse()
    response["Link"] = '<https://example.com/micropub>; rel="micropub"'

    add_websub_link_header(response, "https://example.com/feed", ("https://hub.example/",))

    assert response["Link"] == (
        '<https://example.com/micropub>; rel="micropub", '
        '<https://hub.example/>; rel="hub", <https://example.com/feed>; rel="self"'
    )


def test_notify_hubs_posts_websub_publish_parameters(settings):
    settings.INDIEWEB_WEBSUB_TIMEOUT = 5
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    results = notify_hubs(
        "https://example.com/feed",
        ("https://hub.example/", "https://backup.example/websub"),
        client=client,
    )

    assert [result.success for result in results] == [True, True]
    assert [result.status_code for result in results] == [204, 204]
    assert [str(request.url) for request in requests] == ["https://hub.example/", "https://backup.example/websub"]
    assert [request.headers["content-type"] for request in requests] == [
        "application/x-www-form-urlencoded",
        "application/x-www-form-urlencoded",
    ]
    assert [request.content for request in requests] == [
        b"hub.mode=publish&hub.url=https%3A%2F%2Fexample.com%2Ffeed",
        b"hub.mode=publish&hub.url=https%3A%2F%2Fexample.com%2Ffeed",
    ]


def test_notify_hubs_returns_empty_when_no_hubs_are_configured(settings):
    settings.INDIEWEB_WEBSUB_HUBS = ()

    assert notify_hubs("https://example.com/feed") == []


def test_notify_hubs_reports_non_success_without_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="temporarily unavailable")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    results = notify_hubs("https://example.com/feed", ("https://hub.example/",), client=client)

    assert results[0].success is False
    assert results[0].status_code == 503
    assert results[0].error == "temporarily unavailable"


def test_notify_hubs_reports_request_errors_without_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    results = notify_hubs("https://example.com/feed", ("https://hub.example/",), client=client)

    assert results[0].success is False
    assert results[0].status_code is None
    assert "connection refused" in results[0].error


def test_notify_hubs_rejects_private_hub_without_posting():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    results = notify_hubs("https://example.com/feed", ("http://127.0.0.1/hub",), client=client)

    assert results[0].success is False
    assert results[0].status_code is None
    assert "blocked address" in results[0].error
    assert requests == []


def test_notify_hubs_rejects_redirect_to_private_hub():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/hub"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    results = notify_hubs("https://example.com/feed", ("https://hub.example/",), client=client)

    assert results[0].success is False
    assert results[0].status_code is None
    assert "redirect target" in results[0].error
    assert len(requests) == 1


def test_notify_hubs_rejects_invalid_timeout(settings):
    settings.INDIEWEB_WEBSUB_TIMEOUT = 0

    with pytest.raises(ValueError, match="timeout must be a positive number"):
        notify_hubs("https://example.com/feed", ("https://hub.example/",))
