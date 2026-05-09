import logging

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.http import urlencode

from indieweb.log_redaction import redact_state, redact_token, redact_url, redact_url_origin


@pytest.mark.parametrize("inp", ["https://example.com/post/1", "http://other.example/page"])
def test_redact_url_passthrough_returns_input(inp):
    assert redact_url(inp, mode="passthrough") == inp


def test_redact_url_redact_returns_hex_digest():
    out = redact_url("https://example.com/post/1", mode="redact")
    assert out != "https://example.com/post/1"
    assert len(out) == 12
    assert all(c in "0123456789abcdef" for c in out)


def test_redact_url_redact_is_stable():
    a = redact_url("https://example.com/post/1", mode="redact")
    b = redact_url("https://example.com/post/1", mode="redact")
    assert a == b


def test_redact_url_origin_strips_path():
    a = redact_url_origin("https://example.com/post/1?x=1", mode="redact")
    b = redact_url_origin("https://example.com/different", mode="redact")
    assert a == b  # Same origin -> same digest


def test_redact_state_fixed_length():
    out = redact_state("opaque-state-value", mode="redact")
    assert len(out) == 12


def test_resolve_mode_uses_setting_when_mode_not_passed(settings):
    settings.INDIEWEB_LOG_REDACTION = "redact"
    out = redact_url("https://example.com/x")
    assert out != "https://example.com/x"


def test_resolve_mode_unknown_setting_value_falls_back_to_passthrough(settings):
    settings.INDIEWEB_LOG_REDACTION = "garbage"
    out = redact_url("https://example.com/x")
    assert out == "https://example.com/x"


@pytest.mark.django_db
def test_auth_get_logs_redacted_redirect_uri_in_redact_mode(client, settings, caplog):
    """In redact mode, the auth view's GET log line must not leak redirect_uri."""
    settings.INDIEWEB_LOG_REDACTION = "redact"
    User = get_user_model()
    user = User.objects.create_user(username="rdct", email="rdct@example.org", password="pw")
    client.login(username=user.username, password="pw")

    base_url = reverse("indieweb:auth")
    params = {
        "client_id": "https://client.example/",
        "redirect_uri": "https://attacker.example/cb",
        "state": "opaque-state",
        "me": "https://me.example/",
        "response_type": "code",
    }
    with caplog.at_level(logging.INFO, logger="indieweb.views"):
        client.get(f"{base_url}?{urlencode(params)}")

    # redirect_uri / me / state values should not appear verbatim at INFO/WARNING level.
    assert "https://attacker.example/cb" not in caplog.text
    assert "opaque-state" not in caplog.text


@pytest.mark.django_db
def test_auth_get_logs_passthrough_includes_values_by_default(client, settings, caplog):
    """In passthrough mode (default), values appear in the log as before."""
    settings.INDIEWEB_LOG_REDACTION = "passthrough"
    User = get_user_model()
    user = User.objects.create_user(username="pt", email="pt@example.org", password="pw")
    client.login(username=user.username, password="pw")

    base_url = reverse("indieweb:auth")
    params = {
        "client_id": "https://client.example/",
        "redirect_uri": "https://attacker.example/cb",
        "state": "opaque-state",
        "me": "https://me.example/",
        "response_type": "code",
    }
    with caplog.at_level(logging.INFO, logger="indieweb.views"):
        client.get(f"{base_url}?{urlencode(params)}")

    assert "https://attacker.example/cb" in caplog.text


# ----------------------------------------------------------------------------
# redact_token: bearer / authorization-code values must never appear in full,
# even in passthrough mode. The helper returns ``{value[:8]}...`` for
# diagnostics in passthrough and a stable HMAC digest in redact mode.
# ----------------------------------------------------------------------------


def test_redact_token_passthrough_truncates_value():
    out = redact_token("longbearersecretvalue", mode="passthrough")
    assert out == "longbear..."
    assert "longbearersecretvalue" not in out


def test_redact_token_redact_returns_stable_hex_digest():
    a = redact_token("longbearersecretvalue", mode="redact")
    b = redact_token("longbearersecretvalue", mode="redact")
    assert a == b
    assert len(a) == 12
    assert all(c in "0123456789abcdef" for c in a)
    assert "longbear" not in a


def test_redact_token_passthrough_handles_empty_value():
    assert redact_token("", mode="passthrough") == ""


@pytest.mark.django_db
def test_token_auth_logs_do_not_leak_token_prefix_in_redact_mode(client, settings, caplog):
    """In redact mode, ``TokenAuthMixin`` token-auth failure logs must not echo the
    submitted token prefix. The previous ``key[:8]+'...'`` form leaked the first
    eight bytes of the bearer credential."""
    settings.INDIEWEB_LOG_REDACTION = "redact"

    micropub_url = reverse("indieweb:micropub")
    bearer = "leakyprefixsecretvalue"
    with caplog.at_level(logging.WARNING, logger="indieweb.views"):
        client.get(micropub_url, HTTP_AUTHORIZATION=f"Bearer {bearer}")

    # The leading 8 chars must not appear verbatim in any log record.
    assert bearer[:8] not in caplog.text
    # Some log line should still mention the failure (token not found / no auth).
    assert "Token not found" in caplog.text or "No authorization token" in caplog.text


@pytest.mark.django_db
def test_token_introspection_logs_do_not_leak_token_prefix_in_redact_mode(client, settings, caplog):
    """``TokenIntrospectionView`` token-not-found logs must also redact the submitted token."""
    settings.INDIEWEB_LOG_REDACTION = "redact"

    introspection_url = reverse("indieweb:token-introspection")
    bearer = "introsecretkeyvalue"
    with caplog.at_level(logging.INFO, logger="indieweb.views"):
        client.post(introspection_url, data={"token": bearer}, HTTP_AUTHORIZATION="Bearer somecallerkey")

    assert bearer[:8] not in caplog.text


# ----------------------------------------------------------------------------
# Webmention outcome log lines must redact source/target URLs in redact mode.
# These are emitted at INFO/WARNING by ``WebmentionProcessor``.
# ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_webmention_outcome_logs_redact_source_url_in_redact_mode(settings, caplog):
    """A webmention whose source can't be fetched must not echo the source URL
    verbatim in the resulting outcome log line."""
    import httpx

    from indieweb.processors import WebmentionProcessor

    settings.INDIEWEB_LOG_REDACTION = "redact"

    def handler(request: httpx.Request) -> httpx.Response:
        # 410 Gone is one of the explicit info-level outcome paths in
        # ``_collect_webmention_outcome``; the previous log string interpolated
        # ``source_url`` directly.
        return httpx.Response(410)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    processor = WebmentionProcessor(client=client)

    source = "https://attacker.example.org/leaky-source-path"
    target = "https://example.org/post"
    with caplog.at_level(logging.INFO, logger="indieweb.processors"):
        processor.process_webmention(source, target)

    # In redact mode neither source nor target should appear verbatim in INFO/WARNING logs.
    assert "leaky-source-path" not in caplog.text
    assert "https://attacker.example.org" not in caplog.text


@pytest.mark.django_db
def test_webmention_outcome_logs_passthrough_includes_urls(settings, caplog):
    """In passthrough mode (default) the outcome log line still contains the URLs verbatim
    so existing operators retain the diagnostic value they had before."""
    import httpx

    from indieweb.processors import WebmentionProcessor

    settings.INDIEWEB_LOG_REDACTION = "passthrough"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(410)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    processor = WebmentionProcessor(client=client)

    source = "https://attacker.example.org/leaky-source-path"
    target = "https://example.org/post"
    with caplog.at_level(logging.INFO, logger="indieweb.processors"):
        processor.process_webmention(source, target)

    assert source in caplog.text
