"""Test cases for Webmention endpoint."""

import json
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

import pytest
from django.contrib.sites.models import Site
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse

from indieweb.models import Webmention
from indieweb.views import WebmentionEndpoint


@pytest.mark.django_db
class TestWebmentionEndpoint:
    """Test cases for the Webmention receiving endpoint."""

    @pytest.fixture
    def client(self):
        return Client()

    @pytest.fixture
    def factory(self):
        return RequestFactory()

    @pytest.fixture
    def site(self):
        return Site.objects.get_current()

    def test_endpoint_exists(self, client):
        """Test that the webmention endpoint is accessible."""
        url = reverse("indieweb:webmention")
        response = client.get(url)
        assert response.status_code == 200
        assert b"Webmention endpoint" in response.content

    def test_endpoint_requires_post(self, client):
        """Test that only POST requests are accepted for webmentions."""
        url = reverse("indieweb:webmention")

        # GET should return info
        response = client.get(url)
        assert response.status_code == 200

        # Other methods should fail
        response = client.put(url)
        assert response.status_code == 405

        response = client.delete(url)
        assert response.status_code == 405

    def test_missing_parameters_returns_400(self, client):
        """Test that missing required parameters return 400."""
        url = reverse("indieweb:webmention")

        # Missing both parameters
        response = client.post(url)
        assert response.status_code == 400

        # Missing source
        response = client.post(url, {"target": "https://example.com/post"})
        assert response.status_code == 400

        # Missing target
        response = client.post(url, {"source": "https://other.com/reply"})
        assert response.status_code == 400

    def test_invalid_urls_return_400(self, client):
        """Test that invalid URLs return 400."""
        url = reverse("indieweb:webmention")

        # Invalid source URL
        response = client.post(
            url,
            {
                "source": "not-a-url",
                "target": "https://example.com/post",
            },
        )
        assert response.status_code == 400

        # Invalid target URL
        response = client.post(
            url,
            {
                "source": "https://other.com/reply",
                "target": "not-a-url",
            },
        )
        assert response.status_code == 400

    def test_target_must_be_on_our_domain(self, client, site):
        """Test that target URL must be on our domain."""
        url = reverse("indieweb:webmention")

        # Target on different domain should fail
        response = client.post(
            url,
            {
                "source": "https://other.com/reply",
                "target": "https://different.com/post",
            },
        )
        assert response.status_code == 400

    @patch("indieweb.views.WebmentionProcessor")
    def test_valid_webmention_creates_record(self, mock_processor_class, client, site):
        """Test that valid webmention creates a record."""
        url = reverse("indieweb:webmention")

        # Mock the processor
        mock_processor = MagicMock()
        mock_processor_class.return_value = mock_processor
        mock_webmention = Webmention(
            id=1,
            source_url="https://other.com/reply",
            target_url=f"https://{site.domain}/post",
        )
        mock_processor.process_webmention.return_value = mock_webmention

        response = client.post(
            url,
            {
                "source": "https://other.com/reply",
                "target": f"https://{site.domain}/post",
            },
        )

        assert response.status_code == 201
        mock_processor.process_webmention.assert_called_once_with(
            "https://other.com/reply",
            f"https://{site.domain}/post",
        )

    @patch("indieweb.views.WebmentionProcessor")
    def test_processor_exception_returns_400(self, mock_processor_class, client, site):
        """Test that processor exceptions return 400."""
        url = reverse("indieweb:webmention")

        # Mock the processor to raise an exception
        mock_processor = MagicMock()
        mock_processor_class.return_value = mock_processor
        mock_processor.process_webmention.side_effect = ValueError("Invalid webmention")

        response = client.post(
            url,
            {
                "source": "https://other.com/reply",
                "target": f"https://{site.domain}/post",
            },
        )

        assert response.status_code == 400

    def test_form_encoded_request(self, client, site):
        """Test that form-encoded requests work."""
        url = reverse("indieweb:webmention")

        with patch("indieweb.views.WebmentionProcessor") as mock_processor_class:
            mock_processor = MagicMock()
            mock_processor_class.return_value = mock_processor
            mock_processor.process_webmention.return_value = Webmention(id=2)

            # Send as form-encoded
            response = client.post(
                url,
                urlencode(
                    {
                        "source": "https://other.com/reply",
                        "target": f"https://{site.domain}/post",
                    }
                ),
                content_type="application/x-www-form-urlencoded",
            )

            assert response.status_code == 201

    def test_json_request_not_supported(self, client, site):
        """Test that JSON requests are not supported per spec."""
        url = reverse("indieweb:webmention")

        response = client.post(
            url,
            json.dumps(
                {
                    "source": "https://other.com/reply",
                    "target": f"https://{site.domain}/post",
                }
            ),
            content_type="application/json",
        )

        # Should fail because parameters aren't in POST data
        assert response.status_code == 400

    def test_is_valid_target_method(self, factory, site):
        """Test the is_valid_target method."""
        view = WebmentionEndpoint()
        request = factory.post("/")
        view.setup(request)

        # Valid target on our domain
        assert view.is_valid_target(f"https://{site.domain}/post") is True
        assert view.is_valid_target(f"http://{site.domain}/post") is True

        # Invalid targets
        assert view.is_valid_target("https://other.com/post") is False
        assert view.is_valid_target("not-a-url") is False

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_is_valid_target_with_https_redirect(self, factory, site):
        """Test is_valid_target respects HTTPS redirect setting."""
        view = WebmentionEndpoint()
        request = factory.post("/")
        view.setup(request)

        # Both HTTP and HTTPS should be valid when HTTPS redirect is on
        assert view.is_valid_target(f"https://{site.domain}/post") is True
        assert view.is_valid_target(f"http://{site.domain}/post") is True

    def test_endpoint_discovery_headers(self, client):
        """Test that endpoint advertises itself in headers."""
        url = reverse("indieweb:webmention")
        response = client.get(url)

        # Should have Link header for discovery
        assert "Link" in response
        link_header = response["Link"]
        assert url in link_header
        assert 'rel="webmention"' in link_header

    def test_csrf_exempt(self, client):
        """Test that the endpoint is CSRF exempt."""
        url = reverse("indieweb:webmention")

        # Should work without CSRF token
        with patch("indieweb.views.WebmentionProcessor"):
            # Don't actually process, just check CSRF isn't required
            response = client.post(url)
            # Should get 400 for missing params, not 403 for CSRF
            assert response.status_code == 400

    @patch("indieweb.views.WebmentionProcessor")
    def test_location_header_on_201(self, mock_processor_class, client, site):
        """Test that 201 response includes Location header per W3C spec."""
        url = reverse("indieweb:webmention")

        # Mock the processor
        mock_processor = MagicMock()
        mock_processor_class.return_value = mock_processor
        mock_webmention = Webmention(
            id=123,
            source_url="https://other.com/reply",
            target_url=f"https://{site.domain}/post",
        )
        mock_processor.process_webmention.return_value = mock_webmention

        response = client.post(
            url,
            {
                "source": "https://other.com/reply",
                "target": f"https://{site.domain}/post",
            },
        )

        assert response.status_code == 201
        assert "Location" in response
        # Should contain webmention ID in the URL
        assert str(mock_webmention.id) in response["Location"]

    @pytest.mark.django_db
    def test_webmention_status_view(self, client):
        """Test the webmention status endpoint."""
        # Create a test webmention
        webmention = Webmention.objects.create(
            source_url="https://other.com/reply",
            target_url="https://example.com/post",
            status="verified",
        )

        url = reverse("indieweb:webmention-status", args=[webmention.pk])
        response = client.get(url)

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"

        data = json.loads(response.content)
        assert data["source"] == webmention.source_url
        assert data["target"] == webmention.target_url
        assert data["status"] == webmention.status

    def test_webmention_status_view_not_found(self, client):
        """Test that non-existent webmention returns 404."""
        url = reverse("indieweb:webmention-status", args=[99999])
        response = client.get(url)
        assert response.status_code == 404
