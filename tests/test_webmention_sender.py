from unittest.mock import Mock, patch

from django.test import TestCase

from indieweb.senders import WebmentionSender


def _sender_response(*, status_code=200, text="", headers=None):
    """Build a mocked HTTP response for sender redirect tests."""
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = text
    mock_response.headers = headers if headers is not None else {}
    mock_response.raise_for_status = Mock()
    return mock_response


class TestWebmentionSender(TestCase):
    """Test cases for WebmentionSender."""

    def setUp(self):
        self.sender = WebmentionSender()
        self.source_url = "https://example.com/my-post"
        self.target_url = "https://target.com/their-post"

    def test_extract_urls_from_html(self):
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

        urls = self.sender.extract_urls(html)

        assert len(urls) == 3
        assert "https://example.com/page1" in urls
        assert "https://example.com/page2" in urls
        assert "/relative" in urls

    def test_extract_urls_handles_duplicates(self):
        """Test that duplicate URLs are removed."""
        html = """
        <html>
        <body>
            <p><a href="https://example.com/page">Link 1</a></p>
            <p><a href="https://example.com/page">Link 2</a></p>
        </body>
        </html>
        """

        urls = self.sender.extract_urls(html)

        assert len(urls) == 1
        assert "https://example.com/page" in urls

    @patch("httpx.Client")
    def test_discover_endpoint_from_link_header(self, mock_client_class):
        """Test discovering webmention endpoint from Link header."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        mock_response = Mock()
        mock_response.headers = {"Link": '<https://target.com/webmention>; rel="webmention"'}
        mock_response.raise_for_status = Mock()
        mock_client.head.return_value = mock_response

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint == "https://target.com/webmention"
        mock_client.head.assert_called_once_with(self.target_url, timeout=10)

    @patch("httpx.Client")
    def test_discover_endpoint_follows_redirect_to_link_header(self, mock_client_class):
        """Test endpoint discovery follows target redirects before reading Link headers."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        final_url = "https://target.com/canonical/their-post"
        mock_client.head.side_effect = [
            _sender_response(status_code=302, headers={"Location": final_url}),
            _sender_response(status_code=200, headers={"Link": '<https://target.com/webmention>; rel="webmention"'}),
        ]

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint == "https://target.com/webmention"
        assert mock_client.head.call_args_list[0].args[0] == self.target_url
        assert mock_client.head.call_args_list[1].args[0] == final_url

    @patch("httpx.Client")
    def test_discover_endpoint_resolves_relative_link_header_against_final_url(self, mock_client_class):
        """Test relative Link endpoints after redirects use the final target page URL."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        final_url = "https://target.com/canonical/their-post"
        mock_client.head.side_effect = [
            _sender_response(status_code=301, headers={"Location": final_url}),
            _sender_response(status_code=200, headers={"Link": '<wm>; rel="webmention"'}),
        ]

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint == "https://target.com/canonical/wm"

    @patch("httpx.Client")
    def test_discover_endpoint_from_link_header_with_multiple_rels(self, mock_client_class):
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

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint == "https://target.com/webmention"

    @patch("httpx.Client")
    def test_discover_endpoint_from_html_link_tag(self, mock_client_class):
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

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint == "https://target.com/webmention-endpoint"
        mock_client.head.assert_called_once()
        mock_client.get.assert_called_once_with(self.target_url, timeout=10)

    @patch("httpx.Client")
    def test_discover_endpoint_resolves_html_endpoint_against_final_url(self, mock_client_class):
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

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint == "https://target.com/canonical/wm"

    @patch("httpx.Client")
    def test_discover_endpoint_from_html_a_tag(self, mock_client_class):
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

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint == "https://target.com/webmention"

    @patch("httpx.Client")
    def test_discover_endpoint_relative_url(self, mock_client_class):
        """Test that relative URLs are resolved correctly."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        mock_response = Mock()
        mock_response.headers = {"Link": '</api/webmention>; rel="webmention"'}
        mock_response.raise_for_status = Mock()
        mock_client.head.return_value = mock_response

        endpoint = self.sender.discover_endpoint("https://example.com/post/123")

        assert endpoint == "https://example.com/api/webmention"

    @patch("httpx.Client")
    def test_discover_endpoint_not_found(self, mock_client_class):
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

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint is None

    @patch("httpx.Client")
    def test_discover_endpoint_handles_request_exception(self, mock_client_class):
        """Test that discovery handles request exceptions gracefully."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.head.side_effect = Exception("Network error")

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint is None

    @patch("httpx.Client")
    def test_send_webmention_success(self, mock_client_class):
        """Test successful webmention sending."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        mock_response = Mock()
        mock_response.status_code = 201
        mock_client.post.return_value = mock_response

        endpoint = "https://target.com/webmention"
        result = self.sender.send_webmention(self.source_url, self.target_url, endpoint)

        assert result["success"] is True
        assert result["status_code"] == 201
        mock_client.post.assert_called_once_with(
            endpoint, data={"source": self.source_url, "target": self.target_url}, timeout=30
        )

    @patch("httpx.Client")
    def test_send_webmention_preserves_post_payload_across_endpoint_redirect(self, mock_client_class):
        """Test endpoint redirects keep the Webmention POST body."""
        endpoint = "https://target.com/webmention"
        final_endpoint = "https://target.com/api/webmention"

        for redirect_status_code in [301, 302, 303, 307, 308]:
            with self.subTest(redirect_status_code=redirect_status_code):
                mock_client = Mock()
                mock_client_class.return_value.__enter__.return_value = mock_client
                mock_client.post.side_effect = [
                    _sender_response(status_code=redirect_status_code, headers={"Location": final_endpoint}),
                    _sender_response(status_code=202),
                ]

                result = self.sender.send_webmention(self.source_url, self.target_url, endpoint)

                assert result["success"] is True
                assert result["status_code"] == 202
                assert mock_client.post.call_args_list[0].args[0] == endpoint
                assert mock_client.post.call_args_list[1].args[0] == final_endpoint
                for call in mock_client.post.call_args_list:
                    assert call.kwargs["data"] == {"source": self.source_url, "target": self.target_url}

    @patch("httpx.Client")
    def test_send_webmention_resolves_relative_endpoint_redirect_location(self, mock_client_class):
        """Test relative endpoint redirect locations resolve against the redirecting URL."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        endpoint = "https://target.com/webmention"
        mock_client.post.side_effect = [
            _sender_response(status_code=302, headers={"Location": "/api/webmention"}),
            _sender_response(status_code=202),
        ]

        result = self.sender.send_webmention(self.source_url, self.target_url, endpoint)

        assert result["success"] is True
        assert mock_client.post.call_args_list[1].args[0] == "https://target.com/api/webmention"

    @patch("httpx.Client")
    def test_send_webmention_with_different_success_codes(self, mock_client_class):
        """Test that 200, 201, and 202 are all considered success."""
        for status_code in [200, 201, 202]:
            mock_client = Mock()
            mock_client_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = status_code
            mock_client.post.return_value = mock_response

            result = self.sender.send_webmention(self.source_url, self.target_url, "https://example.com/webmention")

            assert result["success"] is True
            assert result["status_code"] == status_code

    @patch("httpx.Client")
    def test_send_webmention_failure(self, mock_client_class):
        """Test failed webmention sending."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        mock_response = Mock()
        mock_response.status_code = 404
        mock_client.post.return_value = mock_response

        endpoint = "https://target.com/webmention"
        result = self.sender.send_webmention(self.source_url, self.target_url, endpoint)

        assert result["success"] is False
        assert result["status_code"] == 404
        assert "error" in result

    @patch("httpx.Client")
    def test_send_webmention_network_error(self, mock_client_class):
        """Test webmention sending with network error."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        import httpx

        mock_client.post.side_effect = httpx.RequestError("Connection failed")

        endpoint = "https://target.com/webmention"
        result = self.sender.send_webmention(self.source_url, self.target_url, endpoint)

        assert result["success"] is False
        assert "Connection failed" in result["error"]

    @patch("httpx.Client")
    def test_fetch_content(self, mock_client_class):
        """Test fetching content from a URL."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        mock_response = Mock()
        mock_response.text = "<html><body>Test content</body></html>"
        mock_response.raise_for_status = Mock()
        mock_client.get.return_value = mock_response

        content = self.sender.fetch_content("https://example.com/page")

        assert content == "<html><body>Test content</body></html>"
        mock_client.get.assert_called_once_with("https://example.com/page", timeout=10)

    @patch("httpx.Client")
    def test_fetch_content_follows_redirect(self, mock_client_class):
        """Test fetching source content follows bounded redirects."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        final_url = "https://example.com/canonical/page"
        mock_client.get.side_effect = [
            _sender_response(status_code=302, headers={"Location": final_url}),
            _sender_response(status_code=200, text="<html><body>Final content</body></html>"),
        ]

        content = self.sender.fetch_content("https://example.com/page")

        assert content == "<html><body>Final content</body></html>"
        assert mock_client.get.call_args_list[0].args[0] == "https://example.com/page"
        assert mock_client.get.call_args_list[1].args[0] == final_url

    @patch("httpx.Client")
    def test_fetch_content_resolves_relative_redirect_location(self, mock_client_class):
        """Test relative content redirect locations resolve against the redirecting URL."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.get.side_effect = [
            _sender_response(status_code=302, headers={"Location": "/canonical/page"}),
            _sender_response(status_code=200, text="<html><body>Final content</body></html>"),
        ]

        content = self.sender.fetch_content("https://example.com/page")

        assert content == "<html><body>Final content</body></html>"
        assert mock_client.get.call_args_list[1].args[0] == "https://example.com/canonical/page"

    @patch("httpx.Client")
    def test_discover_endpoint_returns_none_when_redirect_limit_exceeded(self, mock_client_class):
        """Test discovery returns None for redirect errors."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.head.side_effect = [
            _sender_response(status_code=302, headers={"Location": f"https://target.com/r{i}"}) for i in range(6)
        ]

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint is None

    @patch("httpx.Client")
    def test_fetch_content_returns_none_when_redirect_limit_exceeded(self, mock_client_class):
        """Test content fetch returns None for redirect errors."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.get.side_effect = [
            _sender_response(status_code=302, headers={"Location": f"https://example.com/r{i}"}) for i in range(6)
        ]

        content = self.sender.fetch_content("https://example.com/page")

        assert content is None

    @patch("httpx.Client")
    def test_fetch_content_returns_none_for_unsupported_redirect_scheme(self, mock_client_class):
        """Test redirects only continue to HTTP and HTTPS URLs."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.get.return_value = _sender_response(status_code=302, headers={"Location": "mailto:a@example.com"})

        content = self.sender.fetch_content("https://example.com/page")

        assert content is None
        assert mock_client.get.call_count == 1

    @patch("httpx.Client")
    def test_send_webmention_returns_failure_when_redirect_limit_exceeded(self, mock_client_class):
        """Test endpoint POST redirect errors use the safe failure shape."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.side_effect = [
            _sender_response(status_code=302, headers={"Location": f"https://target.com/r{i}"}) for i in range(6)
        ]

        result = self.sender.send_webmention(
            self.source_url,
            self.target_url,
            "https://target.com/webmention",
        )

        assert result["success"] is False
        assert result["status_code"] is None
        assert "redirects" in result["error"]

    @patch("httpx.Client")
    def test_fetch_content_error(self, mock_client_class):
        """Test fetching content handles errors."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.get.side_effect = Exception("Network error")

        content = self.sender.fetch_content("https://example.com/page")

        assert content is None

    def test_send_webmentions_without_html_content(self):
        """Test send_webmentions when HTML content is not provided."""
        with patch.object(self.sender, "fetch_content") as mock_fetch:
            # Link to a different domain so it's not skipped
            mock_fetch.return_value = '<html><body><a href="https://otherdomain.com/link">Link</a></body></html>'

            with patch.object(self.sender, "discover_endpoint") as mock_discover:
                mock_discover.return_value = "https://otherdomain.com/webmention"

                with patch.object(self.sender, "send_webmention") as mock_send:
                    mock_send.return_value = {"success": True, "status_code": 201}

                    results = self.sender.send_webmentions(self.source_url)

                    mock_fetch.assert_called_once_with(self.source_url)
                    assert len(results) == 1
                    assert results[0]["target"] == "https://otherdomain.com/link"

    def test_send_webmentions_full_flow(self):
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
        with patch.object(self.sender, "discover_endpoint") as mock_discover:

            def discover_side_effect(url):
                if "target1.com" in url:
                    return "https://target1.com/webmention"
                elif "target2.com" in url:
                    return None  # No endpoint
                return None

            mock_discover.side_effect = discover_side_effect

            # Mock sending
            with patch.object(self.sender, "send_webmention") as mock_send:
                mock_send.return_value = {"success": True, "status_code": 201}

                results = self.sender.send_webmentions(self.source_url, html_content)

                # Should discover endpoints for both external URLs
                assert mock_discover.call_count == 2
                # Should only send to target1 (which has an endpoint)
                assert mock_send.call_count == 1
                assert len(results) == 1
                assert results[0]["target"] == "https://target1.com/post"
                assert results[0]["success"] is True

    @patch("httpx.Client")
    def test_discover_endpoint_handles_fragment_and_query(self, mock_client_class):
        """Test that fragments and query strings don't interfere with endpoint discovery."""
        mock_client = Mock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        mock_response = Mock()
        mock_response.headers = {"Link": '<https://target.com/webmention>; rel="webmention"'}
        mock_response.raise_for_status = Mock()
        mock_client.head.return_value = mock_response

        # URL with fragment and query
        endpoint = self.sender.discover_endpoint("https://target.com/post?param=value#section")

        assert endpoint == "https://target.com/webmention"
