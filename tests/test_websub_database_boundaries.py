"""Rollback and replay boundaries with invented credentials and routed rows."""

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from indieweb.models import WebSubAcceptedDelivery, WebSubSubscription
from indieweb.websub import accept_websub_delivery

ROLLBACK_PROBE = """
import django
django.setup()
import importlib
import sys
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
mode = sys.argv[1]
before = [("indieweb", "0020_hash_token_keys_and_webmention_status_tokens")]
after = [("indieweb", "0021_encrypt_websub_secrets")]
settings.SECRET_KEY = "synthetic-old-key"
executor = MigrationExecutor(connection)
executor.migrate(before)
apps = executor.loader.project_state(before).apps
Sub = apps.get_model("indieweb", "WebSubSubscription")
for i in range(2):
    Sub.objects.create(hub_url="https://hub.example/", topic_url=f"https://topic.example/{i}",
                       callback_token=str(i), secret=f"synthetic-secret-{i}", pending_secret=f"synthetic-pending-{i}")
executor = MigrationExecutor(connection)
executor.migrate(after)
apps = executor.loader.project_state(after).apps
Sub = apps.get_model("indieweb", "WebSubSubscription")
if mode != "current":
    settings.SECRET_KEY = "synthetic-new-key"
    settings.SECRET_KEY_FALLBACKS = ["synthetic-old-key"] if mode != "unknown" else []
if mode == "corrupt":
    Sub.objects.filter(callback_token="1").update(pending_secret="fernet$synthetic-corruption")
if mode == "nonascii":
    Sub.objects.filter(callback_token="1").update(secret="fernet$\N{SNOWMAN}")
original = list(Sub.objects.order_by("pk").values_list("secret", "pending_secret"))
executor = MigrationExecutor(connection)
if mode in {"corrupt", "unknown", "nonascii"}:
    try:
        executor.migrate(before)
    except RuntimeError as exc:
        assert str(exc) == (
            "Cannot reverse WebSub secret encryption: "
            "a stored secret cannot be decrypted with the configured keys."
        )
    else:
        raise AssertionError("Unrecoverable rollback was accepted")
    assert list(Sub.objects.order_by("pk").values_list("secret", "pending_secret")) == original
    assert after[0] in MigrationExecutor(connection).loader.applied_migrations
else:
    executor.migrate(before)
    apps = executor.loader.project_state(before).apps
    Sub = apps.get_model("indieweb", "WebSubSubscription")
    assert list(Sub.objects.order_by("pk").values_list("secret", "pending_secret")) == [
        (f"synthetic-secret-{i}", f"synthetic-pending-{i}") for i in range(2)]
print("ROLLBACK-OK")
"""


@pytest.mark.parametrize("mode", ["current", "fallback", "corrupt", "unknown", "nonascii"])
def test_real_secret_migration_rollback(mode):
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-c", ROLLBACK_PROBE, mode],
        cwd=root,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "tests.settings", "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ROLLBACK-OK" in result.stdout


class ReplayRouter:
    def db_for_read(self, model, **hints):
        if model is WebSubAcceptedDelivery:
            return "other"
        return None

    db_for_write = db_for_read


@pytest.fixture
def routed_subscription(settings):
    settings.DATABASE_ROUTERS = [ReplayRouter()]
    settings.INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS = 60
    settings.INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX = 2
    return WebSubSubscription.objects.using("other").create(
        hub_url="https://hub.example/", topic_url="https://topic.example/"
    )


@pytest.mark.django_db(databases=["default", "other"], transaction=True)
def test_routed_replay_prune_and_insert_rollback_together(routed_subscription):
    row = WebSubAcceptedDelivery.objects.using("other").create(
        subscription=routed_subscription,
        body_digest="a" * 64,
        accepted_at=timezone.now() - timedelta(seconds=120),
    )
    original = QuerySet.create
    calls = []

    def create_then_fail(self, **kwargs):
        result = original(self, **kwargs)
        if self.model is WebSubAcceptedDelivery:
            calls.append(result.pk)
            raise RuntimeError("synthetic failure after insert")
        return result

    with patch.object(QuerySet, "create", create_then_fail), pytest.raises(RuntimeError, match="after insert"):
        accept_websub_delivery(routed_subscription, "b" * 64)
    assert len(calls) == 1
    assert list(WebSubAcceptedDelivery.objects.using("other").values_list("pk", flat=True)) == [row.pk]
    assert WebSubAcceptedDelivery.objects.using("default").count() == 0


@pytest.mark.django_db(databases=["default", "other"], transaction=True)
def test_routed_duplicate_savepoint_preserves_enclosing_transaction(routed_subscription):
    with transaction.atomic(using="other"):
        assert accept_websub_delivery(routed_subscription, "a" * 64)
        assert not accept_websub_delivery(routed_subscription, "a" * 64)
        assert accept_websub_delivery(routed_subscription, "b" * 64)
        assert accept_websub_delivery(routed_subscription, "c" * 64)
        assert set(WebSubAcceptedDelivery.objects.using("other").values_list("body_digest", flat=True)) == {
            "b" * 64,
            "c" * 64,
        }
    assert WebSubAcceptedDelivery.objects.using("default").count() == 0
