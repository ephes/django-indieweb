from collections.abc import Callable
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import pytest
from django.test import override_settings
from django.utils import timezone

from indieweb.models import WebmentionOutboundTarget
from indieweb.senders import WebmentionSender

pytestmark = pytest.mark.django_db


@pytest.fixture
def sender():
    return WebmentionSender()


@pytest.fixture
def source_url():
    return "https://example.com/my-post"


@pytest.fixture
def target_url():
    return "https://target.com/their-post"


def _sender_response(*, status_code=200, text="", headers=None):
    """Build an httpx.Response for sender redirect tests."""
    return httpx.Response(status_code, headers=headers or {}, text=text)


def _make_test_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    """Build an httpx.Client backed by MockTransport for sender tests."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def _request_urls(captured: list[httpx.Request]) -> list[str]:
    return [str(request.url) for request in captured]


def test_extract_urls_from_html(sender, source_url, target_url):
    """Test extracting URLs from HTML content."""
    html = """
    <html>
    <body>
        <p>Check out this <a href="https://example.com/page1">link</a></p>
        <p>And this <a href="https://example.com/page2">other link</a></p>
        <p>Relative link: <a href="/relative">here</a></p>
        <p>No href: <a>broken</a></p>
    </body>
    </html>
    """

    urls = sender.extract_urls(html)

    assert len(urls) == 3
    assert "https://example.com/page1" in urls
    assert "https://example.com/page2" in urls
    assert "/relative" in urls


def test_extract_urls_handles_duplicates(sender, source_url, target_url):
    """Test that duplicate URLs are removed."""
    html = """
    <html>
    <body>
        <p><a href="https://example.com/page">Link 1</a></p>
        <p><a href="https://example.com/page">Link 2</a></p>
    </body>
    </html>
    """

    urls = sender.extract_urls(html)

    assert len(urls) == 1
    assert "https://example.com/page" in urls


def test_extract_external_target_urls_filters_unsafe_hosts(sender, source_url):
    """Private and metadata targets are not eligible for outbound discovery."""
    html = """
    <a href="https://target.com/post">Public</a>
    <a href="http://127.0.0.1/admin">Loopback</a>
    <a href="http://169.254.169.254/latest/meta-data/">Metadata</a>
    <a href="ftp://target.com/file">FTP</a>
    """

    assert sender._extract_external_target_urls(source_url, html) == ["https://target.com/post"]


def test_discover_endpoint_from_link_header(sender, source_url, target_url):
    """Test discovering webmention endpoint from Link header."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, headers={"Link": '<https://target.com/webmention>; rel="webmention"'})

    endpoint = sender.discover_endpoint(target_url, client=_make_test_client(handler))

    assert endpoint == "https://target.com/webmention"
    assert len(captured) == 1
    assert captured[0].method == "HEAD"
    assert str(captured[0].url) == target_url


def test_discover_endpoint_follows_redirect_to_link_header(sender, source_url, target_url):
    """Test endpoint discovery follows target redirects before reading Link headers."""
    final_url = "https://target.com/canonical/their-post"
    responses = iter(
        [
            _sender_response(status_code=302, headers={"Location": final_url}),
            _sender_response(status_code=200, headers={"Link": '<https://target.com/webmention>; rel="webmention"'}),
        ]
    )
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return next(responses)

    endpoint = sender.discover_endpoint(target_url, client=_make_test_client(handler))

    assert endpoint == "https://target.com/webmention"
    assert _request_urls(captured) == [target_url, final_url]


def test_discover_endpoint_resolves_relative_link_header_against_final_url(sender, source_url, target_url):
    """Test relative Link endpoints after redirects use the final target page URL."""
    final_url = "https://target.com/canonical/their-post"
    responses = iter(
        [
            _sender_response(status_code=301, headers={"Location": final_url}),
            _sender_response(status_code=200, headers={"Link": '<wm>; rel="webmention"'}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    endpoint = sender.discover_endpoint(target_url, client=_make_test_client(handler))

    assert endpoint == "https://target.com/canonical/wm"


def test_discover_endpoint_from_link_header_with_multiple_rels(sender, source_url, target_url):
    """Test discovering webmention endpoint from Link header with multiple rel values."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Link": '<https://target.com/other>; rel="other", <https://target.com/webmention>; rel="webmention"',
            },
        )

    endpoint = sender.discover_endpoint(target_url, client=_make_test_client(handler))

    assert endpoint == "https://target.com/webmention"


def test_discover_endpoint_from_html_link_tag(sender, source_url, target_url):
    """Test discovering webmention endpoint from HTML link tag."""
    captured: list[httpx.Request] = []
    html = """
    <html>
    <head>
        <link rel="webmention" href="/webmention-endpoint" />
    </head>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.method == "HEAD":
            return httpx.Response(200)
        return httpx.Response(200, text=html)

    endpoint = sender.discover_endpoint(target_url, client=_make_test_client(handler))

    assert endpoint == "https://target.com/webmention-endpoint"
    methods = [request.method for request in captured]
    assert methods == ["HEAD", "GET"]
    assert str(captured[1].url) == target_url


def test_discover_endpoint_resolves_html_endpoint_against_final_url(sender, source_url, target_url):
    """Test HTML endpoint discovery after redirects uses the final page URL."""
    final_url = "https://target.com/canonical/their-post"
    head_responses = iter(
        [
            _sender_response(status_code=302, headers={"Location": final_url}),
            _sender_response(status_code=200),
        ]
    )
    get_responses = iter(
        [
            _sender_response(status_code=302, headers={"Location": final_url}),
            _sender_response(
                status_code=200,
                text="""
                <html>
                <head>
                    <link rel="webmention" href="wm" />
                </head>
                </html>
                """,
            ),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return next(head_responses)
        return next(get_responses)

    endpoint = sender.discover_endpoint(target_url, client=_make_test_client(handler))

    assert endpoint == "https://target.com/canonical/wm"


def test_discover_endpoint_from_html_a_tag(sender, source_url, target_url):
    """Test discovering webmention endpoint from HTML a tag."""
    html = """
    <html>
    <body>
        <a rel="webmention" href="/webmention">Webmention endpoint</a>
    </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200)
        return httpx.Response(200, text=html)

    endpoint = sender.discover_endpoint(target_url, client=_make_test_client(handler))

    assert endpoint == "https://target.com/webmention"


def test_discover_endpoint_relative_url(sender, source_url, target_url):
    """Test that relative URLs are resolved correctly."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Link": '</api/webmention>; rel="webmention"'})

    endpoint = sender.discover_endpoint("https://example.com/post/123", client=_make_test_client(handler))

    assert endpoint == "https://example.com/api/webmention"


def test_discover_endpoint_not_found(sender, source_url, target_url):
    """Test when no webmention endpoint is found."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200)
        return httpx.Response(200, text="<html><body>No webmention here</body></html>")

    endpoint = sender.discover_endpoint(target_url, client=_make_test_client(handler))

    assert endpoint is None


def test_discover_endpoint_handles_request_exception(sender, source_url, target_url):
    """Test that discovery handles request exceptions gracefully."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RequestError("Network error")

    endpoint = sender.discover_endpoint(target_url, client=_make_test_client(handler))

    assert endpoint is None


def _form_body(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(request.content.decode("ascii"))


def test_send_webmention_success(sender, source_url, target_url):
    """Test successful webmention sending."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(201)

    endpoint = "https://target.com/webmention"
    result = sender.send_webmention(source_url, target_url, endpoint, client=_make_test_client(handler))

    assert result["success"] is True
    assert result["status_code"] == 201
    assert len(captured) == 1
    assert captured[0].method == "POST"
    assert str(captured[0].url) == endpoint
    assert _form_body(captured[0]) == {"source": [source_url], "target": [target_url]}


def test_send_webmention_includes_vouch_when_provided(sender, source_url, target_url):
    """Test sender can opt in to including a Vouch URL."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(202)

    endpoint = "https://target.com/webmention"
    vouch = "https://trusted.example/vouch-for-example"
    result = sender.send_webmention(source_url, target_url, endpoint, vouch=vouch, client=_make_test_client(handler))

    assert result["success"] is True
    assert _form_body(captured[0]) == {"source": [source_url], "target": [target_url], "vouch": [vouch]}


@pytest.mark.parametrize("redirect_status_code", [301, 302, 303, 307, 308])
def test_send_webmention_preserves_post_payload_across_endpoint_redirect(
    sender, source_url, target_url, redirect_status_code
):
    """Test endpoint redirects keep the Webmention POST body."""
    endpoint = "https://target.com/webmention"
    final_endpoint = "https://target.com/api/webmention"
    responses = iter(
        [
            _sender_response(status_code=redirect_status_code, headers={"Location": final_endpoint}),
            _sender_response(status_code=202),
        ]
    )
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return next(responses)

    result = sender.send_webmention(source_url, target_url, endpoint, client=_make_test_client(handler))

    assert result["success"] is True
    assert result["status_code"] == 202
    assert _request_urls(captured) == [endpoint, final_endpoint]
    expected_body = captured[0].content
    assert captured[1].content == expected_body


def test_send_webmention_resolves_relative_endpoint_redirect_location(sender, source_url, target_url):
    """Test relative endpoint redirect locations resolve against the redirecting URL."""
    endpoint = "https://target.com/webmention"
    responses = iter(
        [
            _sender_response(status_code=302, headers={"Location": "/api/webmention"}),
            _sender_response(status_code=202),
        ]
    )
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return next(responses)

    result = sender.send_webmention(source_url, target_url, endpoint, client=_make_test_client(handler))

    assert result["success"] is True
    assert str(captured[1].url) == "https://target.com/api/webmention"


@pytest.mark.parametrize("status_code", [200, 201, 202])
def test_send_webmention_with_different_success_codes(sender, source_url, target_url, status_code):
    """Test that 200, 201, and 202 are all considered success."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)

    result = sender.send_webmention(
        source_url, target_url, "https://example.com/webmention", client=_make_test_client(handler)
    )

    assert result["success"] is True
    assert result["status_code"] == status_code


def test_send_webmention_failure(sender, source_url, target_url):
    """Test failed webmention sending."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    endpoint = "https://target.com/webmention"
    result = sender.send_webmention(source_url, target_url, endpoint, client=_make_test_client(handler))

    assert result["success"] is False
    assert result["status_code"] == 404
    assert "error" in result


def test_send_webmention_network_error(sender, source_url, target_url):
    """Test webmention sending with network error."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RequestError("Connection failed")

    endpoint = "https://target.com/webmention"
    result = sender.send_webmention(source_url, target_url, endpoint, client=_make_test_client(handler))

    assert result["success"] is False
    assert "Connection failed" in result["error"]


@patch("indieweb.senders.request_with_webmention_redirects")
def test_send_webmention_treats_oversized_response_as_failure(
    mock_request_with_redirects, sender, source_url, target_url
):
    """A hostile Webmention endpoint returning a body larger than the cap is a delivery failure."""
    from indieweb.http_client import HTTPResponseTooLarge

    mock_request_with_redirects.side_effect = HTTPResponseTooLarge("response exceeded 1024 decoded bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    result = sender.send_webmention(
        source_url, target_url, "https://target.com/webmention", client=_make_test_client(handler)
    )

    assert result["success"] is False
    assert result["status_code"] is None
    assert "too large" in result["error"]
    # The cap kwarg must have been threaded through to the redirect helper.
    assert "max_bytes" in mock_request_with_redirects.call_args.kwargs
    assert mock_request_with_redirects.call_args.kwargs["max_bytes"] is not None


@override_settings(INDIEWEB_WEBMENTION_RESPONSE_MAX_BYTES=2048)
@patch("indieweb.senders.request_with_webmention_redirects")
def test_send_webmention_passes_configured_response_cap_to_helper(
    mock_request_with_redirects, sender, source_url, target_url
):
    """Configured INDIEWEB_WEBMENTION_RESPONSE_MAX_BYTES is forwarded to the helper."""
    response = _sender_response(status_code=202)

    class _Delivered:
        pass

    delivered = _Delivered()
    delivered.response = response
    delivered.final_url = "https://target.com/webmention"
    mock_request_with_redirects.return_value = delivered

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202)

    result = sender.send_webmention(
        source_url, target_url, "https://target.com/webmention", client=_make_test_client(handler)
    )

    assert result["success"] is True
    assert mock_request_with_redirects.call_args.kwargs["max_bytes"] == 2048


def test_send_webmention_rejects_unsafe_vouch_without_post(sender, source_url, target_url):
    """send_webmention validates Vouch even when callers bypass the command."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    result = sender.send_webmention(
        source_url,
        target_url,
        "https://target.com/webmention",
        vouch="http://127.0.0.1/vouch",
        client=_make_test_client(handler),
    )

    assert result["success"] is False
    assert captured == []


def test_fetch_content(sender, source_url, target_url):
    """Test fetching content from a URL."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, text="<html><body>Test content</body></html>")

    content = sender.fetch_content("https://example.com/page", client=_make_test_client(handler))

    assert content == "<html><body>Test content</body></html>"
    assert len(captured) == 1
    assert captured[0].method == "GET"
    assert str(captured[0].url) == "https://example.com/page"


def test_fetch_content_follows_redirect(sender, source_url, target_url):
    """Test fetching source content follows bounded redirects."""
    final_url = "https://example.com/canonical/page"
    responses = iter(
        [
            _sender_response(status_code=302, headers={"Location": final_url}),
            _sender_response(status_code=200, text="<html><body>Final content</body></html>"),
        ]
    )
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return next(responses)

    content = sender.fetch_content("https://example.com/page", client=_make_test_client(handler))

    assert content == "<html><body>Final content</body></html>"
    assert _request_urls(captured) == ["https://example.com/page", final_url]


def test_fetch_content_resolves_relative_redirect_location(sender, source_url, target_url):
    """Test relative content redirect locations resolve against the redirecting URL."""
    responses = iter(
        [
            _sender_response(status_code=302, headers={"Location": "/canonical/page"}),
            _sender_response(status_code=200, text="<html><body>Final content</body></html>"),
        ]
    )
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return next(responses)

    content = sender.fetch_content("https://example.com/page", client=_make_test_client(handler))

    assert content == "<html><body>Final content</body></html>"
    assert str(captured[1].url) == "https://example.com/canonical/page"


def test_discover_endpoint_returns_none_when_redirect_limit_exceeded(sender, source_url, target_url):
    """Test discovery returns None for redirect errors."""
    responses = iter(
        [_sender_response(status_code=302, headers={"Location": f"https://target.com/r{i}"}) for i in range(6)]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    endpoint = sender.discover_endpoint(target_url, client=_make_test_client(handler))

    assert endpoint is None


def test_fetch_content_returns_none_when_redirect_limit_exceeded(sender, source_url, target_url):
    """Test content fetch returns None for redirect errors."""
    responses = iter(
        [_sender_response(status_code=302, headers={"Location": f"https://example.com/r{i}"}) for i in range(6)]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    content = sender.fetch_content("https://example.com/page", client=_make_test_client(handler))

    assert content is None


def test_fetch_content_returns_none_for_unsupported_redirect_scheme(sender, source_url, target_url):
    """Test redirects only continue to HTTP and HTTPS URLs."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(302, headers={"Location": "mailto:a@example.com"})

    content = sender.fetch_content("https://example.com/page", client=_make_test_client(handler))

    assert content is None
    assert len(captured) == 1


def test_send_webmention_returns_failure_when_redirect_limit_exceeded(sender, source_url, target_url):
    """Test endpoint POST redirect errors use the safe failure shape."""
    responses = iter(
        [_sender_response(status_code=302, headers={"Location": f"https://target.com/r{i}"}) for i in range(6)]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    result = sender.send_webmention(
        source_url,
        target_url,
        "https://target.com/webmention",
        client=_make_test_client(handler),
    )

    assert result["success"] is False
    assert result["status_code"] is None
    assert "redirects" in result["error"]


def test_fetch_content_error(sender, source_url, target_url):
    """Test fetching content handles errors."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RequestError("Network error")

    content = sender.fetch_content("https://example.com/page", client=_make_test_client(handler))

    assert content is None


def test_send_webmentions_without_html_content(sender, source_url, target_url):
    """Test send_webmentions when HTML content is not provided."""
    with patch.object(sender, "fetch_content") as mock_fetch:
        # Link to a different domain so it's not skipped
        mock_fetch.return_value = '<html><body><a href="https://otherdomain.com/link">Link</a></body></html>'

        with patch.object(sender, "discover_endpoint") as mock_discover:
            mock_discover.return_value = "https://otherdomain.com/webmention"

            with patch.object(sender, "send_webmention") as mock_send:
                mock_send.return_value = {"success": True, "status_code": 201}

                results = sender.send_webmentions(source_url)

                mock_fetch.assert_called_once_with(source_url)
                assert len(results) == 1
                assert results[0]["target"] == "https://otherdomain.com/link"


def test_send_webmentions_full_flow(sender, source_url, target_url):
    """Test the full webmention sending flow."""
    html_content = """
    <html>
    <body>
        <p>I wrote about <a href="https://target1.com/post">this post</a></p>
        <p>And also mentioned <a href="https://target2.com/article">this article</a></p>
        <p>But not <a href="https://example.com/my-other-post">my own post</a></p>
    </body>
    </html>
    """

    # Mock endpoint discovery
    with patch.object(sender, "discover_endpoint") as mock_discover:

        def discover_side_effect(url):
            if "target1.com" in url:
                return "https://target1.com/webmention"
            elif "target2.com" in url:
                return None  # No endpoint
            return None

        mock_discover.side_effect = discover_side_effect

        # Mock sending
        with patch.object(sender, "send_webmention") as mock_send:
            mock_send.return_value = {"success": True, "status_code": 201}

            results = sender.send_webmentions(source_url, html_content)

            # Should discover endpoints for both external URLs
            assert mock_discover.call_count == 2
            # Should only send to target1 (which has an endpoint)
            assert mock_send.call_count == 1
            assert len(results) == 1
            assert results[0]["target"] == "https://target1.com/post"
            assert results[0]["success"] is True


def test_send_webmentions_passes_vouch_to_each_delivery(sender, source_url, target_url):
    """Test bulk sending can include the same Vouch URL for each outgoing delivery."""
    html_content = '<html><body><a href="https://target.com/post">Target</a></body></html>'
    vouch = "https://trusted.example/vouch-for-example"

    with patch.object(sender, "discover_endpoint") as mock_discover:
        mock_discover.return_value = "https://target.com/webmention"
        with patch.object(sender, "send_webmention") as mock_send:
            mock_send.return_value = {"success": True, "status_code": 202}

            results = sender.send_webmentions(source_url, html_content, vouch_url=vouch)

    assert len(results) == 1
    mock_send.assert_called_once_with(
        source_url,
        "https://target.com/post",
        "https://target.com/webmention",
        vouch=vouch,
    )


def test_discover_endpoint_handles_fragment_and_query(sender, source_url, target_url):
    """Test that fragments and query strings don't interfere with endpoint discovery."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Link": '<https://target.com/webmention>; rel="webmention"'})

    # URL with fragment and query
    endpoint = sender.discover_endpoint(
        "https://target.com/post?param=value#section",
        client=_make_test_client(handler),
    )

    assert endpoint == "https://target.com/webmention"


def test_send_webmentions_records_outbound_target_history(sender, source_url, target_url):
    """Test ordinary sends record history for delivered current external targets."""
    html_content = '<a href="https://target.com/post">Target</a>'
    sent_at = timezone.now()

    with patch("indieweb.senders.timezone.now", return_value=sent_at):
        with patch.object(sender, "discover_endpoint", return_value="https://target.com/webmention"):
            with patch.object(sender, "send_webmention", return_value={"success": True, "status_code": 202}):
                results = sender.send_webmentions(source_url, html_content)

    assert len(results) == 1
    target = WebmentionOutboundTarget.objects.get(source_url=source_url, target_url="https://target.com/post")
    assert target.endpoint_url == "https://target.com/webmention"
    assert target.endpoint_discovered_at == sent_at
    assert target.first_sent_at == sent_at
    assert target.last_sent_at == sent_at
    assert target.last_attempted_at == sent_at
    assert target.last_status_code == 202
    assert target.last_success is True
    assert target.last_error == ""
    assert target.consecutive_failures == 0
    assert target.last_seen_in_source_at == sent_at


def test_send_webmentions_repeated_send_updates_existing_history_row(sender, source_url, target_url):
    """Test repeated ordinary sends update one row while preserving first_sent_at."""
    html_content = '<a href="https://target.com/post">Target</a>'
    first_sent_at = timezone.now()
    second_sent_at = first_sent_at + timedelta(minutes=5)

    with patch.object(sender, "discover_endpoint", return_value="https://target.com/webmention"):
        with patch.object(sender, "send_webmention", return_value={"success": True, "status_code": 202}):
            with patch("indieweb.senders.timezone.now", return_value=first_sent_at):
                sender.send_webmentions(source_url, html_content)
            with patch("indieweb.senders.timezone.now", return_value=second_sent_at):
                sender.send_webmentions(source_url, html_content)

    assert WebmentionOutboundTarget.objects.count() == 1
    target = WebmentionOutboundTarget.objects.get(source_url=source_url, target_url="https://target.com/post")
    assert target.first_sent_at == first_sent_at
    assert target.last_sent_at == second_sent_at
    assert target.last_seen_in_source_at == second_sent_at


def test_send_webmentions_records_failed_delivery_history(sender, source_url, target_url):
    """Test ordinary failed deliveries record latest failure status and error."""
    html_content = '<a href="https://target.com/post">Target</a>'

    with patch.object(sender, "discover_endpoint", return_value="https://target.com/webmention"):
        with patch.object(
            sender,
            "send_webmention",
            return_value={"success": False, "status_code": 500, "error": "HTTP 500"},
        ):
            sender.send_webmentions(source_url, html_content)

    target = WebmentionOutboundTarget.objects.get(source_url=source_url, target_url="https://target.com/post")
    assert target.last_success is False
    assert target.last_status_code == 500
    assert target.last_error == "HTTP 500"
    assert target.consecutive_failures == 1


def test_send_webmentions_success_resets_consecutive_failures(sender, source_url, target_url):
    """Test a successful current send resets prior failure state."""
    WebmentionOutboundTarget.objects.create(
        source_url=source_url,
        target_url="https://target.com/post",
        consecutive_failures=3,
    )
    html_content = '<a href="https://target.com/post">Target</a>'

    with patch.object(sender, "discover_endpoint", return_value="https://target.com/webmention"):
        with patch.object(sender, "send_webmention", return_value={"success": True, "status_code": 202}):
            sender.send_webmentions(source_url, html_content)

    target = WebmentionOutboundTarget.objects.get(source_url=source_url, target_url="https://target.com/post")
    assert target.consecutive_failures == 0


def test_send_webmentions_records_latest_vouch_url(sender, source_url, target_url):
    """Test ordinary sends record the latest Vouch URL used for delivery."""
    html_content = '<a href="https://target.com/post">Target</a>'
    vouch = "https://trusted.example/vouch-for-example"

    with patch.object(sender, "discover_endpoint", return_value="https://target.com/webmention"):
        with patch.object(sender, "send_webmention", return_value={"success": True, "status_code": 202}):
            sender.send_webmentions(source_url, html_content, vouch_url=vouch)

    target = WebmentionOutboundTarget.objects.get(source_url=source_url, target_url="https://target.com/post")
    assert target.last_vouch_url == vouch


def test_send_webmentions_record_history_false_does_not_write_history(sender, source_url, target_url):
    """Test record_history=False keeps ordinary send delivery but avoids writes."""
    html_content = '<a href="https://target.com/post">Target</a>'

    with patch.object(sender, "discover_endpoint", return_value="https://target.com/webmention"):
        with patch.object(sender, "send_webmention", return_value={"success": True, "status_code": 202}):
            results = sender.send_webmentions(source_url, html_content, record_history=False)

    assert len(results) == 1
    assert WebmentionOutboundTarget.objects.count() == 0


def test_send_webmentions_skips_relative_and_same_domain_urls_without_history(sender, source_url, target_url):
    """Test skipped ordinary targets are neither sent nor recorded."""
    html_content = """
    <a href="/relative">Relative</a>
    <a href="https://example.com/other">Same domain</a>
    <a href="https://target.com/post">Target</a>
    """

    with patch.object(sender, "discover_endpoint", return_value="https://target.com/webmention") as discover:
        with patch.object(sender, "send_webmention", return_value={"success": True, "status_code": 202}):
            results = sender.send_webmentions(source_url, html_content)

    assert len(results) == 1
    discover.assert_called_once_with("https://target.com/post")
    assert list(WebmentionOutboundTarget.objects.values_list("target_url", flat=True)) == ["https://target.com/post"]


def test_send_webmentions_no_endpoint_preserves_no_result_and_no_history(sender, source_url, target_url):
    """Test ordinary sends without endpoint discovery do not create results or history."""
    html_content = '<a href="https://target.com/post">Target</a>'

    with patch.object(sender, "discover_endpoint", return_value=None):
        with patch.object(sender, "send_webmention") as send:
            results = sender.send_webmentions(source_url, html_content)

    assert results == []
    send.assert_not_called()
    assert WebmentionOutboundTarget.objects.count() == 0


def test_send_webmentions_history_uses_exact_url_strings(sender, source_url, target_url):
    """Test ordinary history keys are not canonicalized."""
    target_urls = [
        "https://target.com/post?a=1&b=2",
        "https://target.com/post?b=2&a=1",
        "https://target.com/post#fragment",
        "https://TARGET.com/post",
        "https://target.com/post/",
    ]
    html_content = "".join(f'<a href="{target_url}">Target</a>' for target_url in target_urls)

    with patch.object(sender, "discover_endpoint", return_value="https://target.com/webmention"):
        with patch.object(sender, "send_webmention", return_value={"success": True, "status_code": 202}):
            sender.send_webmentions(source_url, html_content)

    assert set(WebmentionOutboundTarget.objects.values_list("target_url", flat=True)) == set(target_urls)


def test_resend_salmentions_sends_current_history_and_both_for_exact_source(sender, source_url, target_url):
    """Test resend_salmentions sends the exact-source union and labels provenance."""
    html_content = """
    <a href="https://current.example/post">Current</a>
    <a href="https://both.example/post">Both</a>
    """
    WebmentionOutboundTarget.objects.create(
        source_url=source_url,
        target_url="https://history.example/post",
        endpoint_url="https://history.example/old-webmention",
    )
    WebmentionOutboundTarget.objects.create(source_url=source_url, target_url="https://both.example/post")
    WebmentionOutboundTarget.objects.create(
        source_url="https://example.com/other-post",
        target_url="https://other-history.example/post",
    )

    def discover(target_url):
        return f"{target_url}/webmention"

    with patch.object(sender, "discover_endpoint", side_effect=discover) as discover_mock:
        with patch.object(
            sender,
            "send_webmention",
            side_effect=lambda *args, **kwargs: {"success": True, "status_code": 202},
        ) as send:
            results = sender.resend_salmentions(source_url, html_content)

    provenance = {result["target"]: result["provenance"] for result in results}
    assert provenance == {
        "https://both.example/post": "both",
        "https://current.example/post": "current",
        "https://history.example/post": "history",
    }
    assert {call.args[0] for call in discover_mock.call_args_list} == set(provenance)
    assert {call.args[1] for call in send.call_args_list} == set(provenance)
    assert "https://other-history.example/post" not in provenance


def test_resend_salmentions_rediscovers_historical_endpoint(sender, source_url, target_url):
    """Test resend delivery uses a freshly discovered endpoint, not stored diagnostics."""
    WebmentionOutboundTarget.objects.create(
        source_url=source_url,
        target_url="https://history.example/post",
        endpoint_url="https://history.example/old-webmention",
    )

    with patch.object(sender, "discover_endpoint", return_value="https://history.example/new-webmention"):
        with patch.object(
            sender,
            "send_webmention",
            return_value={"success": True, "status_code": 202},
        ) as send:
            sender.resend_salmentions(source_url, "<p>No current links</p>")

    send.assert_called_once_with(
        source_url,
        "https://history.example/post",
        "https://history.example/new-webmention",
        vouch=None,
    )
    target = WebmentionOutboundTarget.objects.get(source_url=source_url, target_url="https://history.example/post")
    assert target.endpoint_url == "https://history.example/new-webmention"


def test_resend_salmentions_refreshes_history_for_current_and_historical_targets(sender, source_url, target_url):
    """Test resend refreshes history rows for both current-only and historical-only targets."""
    html_content = '<a href="https://current.example/post">Current</a>'
    old_seen_at = timezone.now() - timedelta(days=1)
    resent_at = timezone.now()
    WebmentionOutboundTarget.objects.create(
        source_url=source_url,
        target_url="https://history.example/post",
        last_seen_in_source_at=old_seen_at,
    )

    with patch("indieweb.senders.timezone.now", return_value=resent_at):
        with patch.object(sender, "discover_endpoint", return_value="https://endpoint.example/webmention"):
            with patch.object(
                sender,
                "send_webmention",
                side_effect=lambda *args, **kwargs: {"success": True, "status_code": 202},
            ):
                sender.resend_salmentions(source_url, html_content)

    current = WebmentionOutboundTarget.objects.get(
        source_url=source_url,
        target_url="https://current.example/post",
    )
    historical = WebmentionOutboundTarget.objects.get(
        source_url=source_url,
        target_url="https://history.example/post",
    )
    assert current.first_sent_at == resent_at
    assert current.last_seen_in_source_at == resent_at
    assert historical.last_sent_at == resent_at
    assert historical.last_seen_in_source_at == old_seen_at


def test_resend_salmentions_passes_vouch_to_each_delivery(sender, source_url, target_url):
    """Test resend passes Vouch through to all deliveries."""
    html_content = '<a href="https://current.example/post">Current</a>'
    WebmentionOutboundTarget.objects.create(source_url=source_url, target_url="https://history.example/post")
    vouch = "https://trusted.example/vouch-for-example"

    with patch.object(sender, "discover_endpoint", return_value="https://endpoint.example/webmention"):
        with patch.object(
            sender,
            "send_webmention",
            side_effect=lambda *args, **kwargs: {"success": True, "status_code": 202},
        ) as send:
            sender.resend_salmentions(source_url, html_content, vouch_url=vouch)

    assert send.call_count == 2
    for call in send.call_args_list:
        assert call.kwargs["vouch"] == vouch
    assert set(WebmentionOutboundTarget.objects.values_list("last_vouch_url", flat=True)) == {vouch}


def test_resend_salmentions_returns_no_endpoint_result_and_history(sender, source_url, target_url):
    """Test resend reports and records union targets whose endpoints cannot be discovered."""
    discovered_at = timezone.now() - timedelta(days=2, hours=1)
    sent_at = timezone.now() - timedelta(days=2)
    WebmentionOutboundTarget.objects.create(
        source_url=source_url,
        target_url="https://history.example/post",
        endpoint_url="https://history.example/old-webmention",
        endpoint_discovered_at=discovered_at,
        first_sent_at=sent_at,
        last_sent_at=sent_at,
    )

    with patch.object(sender, "discover_endpoint", return_value=None):
        with patch.object(sender, "send_webmention") as send:
            results = sender.resend_salmentions(source_url, "<p>No current links</p>")

    assert results == [
        {
            "success": False,
            "status_code": None,
            "error": "No endpoint found",
            "target": "https://history.example/post",
            "endpoint": None,
            "provenance": "history",
        }
    ]
    send.assert_not_called()
    target = WebmentionOutboundTarget.objects.get(source_url=source_url, target_url="https://history.example/post")
    assert target.last_success is False
    assert target.last_status_code is None
    assert target.last_error == "No endpoint found"
    assert target.consecutive_failures == 1
    assert target.endpoint_url == "https://history.example/old-webmention"
    assert target.endpoint_discovered_at == discovered_at
    assert target.first_sent_at == sent_at
    assert target.last_sent_at == sent_at


def test_resend_salmentions_current_no_endpoint_records_unsent_history(sender, source_url, target_url):
    """Test no-endpoint current resend history is not marked as sent."""
    html_content = '<a href="https://current.example/post">Current</a>'
    discovered_at = timezone.now()

    with patch("indieweb.senders.timezone.now", return_value=discovered_at):
        with patch.object(sender, "discover_endpoint", return_value=None):
            with patch.object(sender, "send_webmention") as send:
                results = sender.resend_salmentions(source_url, html_content)

    assert results == [
        {
            "success": False,
            "status_code": None,
            "error": "No endpoint found",
            "target": "https://current.example/post",
            "endpoint": None,
            "provenance": "current",
        }
    ]
    send.assert_not_called()
    target = WebmentionOutboundTarget.objects.get(source_url=source_url, target_url="https://current.example/post")
    assert target.endpoint_url == ""
    assert target.endpoint_discovered_at is None
    assert target.first_sent_at is None
    assert target.last_sent_at is None
    assert target.last_success is False
    assert target.last_status_code is None
    assert target.last_error == "No endpoint found"
    assert target.consecutive_failures == 1
    assert target.last_seen_in_source_at == discovered_at


@override_settings(INDIEWEB_SALMENTION_RESEND_COOLDOWN_SECONDS=3600)
def test_resend_salmentions_skips_historical_target_inside_cooldown(sender, source_url, target_url):
    """Historical-only targets inside the resend cooldown are skipped without mutation."""
    attempted_at = timezone.now() - timedelta(minutes=30)
    target = WebmentionOutboundTarget.objects.create(
        source_url=source_url,
        target_url="https://history.example/post",
        last_attempted_at=attempted_at,
        consecutive_failures=1,
        last_error="HTTP 500",
    )

    with patch.object(sender, "discover_endpoint") as discover:
        with patch.object(sender, "send_webmention") as send:
            results = sender.resend_salmentions(source_url, "<p>No current links</p>")

    assert results == [
        {
            "success": False,
            "status_code": None,
            "error": "Historical target skipped during resend cooldown",
            "target": "https://history.example/post",
            "endpoint": None,
            "provenance": "history",
            "skipped": True,
            "skip_reason": "cooldown",
        }
    ]
    discover.assert_not_called()
    send.assert_not_called()
    target.refresh_from_db()
    assert target.last_attempted_at == attempted_at
    assert target.consecutive_failures == 1


@override_settings(
    INDIEWEB_SALMENTION_RESEND_COOLDOWN_SECONDS=60,
    INDIEWEB_SALMENTION_SUCCESS_CUTOFF_SECONDS=3600,
)
def test_resend_salmentions_skips_old_successful_historical_target(sender, source_url, target_url):
    """Old successful historical-only targets stop being re-pinged."""
    old_seen_at = timezone.now() - timedelta(hours=2)
    WebmentionOutboundTarget.objects.create(
        source_url=source_url,
        target_url="https://history.example/post",
        first_sent_at=old_seen_at,
        last_sent_at=old_seen_at,
        last_attempted_at=old_seen_at,
        last_seen_in_source_at=old_seen_at,
        last_success=True,
    )

    with patch.object(sender, "discover_endpoint") as discover:
        results = sender.resend_salmentions(source_url, "<p>No current links</p>")

    assert results[0]["skipped"] is True
    assert results[0]["skip_reason"] == "success_cutoff"
    discover.assert_not_called()
    assert WebmentionOutboundTarget.objects.count() == 1


@override_settings(
    INDIEWEB_SALMENTION_RESEND_COOLDOWN_SECONDS=60,
    INDIEWEB_SALMENTION_SUCCESS_CUTOFF_SECONDS=3600,
)
def test_resend_salmentions_attempts_recent_successful_historical_target(sender, source_url, target_url):
    """Successful historical-only targets remain eligible before the success cutoff."""
    seen_at = timezone.now() - timedelta(minutes=30)
    attempted_at = timezone.now() - timedelta(minutes=2)
    WebmentionOutboundTarget.objects.create(
        source_url=source_url,
        target_url="https://history.example/post",
        first_sent_at=seen_at,
        last_sent_at=attempted_at,
        last_attempted_at=attempted_at,
        last_seen_in_source_at=seen_at,
        last_success=True,
    )

    with patch.object(sender, "discover_endpoint", return_value="https://history.example/webmention") as discover:
        with patch.object(sender, "send_webmention", return_value={"success": True, "status_code": 202}) as send:
            results = sender.resend_salmentions(source_url, "<p>No current links</p>")

    assert results[0]["success"] is True
    discover.assert_called_once_with("https://history.example/post")
    send.assert_called_once()


@override_settings(INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES=2)
def test_resend_salmentions_drops_historical_target_after_failure_limit(sender, source_url, target_url):
    """A historical-only failure that reaches the limit is recorded then deleted."""
    WebmentionOutboundTarget.objects.create(
        source_url=source_url,
        target_url="https://history.example/post",
        consecutive_failures=1,
    )

    with patch.object(sender, "discover_endpoint", return_value=None):
        results = sender.resend_salmentions(source_url, "<p>No current links</p>")

    assert results[0]["dropped"] is True
    assert results[0]["skipped"] is True
    assert results[0]["skip_reason"] == "failure_drop"
    assert "dropped" in results[0]["error"]
    assert not WebmentionOutboundTarget.objects.filter(source_url=source_url).exists()


@override_settings(INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES=2)
def test_resend_salmentions_drops_previously_exhausted_historical_target(sender, source_url, target_url):
    """Historical-only targets already at the failure limit are deleted without rediscovery."""
    WebmentionOutboundTarget.objects.create(
        source_url=source_url,
        target_url="https://history.example/post",
        consecutive_failures=2,
    )

    with patch.object(sender, "discover_endpoint") as discover:
        results = sender.resend_salmentions(source_url, "<p>No current links</p>")

    assert results[0]["skipped"] is True
    assert results[0]["dropped"] is True
    assert results[0]["skip_reason"] == "failure_drop"
    discover.assert_not_called()
    assert not WebmentionOutboundTarget.objects.filter(source_url=source_url).exists()


@override_settings(
    INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES=2,
    INDIEWEB_SALMENTION_RESEND_COOLDOWN_SECONDS=86400,
    INDIEWEB_SALMENTION_SUCCESS_CUTOFF_SECONDS=3600,
)
def test_resend_salmentions_current_target_bypasses_historical_policy(sender, source_url, target_url):
    """Current targets are still attempted even when historical-only policy would skip them."""
    old_time = timezone.now() - timedelta(days=3)
    html_content = '<a href="https://history.example/post">Current again</a>'
    WebmentionOutboundTarget.objects.create(
        source_url=source_url,
        target_url="https://history.example/post",
        first_sent_at=old_time,
        last_sent_at=old_time,
        last_attempted_at=timezone.now(),
        last_seen_in_source_at=old_time,
        last_success=True,
        consecutive_failures=2,
    )

    with patch.object(sender, "discover_endpoint", return_value="https://history.example/webmention"):
        with patch.object(sender, "send_webmention", return_value={"success": True, "status_code": 202}) as send:
            results = sender.resend_salmentions(source_url, html_content)

    assert results[0]["provenance"] == "both"
    assert results[0]["success"] is True
    send.assert_called_once()
    assert WebmentionOutboundTarget.objects.get(source_url=source_url).consecutive_failures == 0


@override_settings(INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES=2)
def test_salmention_preview_does_not_mutate_policy_state(sender, source_url, target_url):
    """Dry-run preview reports policy drops without deleting or updating history."""
    target = WebmentionOutboundTarget.objects.create(
        source_url=source_url,
        target_url="https://history.example/post",
        consecutive_failures=2,
    )

    with patch.object(sender, "discover_endpoint") as discover:
        results = sender.preview_salmention_resend_targets(source_url, "<p>No current links</p>")

    assert results[0]["dry_run"] is True
    assert results[0]["dropped"] is True
    discover.assert_not_called()
    target.refresh_from_db()
    assert target.consecutive_failures == 2


def test_resend_salmentions_returns_empty_when_content_fetch_fails(sender, source_url, target_url):
    """Test resend mirrors ordinary fetch failure behavior."""
    with patch.object(sender, "fetch_content", return_value=None):
        results = sender.resend_salmentions(source_url)

    assert results == []


# ----------------------------------------------------------------------------
# Endpoint discovery must require an exact ``webmention`` rel token, not a
# substring match. The previous regex ``\bwebmention\b`` matched values like
# ``not-webmention`` and ``webmention-foo`` because ``-`` is a non-word
# character at a regex word boundary.
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "link_value",
    [
        '<https://target.com/wm>; rel="not-webmention"',
        '<https://target.com/wm>; rel="webmention-foo"',
        '<https://target.com/wm>; rel="foo-webmention-bar"',
    ],
)
def test_parse_link_header_rejects_substring_rel_values(sender, link_value):
    """Substring matches for ``webmention`` in a rel value must not advertise an endpoint."""
    assert sender._parse_link_header(link_value) is None


@pytest.mark.parametrize(
    "link_value, expected",
    [
        ('<https://target.com/wm>; rel="webmention"', "https://target.com/wm"),
        ('<https://target.com/wm>; rel="webmention next"', "https://target.com/wm"),
        ('<https://target.com/wm>; rel="next webmention"', "https://target.com/wm"),
        ('<https://target.com/wm>; rel="WEBMENTION"', "https://target.com/wm"),
        # ``rel`` may appear after other parameters (RFC 8288 makes no
        # ordering requirement). The previous regex only matched ``rel``
        # immediately after ``<url>;`` and silently dropped these.
        ('<https://target.com/wm>; type="text/html"; rel="webmention"', "https://target.com/wm"),
        ('<https://target.com/wm>; hreflang="en"; rel="webmention"; title="WM"', "https://target.com/wm"),
    ],
)
def test_parse_link_header_accepts_exact_webmention_token(sender, link_value, expected):
    assert sender._parse_link_header(link_value) == expected


@pytest.mark.parametrize(
    "html",
    [
        '<link rel="not-webmention" href="https://target.com/wm">',
        '<link rel="webmention-foo" href="https://target.com/wm">',
        '<a rel="foo-webmention-bar" href="https://target.com/wm">x</a>',
    ],
)
def test_parse_html_for_endpoint_rejects_substring_rel_values(sender, html):
    """An HTML rel attribute that merely contains ``webmention`` as a substring must
    not be treated as a webmention endpoint declaration."""
    assert sender._parse_html_for_endpoint(html, "https://target.com/their-post") is None


def test_parse_html_for_endpoint_accepts_exact_token_in_rel_list(sender):
    html = '<link rel="next webmention" href="https://target.com/wm">'
    assert sender._parse_html_for_endpoint(html, "https://target.com/their-post") == "https://target.com/wm"
