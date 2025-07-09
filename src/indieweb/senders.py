"""Webmention sender implementation."""

import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag


class WebmentionSender:
    """Sends webmentions to target URLs."""

    def __init__(self) -> None:
        self.timeout = 10
        self.post_timeout = 30

    def extract_urls(self, html_content: str) -> list[str]:
        """Extract all URLs from HTML content.

        Args:
            html_content: HTML content to parse

        Returns:
            List of unique URLs found in the content
        """
        soup = BeautifulSoup(html_content, "html.parser")
        urls: set[str] = set()

        # Find all anchor tags with href attributes
        for tag in soup.find_all("a", href=True):
            if isinstance(tag, Tag):
                href = tag.get("href")
                if href and isinstance(href, str):
                    urls.add(href)

        return list(urls)

    def discover_endpoint(self, target_url: str) -> str | None:
        """Discover the webmention endpoint for a target URL.

        First checks HTTP Link headers, then falls back to parsing HTML.

        Args:
            target_url: The URL to discover the endpoint for

        Returns:
            The webmention endpoint URL or None if not found
        """
        try:
            # First try HEAD request to check Link headers
            with httpx.Client() as client:
                response = client.head(target_url, timeout=self.timeout)
                response.raise_for_status()

                # Check Link header
                link_header = response.headers.get("Link", "")
                endpoint = self._parse_link_header(link_header)
                if endpoint:
                    return urljoin(target_url, endpoint)

                # Fall back to GET request to parse HTML
                response = client.get(target_url, timeout=self.timeout)
                response.raise_for_status()

                return self._parse_html_for_endpoint(response.text, target_url)

        except Exception:
            # Return None for any errors during discovery
            return None

    def _parse_link_header(self, link_header: str) -> str | None:
        """Parse Link header for webmention endpoint.

        Args:
            link_header: The Link header value

        Returns:
            The webmention endpoint URL or None
        """
        if not link_header:
            return None

        # Match <url>; rel="webmention" or rel="webmention ..." or rel="... webmention"
        pattern = r'<([^>]+)>;\s*rel="[^"]*\bwebmention\b[^"]*"'
        match = re.search(pattern, link_header)

        if match:
            return match.group(1)

        return None

    def _parse_html_for_endpoint(self, html_content: str, base_url: str) -> str | None:
        """Parse HTML for webmention endpoint.

        Args:
            html_content: HTML content to parse
            base_url: Base URL for resolving relative URLs

        Returns:
            The webmention endpoint URL or None
        """
        soup = BeautifulSoup(html_content, "html.parser")

        # Check <link> tags
        link = soup.find("link", rel=lambda x: x and "webmention" in x)
        if link and isinstance(link, Tag):
            href = link.get("href")
            if href and isinstance(href, str):
                return urljoin(base_url, href)

        # Check <a> tags
        a = soup.find("a", rel=lambda x: x and "webmention" in x)
        if a and isinstance(a, Tag):
            href = a.get("href")
            if href and isinstance(href, str):
                return urljoin(base_url, href)

        return None

    def send_webmention(self, source: str, target: str, endpoint: str) -> dict:
        """Send a webmention to an endpoint.

        Args:
            source: The source URL (your post)
            target: The target URL (the linked post)
            endpoint: The webmention endpoint URL

        Returns:
            Dict with 'success', 'status_code', and optionally 'error'
        """
        try:
            with httpx.Client() as client:
                response = client.post(endpoint, data={"source": source, "target": target}, timeout=self.post_timeout)

                # Accept 200, 201, or 202 as success
                if response.status_code in [200, 201, 202]:
                    return {"success": True, "status_code": response.status_code}
                else:
                    # Non-success status code
                    return {
                        "success": False,
                        "status_code": response.status_code,
                        "error": f"HTTP {response.status_code}",
                    }

        except httpx.RequestError as e:
            # Handle httpx exceptions (network errors, timeouts, etc.)
            status_code = None
            if hasattr(e, "response") and e.response is not None:
                status_code = e.response.status_code
            return {"success": False, "status_code": status_code, "error": str(e)}
        except Exception as e:
            # Handle other exceptions
            return {"success": False, "status_code": None, "error": str(e)}

    def fetch_content(self, url: str) -> str | None:
        """Fetch HTML content from a URL.

        Args:
            url: URL to fetch

        Returns:
            HTML content or None if error
        """
        try:
            with httpx.Client() as client:
                response = client.get(url, timeout=self.timeout)
                response.raise_for_status()
                return response.text
        except Exception:
            return None

    def send_webmentions(self, source_url: str, html_content: str | None = None) -> list[dict]:
        """Send webmentions to all URLs found in the content.

        Args:
            source_url: The source URL (your post)
            html_content: Optional HTML content. If not provided, will be fetched.

        Returns:
            List of results for each webmention attempt
        """
        # Fetch content if not provided
        if html_content is None:
            html_content = self.fetch_content(source_url)
            if html_content is None:
                return []

        # Extract URLs from content
        urls = self.extract_urls(html_content)

        # Send webmentions to each URL
        results = []
        source_domain = urlparse(source_url).netloc

        for target_url in urls:
            # Skip relative URLs and self-references
            if not target_url.startswith(("http://", "https://")):
                continue

            target_domain = urlparse(target_url).netloc
            if target_domain == source_domain:
                continue

            # Discover endpoint
            endpoint = self.discover_endpoint(target_url)
            if endpoint:
                # Send webmention
                result = self.send_webmention(source_url, target_url, endpoint)
                result["target"] = target_url
                result["endpoint"] = endpoint
                results.append(result)

        return results
