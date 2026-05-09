"""Test cases for Webmention endpoint."""

import json
from datetime import timedelta
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

import pytest
from django.contrib.sites.models import Site
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from indieweb.models import Webmention, WebmentionNestedResponse, WebmentionSourceSnapshot
from indieweb.views import WebmentionEndpoint
from tests import webmention_enqueue_hooks


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

    @pytest.fixture(autouse=True)
    def reset_webmention_enqueue_hooks(self):
        webmention_enqueue_hooks.reset()

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

        # Unsupported source URL scheme
        response = client.post(
            url,
            {
                "source": "ftp://other.com/reply",
                "target": "https://example.com/post",
            },
        )
        assert response.status_code == 400

        # Invalid vouch URL
        response = client.post(
            url,
            {
                "source": "https://other.com/reply",
                "target": "https://example.com/post",
                "vouch": "not-a-url",
            },
        )
        assert response.status_code == 400

        # Unsupported vouch URL scheme
        response = client.post(
            url,
            {
                "source": "https://other.com/reply",
                "target": "https://example.com/post",
                "vouch": "ftp://trusted.example/vouch",
            },
        )
        assert response.status_code == 400

        # Unsupported target URL scheme
        response = client.post(
            url,
            {
                "source": "https://other.com/reply",
                "target": "ftp://example.com/post",
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
            vouch_url=None,
        )

    @patch("indieweb.views.WebmentionProcessor")
    def test_valid_webmention_accepts_optional_vouch(self, mock_processor_class, client, site):
        """Test optional Vouch URLs are validated and passed to synchronous processing."""
        url = reverse("indieweb:webmention")
        vouch = "https://trusted.example/vouch-for-other"

        mock_processor = MagicMock()
        mock_processor_class.return_value = mock_processor
        mock_webmention = Webmention(
            id=1,
            source_url="https://other.com/reply",
            target_url=f"https://{site.domain}/post",
            vouch_url=vouch,
        )
        mock_processor.process_webmention.return_value = mock_webmention

        response = client.post(
            url,
            {
                "source": "https://other.com/reply",
                "target": f"https://{site.domain}/post",
                "vouch": vouch,
            },
        )

        assert response.status_code == 201
        mock_processor.process_webmention.assert_called_once_with(
            "https://other.com/reply",
            f"https://{site.domain}/post",
            vouch_url=vouch,
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

    @override_settings(INDIEWEB_WEBMENTION_ENQUEUE="tests.webmention_enqueue_hooks.capture_webmention_id")
    @patch("indieweb.views.WebmentionProcessor")
    def test_async_webmention_returns_accepted_without_processing(self, mock_processor_class, client, site):
        """Test async mode queues an existing row without processing in the request path."""
        url = reverse("indieweb:webmention")

        response = client.post(
            url,
            {
                "source": "https://other.com/reply",
                "target": f"https://{site.domain}/post",
            },
        )

        webmention = Webmention.objects.get(
            source_url="https://other.com/reply",
            target_url=f"https://{site.domain}/post",
        )
        assert response.status_code == 202
        assert webmention.status == "pending"
        assert webmention_enqueue_hooks.ENQUEUED_WEBMENTION_IDS == [webmention.pk]
        assert WebmentionSourceSnapshot.objects.count() == 0
        assert WebmentionNestedResponse.objects.count() == 0
        status_url = reverse("indieweb:webmention-status", args=[webmention.status_token])
        assert response["Location"] == f"http://testserver{status_url}"
        mock_processor_class.assert_not_called()

    @override_settings(INDIEWEB_WEBMENTION_ENQUEUE="tests.webmention_enqueue_hooks.capture_webmention_id")
    @patch("indieweb.views.WebmentionProcessor")
    def test_async_webmention_persists_vouch_without_processing(self, mock_processor_class, client, site):
        """Test async mode stores Vouch metadata without fetching or processing in the request path."""
        url = reverse("indieweb:webmention")
        vouch = "https://trusted.example/vouch-for-other"

        response = client.post(
            url,
            {
                "source": "https://other.com/reply",
                "target": f"https://{site.domain}/post",
                "vouch": vouch,
            },
        )

        webmention = Webmention.objects.get(
            source_url="https://other.com/reply",
            target_url=f"https://{site.domain}/post",
        )
        assert response.status_code == 202
        assert webmention.status == "pending"
        assert webmention.vouch_url == vouch
        assert webmention.vouch_verified_at is None
        assert webmention_enqueue_hooks.ENQUEUED_WEBMENTION_IDS == [webmention.pk]
        assert WebmentionSourceSnapshot.objects.count() == 0
        mock_processor_class.assert_not_called()

    @override_settings(
        INDIEWEB_WEBMENTION_ENQUEUE="tests.webmention_enqueue_hooks.capture_webmention_id",
        INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY="tests.vouch_policies.trust_submitted_and_final",
    )
    @patch("indieweb.views.WebmentionProcessor")
    def test_async_webmention_with_vouch_policy_still_does_not_process(self, mock_processor_class, client, site):
        """Test configured Vouch trust policies are not evaluated in the async receive request path."""
        url = reverse("indieweb:webmention")
        vouch = "https://trusted.example/vouch-for-example"

        response = client.post(
            url,
            {
                "source": "https://other.com/reply",
                "target": f"https://{site.domain}/post",
                "vouch": vouch,
            },
        )

        webmention = Webmention.objects.get(
            source_url="https://other.com/reply",
            target_url=f"https://{site.domain}/post",
        )
        assert response.status_code == 202
        assert webmention.vouch_url == vouch
        assert webmention.vouch_verified_at is None
        assert webmention_enqueue_hooks.ENQUEUED_WEBMENTION_IDS == [webmention.pk]
        mock_processor_class.assert_not_called()

    @override_settings(INDIEWEB_WEBMENTION_ENQUEUE="tests.webmention_enqueue_hooks.capture_webmention_id")
    @patch("indieweb.views.WebmentionProcessor")
    def test_async_webmention_reuses_existing_row_without_clearing_fields(self, mock_processor_class, client, site):
        """Test duplicate async receives keep existing processor-owned state intact."""
        source = "https://other.com/reply"
        target = f"https://{site.domain}/post"
        existing = Webmention.objects.create(
            source_url=source,
            target_url=target,
            status="verified",
            author_name="Existing Author",
            content="Existing content",
            verified_at=timezone.now() - timedelta(days=1),
        )
        verified_at = existing.verified_at

        url = reverse("indieweb:webmention")
        response = client.post(url, {"source": source, "target": target})

        existing.refresh_from_db()
        assert response.status_code == 202
        assert Webmention.objects.filter(source_url=source, target_url=target).count() == 1
        assert webmention_enqueue_hooks.ENQUEUED_WEBMENTION_IDS == [existing.pk]
        status_url = reverse("indieweb:webmention-status", args=[existing.status_token])
        assert response["Location"] == f"http://testserver{status_url}"
        assert existing.status == "verified"
        assert existing.verified_at == verified_at
        assert existing.author_name == "Existing Author"
        assert existing.content == "Existing content"
        mock_processor_class.assert_not_called()

    @override_settings(INDIEWEB_WEBMENTION_ENQUEUE="tests.webmention_enqueue_hooks.capture_webmention_id")
    @patch("indieweb.views.WebmentionProcessor")
    def test_async_webmention_without_vouch_does_not_clear_existing_vouch(self, mock_processor_class, client, site):
        """Test duplicate async receives without Vouch keep existing Vouch metadata intact."""
        source = "https://other.com/reply"
        target = f"https://{site.domain}/post"
        vouch = "https://trusted.example/vouch-for-other"
        existing = Webmention.objects.create(
            source_url=source,
            target_url=target,
            vouch_url=vouch,
            vouch_verified_at=timezone.now() - timedelta(days=1),
            status="verified",
            verified_at=timezone.now() - timedelta(days=1),
        )
        vouch_verified_at = existing.vouch_verified_at

        url = reverse("indieweb:webmention")
        response = client.post(url, {"source": source, "target": target})

        existing.refresh_from_db()
        assert response.status_code == 202
        assert existing.status == "verified"
        assert existing.vouch_url == vouch
        assert existing.vouch_verified_at == vouch_verified_at
        assert WebmentionSourceSnapshot.objects.count() == 0
        mock_processor_class.assert_not_called()

    @override_settings(INDIEWEB_WEBMENTION_ENQUEUE="tests.webmention_enqueue_hooks.capture_webmention_id")
    @patch("indieweb.views.WebmentionProcessor")
    def test_async_repeat_submission_does_not_downgrade_verified_vouch(self, mock_processor_class, client, site):
        """A repeat async submission with a different vouch must NOT clear a previously
        verified vouch on the existing row."""
        source = "https://other.com/reply"
        target = f"https://{site.domain}/post"
        original_vouch = "https://trusted.example/vouch-for-other"
        existing = Webmention.objects.create(
            source_url=source,
            target_url=target,
            vouch_url=original_vouch,
            vouch_verified_at=timezone.now() - timedelta(days=1),
            status="verified",
            verified_at=timezone.now() - timedelta(days=1),
        )
        original_verified_at = existing.vouch_verified_at
        new_vouch = "https://trusted.example/vouch-for-something-else"

        url = reverse("indieweb:webmention")
        response = client.post(
            url,
            {"source": source, "target": target, "vouch": new_vouch},
        )

        existing.refresh_from_db()
        assert response.status_code == 202
        assert existing.vouch_url == original_vouch
        assert existing.vouch_verified_at == original_verified_at
        mock_processor_class.assert_not_called()

    @override_settings(INDIEWEB_WEBMENTION_ENQUEUE="tests.webmention_enqueue_hooks.capture_webmention_id")
    @patch("indieweb.views.WebmentionProcessor")
    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"target": "https://example.com/post"},
            {"source": "https://other.com/reply"},
            {"source": "not-a-url", "target": "https://example.com/post"},
            {"source": "https://other.com/reply", "target": "not-a-url"},
            {"source": "https://other.com/reply", "target": "https://different.com/post"},
            {"source": "https://other.com/reply", "target": "https://example.com/post", "vouch": "not-a-url"},
            {
                "source": "https://other.com/reply",
                "target": "https://example.com/post",
                "vouch": "ftp://trusted.example/vouch",
            },
        ],
    )
    def test_async_webmention_rejects_invalid_requests_before_enqueueing(
        self,
        mock_processor_class,
        client,
        payload,
    ):
        """Test validation failures do not enqueue or process Webmentions."""
        url = reverse("indieweb:webmention")

        response = client.post(url, payload)

        assert response.status_code == 400
        assert webmention_enqueue_hooks.ENQUEUED_WEBMENTION_IDS == []
        assert Webmention.objects.count() == 0
        mock_processor_class.assert_not_called()

    @override_settings(INDIEWEB_WEBMENTION_ENQUEUE="tests.webmention_enqueue_hooks.capture_webmention_id")
    def test_async_webmention_does_not_call_failing_processor(self, client, site):
        """Test a failing processor is not invoked while async enqueueing is configured."""
        url = reverse("indieweb:webmention")

        with patch("indieweb.views.WebmentionProcessor") as mock_processor_class:
            mock_processor_class.side_effect = AssertionError("processor should not be instantiated")
            response = client.post(
                url,
                {
                    "source": "https://other.com/reply",
                    "target": f"https://{site.domain}/post",
                },
            )

        assert response.status_code == 202
        assert len(webmention_enqueue_hooks.ENQUEUED_WEBMENTION_IDS) == 1

    @override_settings(INDIEWEB_WEBMENTION_ENQUEUE="tests.webmention_enqueue_hooks.failing_enqueue")
    @patch("indieweb.views.WebmentionProcessor")
    def test_async_webmention_enqueue_failure_returns_500(self, mock_processor_class, client, site):
        """Test enqueue backend failures fail closed and avoid inline processing."""
        url = reverse("indieweb:webmention")

        response = client.post(
            url,
            {
                "source": "https://other.com/reply",
                "target": f"https://{site.domain}/post",
            },
        )

        assert response.status_code == 500
        assert Webmention.objects.filter(
            source_url="https://other.com/reply",
            target_url=f"https://{site.domain}/post",
        ).exists()
        mock_processor_class.assert_not_called()

    @override_settings(INDIEWEB_WEBMENTION_ENQUEUE="tests.webmention_enqueue_hooks.missing_enqueue")
    @patch("indieweb.views.WebmentionProcessor")
    def test_async_webmention_misconfigured_enqueue_returns_500(self, mock_processor_class, client, site):
        """Test an unimportable enqueue hook fails closed before persistence or processing."""
        url = reverse("indieweb:webmention")

        response = client.post(
            url,
            {
                "source": "https://other.com/reply",
                "target": f"https://{site.domain}/post",
            },
        )

        assert response.status_code == 500
        assert Webmention.objects.count() == 0
        mock_processor_class.assert_not_called()

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
        assert view.is_valid_target(f"https://{site.domain.upper()}/post") is True
        assert view.is_valid_target(f"http://{site.domain}/post") is True

        # Invalid targets
        assert view.is_valid_target("https://other.com/post") is False
        assert view.is_valid_target("not-a-url") is False

    def test_is_valid_target_normalizes_default_ports(self, factory, site):
        """Default ports must be treated as equivalent to omitted ports.

        ``https://example.com/p`` and ``https://example.com:443/p`` denote
        the same authority. Without normalization a sender could spoof a
        target by adding the explicit default port to bypass per-domain
        comparisons or downstream caches keyed by the raw netloc.
        """
        view = WebmentionEndpoint()
        request = factory.post("/")
        view.setup(request)

        assert view.is_valid_target(f"https://{site.domain}:443/post") is True
        assert view.is_valid_target(f"http://{site.domain}:80/post") is True
        # Non-default ports must still differ.
        assert view.is_valid_target(f"https://{site.domain}:8443/post") is False

    def test_is_valid_target_rejects_invalid_url_shapes(self, factory, site):
        """URLs with malformed authorities or non-HTTP schemes are not valid targets."""
        view = WebmentionEndpoint()
        request = factory.post("/")
        view.setup(request)

        assert view.is_valid_target(f"ftp://{site.domain}/post") is False
        assert view.is_valid_target("https:///just-a-path") is False

    def test_is_valid_target_normalizes_default_port_in_site_domain(self, factory, site):
        """``Site.domain`` with an explicit default port must compare equal to a
        target that omits the port (and vice versa).

        Without symmetric normalization, ``Site.domain="example.com:443"`` would
        accept ``https://example.com:443/post`` but reject the same URL with
        the port omitted, because target-side normalization drops the default
        port unconditionally.
        """
        original_domain = site.domain
        try:
            site.domain = f"{original_domain}:443"
            site.save()

            view = WebmentionEndpoint()
            request = factory.post("/")
            view.setup(request)

            assert view.is_valid_target(f"https://{original_domain}/post") is True
            assert view.is_valid_target(f"https://{original_domain}:443/post") is True
            assert view.is_valid_target(f"http://{original_domain}/post") is True

            site.domain = f"{original_domain}:80"
            site.save()
            assert view.is_valid_target(f"http://{original_domain}/post") is True
            assert view.is_valid_target(f"https://{original_domain}/post") is True
        finally:
            site.domain = original_domain
            site.save()

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

    def test_userinfo_in_pair_is_rejected(self, client, site):
        """``alice@example`` and ``bob@example`` must not collapse to one canonical row."""
        url = reverse("indieweb:webmention")
        for source in [
            "https://alice@other.com/post",
            "https://alice:secret@other.com/post",
        ]:
            response = client.post(
                url,
                {"source": source, "target": f"https://{site.domain}/post"},
            )
            assert response.status_code == 400

    def test_csrf_exempt(self, client):
        """Test that the endpoint is CSRF exempt."""
        url = reverse("indieweb:webmention")

        # Should work without CSRF token
        with patch("indieweb.views.WebmentionProcessor"):
            # Don't actually process, just check CSRF isn't required
            response = client.post(url)
            # Should get 400 for missing params, not 403 for CSRF
            assert response.status_code == 400

    @override_settings(INDIEWEB_WEBMENTION_ENQUEUE="tests.webmention_enqueue_hooks.capture_webmention_id")
    def test_async_canonicalizes_pair_and_collapses_cosmetic_variants(self, client, site):
        """Cosmetic source/target variants must collapse onto a single canonical Webmention row."""
        url = reverse("indieweb:webmention")
        domain = site.domain

        variants = [
            ("https://Other.com/Reply", f"https://{domain}/post"),
            ("https://other.com:443/Reply", f"https://{domain}:443/post"),
            ("HTTPS://other.com/Reply", f"HTTPS://{domain}/post"),
            ("https://OTHER.com/Reply", f"https://{domain.upper()}/post"),
        ]
        for source, target in variants:
            response = client.post(url, {"source": source, "target": target})
            assert response.status_code == 202

        # Despite cosmetic variation across submissions, the canonicalizer must
        # collapse them to a single stored row rather than spawning new rows.
        assert Webmention.objects.count() == 1

    @patch("indieweb.views.WebmentionProcessor")
    def test_sync_pair_cooldown_reuses_existing_row_without_reprocessing(self, mock_processor_class, client, site):
        """A repeat sync receive of the same canonical pair within the cooldown must skip processing."""
        url = reverse("indieweb:webmention")
        domain = site.domain

        mock_processor = MagicMock()
        mock_processor_class.return_value = mock_processor
        existing = Webmention.objects.create(
            source_url="https://other.com/reply",
            target_url=f"https://{domain}/post",
            status="verified",
            last_received_at=timezone.now(),
        )
        # Configure a 60-second cooldown.
        with override_settings(INDIEWEB_WEBMENTION_PAIR_COOLDOWN_SECONDS=60):
            response = client.post(
                url,
                {
                    "source": "https://Other.com:443/reply",  # cosmetic variant
                    "target": f"https://{domain}/post",
                },
            )

        assert response.status_code == 200
        # Processor must NOT be called within the cooldown window for the same pair.
        mock_processor.process_webmention.assert_not_called()
        status_url = reverse("indieweb:webmention-status", args=[existing.status_token])
        assert response["Location"].endswith(status_url)
        # No additional rows.
        assert Webmention.objects.count() == 1

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
        assert str(mock_webmention.status_token) in response["Location"]

    @pytest.mark.django_db
    def test_webmention_status_view(self, client):
        """Test the webmention status endpoint."""
        # Create a test webmention
        webmention = Webmention.objects.create(
            source_url="https://other.com/reply",
            target_url="https://example.com/post",
            status="verified",
        )

        url = reverse("indieweb:webmention-status", args=[webmention.status_token])
        response = client.get(url)

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"

        data = json.loads(response.content)
        assert data["source"] == webmention.source_url
        assert data["target"] == webmention.target_url
        assert data["status"] == webmention.status

    def test_webmention_status_view_emits_no_store_cache_control(self, client):
        """The status endpoint must opt out of shared caches."""
        webmention = Webmention.objects.create(
            source_url="https://other.com/reply",
            target_url="https://example.com/post",
            status="verified",
        )
        url = reverse("indieweb:webmention-status", args=[webmention.status_token])
        response = client.get(url)
        assert response["Cache-Control"] == "no-store"
        assert "Cookie" in response["Vary"]

    def test_webmention_status_view_omits_vouch_metadata(self, client):
        """Test the status endpoint does not expose stored Vouch metadata."""
        vouch_verified_at = timezone.now()
        webmention = Webmention.objects.create(
            source_url="https://other.com/reply",
            target_url="https://example.com/post",
            status="verified",
            vouch_url="https://trusted.example/vouch-for-other",
            vouch_verified_at=vouch_verified_at,
        )

        url = reverse("indieweb:webmention-status", args=[webmention.status_token])
        response = client.get(url)

        data = json.loads(response.content)
        assert "vouch" not in data
        assert "vouch_verified_at" not in data

    def test_webmention_status_view_does_not_allow_pk_enumeration(self, client):
        """Test sequential primary keys cannot enumerate private status metadata."""
        webmention = Webmention.objects.create(
            source_url="https://other.com/private-reply",
            target_url="https://example.com/private-post",
            status="pending",
            vouch_url="https://trusted.example/private-vouch",
        )

        response = client.get(reverse("indieweb:webmention-status", args=[webmention.pk]))

        assert response.status_code == 404
        body = response.content.decode()
        assert webmention.source_url not in body
        assert webmention.target_url not in body
        assert webmention.vouch_url not in body

    def test_webmention_status_view_not_found(self, client):
        """Test that non-existent webmention returns 404."""
        url = reverse("indieweb:webmention-status", args=[99999])
        response = client.get(url)
        assert response.status_code == 404

    def test_webmention_status_public_mode_returns_minimal_fields(self, client):
        """When INDIEWEB_WEBMENTION_STATUS_PUBLIC is True, response includes only status and verified_at."""
        verified_at = timezone.now()
        webmention = Webmention.objects.create(
            source_url="https://other.example/reply",
            target_url="https://example.com/post",
            status="verified",
            verified_at=verified_at,
            vouch_url="https://trusted.example/vouch",
        )

        url = reverse("indieweb:webmention-status", args=[webmention.status_token])
        with override_settings(INDIEWEB_WEBMENTION_STATUS_PUBLIC=True):
            response = client.get(url)

        assert response.status_code == 200
        body = json.loads(response.content)
        assert set(body.keys()) <= {"status", "verified_at"}
        assert body["status"] == "verified"
        assert body["verified_at"] == verified_at.isoformat()
        assert "source" not in body
        assert "target" not in body
        assert "vouch_url" not in body
        # No leak of URLs in body even as substrings.
        raw = response.content.decode()
        assert webmention.source_url not in raw
        assert webmention.target_url not in raw
        assert webmention.vouch_url not in raw

    def test_webmention_status_public_mode_pending_omits_verified_at(self, client):
        """Public mode for an unverified Webmention returns status only without verified_at."""
        webmention = Webmention.objects.create(
            source_url="https://other.example/reply",
            target_url="https://example.com/post",
            status="pending",
        )

        url = reverse("indieweb:webmention-status", args=[webmention.status_token])
        with override_settings(INDIEWEB_WEBMENTION_STATUS_PUBLIC=True):
            response = client.get(url)

        assert response.status_code == 200
        body = json.loads(response.content)
        assert body == {"status": "pending"}

    def test_webmention_status_default_mode_returns_full_fields(self, client):
        """Default INDIEWEB_WEBMENTION_STATUS_PUBLIC=False keeps the existing diagnostic shape."""
        webmention = Webmention.objects.create(
            source_url="https://other.example/reply",
            target_url="https://example.com/post",
            status="verified",
            verified_at=timezone.now(),
        )

        url = reverse("indieweb:webmention-status", args=[webmention.status_token])
        response = client.get(url)

        assert response.status_code == 200
        body = json.loads(response.content)
        assert "source" in body
        assert "target" in body
        assert "status" in body


@pytest.mark.django_db
def test_webmention_rejects_overlong_source(client):
    """Source URLs longer than the model max_length are rejected before persistence."""
    overlong = "https://example.com/" + ("a" * 5000)
    response = client.post(
        reverse("indieweb:webmention"),
        data={"source": overlong, "target": "https://example.com/post"},
    )
    assert response.status_code == 400
    assert Webmention.objects.count() == 0


@pytest.mark.django_db
def test_webmention_rejects_overlong_target(client):
    """Target URLs longer than the model max_length are rejected before persistence."""
    overlong = "https://example.com/" + ("a" * 5000)
    response = client.post(
        reverse("indieweb:webmention"),
        data={"source": "https://other.example/reply", "target": overlong},
    )
    assert response.status_code == 400
    assert Webmention.objects.count() == 0


@pytest.mark.django_db
def test_webmention_rejects_overlong_vouch(client):
    """Vouch URLs longer than the model max_length are rejected before persistence."""
    overlong = "https://vouch.example/" + ("a" * 5000)
    response = client.post(
        reverse("indieweb:webmention"),
        data={
            "source": "https://other.example/reply",
            "target": "https://example.com/post",
            "vouch": overlong,
        },
    )
    assert response.status_code == 400
    assert Webmention.objects.count() == 0
