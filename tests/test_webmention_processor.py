"""Test cases for WebmentionProcessor."""

import hashlib
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory, override_settings
from django.utils import timezone as django_timezone

from indieweb.models import Profile, Webmention, WebmentionNestedResponse, WebmentionSourceSnapshot
from indieweb.processors import WebmentionProcessor, process_queued_webmention
from indieweb.sanitizers import sanitize_remote_webmention_url, sanitize_webmention_html


def _mock_source_response(
    mock_get_class,
    *,
    status_code,
    text="",
    content_type="text/html",
):
    """Configure the patched httpx client to return a source response."""
    mock_client = Mock()
    mock_get_class.return_value.__enter__.return_value = mock_client
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = text
    mock_response.headers = {"content-type": content_type}
    mock_client.get.return_value = mock_response
    return mock_response


def _source_response(*, status_code, text="", content_type="text/html", headers=None):
    """Build a mocked source response for redirect chains."""
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = text
    mock_response.headers = headers if headers is not None else {"content-type": content_type}
    return mock_response


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "data:image/svg+xml,<svg onload=alert(1)>",
        "file:///etc/passwd",
        "ftp://example.com/avatar.jpg",
        "http://[broken",
        "/relative/path",
    ],
)
def test_sanitize_remote_webmention_url_blanks_unsafe_values(value):
    """Remote Webmention URL fields only accept absolute HTTP(S) URLs."""
    assert sanitize_remote_webmention_url(value) == ""


@pytest.mark.parametrize("value", ["http://example.com/author", "https://example.com/avatar.jpg"])
def test_sanitize_remote_webmention_url_allows_http_urls(value):
    """Remote Webmention URL sanitization preserves absolute HTTP(S) URLs."""
    assert sanitize_remote_webmention_url(value) == value


def test_sanitize_webmention_html_drops_relative_url_attributes():
    """Remote HTML fragments cannot create same-origin-looking relative links."""
    sanitized = sanitize_webmention_html(
        '<p><a href="/admin">local link</a> '
        '<a href="https://example.com/post">remote link</a> '
        '<blockquote cite="/private">quote</blockquote></p>'
    )

    assert 'href="/admin"' not in sanitized
    assert 'cite="/private"' not in sanitized
    assert 'href="https://example.com/post"' in sanitized


@pytest.mark.django_db
class TestWebmentionProcessor:
    """Test cases for the WebmentionProcessor class."""

    @pytest.fixture
    def processor(self):
        """Create a WebmentionProcessor instance."""
        return WebmentionProcessor()

    @pytest.fixture
    def factory(self):
        """Create a RequestFactory instance."""
        return RequestFactory()

    def test_verify_target_link_accepts_exact_absolute_link(self, processor):
        """Test that exact absolute target links still verify."""
        target_url = "https://mysite.com/article"
        html_content = f'<html><body><a href="{target_url}">Link</a></body></html>'

        assert processor._verify_target_link(html_content, target_url) is True

    def test_verify_target_link_matches_source_fragment_variant(self, processor):
        """Test that a source link with a fragment matches a target without it."""
        target_url = "https://mysite.com/article"
        html_content = '<html><body><a href="https://mysite.com/article#comments">Link</a></body></html>'

        assert processor._verify_target_link(html_content, target_url) is True

    def test_verify_target_link_matches_submitted_fragment_variant(self, processor):
        """Test that a submitted target with a fragment matches a source link without it."""
        target_url = "https://mysite.com/article#comments"
        html_content = '<html><body><a href="https://mysite.com/article">Link</a></body></html>'

        assert processor._verify_target_link(html_content, target_url) is True

    def test_verify_target_link_matches_scheme_and_host_case_variants(self, processor):
        """Test that scheme and host case differences are ignored."""
        target_url = "https://mysite.com/Post"
        html_content = '<html><body><a href="HTTPS://MySite.COM/Post">Link</a></body></html>'

        assert processor._verify_target_link(html_content, target_url) is True

    def test_verify_target_link_matches_leading_www_variant(self, processor):
        """Test that leading www on the host is ignored during target matching."""
        target_url = "https://mysite.com/article"
        html_content = '<html><body><a href="https://www.mysite.com/article">Link</a></body></html>'

        assert processor._verify_target_link(html_content, target_url) is True

    def test_verify_target_link_matches_trailing_slash_variant(self, processor):
        """Test that one trailing slash on non-root paths is ignored."""
        target_url = "https://mysite.com/article"
        html_content = '<html><body><a href="https://mysite.com/article/">Link</a></body></html>'

        assert processor._verify_target_link(html_content, target_url) is True

    def test_verify_target_link_matches_query_parameter_order_variant(self, processor):
        """Test that query parameter ordering is ignored."""
        target_url = "https://mysite.com/article?a=1&b=2"
        html_content = '<html><body><a href="https://mysite.com/article?b=2&a=1">Link</a></body></html>'

        assert processor._verify_target_link(html_content, target_url) is True

    def test_verify_target_link_accepts_non_anchor_href(self, processor):
        """Test that structured href extraction preserves non-anchor href matching."""
        target_url = "https://mysite.com/article"
        html_content = f'<html><head><link rel="canonical" href="{target_url}"></head></html>'

        assert processor._verify_target_link(html_content, target_url) is True

    @pytest.mark.parametrize(
        ("href", "target_url"),
        [
            ("https://mysite.com/other", "https://mysite.com/article"),
            ("https://mysite.com/article?a=2", "https://mysite.com/article?a=1"),
            ("https://mysite.com/article?a=1&a=1", "https://mysite.com/article?a=1"),
            ("https://mysite.com/foo", "https://mysite.com/Foo"),
            ("https://mysite.com/", "https://mysite.com"),
        ],
    )
    def test_verify_target_link_rejects_non_equivalent_urls(self, processor, href, target_url):
        """Test that genuinely different target URLs do not verify."""
        html_content = f'<html><body><a href="{href}">Link</a></body></html>'

        assert processor._verify_target_link(html_content, target_url) is False

    def test_verify_target_link_handles_malformed_href_without_crashing(self, processor):
        """Test that malformed href values do not crash target verification."""
        html_content = '<html><body><a href="http://[broken">Link</a></body></html>'

        assert processor._verify_target_link(html_content, "https://mysite.com/article") is False

    def test_processor_fetches_source_url(self, processor):
        """Test that processor fetches the source URL."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = '<html><body><a href="https://mysite.com/article">Link</a></body></html>'

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            mock_client.get.assert_called_once_with(
                source_url, headers={"User-Agent": "django-indieweb/1.0"}, timeout=30
            )
            assert webmention.status == "verified"

    def test_processor_stores_vouch_without_verification_when_policy_unset(self, processor):
        """Test submitted Vouch metadata is stored without extra fetching by default."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        vouch_url = "https://trusted.example/vouch-for-example"
        html_content = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = _source_response(status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url, vouch_url=vouch_url)

            assert webmention.status == "verified"
            assert webmention.vouch_url == vouch_url
            assert webmention.vouch_verified_at is None
            mock_client.get.assert_called_once_with(
                source_url, headers={"User-Agent": "django-indieweb/1.0"}, timeout=30
            )

    def test_processor_without_vouch_does_not_clear_existing_vouch(self, processor):
        """Test synchronous duplicate processing preserves existing Vouch metadata."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        vouch_url = "https://trusted.example/vouch-for-example"
        vouch_verified_at = django_timezone.now() - timedelta(days=1)
        Webmention.objects.create(
            source_url=source_url,
            target_url=target_url,
            vouch_url=vouch_url,
            vouch_verified_at=vouch_verified_at,
        )
        html_content = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = _source_response(status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.vouch_url == vouch_url
            assert webmention.vouch_verified_at == vouch_verified_at

    @override_settings(INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS=("trusted.example",))
    def test_processor_verifies_trusted_vouch_linking_to_source_domain(self, processor):
        """Test opt-in Vouch verification fetches trusted vouchers in processor-owned logic."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        vouch_url = "https://trusted.example/vouch-for-example"
        source_html = f'<html><body><a href="{target_url}">Link</a></body></html>'
        vouch_html = '<html><body><a href="https://example.com/">Example</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = [
                _source_response(status_code=200, text=source_html),
                _source_response(status_code=200, text=vouch_html),
            ]

            webmention = processor.process_webmention(source_url, target_url, vouch_url=vouch_url)

            assert webmention.status == "verified"
            assert webmention.vouch_url == vouch_url
            assert webmention.vouch_verified_at is not None
            assert mock_client.get.call_args_list[0].args[0] == source_url
            assert mock_client.get.call_args_list[1].args[0] == vouch_url

    @override_settings(
        INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY="tests.vouch_policies.trust_submitted_and_final",
        INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS=("other.example",),
    )
    def test_processor_verifies_vouch_with_trust_policy(self, processor):
        """Test a configured trust policy decides submitted and final Vouch URL trust."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        vouch_url = "https://trusted.example/vouch-for-example"
        final_vouch_url = "https://trusted.example/final-vouch"
        source_html = f'<html><body><a href="{target_url}">Link</a></body></html>'
        vouch_html = '<html><body><a href="https://example.com/">Example</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = [
                _source_response(status_code=200, text=source_html),
                _source_response(status_code=302, headers={"Location": final_vouch_url}),
                _source_response(status_code=200, text=vouch_html),
            ]

            webmention = processor.process_webmention(source_url, target_url, vouch_url=vouch_url)

            assert webmention.status == "verified"
            assert webmention.vouch_verified_at is not None
            assert mock_client.get.call_args_list[0].args[0] == source_url
            assert mock_client.get.call_args_list[1].args[0] == vouch_url
            assert mock_client.get.call_args_list[2].args[0] == final_vouch_url

    @override_settings(INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY="tests.vouch_policies.reject_submitted")
    def test_processor_policy_rejects_submitted_vouch_without_fetching_it(self, processor):
        """Test trust-policy rejection before fetch fails Vouch verification."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        source_html = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = _source_response(status_code=200, text=source_html)

            webmention = processor.process_webmention(
                source_url,
                target_url,
                vouch_url="https://trusted.example/vouch-for-example",
            )

            assert webmention.status == "failed"
            assert webmention.vouch_verified_at is None
            mock_client.get.assert_called_once_with(
                source_url, headers={"User-Agent": "django-indieweb/1.0"}, timeout=30
            )

    @override_settings(INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY="tests.vouch_policies.reject_final")
    def test_processor_policy_rejects_final_vouch_after_redirect(self, processor):
        """Test trust-policy rejection after redirects fails Vouch verification."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        vouch_url = "https://trusted.example/vouch-for-example"
        final_vouch_url = "https://untrusted.example/final-vouch"
        source_html = f'<html><body><a href="{target_url}">Link</a></body></html>'
        vouch_html = '<html><body><a href="https://example.com/">Example</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = [
                _source_response(status_code=200, text=source_html),
                _source_response(status_code=302, headers={"Location": final_vouch_url}),
                _source_response(status_code=200, text=vouch_html),
            ]

            webmention = processor.process_webmention(source_url, target_url, vouch_url=vouch_url)

            assert webmention.status == "failed"
            assert webmention.vouch_verified_at is None
            assert mock_client.get.call_args_list[2].args[0] == final_vouch_url

    @pytest.mark.parametrize(
        "policy_path",
        [
            "tests.vouch_policies.missing_policy",
            "tests.vouch_policies.non_callable",
            "tests.vouch_policies.raises",
        ],
    )
    def test_processor_vouch_policy_misconfiguration_fails_closed(self, processor, settings, policy_path):
        """Test bad policy imports, non-callables, and exceptions fail Vouch verification."""
        settings.INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY = policy_path
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        source_html = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = _source_response(status_code=200, text=source_html)

            webmention = processor.process_webmention(
                source_url,
                target_url,
                vouch_url="https://trusted.example/vouch-for-example",
            )

            assert webmention.status == "failed"
            assert webmention.vouch_verified_at is None
            mock_client.get.assert_called_once_with(
                source_url, headers={"User-Agent": "django-indieweb/1.0"}, timeout=30
            )

    @override_settings(INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS=("trusted.example",))
    def test_processor_preserves_parsed_fields_after_successful_vouch_verification(self, processor):
        """Test successful Vouch verification does not overwrite parsed microformats fields."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        vouch_url = "https://trusted.example/vouch-for-example"
        source_html = f"""
        <html>
        <body>
            <article class="h-entry">
                <div class="p-author h-card">
                    <a class="p-name u-url" href="https://author.example/">Jane Doe</a>
                </div>
                <div class="e-content">
                    <p>Hello from Vouch <a href="{target_url}">target</a></p>
                </div>
            </article>
        </body>
        </html>
        """
        vouch_html = '<html><body><a href="https://example.com/">Example</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = [
                _source_response(status_code=200, text=source_html),
                _source_response(status_code=200, text=vouch_html),
            ]

            webmention = processor.process_webmention(source_url, target_url, vouch_url=vouch_url)

        webmention.refresh_from_db()
        assert webmention.status == "verified"
        assert webmention.vouch_verified_at is not None
        assert webmention.author_name == "Jane Doe"
        assert webmention.author_url == "https://author.example/"
        assert "Hello from Vouch" in webmention.content
        assert "Hello from Vouch" in webmention.content_html
        assert webmention.source_snapshot.raw_source_html == source_html
        assert webmention.source_snapshot.content_digest == hashlib.sha256(source_html.encode("utf-8")).hexdigest()

    @override_settings(INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS=("trusted.example",))
    def test_processor_fails_untrusted_vouch_without_fetching_it(self, processor):
        """Test Vouch verification rejects untrusted voucher domains before fetch."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        source_html = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = _source_response(status_code=200, text=source_html)

            webmention = processor.process_webmention(
                source_url,
                target_url,
                vouch_url="https://untrusted.example/vouch-for-example",
            )

            assert webmention.status == "failed"
            assert webmention.vouch_verified_at is None
            mock_client.get.assert_called_once_with(
                source_url, headers={"User-Agent": "django-indieweb/1.0"}, timeout=30
            )

    @override_settings(INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS=("trusted.example",))
    def test_processor_fails_vouch_that_does_not_link_to_source_domain(self, processor):
        """Test Vouch verification rejects vouchers that do not link to the source domain."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        vouch_url = "https://trusted.example/vouch-for-example"
        source_html = f'<html><body><a href="{target_url}">Link</a></body></html>'
        vouch_html = '<html><body><a href="https://someone-else.example/">Elsewhere</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = [
                _source_response(status_code=200, text=source_html),
                _source_response(status_code=200, text=vouch_html),
            ]

            webmention = processor.process_webmention(source_url, target_url, vouch_url=vouch_url)

            assert webmention.status == "failed"
            assert webmention.vouch_verified_at is None

    @override_settings(INDIEWEB_WEBMENTION_VOUCH_REQUIRED=True)
    def test_processor_fails_missing_vouch_when_required(self, processor):
        """Test deployments can require Vouch without changing the endpoint request path."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        source_html = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = _source_response(status_code=200, text=source_html)

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "failed"
            assert webmention.vouch_url == ""

    @override_settings(INDIEWEB_WEBMENTION_VOUCH_REQUIRED=True)
    def test_processor_required_vouch_without_trust_configuration_fails_closed(self, processor):
        """Test required mode needs an explicit trust policy or domain allowlist."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        source_html = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = _source_response(status_code=200, text=source_html)

            webmention = processor.process_webmention(
                source_url,
                target_url,
                vouch_url="https://mysite.com/vouch-for-example",
            )

            assert webmention.status == "failed"
            assert webmention.vouch_verified_at is None
            mock_client.get.assert_called_once_with(
                source_url, headers={"User-Agent": "django-indieweb/1.0"}, timeout=30
            )

    def test_process_queued_webmention_processes_existing_row(self):
        """Test the public worker helper dispatches processing for an existing row."""
        webmention = Webmention.objects.create(
            source_url="https://example.com/post",
            target_url="https://mysite.com/article",
        )

        with patch("indieweb.processors.WebmentionProcessor") as mock_processor_class:
            mock_processor = Mock()
            mock_processor_class.return_value = mock_processor
            mock_processor.process_webmention.return_value = webmention

            result = process_queued_webmention(webmention.pk)

        assert result == webmention
        mock_processor.process_webmention.assert_called_once_with(
            "https://example.com/post",
            "https://mysite.com/article",
            vouch_url=None,
        )

    def test_process_queued_webmention_passes_stored_vouch(self):
        """Test queued processing includes persisted Vouch metadata."""
        webmention = Webmention.objects.create(
            source_url="https://example.com/post",
            target_url="https://mysite.com/article",
            vouch_url="https://trusted.example/vouch-for-example",
        )

        with patch("indieweb.processors.WebmentionProcessor") as mock_processor_class:
            mock_processor = Mock()
            mock_processor_class.return_value = mock_processor
            mock_processor.process_webmention.return_value = webmention

            result = process_queued_webmention(webmention.pk)

        assert result == webmention
        mock_processor.process_webmention.assert_called_once_with(
            "https://example.com/post",
            "https://mysite.com/article",
            vouch_url="https://trusted.example/vouch-for-example",
        )

    def test_process_queued_webmention_creates_source_snapshot(self):
        """Test the worker helper can create snapshots through WebmentionProcessor."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        webmention = Webmention.objects.create(source_url=source_url, target_url=target_url)
        html_content = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            result = process_queued_webmention(webmention.pk)

        assert result.status == "verified"
        snapshot = result.source_snapshot
        assert snapshot.raw_source_html == html_content
        assert snapshot.content_digest == hashlib.sha256(html_content.encode("utf-8")).hexdigest()

    def test_process_queued_webmention_creates_nested_responses(self):
        """Test the worker helper can create child responses through WebmentionProcessor."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        webmention = Webmention.objects.create(source_url=source_url, target_url=target_url)
        html_content = f'''
        <html><body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <article class="h-entry"><a class="u-url" href="/comments/child">Child</a></article>
            </article>
        </body></html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            result = process_queued_webmention(webmention.pk)

        assert result.status == "verified"
        child = WebmentionNestedResponse.objects.get(webmention=result)
        assert child.identity == "https://example.com/comments/child"
        assert child.status == "verified"

    def test_process_queued_webmention_raises_for_missing_row(self):
        """Test the public worker helper surfaces missing queued rows."""
        with pytest.raises(Webmention.DoesNotExist):
            process_queued_webmention(99999)

    def test_processor_follows_source_redirect_and_preserves_submitted_urls(self, processor):
        """Test source redirects verify the submitted source/target row."""
        source_url = "https://example.com/post"
        final_url = "https://cdn.example.com/posts/post"
        target_url = "https://mysite.com/article"
        html_content = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = [
                _source_response(status_code=302, headers={"Location": final_url}),
                _source_response(status_code=200, text=html_content),
            ]

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.source_url == source_url
            assert webmention.target_url == target_url
            assert mock_client.get.call_args_list[0].args[0] == source_url
            assert mock_client.get.call_args_list[1].args[0] == final_url

    def test_processor_resolves_relative_source_redirect_location(self, processor):
        """Test relative source redirect locations resolve against the redirecting URL."""
        source_url = "https://example.com/posts/original"
        target_url = "https://mysite.com/article"
        html_content = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = [
                _source_response(status_code=302, headers={"Location": "/posts/final"}),
                _source_response(status_code=200, text=html_content),
            ]

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert mock_client.get.call_args_list[1].args[0] == "https://example.com/posts/final"

    def test_processor_uses_final_source_url_as_microformats_base_after_redirect(self, processor):
        """Test relative author URLs resolve against the final redirected source URL."""
        source_url = "https://old.example.com/posts/original"
        final_url = "https://new.example.com/final/post"
        target_url = "https://mysite.com/article"
        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <div class="p-author h-card">
                    <img class="u-photo" src="avatar.jpg" alt="Jane">
                    <a class="p-name u-url" href="author">Jane Doe</a>
                </div>
                <div class="e-content">
                    Content with <a href="{target_url}">link</a>
                </div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = [
                _source_response(status_code=301, headers={"Location": final_url}),
                _source_response(status_code=200, text=html_content),
            ]

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_url == "https://new.example.com/final/author"
            assert webmention.author_photo == "https://new.example.com/final/avatar.jpg"

    def test_processor_sanitizes_remote_webmention_content_html(self, processor):
        """Remote rich content is allowlist-sanitized before it is stored."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <div class="e-content">
                    <p onclick="alert(1)">Safe <strong>formatting</strong>
                        <a href="{target_url}">target</a>
                        <a href="javascript:alert(1)">bad link</a>
                        <a href="data:text/html,evil">bad data</a>
                    </p>
                    <script>alert(1)</script>
                    <svg onload="alert(1)"><circle></circle></svg>
                    <form action="https://evil.example"><input name="x"></form>
                    <iframe src="https://evil.example/frame"></iframe>
                    <style>body {{ background: url(javascript:alert(1)); }}</style>
                </div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

        assert webmention.status == "verified"
        assert "<strong>formatting</strong>" in webmention.content_html
        assert f'href="{target_url}"' in webmention.content_html
        assert "<script" not in webmention.content_html
        assert "<svg" not in webmention.content_html
        assert "<form" not in webmention.content_html
        assert "<iframe" not in webmention.content_html
        assert "<style" not in webmention.content_html
        assert "onclick" not in webmention.content_html
        assert "onload" not in webmention.content_html
        assert 'href="javascript:' not in webmention.content_html
        assert 'href="data:' not in webmention.content_html

    def test_processor_blanks_unsafe_remote_author_url_fields(self, processor):
        """Unsafe top-level author URL and photo schemes are not persisted."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <div class="p-author h-card">
                    <a class="p-name u-url" href="javascript:alert(1)">Mallory</a>
                    <img class="u-photo" src="data:image/svg+xml,<svg onload=alert(1)>">
                </div>
                <div class="e-content">
                    Content with <a href="{target_url}">link</a>
                </div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

        assert webmention.status == "verified"
        assert webmention.author_name == "Mallory"
        assert webmention.author_url == ""
        assert webmention.author_photo == ""

    def test_processor_fails_when_source_redirect_limit_is_exceeded(self, processor):
        """Test excess redirects fail predictably and clear stale verification."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        existing = Webmention.objects.create(
            source_url=source_url,
            target_url=target_url,
            status="verified",
            verified_at=django_timezone.now(),
        )

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = [
                _source_response(status_code=302, headers={"Location": f"https://example.com/r{i}"}) for i in range(6)
            ]

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.id == existing.id
            assert webmention.status == "failed"
            assert webmention.verified_at is None

    def test_processor_fails_when_source_redirect_lands_on_non_html(self, processor):
        """Test redirected non-HTML source responses remain failed."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = [
                _source_response(status_code=302, headers={"Location": "https://example.com/data.json"}),
                _source_response(status_code=200, text='{"ok": true}', content_type="application/json"),
            ]

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "failed"
            assert webmention.verified_at is None

    def test_processor_fails_when_source_redirect_lands_on_non_200(self, processor):
        """Test redirected non-200 source responses remain failed."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = [
                _source_response(status_code=302, headers={"Location": "https://example.com/missing"}),
                _source_response(status_code=404, text="Not found"),
            ]

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "failed"
            assert webmention.verified_at is None

    def test_processor_fails_when_source_redirect_uses_unsupported_scheme(self, processor):
        """Test source redirects only continue to HTTP and HTTPS URLs."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = _source_response(
                status_code=302,
                headers={"Location": "mailto:a@example.com"},
            )

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "failed"
            assert mock_client.get.call_count == 1

    def test_processor_verifies_canonical_equivalent_target_link(self, processor):
        """Test processing succeeds when the source links a canonical-equivalent target."""
        source_url = "https://example.com/canonical-source"
        target_url = "https://mysite.com/article?a=1&b=2"
        html_content = '<html><body><a href="https://www.mysite.com/article/?b=2&a=1#comments">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = html_content
            mock_response.headers = {"content-type": "text/html"}
            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.source_url == source_url
            assert webmention.target_url == target_url

    def test_processor_handles_fetch_errors(self, processor):
        """Test that processor handles fetch errors gracefully."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = Exception("Network error")

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "failed"
            assert webmention.source_url == source_url
            assert webmention.target_url == target_url

    def test_processor_verifies_target_link_exists(self, processor):
        """Test that processor verifies the target link exists in source."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        # Test with link present
        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = f'<html><body><a href="{target_url}">Link to article</a></body></html>'

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)
            assert webmention.status == "verified"

        # Test with link missing
        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = "<html><body>No link here</body></html>"

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)
            assert webmention.status == "failed"

    def test_processor_handles_404_response(self, processor):
        """Test that processor handles 404 responses."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 404

            mock_response.text = "Not found"

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)
            assert webmention.status == "failed"

    def test_processor_parses_microformats2(self, processor):
        """Test that processor parses microformats2 data."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <div class="p-author h-card">
                    <img class="u-photo" src="https://example.com/avatar.jpg" alt="John Doe">
                    <a class="p-name u-url" href="https://example.com">John Doe</a>
                </div>
                <div class="e-content">
                    <p>Great article! <a href="{target_url}">Check it out</a></p>
                </div>
                <time class="dt-published" datetime="2024-01-15T10:00:00Z">January 15, 2024</time>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_name == "John Doe"
            assert webmention.author_url == "https://example.com"
            assert webmention.author_photo == "https://example.com/avatar.jpg"
            assert "Great article!" in webmention.content
            assert webmention.published is not None

    def test_processor_creates_source_snapshot_after_verified_processing(self, processor):
        """Test verified processing stores the latest fetched source snapshot."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        html_content = f'''
        <html>
        <body>
            <article class="h-entry" id="parent">
                <a class="u-in-reply-to" href="{target_url}">In reply to</a>
                <div class="e-content">
                    <p>Parent response</p>
                    <article class="h-entry" id="child-with-id">
                        <p class="p-name">Child with id</p>
                    </article>
                    <article class="h-entry">
                        <a class="u-url" href="/comments/child-with-url">Child with URL</a>
                    </article>
                    <article class="h-entry">
                        <data class="u-uid" value="https://example.com/comments/child-with-uid"></data>
                    </article>
                </div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

        snapshot = webmention.source_snapshot
        assert snapshot.raw_source_html == html_content
        assert snapshot.final_source_url == source_url
        assert snapshot.content_digest == hashlib.sha256(html_content.encode("utf-8")).hexdigest()
        assert snapshot.fetched_at is not None
        assert snapshot.parsed_h_entry["type"] == ["h-entry"]
        assert snapshot.parsed_h_entry["id"] == "parent"
        assert snapshot.nested_response_identities == [
            "https://example.com/comments/child-with-uid",
            "https://example.com/comments/child-with-url",
            "https://example.com/post#child-with-id",
        ]

    def test_processor_creates_nested_responses_after_verified_processing(self, processor):
        """Test verified processing stores stable nested h-entry responses."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">In reply to</a>
                <div class="e-content">
                    Parent response
                    <article class="h-entry">
                        <a class="u-url" href="/comments/child">Permalink</a>
                        <a class="u-in-reply-to" href="{source_url}">Reply</a>
                        <div class="p-author h-card">
                            <a class="p-name u-url" href="/authors/jane">Jane Child</a>
                            <img class="u-photo" src="/authors/jane.jpg">
                        </div>
                        <time class="dt-published" datetime="2026-05-01T10:00:00+00:00">May 1</time>
                        <div class="e-content"><p>Nested reply content</p></div>
                    </article>
                </div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

        child = WebmentionNestedResponse.objects.get(webmention=webmention)
        assert child.identity == "https://example.com/comments/child"
        assert child.response_url == "https://example.com/comments/child"
        assert child.author_name == "Jane Child"
        assert child.author_url == "https://example.com/authors/jane"
        assert child.author_photo == "https://example.com/authors/jane.jpg"
        assert child.content == "Nested reply content"
        assert child.content_html == "<p>Nested reply content</p>"
        assert child.published is not None
        assert child.mention_type == "reply"
        assert child.status == "verified"
        assert child.verified_at is not None
        assert child.first_seen_at == child.last_seen_at
        assert child.parsed_h_entry["type"] == ["h-entry"]
        assert len(child.content_digest) == 64
        assert child.is_currently_displayable is True

    def test_processor_sanitizes_nested_response_remote_fields(self, processor):
        """Nested response author URLs and HTML content use the same remote sanitizers."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">In reply to</a>
                <div class="e-content">
                    Parent response
                    <article class="h-entry">
                        <a class="u-url" href="/comments/unsafe-child">Permalink</a>
                        <a class="u-in-reply-to" href="{source_url}">Reply</a>
                        <div class="p-author h-card">
                            <a class="p-name u-url" href="data:text/html,evil">Nested Mallory</a>
                            <img class="u-photo" src="javascript:alert(1)">
                        </div>
                        <div class="e-content">
                            <p onmouseover="alert(1)">Nested <em>reply</em></p>
                            <script>alert(1)</script>
                            <svg onload="alert(1)"></svg>
                            <iframe src="https://evil.example"></iframe>
                            <a href="javascript:alert(1)">bad child link</a>
                        </div>
                    </article>
                </div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

        child = WebmentionNestedResponse.objects.get(webmention=webmention)
        assert child.author_name == "Nested Mallory"
        assert child.author_url == ""
        assert child.author_photo == ""
        assert "<em>reply</em>" in child.content_html
        assert "<script" not in child.content_html
        assert "<svg" not in child.content_html
        assert "<iframe" not in child.content_html
        assert "onmouseover" not in child.content_html
        assert 'href="javascript:' not in child.content_html

    def test_processor_duplicate_receive_updates_existing_nested_response(self, processor):
        """Test duplicate processing updates one child row without creating duplicates."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        first_html = f'''
        <html><body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <article class="h-entry">
                    <a class="u-url" href="/comments/child">Child</a>
                    <div class="e-content">First nested content</div>
                </article>
            </article>
        </body></html>
        '''
        second_html = f'''
        <html><body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <article class="h-entry">
                    <a class="u-url" href="/comments/child">Child</a>
                    <div class="e-content">Updated nested content</div>
                </article>
            </article>
        </body></html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=first_html)
            webmention = processor.process_webmention(source_url, target_url)

        child = WebmentionNestedResponse.objects.get(webmention=webmention)
        first_child_id = child.pk
        first_seen_at = child.first_seen_at

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=second_html)
            duplicate = processor.process_webmention(source_url, target_url)

        child.refresh_from_db()
        assert duplicate.pk == webmention.pk
        assert WebmentionNestedResponse.objects.filter(webmention=webmention).count() == 1
        assert child.pk == first_child_id
        assert child.first_seen_at == first_seen_at
        assert child.content == "Updated nested content"
        assert child.status == "verified"

    def test_processor_duplicate_receive_clears_missing_current_nested_fields(self, processor):
        """Test current child fields stay consistent with the latest parsed nested snapshot."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        first_html = f'''
        <html><body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <article class="h-entry">
                    <a class="u-url" href="/comments/child">Child</a>
                    <a class="u-in-reply-to" href="{source_url}">Nested reply</a>
                    <div class="p-author h-card">
                        <a class="p-name u-url" href="/authors/jane">Jane Child</a>
                    </div>
                    <div class="e-content">First nested content</div>
                </article>
            </article>
        </body></html>
        '''
        second_html = f'''
        <html><body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <article class="h-entry">
                    <a class="u-url" href="/comments/child">Child</a>
                </article>
            </article>
        </body></html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=first_html)
            webmention = processor.process_webmention(source_url, target_url)

        child = WebmentionNestedResponse.objects.get(webmention=webmention)
        assert child.content == "First nested content"
        assert child.author_name == "Jane Child"
        assert child.mention_type == "reply"

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=second_html)
            processor.process_webmention(source_url, target_url)

        child.refresh_from_db()
        assert child.content == ""
        assert child.content_html == ""
        assert child.author_name == ""
        assert child.author_url == ""
        assert child.mention_type == "mention"
        assert child.parsed_h_entry["properties"]["url"] == ["https://example.com/comments/child"]

    def test_processor_creates_newly_discovered_nested_response_from_previous_snapshot(self, processor):
        """Test duplicate processing creates stable children discovered after the previous snapshot."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        first_html = f'''
        <html><body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <article class="h-entry"><a class="u-url" href="/comments/one">One</a></article>
            </article>
        </body></html>
        '''
        second_html = f'''
        <html><body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <article class="h-entry"><a class="u-url" href="/comments/one">One</a></article>
                <article class="h-entry"><a class="u-url" href="/comments/two">Two</a></article>
            </article>
        </body></html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=first_html)
            webmention = processor.process_webmention(source_url, target_url)

        assert webmention.source_snapshot.nested_response_identities == ["https://example.com/comments/one"]

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=second_html)
            processor.process_webmention(source_url, target_url)

        assert WebmentionNestedResponse.objects.filter(webmention=webmention).count() == 2
        assert WebmentionNestedResponse.objects.filter(
            webmention=webmention,
            identity="https://example.com/comments/two",
            status="verified",
        ).exists()
        webmention.source_snapshot.refresh_from_db()
        assert webmention.source_snapshot.nested_response_identities == [
            "https://example.com/comments/one",
            "https://example.com/comments/two",
        ]

    def test_processor_marks_disappeared_nested_responses_missing(self, processor):
        """Test disappeared children stop being current without deleting historical fields."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        first_html = f'''
        <html><body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <article class="h-entry"><a class="u-url" href="/comments/one">One</a></article>
                <article class="h-entry">
                    <a class="u-url" href="/comments/two">Two</a>
                    <div class="e-content">Keep this historical content</div>
                </article>
            </article>
        </body></html>
        '''
        second_html = f'''
        <html><body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <article class="h-entry"><a class="u-url" href="/comments/one">One</a></article>
            </article>
        </body></html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=first_html)
            webmention = processor.process_webmention(source_url, target_url)

        missing_child = WebmentionNestedResponse.objects.get(webmention=webmention, identity__endswith="/two")

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=second_html)
            processor.process_webmention(source_url, target_url)

        missing_child.refresh_from_db()
        assert missing_child.status == "missing"
        assert missing_child.verified_at is None
        assert missing_child.content == "Keep this historical content"
        assert missing_child.is_currently_displayable is False

    def test_processor_marks_all_nested_responses_missing_when_current_source_has_none(self, processor):
        """Test a verified source with no current children retires all stored child rows."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        first_html = f'''
        <html><body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <article class="h-entry"><a class="u-url" href="/comments/one">One</a></article>
                <article class="h-entry"><a class="u-url" href="/comments/two">Two</a></article>
            </article>
        </body></html>
        '''
        second_html = f'''
        <html><body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <div class="e-content">Parent only</div>
            </article>
        </body></html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=first_html)
            webmention = processor.process_webmention(source_url, target_url)

        assert WebmentionNestedResponse.objects.filter(webmention=webmention, status="verified").count() == 2

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=second_html)
            processor.process_webmention(source_url, target_url)

        assert WebmentionNestedResponse.objects.filter(webmention=webmention, status="missing").count() == 2
        webmention.source_snapshot.refresh_from_db()
        assert webmention.source_snapshot.nested_response_identities == []

    def test_processor_ignores_nested_entries_without_stable_identity(self, processor):
        """Test nested h-entries without uid, url, or HTML id do not become durable child rows."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        html_content = f'''
        <html><body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <article class="h-entry">
                    <div class="e-content">No stable identity</div>
                </article>
            </article>
        </body></html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)
            webmention = processor.process_webmention(source_url, target_url)

        assert webmention.status == "verified"
        assert WebmentionNestedResponse.objects.filter(webmention=webmention).count() == 0
        assert webmention.source_snapshot.nested_response_identities == []

    def test_processor_ignores_overlong_nested_response_identity(self, processor):
        """Test stable identities longer than the storage field are skipped."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        overlong_id = "child-" + ("x" * 520)
        html_content = f'''
        <html><body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <article class="h-entry" id="{overlong_id}">
                    <div class="e-content">Too long to store safely</div>
                </article>
            </article>
        </body></html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)
            webmention = processor.process_webmention(source_url, target_url)

        assert WebmentionNestedResponse.objects.filter(webmention=webmention).count() == 0
        assert webmention.source_snapshot.nested_response_identities == []

    def test_processor_updates_existing_source_snapshot_on_duplicate_receive(self, processor):
        """Test duplicate Webmention processing updates the related snapshot row."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        first_html = f'<html><body><a href="{target_url}">First</a></body></html>'
        second_html = f'<html><body><a href="{target_url}">Second</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=first_html)
            webmention = processor.process_webmention(source_url, target_url)

        snapshot = webmention.source_snapshot
        snapshot_id = snapshot.pk

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=second_html)
            duplicate = processor.process_webmention(source_url, target_url)

        duplicate_snapshot = duplicate.source_snapshot
        assert duplicate.pk == webmention.pk
        assert duplicate_snapshot.pk == snapshot_id
        assert duplicate_snapshot.raw_source_html == second_html
        assert duplicate_snapshot.content_digest == hashlib.sha256(second_html.encode("utf-8")).hexdigest()

    def test_processor_preserves_verified_status_when_source_snapshot_write_fails(self, processor):
        """Test snapshot storage failures do not demote an otherwise verified Webmention."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        html_content = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            with (
                patch(
                    "indieweb.processors.WebmentionSourceSnapshot.objects.update_or_create",
                    side_effect=RuntimeError("snapshot unavailable"),
                ),
                patch("indieweb.processors.webmention_received.send") as mock_signal,
            ):
                webmention = processor.process_webmention(source_url, target_url)

        webmention.refresh_from_db()
        assert webmention.status == "verified"
        assert webmention.verified_at is not None
        assert not WebmentionSourceSnapshot.objects.filter(webmention=webmention).exists()
        mock_signal.assert_called_once_with(
            sender=WebmentionProcessor,
            webmention=webmention,
            source_url=source_url,
            target_url=target_url,
        )

    @pytest.mark.parametrize(
        ("status_code", "html_content", "content_type"),
        [
            (404, "Not found", "text/html"),
            (200, '{"ok": true}', "application/json"),
            (200, "<html><body>No target link</body></html>", "text/html"),
        ],
    )
    def test_processor_failure_paths_do_not_create_source_snapshot(
        self, processor, status_code, html_content, content_type
    ):
        """Test failed fetch, non-HTML, and missing-target paths do not store snapshots."""
        source_url = f"https://example.com/post-{status_code}-{content_type}"
        target_url = "https://mysite.com/article"

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(
                mock_get_class,
                status_code=status_code,
                text=html_content,
                content_type=content_type,
            )

            webmention = processor.process_webmention(source_url, target_url)

        assert webmention.status == "failed"
        assert not WebmentionSourceSnapshot.objects.filter(webmention=webmention).exists()

    def test_processor_failure_does_not_update_existing_source_snapshot(self, processor):
        """Test later failure preserves the previous successful source snapshot."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        verified_html = f'<html><body><a href="{target_url}">Verified</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=verified_html)
            webmention = processor.process_webmention(source_url, target_url)

        snapshot = webmention.source_snapshot
        original_snapshot_id = snapshot.pk
        original_digest = snapshot.content_digest

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=410)
            processor.process_webmention(source_url, target_url)

        snapshot.refresh_from_db()
        assert snapshot.pk == original_snapshot_id
        assert snapshot.raw_source_html == verified_html
        assert snapshot.content_digest == original_digest

    def test_processor_failure_preserves_children_but_parent_status_controls_displayability(self, processor):
        """Test later source failures do not update children from failed content."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        verified_html = f'''
        <html><body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <article class="h-entry">
                    <a class="u-url" href="/comments/child">Child</a>
                    <div class="e-content">Original child content</div>
                </article>
            </article>
        </body></html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=verified_html)
            webmention = processor.process_webmention(source_url, target_url)

        child = WebmentionNestedResponse.objects.get(webmention=webmention)

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=410)
            processor.process_webmention(source_url, target_url)

        webmention.refresh_from_db()
        child.refresh_from_db()
        assert webmention.status == "failed"
        assert child.status == "verified"
        assert child.content == "Original child content"
        assert child.is_currently_displayable is False

    @override_settings(INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS=("trusted.example",))
    def test_processor_vouch_failure_does_not_create_source_snapshot(self, processor):
        """Test Vouch failures do not store snapshots for otherwise fetched sources."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        source_html = f'''
        <html><body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <article class="h-entry"><a class="u-url" href="/comments/child">Child</a></article>
            </article>
        </body></html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = _source_response(status_code=200, text=source_html)

            webmention = processor.process_webmention(
                source_url,
                target_url,
                vouch_url="https://untrusted.example/vouch-for-example",
            )

        assert webmention.status == "failed"
        assert not WebmentionSourceSnapshot.objects.filter(webmention=webmention).exists()
        assert not WebmentionNestedResponse.objects.filter(webmention=webmention).exists()

    @override_settings(INDIEWEB_SPAM_CHECKER="indieweb.interfaces.NoOpSpamChecker")
    def test_processor_spam_does_not_create_source_snapshot(self, processor):
        """Test spam-classified Webmentions do not store source snapshots."""
        source_url = "https://spam.example/post"
        target_url = "https://mysite.com/article"
        html_content = f'''
        <html><body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <article class="h-entry"><a class="u-url" href="/comments/child">Child</a></article>
            </article>
        </body></html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            with patch("indieweb.interfaces.NoOpSpamChecker.check") as mock_check:
                mock_check.return_value = {
                    "is_spam": True,
                    "confidence": 0.95,
                    "details": "Spam keywords detected",
                }

                webmention = processor.process_webmention(source_url, target_url)

        assert webmention.status == "spam"
        assert not WebmentionSourceSnapshot.objects.filter(webmention=webmention).exists()
        assert not WebmentionNestedResponse.objects.filter(webmention=webmention).exists()

    def test_processor_detects_mention_types(self, processor):
        """Test that processor correctly detects different mention types."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        # Test reply
        reply_html = f'''
        <html>
        <body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">In reply to</a>
                <div class="e-content">This is a reply</div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = reply_html

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)
            assert webmention.mention_type == "reply"

        # Test like
        like_html = f'''
        <html>
        <body>
            <article class="h-entry">
                <a class="u-like-of" href="{target_url}">Liked</a>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = like_html

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)
            assert webmention.mention_type == "like"

        # Test repost
        repost_html = f'''
        <html>
        <body>
            <article class="h-entry">
                <a class="u-repost-of" href="{target_url}">Reposted</a>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = repost_html

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)
            assert webmention.mention_type == "repost"

    def test_processor_classifies_microformats_with_canonical_target_variant(self, processor):
        """Test microformats mention type matching uses canonical URL equivalence."""
        source_url = "https://example.com/canonical-reply"
        target_url = "https://mysite.com/article?a=1&b=2"

        html_content = """
        <html>
        <body>
            <article class="h-entry">
                <a class="u-in-reply-to" href="https://www.mysite.com/article/?b=2&a=1#comments">Reply</a>
                <div class="e-content">This is a reply</div>
            </article>
        </body>
        </html>
        """

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = html_content
            mock_response.headers = {"content-type": "text/html"}
            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.mention_type == "reply"

    def test_search_for_mentioning_entry_matches_dict_property_value(self, processor):
        """Test microformats URL properties can match dict-shaped values."""
        target_url = "https://mysite.com/article"
        items = [
            {
                "type": ["h-entry"],
                "properties": {
                    "like-of": [{"value": "https://www.mysite.com/article#liked"}],
                },
            }
        ]

        assert processor._search_for_mentioning_entry(items, target_url) == items[0]

    def test_search_for_mentioning_entry_matches_plain_text_url_token(self, processor):
        """Test plain text content can conservatively match target URL tokens."""
        target_url = "https://en.wikipedia.org/wiki/Foo_(bar)"
        items = [
            {
                "type": ["h-entry"],
                "properties": {
                    "content": [
                        {
                            "value": (
                                "Reading https://en.wikipedia.org/wiki/Foo_(bar), then https://example.com/other."
                            ),
                        }
                    ],
                },
            }
        ]

        assert processor._search_for_mentioning_entry(items, target_url) == items[0]

    def test_search_for_mentioning_entry_matches_angle_bracketed_plain_text_url_token(self, processor):
        """Test angle-bracketed plain text URL tokens can match the target."""
        target_url = "https://mysite.com/article"
        items = [
            {
                "type": ["h-entry"],
                "properties": {
                    "content": [
                        {
                            "value": "Reading <https://mysite.com/article> now.",
                        }
                    ],
                },
            }
        ]

        assert processor._search_for_mentioning_entry(items, target_url) == items[0]

    def test_processor_handles_no_microformats(self, processor):
        """Test that processor handles pages without microformats."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <body>
            <p>Simple page with <a href="{target_url}">a link</a></p>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_name == ""
            assert webmention.author_url == ""
            assert webmention.mention_type == "mention"

    @override_settings(INDIEWEB_SPAM_CHECKER="indieweb.interfaces.NoOpSpamChecker")
    def test_processor_uses_spam_checker(self, processor):
        """Test that processor uses configured spam checker."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        html_content = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            # Patch the spam checker to verify it's called
            with patch("indieweb.interfaces.NoOpSpamChecker.check") as mock_check:
                mock_check.return_value = {
                    "is_spam": False,
                    "confidence": 0.0,
                    "details": None,
                }

                webmention = processor.process_webmention(source_url, target_url)

                mock_check.assert_called_once()
                assert webmention.status == "verified"
                assert webmention.spam_check_result is not None

    @override_settings(INDIEWEB_SPAM_CHECKER="indieweb.interfaces.NoOpSpamChecker")
    def test_processor_marks_spam(self, processor):
        """Test that processor marks webmentions as spam when detected."""
        source_url = "https://spam.com/post"
        target_url = "https://mysite.com/article"

        html_content = f'<html><body>Buy cheap stuff! <a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            # Mock spam checker to return spam
            with patch("indieweb.interfaces.NoOpSpamChecker.check") as mock_check:
                mock_check.return_value = {
                    "is_spam": True,
                    "confidence": 0.95,
                    "details": "Spam keywords detected",
                }

                webmention = processor.process_webmention(source_url, target_url)

                assert webmention.status == "spam"
                assert webmention.spam_check_result["is_spam"] is True
                assert webmention.verified_at is None

    @override_settings(INDIEWEB_SPAM_CHECKER="indieweb.interfaces.NoOpSpamChecker")
    def test_processor_clears_verified_timestamp_and_preserves_fields_when_existing_webmention_becomes_spam(
        self, processor
    ):
        """Test that spam reclassification clears timestamps and preserves parsed fields."""
        source_url = "https://spam.com/post"
        target_url = "https://mysite.com/article"
        Webmention.objects.create(
            source_url=source_url,
            target_url=target_url,
            status="verified",
            author_name="Original Author",
            content="Original content",
            content_html="<p>Original content</p>",
            mention_type="reply",
            verified_at=django_timezone.now() - timedelta(days=1),
        )

        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <div class="p-author h-card">
                    <a class="p-name" href="https://spam.com">Spam Author</a>
                </div>
                <a class="u-like-of" href="{target_url}">Liked</a>
                <div class="e-content">Spam content</div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            with patch("indieweb.interfaces.NoOpSpamChecker.check") as mock_check:
                mock_check.return_value = {
                    "is_spam": True,
                    "confidence": 0.95,
                    "details": "Spam keywords detected",
                }

                webmention = processor.process_webmention(source_url, target_url)

                assert webmention.status == "spam"
                assert webmention.verified_at is None
                assert webmention.author_name == "Original Author"
                assert webmention.content == "Original content"
                assert webmention.content_html == "<p>Original content</p>"
                assert webmention.mention_type == "reply"

    def test_processor_updates_existing_webmention(self, processor):
        """Test that processor updates existing webmention."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        # Create existing webmention
        existing = Webmention.objects.create(
            source_url=source_url,
            target_url=target_url,
            status="pending",
            author_name="Old Name",
        )

        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <div class="p-author h-card">
                    <a class="p-name" href="https://example.com">New Name</a>
                </div>
                <div class="e-content">Updated content <a href="{target_url}">link</a></div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.id == existing.id
            assert webmention.author_name == "New Name"
            assert webmention.status == "verified"
            assert "Updated content" in webmention.content

    def test_processor_handles_deleted_source(self, processor):
        """Test that processor handles when source is deleted."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        verified_at = django_timezone.now()

        # Create existing verified webmention
        existing = Webmention.objects.create(
            source_url=source_url,
            target_url=target_url,
            status="verified",
            author_name="John Doe",
            author_url="https://example.com/author",
            author_photo="https://example.com/avatar.jpg",
            content="Original content",
            content_html="<p>Original content</p>",
            verified_at=verified_at,
        )

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=410)

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.id == existing.id
            assert webmention.status == "failed"
            assert webmention.source_url == source_url
            assert webmention.target_url == target_url
            assert webmention.verified_at is None
            # Original content should be preserved
            assert webmention.author_name == "John Doe"
            assert webmention.author_url == "https://example.com/author"
            assert webmention.author_photo == "https://example.com/avatar.jpg"
            assert webmention.content == "Original content"
            assert webmention.content_html == "<p>Original content</p>"

    def test_processor_clears_verified_timestamp_when_source_no_longer_links_target(self, processor):
        """Test that a verified webmention fails when the source no longer links the target."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        existing = Webmention.objects.create(
            source_url=source_url,
            target_url=target_url,
            status="verified",
            author_name="John Doe",
            content="Original content",
            verified_at=django_timezone.now(),
        )

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(
                mock_get_class,
                status_code=200,
                text="<html><body><p>The old target link is gone.</p></body></html>",
            )

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.id == existing.id
            assert webmention.status == "failed"
            assert webmention.verified_at is None
            assert webmention.author_name == "John Doe"
            assert webmention.content == "Original content"

    def test_processor_can_reverify_existing_failed_webmention(self, processor):
        """Test that a failed webmention can become verified again when the link returns."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        existing = Webmention.objects.create(
            source_url=source_url,
            target_url=target_url,
            status="failed",
            author_name="Old Name",
            content="Original content",
            verified_at=django_timezone.now() - timedelta(days=1),
        )
        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <div class="p-author h-card">
                    <a class="p-name" href="https://example.com">New Name</a>
                </div>
                <div class="e-content">Restored content <a href="{target_url}">link</a></div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            before = django_timezone.now()
            webmention = processor.process_webmention(source_url, target_url)
            after = django_timezone.now()

            assert webmention.id == existing.id
            assert webmention.status == "verified"
            assert webmention.author_name == "New Name"
            assert "Restored content" in webmention.content
            assert webmention.verified_at is not None
            assert before <= webmention.verified_at <= after

    def test_processor_handles_new_gone_source_without_verified_timestamp(self, processor):
        """Test that a new webmention with a gone source fails predictably."""
        source_url = "https://example.com/gone"
        target_url = "https://mysite.com/article"

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=410)

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "failed"
            assert webmention.source_url == source_url
            assert webmention.target_url == target_url
            assert webmention.verified_at is None

    def test_processor_clears_verified_timestamp_on_failed_fetch(self, processor):
        """Test that failed reprocessing clears stale verification timestamps."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"
        existing = Webmention.objects.create(
            source_url=source_url,
            target_url=target_url,
            status="verified",
            verified_at=django_timezone.now(),
        )

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=404)

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.id == existing.id
            assert webmention.status == "failed"
            assert webmention.verified_at is None

    def test_processor_emits_signal(self, processor):
        """Test that processor emits webmention_received signal."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        html_content = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            with patch("indieweb.processors.webmention_received.send") as mock_signal:
                webmention = processor.process_webmention(source_url, target_url)

                mock_signal.assert_called_once_with(
                    sender=WebmentionProcessor,
                    webmention=webmention,
                    source_url=source_url,
                    target_url=target_url,
                )

    def test_processor_sets_verified_timestamp(self, processor):
        """Test that processor sets verified_at timestamp."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        html_content = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            before = django_timezone.now()
            webmention = processor.process_webmention(source_url, target_url)
            after = django_timezone.now()

            assert webmention.verified_at is not None
            assert before <= webmention.verified_at <= after

    def test_processor_handles_non_html_content(self, processor):
        """Test that processor rejects non-HTML content."""
        source_url = "https://example.com/data.json"
        target_url = "https://mysite.com/article"

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = '{"data": "json"}'

            mock_response.headers = {"content-type": "application/json"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)
            assert webmention.status == "failed"

    def test_processor_handles_relative_author_urls(self, processor):
        """Test that processor handles relative URLs in author data."""
        source_url = "https://example.com/posts/123"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <div class="p-author h-card">
                    <img class="u-photo" src="/avatar.jpg" alt="John">
                    <a class="p-name u-url" href="/about">John Doe</a>
                </div>
                <div class="e-content">
                    Content with <a href="{target_url}">link</a>
                </div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.author_url == "https://example.com/about"
            assert webmention.author_photo == "https://example.com/avatar.jpg"

    def test_processor_extracts_text_content(self, processor):
        """Test that processor extracts both text and HTML content."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <div class="e-content">
                    <p>This is <strong>bold</strong> text with a <a href="{target_url}">link</a>.</p>
                </div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.content == "This is bold text with a link."
            assert "<strong>bold</strong>" in webmention.content_html

    def test_processor_logging(self, processor, caplog):
        """Test that processor logs appropriate messages."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        html_content = f'<html><body><a href="{target_url}">Link</a></body></html>'

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            import logging

            with caplog.at_level(logging.INFO):
                processor.process_webmention(source_url, target_url)

            assert "Processing webmention" in caplog.text
            assert "Successfully processed webmention" in caplog.text

    def test_processor_handles_author_url_with_separate_hcard(self, processor):
        """Test that processor handles author as URL reference with separate h-card (like feed.city)."""
        source_url = "https://example.com/post/123"
        target_url = "https://mysite.com/article"

        # Simulate feed.city style markup: separate h-card and h-entry with author as URL string
        html_content = f'''
        <html>
        <body>
            <div class="h-card">
                <img class="u-photo" src="https://example.com/avatar.jpg" alt="John">
                <a class="p-name u-url" href="https://example.com/author">John Doe</a>
            </div>
            <article class="h-entry">
                <a class="u-like-of" href="{target_url}">Liked this</a>
                <data class="p-author" value="https://example.com/author"></data>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            # Should extract author info from the separate h-card
            assert webmention.status == "verified"
            assert webmention.author_name == "John Doe"
            assert webmention.author_url == "https://example.com/author"
            assert webmention.author_photo == "https://example.com/avatar.jpg"
            assert webmention.mention_type == "like"

    @pytest.mark.parametrize(
        ("author_reference", "h_card_url"),
        [
            ("https://example.com/author/", "https://example.com/author"),
            ("https://www.example.com/author", "https://example.com/author"),
            ("HTTPS://Example.COM/author", "https://example.com/author"),
            ("https://example.com/author#bio", "https://example.com/author"),
            ("https://example.com/author?b=2&a=1", "https://example.com/author?a=1&b=2"),
        ],
    )
    def test_processor_matches_explicit_author_reference_to_canonical_hcard_url(
        self, processor, author_reference, h_card_url
    ):
        """Test explicit URL-valued p-author references use canonical h-card URL matching."""
        source_url = "https://example.com/post/123"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <body>
            <div class="h-card">
                <img class="u-photo" src="https://example.com/avatar.jpg" alt="John">
                <a class="p-name u-url" href="{h_card_url}">John Doe</a>
            </div>
            <article class="h-entry">
                <a class="u-like-of" href="{target_url}">Liked this</a>
                <data class="p-author" value="{author_reference}"></data>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_name == "John Doe"
            assert webmention.author_url == h_card_url
            assert webmention.author_photo == "https://example.com/avatar.jpg"

    def test_processor_matches_rel_author_to_canonical_hcard_url(self, processor):
        """Test rel=author uses canonical h-card URL matching."""
        source_url = "https://example.com/post/123"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <head><link rel="author" href="https://www.example.com/author/?b=2&a=1"></head>
        <body>
            <div class="h-card">
                <img class="u-photo" src="https://example.com/avatar.jpg" alt="John">
                <a class="p-name u-url" href="https://example.com/author?a=1&b=2">John Doe</a>
            </div>
            <article class="h-entry">
                <a class="u-like-of" href="{target_url}">Liked this</a>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_name == "John Doe"
            assert webmention.author_url == "https://example.com/author?a=1&b=2"
            assert webmention.author_photo == "https://example.com/avatar.jpg"

    def test_find_h_card_by_url_ignores_non_string_url_properties(self, processor):
        """Test malformed h-card URL properties do not crash canonical h-card lookup."""
        items = [
            {
                "type": ["h-card"],
                "properties": {
                    "name": ["Broken"],
                    "url": [{"value": "https://example.com/author"}, None],
                },
            },
            {
                "type": ["h-card"],
                "properties": {
                    "name": ["John Doe"],
                    "url": ["https://example.com/author"],
                },
            },
        ]

        h_card = processor._search_items_for_h_card(items, "https://example.com/author/")

        assert h_card == items[1]

    def test_processor_handles_nested_hcard_in_hfeed(self, processor):
        """Test that processor handles h-card nested inside an h-feed structure."""
        source_url = "https://example.com/feed"
        target_url = "https://mysite.com/article"

        # Simulate h-feed containing h-card and h-entry
        html_content = f'''
        <html>
        <body>
            <div class="h-feed">
                <div class="h-card">
                    <img class="u-photo" src="https://example.com/photo.jpg" alt="Jane">
                    <a class="p-name u-url" href="https://example.com/jane">Jane Smith</a>
                </div>
                <article class="h-entry">
                    <a class="u-in-reply-to" href="{target_url}">Reply</a>
                    <data class="p-author" value="https://example.com/jane"></data>
                    <div class="e-content">Great post!</div>
                </article>
            </div>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            # Should find the nested h-card and extract author info
            assert webmention.status == "verified"
            assert webmention.author_name == "Jane Smith"
            assert webmention.author_url == "https://example.com/jane"
            assert webmention.author_photo == "https://example.com/photo.jpg"
            assert webmention.mention_type == "reply"

    def test_processor_handles_author_url_without_matching_hcard(self, processor):
        """Test that processor falls back to URL as name when no matching h-card exists."""
        source_url = "https://example.com/post"
        target_url = "https://mysite.com/article"

        # Author is a URL but there's no matching h-card on the page
        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <a class="u-like-of" href="{target_url}">Liked</a>
                <data class="p-author" value="https://example.com/nonexistent"></data>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()

            mock_get_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()

            mock_response.status_code = 200

            mock_response.text = html_content

            mock_response.headers = {"content-type": "text/html"}

            mock_client.get.return_value = mock_response

            webmention = processor.process_webmention(source_url, target_url)

            # Should fall back to using URL as name (backwards compatibility)
            assert webmention.status == "verified"
            assert webmention.author_name == "https://example.com/nonexistent"
            assert webmention.author_url == "https://example.com/nonexistent"
            assert webmention.author_photo == ""
            assert webmention.mention_type == "like"

    def test_processor_handles_relative_author_url_without_matching_hcard(self, processor):
        """Test relative author URL references fall back to an absolute URL as the name."""
        source_url = "https://example.com/posts/source"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <body>
            <article class="h-entry">
                <a class="u-like-of" href="{target_url}">Liked</a>
                <data class="p-author" value="/authors/missing"></data>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_name == "https://example.com/authors/missing"
            assert webmention.author_url == "https://example.com/authors/missing"
            assert webmention.author_photo == ""

    def test_processor_uses_rel_author_fragment_to_find_same_page_hcard(self, processor):
        """Test rel=author can point to an h-card already present on the same page."""
        source_url = "https://example.com/posts/source"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <head><link rel="author" href="#author"></head>
        <body>
            <div id="author" class="h-card">
                <img class="u-photo" src="/avatar.jpg" alt="Alice">
                <a class="p-name u-url" href="/authors/alice">Alice Author</a>
            </div>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <div class="e-content">Reply content</div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_name == "Alice Author"
            assert webmention.author_url == "https://example.com/authors/alice"
            assert webmention.author_photo == "https://example.com/avatar.jpg"

    def test_processor_prefers_explicit_author_over_rel_author_and_page_hcard(self, processor):
        """Test explicit h-entry author data has priority over later authorship fallbacks."""
        source_url = "https://example.com/posts/source"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <head><link rel="author" href="#rel-author"></head>
        <body>
            <div id="rel-author" class="h-card">
                <a class="p-name u-url" href="/authors/rel">Rel Author</a>
            </div>
            <div class="h-card">
                <a class="p-name u-url" href="/authors/page">Page Author</a>
            </div>
            <article class="h-entry">
                <div class="p-author h-card">
                    <a class="p-name u-url" href="/authors/explicit">Explicit Author</a>
                </div>
                <a class="u-like-of" href="{target_url}">Liked</a>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_name == "Explicit Author"
            assert webmention.author_url == "https://example.com/authors/explicit"

    def test_processor_resolves_relative_rel_author_to_same_page_hcard(self, processor):
        """Test relative rel=author links resolve against the source base URL."""
        source_url = "https://example.com/posts/source"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <head><link rel="author" href="/authors/bob"></head>
        <body>
            <div class="h-card">
                <a class="p-name u-url" href="/authors/bob">Bob Author</a>
            </div>
            <article class="h-entry">
                <a class="u-repost-of" href="{target_url}">Repost</a>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_name == "Bob Author"
            assert webmention.author_url == "https://example.com/authors/bob"

    def test_processor_uses_final_source_url_as_rel_author_base_after_redirect(self, processor):
        """Test relative rel=author links resolve against the final redirected source URL."""
        source_url = "https://old.example.com/posts/source"
        final_url = "https://new.example.com/posts/final"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <head><link rel="author" href="/authors/carol"></head>
        <body>
            <div class="h-card">
                <img class="u-photo" src="avatar.jpg" alt="Carol">
                <a class="p-name u-url" href="/authors/carol">Carol Author</a>
            </div>
            <article class="h-entry">
                <a class="u-like-of" href="{target_url}">Liked</a>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            mock_client = Mock()
            mock_get_class.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = [
                _source_response(status_code=302, headers={"Location": final_url}),
                _source_response(status_code=200, text=html_content),
            ]

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_name == "Carol Author"
            assert webmention.author_url == "https://new.example.com/authors/carol"
            assert webmention.author_photo == "https://new.example.com/posts/avatar.jpg"

    def test_processor_uses_single_page_level_hcard_fallback(self, processor):
        """Test a single page-level h-card is used when an h-entry has no author."""
        source_url = "https://example.com/posts/source"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <body>
            <div class="h-card">
                <img class="u-photo" src="/dana.jpg" alt="Dana">
                <a class="p-name u-url" href="/authors/dana">Dana Author</a>
            </div>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
                <div class="e-content">No explicit author here.</div>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_name == "Dana Author"
            assert webmention.author_url == "https://example.com/authors/dana"
            assert webmention.author_photo == "https://example.com/dana.jpg"

    def test_processor_uses_page_hcard_when_rel_author_has_no_matching_hcard(self, processor):
        """Test an unresolved rel=author link can fall through to the page-level h-card fallback."""
        source_url = "https://example.com/posts/source"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <head><link rel="author" href="/authors/missing"></head>
        <body>
            <div class="h-card">
                <a class="p-name u-url" href="/authors/erin">Erin Author</a>
            </div>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_name == "Erin Author"
            assert webmention.author_url == "https://example.com/authors/erin"

    def test_processor_declines_ambiguous_page_level_hcard_fallback(self, processor):
        """Test multiple page-level h-cards do not produce a guessed fallback author."""
        source_url = "https://example.com/posts/source"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <body>
            <div class="h-card"><a class="p-name u-url" href="/authors/one">One Author</a></div>
            <div class="h-card"><a class="p-name u-url" href="/authors/two">Two Author</a></div>
            <article class="h-entry">
                <a class="u-like-of" href="{target_url}">Liked</a>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_name == ""
            assert webmention.author_url == ""
            assert webmention.author_photo == ""

    def test_processor_uses_local_profile_for_rel_author_hcard(self, processor):
        """Test local Profile data still overrides authors extracted through rel=author."""
        user = get_user_model().objects.create_user(username="localauthor", email="local@example.com")
        Profile.objects.create(
            user=user,
            h_card={
                "name": ["Local Profile Name"],
                "url": ["https://example.com/authors/local"],
                "photo": ["https://example.com/local-profile.jpg"],
            },
        )
        source_url = "https://remote.example.com/posts/source"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <head><link rel="author" href="https://example.com/authors/local"></head>
        <body>
            <div class="h-card">
                <img class="u-photo" src="https://remote.example.com/remote.jpg" alt="Remote">
                <a class="p-name u-url" href="https://example.com/authors/local">Remote Parsed Name</a>
            </div>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_name == "Local Profile Name"
            assert webmention.author_url == "https://example.com/authors/local"
            assert webmention.author_photo == "https://example.com/local-profile.jpg"

    def test_processor_uses_local_profile_after_canonical_hcard_url_match(self, processor):
        """Test Profile overrides still apply after canonical h-card URL matching."""
        user = get_user_model().objects.create_user(username="canonicalauthor", email="canonical@example.com")
        Profile.objects.create(
            user=user,
            h_card={
                "name": ["Canonical Profile Name"],
                "url": ["https://example.com/authors/canonical"],
                "photo": ["https://example.com/canonical-profile.jpg"],
            },
        )
        source_url = "https://remote.example.com/posts/source"
        target_url = "https://mysite.com/article"

        html_content = f'''
        <html>
        <head><link rel="author" href="https://www.example.com/authors/canonical/"></head>
        <body>
            <div class="h-card">
                <img class="u-photo" src="https://remote.example.com/remote.jpg" alt="Remote">
                <a class="p-name u-url" href="https://example.com/authors/canonical">Remote Parsed Name</a>
            </div>
            <article class="h-entry">
                <a class="u-in-reply-to" href="{target_url}">Reply</a>
            </article>
        </body>
        </html>
        '''

        with patch("httpx.Client") as mock_get_class:
            _mock_source_response(mock_get_class, status_code=200, text=html_content)

            webmention = processor.process_webmention(source_url, target_url)

            assert webmention.status == "verified"
            assert webmention.author_name == "Canonical Profile Name"
            assert webmention.author_url == "https://example.com/authors/canonical"
            assert webmention.author_photo == "https://example.com/canonical-profile.jpg"
