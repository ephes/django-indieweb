"""Migration 0021 must authenticate a reserved prefix before treating it as ciphertext."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROBE = """
import django
django.setup()
import hashlib
import hmac
import importlib
import sys
from types import SimpleNamespace
from django.conf import settings
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from indieweb.models import WebSubSubscription
from indieweb.websub import validate_websub_delivery_signature

alias = sys.argv[1]
untouched = "other" if alias == "default" else "default"
before = [("indieweb", "0020_hash_token_keys_and_webmention_status_tokens")]
after = [("indieweb", "0021_encrypt_websub_secrets")]
migration = importlib.import_module("indieweb.migrations.0021_encrypt_websub_secrets")
settings.SECRET_KEY = "synthetic-old-key"
settings.SECRET_KEY_FALLBACKS = []
old_ciphertext = "fernet$" + migration._websub_secret_fernet().encrypt(b"already-encrypted").decode("ascii")
legacy = [
    ("ordinary-active", "ordinary-pending"),
    ("fernet$not-a-token", "fernet$"),
    ("fernet$synthetic-☃", "fernet$gAAAA-invalid"),
    ("", ""),
    (old_ciphertext, old_ciphertext),
]
expected = [*legacy[:-1], ("already-encrypted", "already-encrypted")]
for db in ("default", "other"):
    executor = MigrationExecutor(connections[db])
    executor.migrate(before)
    Sub = executor.loader.project_state(before).apps.get_model("indieweb", "WebSubSubscription")
    for i, (active, pending) in enumerate(legacy):
        Sub.objects.using(db).create(
            hub_url="https://hub.example/", topic_url=f"https://topic.example/{i}",
            callback_token=str(i), secret=active, pending_secret=pending)

settings.SECRET_KEY = "synthetic-new-key"
settings.SECRET_KEY_FALLBACKS = ["synthetic-wrong-fallback", "synthetic-old-key"]
executor = MigrationExecutor(connections[alias])
executor.migrate(after)
apps = executor.loader.project_state(after).apps
Sub = apps.get_model("indieweb", "WebSubSubscription")
stored = list(Sub.objects.using(alias).order_by("pk").values_list("secret", "pending_secret"))
assert stored[-1] == (old_ciphertext, old_ciphertext), "Authenticated fallback ciphertext was changed"
for pair, plain_pair in zip(stored, expected, strict=True):
    for value, plain in zip(pair, plain_pair, strict=True):
        assert WebSubSubscription.decrypt_secret(value) == plain
        if plain:
            body = b"synthetic delivery"
            digest = hmac.new(plain.encode("utf-8"), body, hashlib.sha256).hexdigest()
            row = WebSubSubscription(secret=value)
            headers = {"X-Hub-Signature-256": f"sha256={digest}"}
            assert validate_websub_delivery_signature(row, body, headers) == "sha256"
        else:
            assert value == ""
# Retrying the transform must not double-encrypt an authenticated token.
migration.encrypt_websub_secrets(apps, SimpleNamespace(connection=connections[alias]))
assert list(Sub.objects.using(alias).order_by("pk").values_list("secret", "pending_secret")) == stored
OldSub = executor.loader.project_state(before).apps.get_model("indieweb", "WebSubSubscription")
assert list(OldSub.objects.using(untouched).order_by("pk").values_list("secret", "pending_secret")) == legacy
executor = MigrationExecutor(connections[alias])
executor.migrate(before)
OldSub = executor.loader.project_state(before).apps.get_model("indieweb", "WebSubSubscription")
assert list(OldSub.objects.using(alias).order_by("pk").values_list("secret", "pending_secret")) == expected
print("PREFIX-MIGRATION-OK")
"""


@pytest.mark.parametrize("alias", ["default", "other"])
def test_historical_prefix_secrets_roundtrip(alias):
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-c", PROBE, alias],
        cwd=root,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "tests.settings", "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PREFIX-MIGRATION-OK" in result.stdout
