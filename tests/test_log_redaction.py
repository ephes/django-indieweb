import logging

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.http import urlencode

from indieweb.log_redaction import redact_state, redact_url, redact_url_origin


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
