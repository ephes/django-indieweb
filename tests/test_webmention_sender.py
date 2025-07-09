from unittest.mock import Mock, patch

from django.test import TestCase

from indieweb.senders import WebmentionSender


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

        assert "https://example.com/page1" in urls
        assert "https://example.com/page2" in urls
        assert "/relative" in urls
        assert len(urls) == 3

    def test_extract_urls_handles_duplicates(self):
        """Test that duplicate URLs are only returned once."""
        html = """
        <a href="https://example.com/page">link</a>
        <a href="https://example.com/page">same link</a>
        """

        urls = self.sender.extract_urls(html)

        assert len(urls) == 1
        assert "https://example.com/page" in urls

    @patch("indieweb.senders.requests.head")
    def test_discover_endpoint_from_link_header(self, mock_head):
        """Test discovering webmention endpoint from Link header."""
        mock_response = Mock()
        mock_response.headers = {"Link": '<https://target.com/webmention>; rel="webmention"'}
        mock_response.raise_for_status = Mock()
        mock_head.return_value = mock_response

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint == "https://target.com/webmention"
        mock_head.assert_called_once_with(self.target_url, timeout=10)

    @patch("indieweb.senders.requests.head")
    def test_discover_endpoint_from_link_header_with_multiple_rels(self, mock_head):
        """Test discovering webmention endpoint from Link header with multiple rel values."""
        mock_response = Mock()
        mock_response.headers = {"Link": '<https://target.com/webmention>; rel="webmention alternate"'}
        mock_response.raise_for_status = Mock()
        mock_head.return_value = mock_response

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint == "https://target.com/webmention"

    @patch("indieweb.senders.requests.get")
    @patch("indieweb.senders.requests.head")
    def test_discover_endpoint_from_html_link_tag(self, mock_head, mock_get):
        """Test discovering webmention endpoint from HTML link tag."""
        mock_head_response = Mock()
        mock_head_response.headers = {}
        mock_head_response.raise_for_status = Mock()
        mock_head.return_value = mock_head_response

        mock_get_response = Mock()
        mock_get_response.text = """
        <html>
        <head>
            <link rel="webmention" href="https://target.com/webmention" />
        </head>
        </html>
        """
        mock_get_response.raise_for_status = Mock()
        mock_get.return_value = mock_get_response

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint == "https://target.com/webmention"
        mock_get.assert_called_once_with(self.target_url, timeout=10)

    @patch("indieweb.senders.requests.get")
    @patch("indieweb.senders.requests.head")
    def test_discover_endpoint_from_html_a_tag(self, mock_head, mock_get):
        """Test discovering webmention endpoint from HTML a tag."""
        mock_head_response = Mock()
        mock_head_response.headers = {}
        mock_head_response.raise_for_status = Mock()
        mock_head.return_value = mock_head_response

        mock_get_response = Mock()
        mock_get_response.text = """
        <html>
        <body>
            <a rel="webmention" href="https://target.com/webmention">Webmention</a>
        </body>
        </html>
        """
        mock_get_response.raise_for_status = Mock()
        mock_get.return_value = mock_get_response

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint == "https://target.com/webmention"

    @patch("indieweb.senders.requests.get")
    @patch("indieweb.senders.requests.head")
    def test_discover_endpoint_relative_url(self, mock_head, mock_get):
        """Test discovering webmention endpoint with relative URL."""
        mock_head_response = Mock()
        mock_head_response.headers = {}
        mock_head_response.raise_for_status = Mock()
        mock_head.return_value = mock_head_response

        mock_get_response = Mock()
        mock_get_response.text = """
        <html>
        <head>
            <link rel="webmention" href="/webmention" />
        </head>
        </html>
        """
        mock_get_response.raise_for_status = Mock()
        mock_get.return_value = mock_get_response

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint == "https://target.com/webmention"

    @patch("indieweb.senders.requests.get")
    @patch("indieweb.senders.requests.head")
    def test_discover_endpoint_not_found(self, mock_head, mock_get):
        """Test when no webmention endpoint is found."""
        mock_head_response = Mock()
        mock_head_response.headers = {}
        mock_head_response.raise_for_status = Mock()
        mock_head.return_value = mock_head_response

        mock_get_response = Mock()
        mock_get_response.text = "<html><body>No webmention here</body></html>"
        mock_get_response.raise_for_status = Mock()
        mock_get.return_value = mock_get_response

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint is None

    @patch("indieweb.senders.requests.head")
    def test_discover_endpoint_handles_request_exception(self, mock_head):
        """Test handling request exceptions during endpoint discovery."""
        mock_head.side_effect = Exception("Network error")

        endpoint = self.sender.discover_endpoint(self.target_url)

        assert endpoint is None

    @patch("indieweb.senders.requests.post")
    def test_send_webmention_success(self, mock_post):
        """Test successfully sending a webmention."""
        mock_response = Mock()
        mock_response.status_code = 202
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        result = self.sender.send_webmention(self.source_url, self.target_url, "https://target.com/webmention")

        assert result["success"] is True
        assert result["status_code"] == 202
        mock_post.assert_called_once_with(
            "https://target.com/webmention", data={"source": self.source_url, "target": self.target_url}, timeout=30
        )

    @patch("indieweb.senders.requests.post")
    def test_send_webmention_with_different_success_codes(self, mock_post):
        """Test various successful status codes."""
        success_codes = [200, 201, 202]

        for code in success_codes:
            mock_response = Mock()
            mock_response.status_code = code
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response

            result = self.sender.send_webmention(self.source_url, self.target_url, "https://target.com/webmention")

            assert result["success"] is True
            assert result["status_code"] == code

    @patch("indieweb.senders.requests.post")
    def test_send_webmention_failure(self, mock_post):
        """Test handling webmention sending failure."""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"
        mock_post.return_value = mock_response

        result = self.sender.send_webmention(self.source_url, self.target_url, "https://target.com/webmention")

        assert result["success"] is False
        assert result["status_code"] == 400
        assert "error" in result
        assert result["error"] == "HTTP 400"

    @patch("indieweb.senders.requests.post")
    def test_send_webmention_network_error(self, mock_post):
        """Test handling network errors when sending webmention."""
        mock_post.side_effect = Exception("Network error")

        result = self.sender.send_webmention(self.source_url, self.target_url, "https://target.com/webmention")

        assert result["success"] is False
        assert result["error"] == "Network error"
        assert result["status_code"] is None

    @patch("indieweb.senders.requests.get")
    def test_send_webmentions_full_flow(self, mock_get):
        """Test the full flow of sending webmentions."""
        html_content = """
        <html>
        <body>
            <a href="https://target1.com/post">First link</a>
            <a href="https://target2.com/post">Second link</a>
            <a href="https://example.com/my-post">Self link</a>
        </body>
        </html>
        """

        # Mock discovery responses
        with patch.object(self.sender, "discover_endpoint") as mock_discover:
            with patch.object(self.sender, "send_webmention") as mock_send:
                mock_discover.side_effect = ["https://target1.com/webmention", "https://target2.com/webmention"]

                mock_send.side_effect = [
                    {"success": True, "status_code": 202},
                    {"success": False, "status_code": 400, "error": "Bad request"},
                ]

                results = self.sender.send_webmentions(self.source_url, html_content)

                assert len(results) == 2

                # Sort results by target URL for consistent testing
                results_by_target = {r["target"]: r for r in results}

                # Verify both targets are in results
                assert "https://target1.com/post" in results_by_target
                assert "https://target2.com/post" in results_by_target

                # One should succeed, one should fail
                success_count = sum(1 for r in results if r["success"])
                assert success_count == 1

                # Should not try to discover endpoint for self-links
                assert mock_discover.call_count == 2
                assert mock_send.call_count == 2

    def test_send_webmentions_without_html_content(self):
        """Test sending webmentions when HTML content needs to be fetched."""
        html_content = """
        <html>
        <body>
            <a href="https://target.com/post">Link</a>
        </body>
        </html>
        """

        with patch.object(self.sender, "fetch_content") as mock_fetch:
            with patch.object(self.sender, "discover_endpoint") as mock_discover:
                with patch.object(self.sender, "send_webmention") as mock_send:
                    mock_fetch.return_value = html_content
                    mock_discover.return_value = "https://target.com/webmention"
                    mock_send.return_value = {"success": True, "status_code": 202}

                    results = self.sender.send_webmentions(self.source_url)

                    mock_fetch.assert_called_once_with(self.source_url)
                    assert len(results) == 1
                    assert results[0]["success"] is True

    @patch("indieweb.senders.requests.get")
    def test_fetch_content(self, mock_get):
        """Test fetching content from a URL."""
        mock_response = Mock()
        mock_response.text = "<html><body>Content</body></html>"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        content = self.sender.fetch_content(self.source_url)

        assert content == "<html><body>Content</body></html>"
        mock_get.assert_called_once_with(self.source_url, timeout=10)

    @patch("indieweb.senders.requests.get")
    def test_fetch_content_error(self, mock_get):
        """Test handling errors when fetching content."""
        mock_get.side_effect = Exception("Network error")

        content = self.sender.fetch_content(self.source_url)

        assert content is None
