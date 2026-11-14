"""Bound delivery hashing and keep lease inspection output credential-free."""

import hashlib
import hmac
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from indieweb.models import WebSubSubscription
from indieweb.websub import validate_websub_delivery_signature


@pytest.mark.django_db
@pytest.mark.parametrize("valid_position", [None, 0, 99])
def test_many_signatures_hash_the_body_once(valid_position, settings):
    settings.INDIEWEB_WEBSUB_ALLOW_SHA1_SIGNATURES = True
    row = WebSubSubscription(secret="synthetic-secret")
    body = b"x" * (1024 * 1024)
    valid = hmac.new(b"synthetic-secret", body, hashlib.sha256).hexdigest()
    candidates = ["sha256=" + "0" * 64] * 100
    if valid_position is not None:
        candidates[valid_position] = "sha256=" + valid
    headers = {
        "X-Hub-Signature-256": ", ".join(candidates),
        "X-Hub-Signature": "sha1=" + hmac.new(b"synthetic-secret", body, hashlib.sha1).hexdigest(),
    }
    with patch("indieweb.websub.hmac.new", wraps=hmac.new) as new:
        if valid_position is None:
            with pytest.raises(ValueError, match="HMAC"):
                validate_websub_delivery_signature(row, body, headers)
        else:
            assert validate_websub_delivery_signature(row, body, headers) == "sha256"
    assert new.call_count == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "topic,hub",
    [
        (
            "https://synthetic-user:synthetic-password@topic.example/feed?signed-sentinel#fragment-sentinel",
            "https://hub.example/publish?hub-sentinel",
        ),
        ("https://topic.example/feed", "https://hub.example/fe\x1bed\ncontrol-sentinel?query-sentinel"),
    ],
    ids=["credentials", "controls"],
)
def test_lease_cli_omits_credentials_and_controls(topic, hub):
    now = timezone.now()
    row = WebSubSubscription.objects.create(topic_url=topic, hub_url=hub, state="active", lease_expires_at=now)
    stdout, stderr = StringIO(), StringIO()
    call_command("websub_subscriptions", stdout=stdout, stderr=stderr)
    text = stdout.getvalue() + stderr.getvalue()
    for sentinel in (
        "synthetic-user",
        "synthetic-password",
        "signed-sentinel",
        "fragment-sentinel",
        "hub-sentinel",
        "query-sentinel",
        "broken-sentinel",
        "\x1b",
        "control-sentinel",
    ):
        assert sentinel not in text
    assert f"expired: #{row.pk}" in text
    assert "lease_expires_at=" in text
    assert "topic.example" in text


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://name:password@[2001:db8::1]:8443/feed?secret#fragment", "https://[2001:db8::1]:8443/feed"),
        ("https://hub.example/publish?secret#fragment", "https://hub.example/publish"),
        ("https://bad[host/path?secret", "[invalid URL]"),
        ("https://hub.example:bad/path?secret", "[invalid URL]"),
        ("file:///private?secret", "[invalid URL]"),
        ("https:///missing-host?secret", "[invalid URL]"),
    ],
)
def test_cli_url_description(url, expected):
    from indieweb.management.commands.websub_subscriptions import _describe_url

    assert _describe_url(url) == expected
