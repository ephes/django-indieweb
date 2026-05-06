from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone

from indieweb.http_client import SAFE_HTTP_DEFAULT_TIMEOUT
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
    """Build a mocked HTTP response for sender redirect tests."""
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = text
    mock_response.headers = headers if headers is not None else {}
    mock_response.raise_for_status = Mock()
    return mock_response


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


@patch("httpx.Client")
def test_discover_endpoint_from_link_header(mock_client_class, sender, source_url, target_url):
    """Test discovering webmention endpoint from Link header."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    mock_response = Mock()
    mock_response.headers = {"Link": '<https://target.com/webmention>; rel="webmention"'}
    mock_response.raise_for_status = Mock()
    mock_client.head.return_value = mock_response

    endpoint = sender.discover_endpoint(target_url)

    assert endpoint == "https://target.com/webmention"
    mock_client.head.assert_called_once_with(target_url, timeout=10)


@patch("httpx.Client")
def test_discover_endpoint_follows_redirect_to_link_header(mock_client_class, sender, source_url, target_url):
    """Test endpoint discovery follows target redirects before reading Link headers."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client
    final_url = "https://target.com/canonical/their-post"
    mock_client.head.side_effect = [
        _sender_response(status_code=302, headers={"Location": final_url}),
        _sender_response(status_code=200, headers={"Link": '<https://target.com/webmention>; rel="webmention"'}),
    ]

    endpoint = sender.discover_endpoint(target_url)

    assert endpoint == "https://target.com/webmention"
    assert mock_client.head.call_args_list[0].args[0] == target_url
    assert mock_client.head.call_args_list[1].args[0] == final_url


@patch("httpx.Client")
def test_discover_endpoint_resolves_relative_link_header_against_final_url(
    mock_client_class, sender, source_url, target_url
):
    """Test relative Link endpoints after redirects use the final target page URL."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client
    final_url = "https://target.com/canonical/their-post"
    mock_client.head.side_effect = [
        _sender_response(status_code=301, headers={"Location": final_url}),
        _sender_response(status_code=200, headers={"Link": '<wm>; rel="webmention"'}),
    ]

    endpoint = sender.discover_endpoint(target_url)

    assert endpoint == "https://target.com/canonical/wm"


@patch("httpx.Client")
def test_discover_endpoint_from_link_header_with_multiple_rels(mock_client_class, sender, source_url, target_url):
    """Test discovering webmention endpoint from Link header with multiple rel values."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    mock_response = Mock()
    # Multiple Link headers
    mock_response.headers = {
        "Link": '<https://target.com/other>; rel="other", <https://target.com/webmention>; rel="webmention"'
    }
    mock_response.raise_for_status = Mock()
    mock_client.head.return_value = mock_response

    endpoint = sender.discover_endpoint(target_url)

    assert endpoint == "https://target.com/webmention"


@patch("httpx.Client")
def test_discover_endpoint_from_html_link_tag(mock_client_class, sender, source_url, target_url):
    """Test discovering webmention endpoint from HTML link tag."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    # HEAD request returns no Link header
    mock_head_response = Mock()
    mock_head_response.headers = {}
    mock_head_response.raise_for_status = Mock()
    mock_client.head.return_value = mock_head_response

    # GET request returns HTML with link tag
    mock_get_response = Mock()
    mock_get_response.headers = {}
    mock_get_response.text = """
    <html>
    <head>
        <link rel="webmention" href="/webmention-endpoint" />
    </head>
    </html>
    """
    mock_get_response.raise_for_status = Mock()
    mock_client.get.return_value = mock_get_response

    endpoint = sender.discover_endpoint(target_url)

    assert endpoint == "https://target.com/webmention-endpoint"
    mock_client.head.assert_called_once()
    mock_client.get.assert_called_once_with(target_url, timeout=SAFE_HTTP_DEFAULT_TIMEOUT)


@patch("httpx.Client")
def test_discover_endpoint_resolves_html_endpoint_against_final_url(mock_client_class, sender, source_url, target_url):
    """Test HTML endpoint discovery after redirects uses the final page URL."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client
    final_url = "https://target.com/canonical/their-post"
    mock_client.head.side_effect = [
        _sender_response(status_code=302, headers={"Location": final_url}),
        _sender_response(status_code=200),
    ]
    mock_client.get.side_effect = [
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

    endpoint = sender.discover_endpoint(target_url)

    assert endpoint == "https://target.com/canonical/wm"


@patch("httpx.Client")
def test_discover_endpoint_from_html_a_tag(mock_client_class, sender, source_url, target_url):
    """Test discovering webmention endpoint from HTML a tag."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    # HEAD request returns no Link header
    mock_head_response = Mock()
    mock_head_response.headers = {}
    mock_head_response.raise_for_status = Mock()
    mock_client.head.return_value = mock_head_response

    # GET request returns HTML with a tag
    mock_get_response = Mock()
    mock_get_response.headers = {}
    mock_get_response.text = """
    <html>
    <body>
        <a rel="webmention" href="/webmention">Webmention endpoint</a>
    </body>
    </html>
    """
    mock_get_response.raise_for_status = Mock()
    mock_client.get.return_value = mock_get_response

    endpoint = sender.discover_endpoint(target_url)

    assert endpoint == "https://target.com/webmention"


@patch("httpx.Client")
def test_discover_endpoint_relative_url(mock_client_class, sender, source_url, target_url):
    """Test that relative URLs are resolved correctly."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    mock_response = Mock()
    mock_response.headers = {"Link": '</api/webmention>; rel="webmention"'}
    mock_response.raise_for_status = Mock()
    mock_client.head.return_value = mock_response

    endpoint = sender.discover_endpoint("https://example.com/post/123")

    assert endpoint == "https://example.com/api/webmention"


@patch("httpx.Client")
def test_discover_endpoint_not_found(mock_client_class, sender, source_url, target_url):
    """Test when no webmention endpoint is found."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    # HEAD request returns no Link header
    mock_head_response = Mock()
    mock_head_response.headers = {}
    mock_head_response.raise_for_status = Mock()
    mock_client.head.return_value = mock_head_response

    # GET request returns HTML with no webmention
    mock_get_response = Mock()
    mock_get_response.headers = {}
    mock_get_response.text = "<html><body>No webmention here</body></html>"
    mock_get_response.raise_for_status = Mock()
    mock_client.get.return_value = mock_get_response

    endpoint = sender.discover_endpoint(target_url)

    assert endpoint is None


@patch("httpx.Client")
def test_discover_endpoint_handles_request_exception(mock_client_class, sender, source_url, target_url):
    """Test that discovery handles request exceptions gracefully."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client
    mock_client.head.side_effect = Exception("Network error")

    endpoint = sender.discover_endpoint(target_url)

    assert endpoint is None


@patch("httpx.Client")
def test_send_webmention_success(mock_client_class, sender, source_url, target_url):
    """Test successful webmention sending."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    mock_response = Mock()
    mock_response.status_code = 201
    mock_client.post.return_value = mock_response

    endpoint = "https://target.com/webmention"
    result = sender.send_webmention(source_url, target_url, endpoint)

    assert result["success"] is True
    assert result["status_code"] == 201
    mock_client.post.assert_called_once_with(endpoint, data={"source": source_url, "target": target_url}, timeout=30)


@patch("httpx.Client")
def test_send_webmention_includes_vouch_when_provided(mock_client_class, sender, source_url, target_url):
    """Test sender can opt in to including a Vouch URL."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    mock_response = Mock()
    mock_response.status_code = 202
    mock_client.post.return_value = mock_response

    endpoint = "https://target.com/webmention"
    vouch = "https://trusted.example/vouch-for-example"
    result = sender.send_webmention(source_url, target_url, endpoint, vouch=vouch)

    assert result["success"] is True
    mock_client.post.assert_called_once_with(
        endpoint,
        data={"source": source_url, "target": target_url, "vouch": vouch},
        timeout=30,
    )


@pytest.mark.parametrize("redirect_status_code", [301, 302, 303, 307, 308])
@patch("httpx.Client")
def test_send_webmention_preserves_post_payload_across_endpoint_redirect(
    mock_client_class, sender, source_url, target_url, redirect_status_code
):
    """Test endpoint redirects keep the Webmention POST body."""
    endpoint = "https://target.com/webmention"
    final_endpoint = "https://target.com/api/webmention"

    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client
    mock_client.post.side_effect = [
        _sender_response(status_code=redirect_status_code, headers={"Location": final_endpoint}),
        _sender_response(status_code=202),
    ]

    result = sender.send_webmention(source_url, target_url, endpoint)

    assert result["success"] is True
    assert result["status_code"] == 202
    assert mock_client.post.call_args_list[0].args[0] == endpoint
    assert mock_client.post.call_args_list[1].args[0] == final_endpoint
    for call in mock_client.post.call_args_list:
        assert call.kwargs["data"] == {"source": source_url, "target": target_url}


@patch("httpx.Client")
def test_send_webmention_resolves_relative_endpoint_redirect_location(
    mock_client_class, sender, source_url, target_url
):
    """Test relative endpoint redirect locations resolve against the redirecting URL."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client
    endpoint = "https://target.com/webmention"
    mock_client.post.side_effect = [
        _sender_response(status_code=302, headers={"Location": "/api/webmention"}),
        _sender_response(status_code=202),
    ]

    result = sender.send_webmention(source_url, target_url, endpoint)

    assert result["success"] is True
    assert mock_client.post.call_args_list[1].args[0] == "https://target.com/api/webmention"


@pytest.mark.parametrize("status_code", [200, 201, 202])
@patch("httpx.Client")
def test_send_webmention_with_different_success_codes(mock_client_class, sender, source_url, target_url, status_code):
    """Test that 200, 201, and 202 are all considered success."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    mock_response = Mock()
    mock_response.status_code = status_code
    mock_client.post.return_value = mock_response

    result = sender.send_webmention(source_url, target_url, "https://example.com/webmention")

    assert result["success"] is True
    assert result["status_code"] == status_code


@patch("httpx.Client")
def test_send_webmention_failure(mock_client_class, sender, source_url, target_url):
    """Test failed webmention sending."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    mock_response = Mock()
    mock_response.status_code = 404
    mock_client.post.return_value = mock_response

    endpoint = "https://target.com/webmention"
    result = sender.send_webmention(source_url, target_url, endpoint)

    assert result["success"] is False
    assert result["status_code"] == 404
    assert "error" in result


@patch("httpx.Client")
def test_send_webmention_network_error(mock_client_class, sender, source_url, target_url):
    """Test webmention sending with network error."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    import httpx

    mock_client.post.side_effect = httpx.RequestError("Connection failed")

    endpoint = "https://target.com/webmention"
    result = sender.send_webmention(source_url, target_url, endpoint)

    assert result["success"] is False
    assert "Connection failed" in result["error"]


@patch("httpx.Client")
def test_send_webmention_rejects_unsafe_vouch_without_post(mock_client_class, sender, source_url, target_url):
    """send_webmention validates Vouch even when callers bypass the command."""
    result = sender.send_webmention(
        source_url,
        target_url,
        "https://target.com/webmention",
        vouch="http://127.0.0.1/vouch",
    )

    assert result["success"] is False
    mock_client_class.return_value.__enter__.return_value.post.assert_not_called()


@patch("httpx.Client")
def test_fetch_content(mock_client_class, sender, source_url, target_url):
    """Test fetching content from a URL."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    mock_response = Mock()
    mock_response.text = "<html><body>Test content</body></html>"
    mock_response.raise_for_status = Mock()
    mock_client.get.return_value = mock_response

    content = sender.fetch_content("https://example.com/page")

    assert content == "<html><body>Test content</body></html>"
    mock_client.get.assert_called_once_with("https://example.com/page", timeout=SAFE_HTTP_DEFAULT_TIMEOUT)


@patch("httpx.Client")
def test_fetch_content_follows_redirect(mock_client_class, sender, source_url, target_url):
    """Test fetching source content follows bounded redirects."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client
    final_url = "https://example.com/canonical/page"
    mock_client.get.side_effect = [
        _sender_response(status_code=302, headers={"Location": final_url}),
        _sender_response(status_code=200, text="<html><body>Final content</body></html>"),
    ]

    content = sender.fetch_content("https://example.com/page")

    assert content == "<html><body>Final content</body></html>"
    assert mock_client.get.call_args_list[0].args[0] == "https://example.com/page"
    assert mock_client.get.call_args_list[1].args[0] == final_url


@patch("httpx.Client")
def test_fetch_content_resolves_relative_redirect_location(mock_client_class, sender, source_url, target_url):
    """Test relative content redirect locations resolve against the redirecting URL."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client
    mock_client.get.side_effect = [
        _sender_response(status_code=302, headers={"Location": "/canonical/page"}),
        _sender_response(status_code=200, text="<html><body>Final content</body></html>"),
    ]

    content = sender.fetch_content("https://example.com/page")

    assert content == "<html><body>Final content</body></html>"
    assert mock_client.get.call_args_list[1].args[0] == "https://example.com/canonical/page"


@patch("httpx.Client")
def test_discover_endpoint_returns_none_when_redirect_limit_exceeded(
    mock_client_class, sender, source_url, target_url
):
    """Test discovery returns None for redirect errors."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client
    mock_client.head.side_effect = [
        _sender_response(status_code=302, headers={"Location": f"https://target.com/r{i}"}) for i in range(6)
    ]

    endpoint = sender.discover_endpoint(target_url)

    assert endpoint is None


@patch("httpx.Client")
def test_fetch_content_returns_none_when_redirect_limit_exceeded(mock_client_class, sender, source_url, target_url):
    """Test content fetch returns None for redirect errors."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client
    mock_client.get.side_effect = [
        _sender_response(status_code=302, headers={"Location": f"https://example.com/r{i}"}) for i in range(6)
    ]

    content = sender.fetch_content("https://example.com/page")

    assert content is None


@patch("httpx.Client")
def test_fetch_content_returns_none_for_unsupported_redirect_scheme(mock_client_class, sender, source_url, target_url):
    """Test redirects only continue to HTTP and HTTPS URLs."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client
    mock_client.get.return_value = _sender_response(status_code=302, headers={"Location": "mailto:a@example.com"})

    content = sender.fetch_content("https://example.com/page")

    assert content is None
    assert mock_client.get.call_count == 1


@patch("httpx.Client")
def test_send_webmention_returns_failure_when_redirect_limit_exceeded(
    mock_client_class, sender, source_url, target_url
):
    """Test endpoint POST redirect errors use the safe failure shape."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client
    mock_client.post.side_effect = [
        _sender_response(status_code=302, headers={"Location": f"https://target.com/r{i}"}) for i in range(6)
    ]

    result = sender.send_webmention(
        source_url,
        target_url,
        "https://target.com/webmention",
    )

    assert result["success"] is False
    assert result["status_code"] is None
    assert "redirects" in result["error"]


@patch("httpx.Client")
def test_fetch_content_error(mock_client_class, sender, source_url, target_url):
    """Test fetching content handles errors."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client
    mock_client.get.side_effect = Exception("Network error")

    content = sender.fetch_content("https://example.com/page")

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


@patch("httpx.Client")
def test_discover_endpoint_handles_fragment_and_query(mock_client_class, sender, source_url, target_url):
    """Test that fragments and query strings don't interfere with endpoint discovery."""
    mock_client = Mock()
    mock_client_class.return_value.__enter__.return_value = mock_client

    mock_response = Mock()
    mock_response.headers = {"Link": '<https://target.com/webmention>; rel="webmention"'}
    mock_response.raise_for_status = Mock()
    mock_client.head.return_value = mock_response

    # URL with fragment and query
    endpoint = sender.discover_endpoint("https://target.com/post?param=value#section")

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
    assert target.last_status_code == 202
    assert target.last_success is True
    assert target.last_error == ""
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
    discovered_at = timezone.now() - timedelta(hours=2)
    sent_at = timezone.now() - timedelta(hours=1)
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
    assert target.last_seen_in_source_at == discovered_at


def test_resend_salmentions_returns_empty_when_content_fetch_fails(sender, source_url, target_url):
    """Test resend mirrors ordinary fetch failure behavior."""
    with patch.object(sender, "fetch_content", return_value=None):
        results = sender.resend_salmentions(source_url)

    assert results == []
