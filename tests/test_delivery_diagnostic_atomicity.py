"""Atomic delivery diagnostics on the subscription's routed write database."""

from unittest.mock import patch

import pytest
from django.db import connections
from django.db.models import QuerySet

from indieweb.models import WebSubDeliveryAttempt, WebSubSubscription
from indieweb.websub import record_websub_delivery


class DiagnosticRouter:
    def db_for_write(self, model, **hints):
        # Intentionally conflicting attempt routing: the diagnostic pair must
        # follow the subscription's write alias explicitly.
        return "other" if model is WebSubSubscription else "default"


@pytest.mark.django_db(databases=["default", "other"])
@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("status", [204, 500])
@pytest.mark.parametrize("fail", [False, True])
def test_delivery_diagnostics_are_atomic(settings, routed, status, fail):
    alias = "other" if routed else "default"
    settings.DATABASE_ROUTERS = [DiagnosticRouter()] if routed else []
    subscription = WebSubSubscription.objects.using(alias).create(
        hub_url="https://hub.example/", topic_url="https://topic.example/"
    )
    before = WebSubSubscription.objects.using(alias).values().get(pk=subscription.pk)
    original = QuerySet.create
    calls = []

    def create_attempt(self, **kwargs):
        if self.model is WebSubDeliveryAttempt:
            calls.append((self.db, connections[self.db].in_atomic_block))
        result = original(self, **kwargs)
        if fail and self.model is WebSubDeliveryAttempt:
            raise RuntimeError("synthetic diagnostic failure after insert")
        return result

    def record():
        record_websub_delivery(
            subscription,
            b"synthetic payload",
            content_type="text/plain" * 30,
            status_code=status,
            error="E" * 700,
            signature_algorithm="sha256",
        )

    with patch.object(QuerySet, "create", create_attempt):
        if fail:
            with pytest.raises(RuntimeError, match="after insert"):
                record()
        else:
            record()
    assert calls == [(alias, True)]
    if fail:
        assert WebSubSubscription.objects.using(alias).values().get(pk=subscription.pk) == before
        assert not WebSubDeliveryAttempt.objects.using(alias).exists()
    else:
        subscription.refresh_from_db(using=alias)
        attempt = WebSubDeliveryAttempt.objects.using(alias).get()
        assert subscription.last_delivery_status_code == attempt.status_code == status
        assert subscription.last_delivery_digest == attempt.digest
        assert subscription.last_delivery_at == attempt.received_at
        assert subscription.last_delivery_content_type == attempt.content_type == ("text/plain" * 30)[:200]
        assert subscription.last_delivery_error == attempt.error == "E" * 500
        assert subscription.last_delivery_size == attempt.size == len(b"synthetic payload")
        if status == 204:
            assert subscription.last_accepted_delivery_at == attempt.received_at
            assert subscription.last_accepted_delivery_digest == attempt.digest
        else:
            assert subscription.last_accepted_delivery_at is None
    if routed:
        assert not WebSubSubscription.objects.using("default").exists()
        assert not WebSubDeliveryAttempt.objects.using("default").exists()
