import logging

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.http import urlencode

from indieweb import log_redaction
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


@pytest.mark.parametrize("value", ["garbage", "true", True, 1, None])
def test_resolve_mode_unknown_setting_value_fails_closed_to_redact(settings, caplog, value):
    settings.INDIEWEB_LOG_REDACTION = value
    log_redaction._warned_settings.clear()
    with caplog.at_level(logging.WARNING, logger="indieweb.log_redaction"):
        out = redact_url("https://example.com/x")
        redact_url("https://example.com/y")
    assert out != "https://example.com/x"
    assert len(out) == 12
    # The misconfiguration is reported once, not on every log line.
    assert caplog.text.count("INDIEWEB_LOG_REDACTION=") == 1


@pytest.mark.parametrize(
    ("value", "expected_redacted"), [(" REDACT ", True), ("Redact", True), ("PassThrough", False)]
)
def test_resolve_mode_accepts_case_and_whitespace_variants(settings, value, expected_redacted):
    settings.INDIEWEB_LOG_REDACTION = value
    out = redact_url("https://example.com/x")
    assert (out != "https://example.com/x") is expected_redacted


def test_resolve_mode_defaults_to_passthrough_when_unset(settings):
    del settings.INDIEWEB_LOG_REDACTION
    assert redact_url("https://example.com/x") == "https://example.com/x"


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
# even in passthrough mode. The helper returns ``{value[:4]}...`` for
# diagnostics in passthrough and a stable HMAC digest in redact mode.
# ----------------------------------------------------------------------------


def test_redact_token_passthrough_truncates_value():
    out = redact_token("longbearersecretvalue", mode="passthrough")
    assert out == "long..."
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


# ----------------------------------------------------------------------------
# Redact mode must also cover authorization codes, client_id URLs and token
# owner identities, at every log level. Passthrough keeps the earlier output.
# ----------------------------------------------------------------------------

CODE_MARKER = "codemarkerSECRETvalue0123456789"
CLIENT_MARKER = "https://client-marker.example/app"
OWNER_MARKER = "owner-marker-name"
HEX_DIGITS = set("0123456789abcdef")


@pytest.fixture
def marker_owner(db):
    return get_user_model().objects.create_user(username=OWNER_MARKER, email="marker@example.org", password="pw")


@pytest.fixture
def marker_auth(marker_owner):
    from indieweb.models import Auth

    return Auth.objects.create(
        owner=marker_owner,
        key=CODE_MARKER,
        state="state",
        me="https://me.example/",
        scope="create",
        client_id=CLIENT_MARKER,
        redirect_uri="https://client-marker.example/cb",
    )


@pytest.fixture
def inactive_owner_token(marker_owner):
    from datetime import timedelta

    from django.utils import timezone

    from indieweb.models import Token

    marker_owner.is_active = False
    marker_owner.save()
    Token.objects.create(
        owner=marker_owner,
        key="inactiveownerbearer",
        client_id=CLIENT_MARKER,
        me="https://me.example/",
        scope="create",
        expires_at=timezone.now() + timedelta(hours=1),
    )
    return "inactiveownerbearer"


def test_redact_text_passthrough_returns_input():
    from indieweb.log_redaction import redact_text

    assert redact_text("failed for https://example.com/x", mode="passthrough") == "failed for https://example.com/x"


def test_redact_text_redact_returns_marked_stable_digest():
    from indieweb.log_redaction import redact_text

    out = redact_text("failed for https://example.com/x", mode="redact")

    assert out == redact_text("failed for https://example.com/x", mode="redact")
    assert out.startswith("<redacted:") and out.endswith(">")
    assert "example.com" not in out


def test_redact_auth_code_uses_digest_in_redact_mode(settings):
    from indieweb.views import _redact_auth_code

    settings.INDIEWEB_LOG_REDACTION = "redact"

    out = _redact_auth_code(CODE_MARKER)

    assert out == redact_token(CODE_MARKER, mode="redact")
    assert len(out) == 12 and set(out) <= HEX_DIGITS
    assert _redact_auth_code("") == "<empty>"
    assert _redact_auth_code(None) == "<empty>"
    assert set(_redact_auth_code("abc")) <= HEX_DIGITS


def test_redact_auth_code_keeps_prefix_in_passthrough_mode(settings):
    from indieweb.views import _redact_auth_code

    settings.INDIEWEB_LOG_REDACTION = "passthrough"

    assert _redact_auth_code(CODE_MARKER) == f"{CODE_MARKER[:6]}..."
    assert _redact_auth_code("abc") == "<redacted:3 chars>"
    assert _redact_auth_code(None) == "<empty>"


def _exchange_unknown_code(client):
    return client.post(reverse("indieweb:token"), data={"code": CODE_MARKER, "client_id": CLIENT_MARKER})


@pytest.mark.django_db
def test_token_exchange_unknown_code_log_is_redacted_in_redact_mode(client, settings, caplog):
    settings.INDIEWEB_LOG_REDACTION = "redact"

    with caplog.at_level(logging.INFO, logger="indieweb.views"):
        response = _exchange_unknown_code(client)

    assert response.status_code == 400
    assert "Auth not found" in caplog.text
    assert CODE_MARKER[:6] not in caplog.text
    assert "client-marker" not in caplog.text
    assert f"code={redact_token(CODE_MARKER)}, client_id={redact_url(CLIENT_MARKER)}" in caplog.text


@pytest.mark.django_db
def test_token_exchange_unknown_code_log_keeps_values_in_passthrough_mode(client, settings, caplog):
    settings.INDIEWEB_LOG_REDACTION = "passthrough"

    with caplog.at_level(logging.INFO, logger="indieweb.views"):
        _exchange_unknown_code(client)

    assert f"code={CODE_MARKER[:6]}..., client_id={CLIENT_MARKER}" in caplog.text
    assert CODE_MARKER not in caplog.text


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["redact", "passthrough"])
def test_token_exchange_missing_client_id_log_handles_absent_value(client, settings, caplog, mode):
    settings.INDIEWEB_LOG_REDACTION = mode

    with caplog.at_level(logging.INFO, logger="indieweb.views"):
        response = client.post(reverse("indieweb:token"), data={"code": CODE_MARKER})

    assert response.status_code == 400
    assert "client_id=None" in caplog.text
    assert CODE_MARKER not in caplog.text
    if mode == "redact":
        assert CODE_MARKER[:6] not in caplog.text


@pytest.mark.django_db
def test_token_exchange_scope_mismatch_log_redacts_client_id_in_redact_mode(client, settings, caplog, marker_auth):
    settings.INDIEWEB_LOG_REDACTION = "redact"

    with caplog.at_level(logging.INFO, logger="indieweb.views"):
        response = client.post(
            reverse("indieweb:token"),
            data={
                "code": CODE_MARKER,
                "client_id": CLIENT_MARKER,
                "redirect_uri": marker_auth.redirect_uri,
                "scope": "create delete",
            },
        )

    assert response.status_code == 400
    assert f"Scope mismatch on token exchange for client_id={redact_url(CLIENT_MARKER)}" in caplog.text
    assert "client-marker" not in caplog.text
    assert CODE_MARKER[:6] not in caplog.text


@pytest.mark.django_db
def test_token_exchange_scope_mismatch_log_keeps_client_id_in_passthrough_mode(client, settings, caplog, marker_auth):
    settings.INDIEWEB_LOG_REDACTION = "passthrough"

    with caplog.at_level(logging.INFO, logger="indieweb.views"):
        client.post(
            reverse("indieweb:token"),
            data={
                "code": CODE_MARKER,
                "client_id": CLIENT_MARKER,
                "redirect_uri": marker_auth.redirect_uri,
                "scope": "create delete",
            },
        )

    assert f"Scope mismatch on token exchange for client_id={CLIENT_MARKER}" in caplog.text


@pytest.mark.django_db
def test_resource_server_inactive_owner_log_is_redacted_in_redact_mode(client, settings, caplog, inactive_owner_token):
    settings.INDIEWEB_LOG_REDACTION = "redact"

    with caplog.at_level(logging.INFO, logger="indieweb.views"):
        response = client.get(reverse("indieweb:micropub"), HTTP_AUTHORIZATION=f"Bearer {inactive_owner_token}")

    assert response.status_code == 401
    assert f"Token owner is not active: {redact_state(OWNER_MARKER)}" in caplog.text
    assert OWNER_MARKER not in caplog.text


@pytest.mark.django_db
def test_resource_server_inactive_owner_log_keeps_name_in_passthrough_mode(
    client, settings, caplog, inactive_owner_token
):
    settings.INDIEWEB_LOG_REDACTION = "passthrough"

    with caplog.at_level(logging.INFO, logger="indieweb.views"):
        client.get(reverse("indieweb:micropub"), HTTP_AUTHORIZATION=f"Bearer {inactive_owner_token}")

    assert f"Token owner is not active: {OWNER_MARKER}" in caplog.text


@pytest.mark.django_db
def test_introspection_inactive_owner_log_is_redacted_in_redact_mode(client, settings, caplog, inactive_owner_token):
    settings.INDIEWEB_LOG_REDACTION = "redact"

    with caplog.at_level(logging.INFO, logger="indieweb.views"):
        client.post(
            reverse("indieweb:token-introspection"),
            data={"token": "anything"},
            HTTP_AUTHORIZATION=f"Bearer {inactive_owner_token}",
        )

    assert f"rejected inactive token owner: {redact_state(OWNER_MARKER)}" in caplog.text
    assert OWNER_MARKER not in caplog.text


def raising_client_id_validator(client_id):
    raise ValueError(f"Policy lookup failed for {client_id}")


@pytest.mark.django_db
def test_client_id_validator_failure_log_is_redacted_in_redact_mode(client, settings, caplog):
    """Neither the client_id nor a validator message that embeds it may reach the log."""
    from indieweb.log_redaction import redact_text

    settings.INDIEWEB_LOG_REDACTION = "redact"
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.test_log_redaction.raising_client_id_validator"

    with caplog.at_level(logging.INFO, logger="indieweb.views"):
        _exchange_unknown_code(client)

    assert "INDIEWEB_CLIENT_ID_VALIDATOR raised" in caplog.text
    assert "client-marker" not in caplog.text
    assert redact_text(f"Policy lookup failed for {CLIENT_MARKER}") in caplog.text


@pytest.mark.django_db
def test_client_id_validator_failure_log_keeps_values_in_passthrough_mode(client, settings, caplog):
    settings.INDIEWEB_LOG_REDACTION = "passthrough"
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.test_log_redaction.raising_client_id_validator"

    with caplog.at_level(logging.INFO, logger="indieweb.views"):
        _exchange_unknown_code(client)

    assert (
        f"INDIEWEB_CLIENT_ID_VALIDATOR raised for client_id={CLIENT_MARKER!r}: "
        f"Policy lookup failed for {CLIENT_MARKER}"
    ) in caplog.text
