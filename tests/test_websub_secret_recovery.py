"""Malformed restored secrets stay recoverable and never escape the domain boundary."""

import httpx
import pytest
from django.contrib import admin
from django.urls import reverse

from indieweb.models import WebSubSecretDecryptionError, WebSubSubscription
from indieweb.websub import request_websub_subscription

CORRUPT = "fernet$synthetic-☃-secret"


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["secret", "pending_secret"])
def test_nonascii_ciphertext_read_and_request_save(client, admin_user, field, caplog):
    row = WebSubSubscription.objects.create(
        hub_url="https://hub.example/", topic_url="https://topic.example/", state="active"
    )
    WebSubSubscription.objects.filter(pk=row.pk).update(**{field: CORRUPT})
    row.refresh_from_db()
    getter = row.get_secret if field == "secret" else row.get_pending_secret
    with pytest.raises(WebSubSecretDecryptionError, match="Could not decrypt"):
        getter()
    row.last_request_error = "synthetic diagnostic"
    row.save(update_fields=["last_request_error"])
    row.refresh_from_db()
    assert getattr(row, field) == CORRUPT
    # Subscribe retains active ciphertext; unsubscribe also retains pending ciphertext.
    mode = "subscribe" if field == "secret" else "unsubscribe"
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(202))) as hub:
        assert request_websub_subscription(
            row.topic_url, row.hub_url, mode=mode, callback_base_url="https://callback.example/", client=hub
        ).success
    row.refresh_from_db()
    assert getattr(row, field) == CORRUPT
    client.force_login(admin_user)
    response = client.get(reverse("admin:indieweb_websubsubscription_change", args=[row.pk]))
    assert response.status_code == 200
    assert CORRUPT.encode() not in response.content
    assert CORRUPT not in caplog.text
    assert admin.site._registry[WebSubSubscription].masked_secret(row) in ("configured", "")


@pytest.mark.django_db
def test_nonascii_active_ciphertext_callback_is_controlled_refusal(client, caplog):
    row = WebSubSubscription.objects.create(
        hub_url="https://hub.example/", topic_url="https://topic.example/", state="active"
    )
    WebSubSubscription.objects.filter(pk=row.pk).update(secret=CORRUPT)
    response = client.post(
        reverse("indieweb:websub-callback", args=[row.callback_token]),
        data=b"synthetic body",
        content_type="application/atom+xml",
        HTTP_LINK=f'<{row.topic_url}>; rel="self"',
        HTTP_X_HUB_SIGNATURE_256="sha256=" + "a" * 64,
    )
    assert response.status_code == 403
    row.refresh_from_db()
    assert row.secret == CORRUPT
    assert row.last_delivery_error == "secret decryption failed"
    assert not row.accepted_deliveries.exists()
    assert CORRUPT not in caplog.text
