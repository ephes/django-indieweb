"""Exception text and hub response bodies never reach logs or stored diagnostics.

Only the exception class name, ``safe_url()`` forms of URLs, and a length and
digest of remote bodies are logged or stored.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest
from django.contrib.sites.models import Site
from django.urls import reverse

from indieweb.log_redaction import text_fingerprint
from indieweb.models import WebSubSubscription
from indieweb.senders import WebmentionSender
from indieweb.websub import notify_hubs, request_websub_subscription

# Built at runtime so traceback source lines never contain the markers.
TOKEN = "-".join(("private", "token", "value"))
PASSWORD = "-".join(("private", "pw", "value"))
LEAKY_URL = f"https://user:{PASSWORD}@hub.example/endpoint?access_token={TOKEN}&page=2"
LEAKY_MESSAGE = f"connection failed for {LEAKY_URL}\nINFO forged log line"


def _raising_client(message: str = LEAKY_MESSAGE) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(message, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _assert_no_free_text(text: str) -> None:
    for private in (TOKEN, PASSWORD, "connection failed", "forged", "hub.example/endpoint"):
        assert private not in text


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["passthrough", "redact"])
def test_websub_subscription_failure_stores_and_logs_exception_class_only(settings, caplog, mode):
    settings.INDIEWEB_LOG_REDACTION = mode

    with caplog.at_level(logging.WARNING, logger="indieweb.websub"):
        result = request_websub_subscription(
            "https://source.example/feed",
            "https://hub.example/sub",
            callback_base_url="https://example.org/indieweb/websub",
            secret="scrub-test-secret-value-20x",
            client=_raising_client(),
        )

    result.subscription.refresh_from_db()
    assert result.success is False
    assert result.error == result.subscription.last_request_error == "ConnectError"
    assert "ConnectError" in caplog.text
    _assert_no_free_text(caplog.text)


@pytest.mark.django_db
def test_websub_hub_rejection_body_is_stored_as_a_fingerprint():
    body = f"bad request, retry with {LEAKY_URL}"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=body)

    result = request_websub_subscription(
        "https://source.example/feed",
        "https://hub.example/sub",
        callback_base_url="https://example.org/indieweb/websub",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result.subscription.refresh_from_db()
    assert result.subscription.last_request_error == f"HTTP 400; body {text_fingerprint(body)}"
    assert result.subscription.state == WebSubSubscription.STATE_DENIED


@pytest.mark.parametrize("mode", ["passthrough", "redact"])
def test_websub_notification_failure_keeps_exception_class_only(settings, caplog, mode):
    settings.INDIEWEB_LOG_REDACTION = mode

    with caplog.at_level(logging.WARNING, logger="indieweb.websub"):
        results = notify_hubs("https://example.org/feed", ["https://hub.example/"], client=_raising_client())

    assert results[0].success is False
    assert results[0].error == "ConnectError"
    _assert_no_free_text(caplog.text)


def test_webmention_sender_stores_transport_error_class_only():
    result = WebmentionSender().send_webmention(
        "https://example.org/post",
        "https://target.example/post",
        "https://target.example/webmention",
        client=_raising_client(),
    )

    assert result["success"] is False
    assert result["error"] == "ConnectError"


@pytest.mark.django_db
@patch("indieweb.views.WebmentionProcessor")
def test_webmention_endpoint_logs_processor_exception_class_only(mock_processor_class, client, caplog):
    site = Site.objects.get_current()
    mock_processor = MagicMock()
    mock_processor_class.return_value = mock_processor
    mock_processor.process_webmention.side_effect = ValueError(LEAKY_MESSAGE)

    with caplog.at_level(logging.ERROR, logger="indieweb.views"):
        response = client.post(
            reverse("indieweb:webmention"),
            {"source": "https://other.example/reply", "target": f"https://{site.domain}/post"},
        )

    assert response.status_code == 400
    assert "Failed to process webmention: ValueError" in caplog.text
    _assert_no_free_text(caplog.text)


@pytest.mark.django_db
def test_websub_hook_failure_traceback_has_no_exception_text(settings, client, caplog, monkeypatch):
    settings.INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES = False
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"

    def failing_hook(**kwargs):
        raise RuntimeError(LEAKY_MESSAGE)

    monkeypatch.setattr("tests.websub_hooks.capture_delivery", failing_hook)
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_ACTIVE,
    )

    with caplog.at_level(logging.ERROR, logger="indieweb.websub"):
        response = client.post(
            reverse("indieweb:websub-callback", args=[subscription.callback_token]),
            data=b"<feed/>",
            content_type="application/atom+xml",
            HTTP_LINK=f'<{subscription.topic_url}>; rel="self"',
        )

    assert response.status_code == 500
    records = [record for record in caplog.records if record.name == "indieweb.websub"]
    assert records and records[-1].exc_info
    _assert_no_free_text(caplog.text)
    assert "Traceback (most recent call last)" in caplog.text
    assert "\nRuntimeError\n" in caplog.text


def test_websub_notification_stores_hub_response_as_a_fingerprint():
    body = f"x{LEAKY_URL}" * 300

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=body)

    results = notify_hubs(
        "https://example.org/feed",
        ["https://hub.example/"],
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert results[0].status_code == 400
    assert results[0].error == f"HTTP 400; body {text_fingerprint(body)}"
    _assert_no_free_text(results[0].error)


@pytest.mark.django_db
def test_websub_callback_rejection_logs_fixed_reason_or_class(client, caplog, monkeypatch):
    subscription = WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=WebSubSubscription.STATE_PENDING_SUBSCRIBE,
        pending_mode=WebSubSubscription.MODE_SUBSCRIBE,
    )
    url = reverse("indieweb:websub-callback", args=[subscription.callback_token])

    with caplog.at_level(logging.WARNING, logger="indieweb.views"):
        response = client.get(url, {"hub.mode": "subscribe", "hub.topic": LEAKY_URL, "hub.challenge": "c"})
    assert response.status_code == 404
    assert "WebSub verification topic does not match subscription" in caplog.text

    def failing_denial(*args, **kwargs):
        raise ValueError(LEAKY_MESSAGE)

    monkeypatch.setattr("indieweb.views.record_websub_denial", failing_denial)
    with caplog.at_level(logging.WARNING, logger="indieweb.views"):
        response = client.get(url, {"hub.mode": "denied", "hub.topic": subscription.topic_url})
    assert response.status_code == 404
    assert f"Rejected WebSub denial for subscription {subscription.pk}: ValueError" in caplog.text
    _assert_no_free_text(caplog.text)


@pytest.mark.django_db
def test_rejected_action_url_with_lone_surrogate_still_returns_400(client, caplog, monkeypatch):
    from django.contrib.auth import get_user_model

    from indieweb.handlers import InMemoryMicropubHandler
    from indieweb.models import Token

    owner = get_user_model().objects.create_user(username="surrogate-owner")
    grant = Token.objects.create(
        owner=owner, me="https://me.example/", client_id="https://client.example/", scope="delete"
    )

    class RejectingHandler(InMemoryMicropubHandler):
        def delete_entry(self, url, user):
            raise ValueError("no such entry")

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: RejectingHandler())
    with caplog.at_level(logging.WARNING, logger="indieweb.views"):
        response = client.post(
            reverse("indieweb:micropub"),
            '{"action": "delete", "url": "/entry/\\ud800"}',
            content_type="application/json",
            Authorization=f"Bearer {grant.key}",
        )

    assert response.status_code == 400
    assert "delete_entry rejected url='/entry/%ED%A0%80' (ValueError)" in caplog.text


def test_unparseable_published_date_is_logged_as_a_fingerprint(caplog):
    from indieweb.processors import WebmentionProcessor

    published = f"not a date {LEAKY_URL}"
    with caplog.at_level(logging.WARNING, logger="indieweb.processors"):
        result = WebmentionProcessor()._extract_published({"properties": {"published": [published]}})

    assert result is None
    assert f"Failed to parse published date ({text_fingerprint(published)})" in caplog.text
    _assert_no_free_text(caplog.text)
    assert "not a date" not in caplog.text
