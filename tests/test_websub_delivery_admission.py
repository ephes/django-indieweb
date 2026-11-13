"""Delivery authority comes from one current, committed subscription generation."""

import hashlib
import hmac
from datetime import timedelta
from threading import Thread
from unittest.mock import patch

import pytest
from django.db import connection, connections
from django.urls import reverse
from django.utils import timezone

from indieweb.models import WebSubAcceptedDelivery, WebSubSubscription
from indieweb.views import WebSubCallbackView
from indieweb.websub import confirm_websub_verification, record_websub_denial
from tests import websub_hooks

SECRET = "synthetic-active-secret-20x"
NEW_SECRET = "synthetic-rotated-secret-20x"
BODY = b"<feed>synthetic</feed>"


@pytest.fixture
def active_subscription(settings):
    settings.INDIEWEB_WEBSUB_DELIVERY_HOOK = "tests.websub_hooks.capture_delivery"
    settings.INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS = 300
    websub_hooks.reset()
    row = WebSubSubscription.objects.create(
        hub_url="https://hub.example/", topic_url="https://topic.example/", state="active", secret=SECRET
    )
    yield row
    websub_hooks.reset()


def deliver(client, row, secret=SECRET):
    digest = hmac.new(secret.encode(), BODY, hashlib.sha256).hexdigest()
    return client.post(
        reverse("indieweb:websub-callback", args=[row.callback_token]),
        data=BODY,
        content_type="application/atom+xml",
        HTTP_LINK=f'<{row.topic_url}>; rel="self"',
        HTTP_X_HUB_SIGNATURE_256=f"sha256={digest}",
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("change", ["rotate", "unsubscribe", "delete"])
def test_delivery_reloads_authority_after_initial_lookup(client, active_subscription, concurrent_database, change):
    original = WebSubCallbackView._get_subscription
    writer_connections = []
    errors = []

    def lookup(self, token):
        stale = original(self, token)

        def change_authority():
            try:
                writer_connections.append(connection.connection)
                current = WebSubSubscription.objects.get(pk=stale.pk)
                writer_connections[-1] = connection.connection
                if change == "delete":
                    current.delete()
                elif change == "rotate":
                    current.pending_mode = "subscribe"
                    current.set_pending_secret(NEW_SECRET)
                    current.pending_secret_set = True
                    current.save()
                    confirm_websub_verification(
                        current,
                        mode="subscribe",
                        topic_url=current.topic_url,
                        challenge="synthetic",
                        lease_seconds=600,
                    )
                else:
                    current.state = "pending_unsubscribe"
                    current.pending_mode = "unsubscribe"
                    current.save()
                    confirm_websub_verification(
                        current,
                        mode="unsubscribe",
                        topic_url=current.topic_url,
                        challenge="synthetic",
                        lease_seconds=None,
                    )
            except BaseException as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        worker = Thread(target=change_authority, daemon=True)
        worker.start()
        worker.join(10)
        assert not worker.is_alive()
        assert not errors, errors
        assert writer_connections[0] is not connection.connection
        return stale

    with patch.object(WebSubCallbackView, "_get_subscription", lookup):
        response = deliver(client, active_subscription)
    assert response.status_code == (403 if change == "rotate" else 404)
    assert websub_hooks.DELIVERIES == []
    assert not WebSubAcceptedDelivery.objects.exists()
    if change == "rotate":
        assert deliver(client, active_subscription, NEW_SECRET).status_code == 204


@pytest.mark.django_db
@pytest.mark.parametrize("offset, expected", [(-1, 204), (0, 404), (1, 404)])
@pytest.mark.parametrize("renewal", ["none", "denied", "confirmed"])
def test_delivery_known_lease_boundary(client, active_subscription, offset, expected, renewal):
    expiry = timezone.now()
    row = active_subscription
    row.lease_expires_at = expiry
    if renewal != "none":
        row.pending_mode = "subscribe"
    row.save()
    if renewal == "denied":
        record_websub_denial(row, topic_url=row.topic_url, reason="synthetic denial")
    elif renewal == "confirmed":
        confirm_websub_verification(
            row, mode="subscribe", topic_url=row.topic_url, challenge="synthetic", lease_seconds=600
        )
        expected = 204
    with patch("indieweb.websub.timezone.now", return_value=expiry + timedelta(microseconds=offset)):
        response = deliver(client, row)
    assert response.status_code == expected
    assert len(websub_hooks.DELIVERIES) == int(expected == 204)
    assert WebSubAcceptedDelivery.objects.count() == int(expected == 204)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("atomic_requests", [False, True])
def test_admission_commits_before_host_dispatch(client, active_subscription, monkeypatch, atomic_requests):
    monkeypatch.setitem(connection.settings_dict, "ATOMIC_REQUESTS", atomic_requests)

    def hook(**kwargs):
        assert not connection.in_atomic_block
        assert WebSubAcceptedDelivery.objects.filter(subscription=active_subscription).exists()

    monkeypatch.setattr(websub_hooks, "capture_delivery", hook)
    assert deliver(client, active_subscription).status_code == 204


@pytest.mark.django_db(databases=["default", "other"])
def test_admission_reloads_on_subscription_database(active_subscription, settings):
    from django.test import RequestFactory

    row = WebSubSubscription.objects.using("other").create(
        pk=active_subscription.pk,
        hub_url="https://other.example/",
        topic_url=active_subscription.topic_url,
        state="unsubscribed",
        secret=SECRET,
    )
    stale = WebSubSubscription.objects.using("other").get(pk=row.pk)
    stale.state = "active"
    request = RequestFactory().post("/", data=BODY, content_type="application/atom+xml")
    with patch.object(WebSubCallbackView, "_get_subscription", return_value=stale):
        assert WebSubCallbackView.as_view()(request, token=row.callback_token).status_code == 404
    assert not WebSubAcceptedDelivery.objects.using("other").exists()
    assert not WebSubAcceptedDelivery.objects.using("default").exists()


@pytest.mark.parametrize("mode", ["inline", "enqueue"])
@pytest.mark.parametrize("kind", ["positional", "keyword", "decorated", "kwargs", "varargs"])
@pytest.mark.django_db
def test_optional_digest_obeys_callable_keyword_contract(
    client, active_subscription, settings, monkeypatch, mode, kind
):
    from functools import wraps

    calls = []

    def positional(body_digest=None, /, *, subscription_id, hub_url, topic_url, body, headers):
        calls.append(body_digest)

    def keyword(*, body_digest, subscription_id, hub_url, topic_url, body, headers):
        calls.append(body_digest)

    @wraps(positional)
    def decorated(*args, **kwargs):
        return positional(*args, **kwargs)

    def kwargs(**values):
        calls.append(values["body_digest"])

    def varargs(*body_digest, subscription_id, hub_url, topic_url, body, headers):
        calls.append(None)

    hook = {
        "positional": positional,
        "keyword": keyword,
        "decorated": decorated,
        "kwargs": kwargs,
        "varargs": varargs,
    }[kind]
    monkeypatch.setattr(websub_hooks, "capture_delivery", hook)
    if mode == "enqueue":
        settings.INDIEWEB_WEBSUB_DELIVERY_ENQUEUE = "tests.websub_hooks.capture_delivery"
    response = deliver(client, active_subscription)
    assert response.status_code == 204
    assert calls == [hashlib.sha256(BODY).hexdigest() if kind in ("keyword", "kwargs") else None]


@pytest.mark.django_db(transaction=True)
def test_transition_waits_for_delivery_admission(active_subscription, concurrent_database, monkeypatch):
    from threading import Event

    from django.test import Client

    from indieweb import websub

    checked = Event()
    release = Event()
    updating = Event()
    updated = Event()
    errors = []
    responses = []
    raw_connections = []
    original = websub.validate_websub_delivery_signature

    def validate(*args, **kwargs):
        result = original(*args, **kwargs)
        checked.set()
        assert release.wait(10)
        return result

    def receive():
        try:
            responses.append(deliver(Client(), active_subscription))
            raw_connections.append(connection.connection)
        except BaseException as exc:
            errors.append(exc)
        finally:
            connections.close_all()

    def observe_update(execute, sql, params, many, context):
        if sql.lstrip().upper().startswith("UPDATE"):
            updating.set()
        return execute(sql, params, many, context)

    def rotate():
        try:
            with connection.execute_wrapper(observe_update):
                WebSubSubscription.objects.filter(pk=active_subscription.pk).update(
                    secret=WebSubSubscription.encrypt_secret(NEW_SECRET)
                )
            updated.set()
            raw_connections.append(connection.connection)
        except BaseException as exc:
            errors.append(exc)
        finally:
            connections.close_all()

    monkeypatch.setattr(websub, "validate_websub_delivery_signature", validate)
    receiver = Thread(target=receive, daemon=True)
    writer = Thread(target=rotate, daemon=True)
    receiver.start()
    try:
        assert checked.wait(10)
        writer.start()
        assert updating.wait(10)
        assert not updated.wait(0.1), "authority changed between signature validation and replay acceptance"
    finally:
        release.set()
        receiver.join(10)
        if writer.ident is not None:
            writer.join(10)
    assert not receiver.is_alive() and not writer.is_alive()
    assert not errors, errors
    assert len({id(raw) for raw in raw_connections}) == 2
    assert responses[0].status_code == 204
    assert WebSubAcceptedDelivery.objects.count() == 1
    assert updated.is_set()
    active_subscription.refresh_from_db()
    assert active_subscription.get_secret() == NEW_SECRET
