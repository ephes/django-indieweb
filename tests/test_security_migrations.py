"""Historical security transforms run on isolated synthetic databases."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

PROBE = """
import django
django.setup()
import importlib
from types import SimpleNamespace
from unittest.mock import patch
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.db.models.query import QuerySet

before = [("indieweb", "0019_webmentionoutboundtarget_consecutive_failures_and_more")]
after = [("indieweb", "0023_hash_auth_keys")]
for alias in ("default", "other"):
    executor = MigrationExecutor(connections[alias])
    executor.migrate(before)
    apps = executor.loader.project_state(before).apps
    owner = apps.get_model("auth", "User").objects.using(alias).create(username="synthetic")
    for name in ("Token", "Auth"):
        model = apps.get_model("indieweb", name)
        extra = {"state": "s", "redirect_uri": "https://client.example/cb"} if name == "Auth" else {}
        model.objects.using(alias).bulk_create([
            model(owner_id=owner.pk, key=f"{['0', 'A', 'a', 'z'][i % 4]}-{alias}-{name}-{i}", scope=str(i),
                  client_id="https://client.example/", me="https://me.example/", **extra)
            for i in range(1005)
        ])
    apps.get_model("indieweb", "Webmention").objects.using(alias).create(
        source_url="https://source.example/", target_url="https://target.example/")
    apps.get_model("indieweb", "WebSubSubscription").objects.using(alias).create(
        hub_url="https://hub.example/", topic_url="https://topic.example/",
        callback_token=alias, secret=f"{alias}-secret", pending_secret=f"{alias}-pending")

seen = set()
original = QuerySet.iterator
def streaming(self, chunk_size=None):
    if self.model._meta.label in {"indieweb.Token", "indieweb.Auth"}:
        assert chunk_size == 1000, chunk_size
        seen.add(self.model._meta.model_name)
    yield from original(self, chunk_size=chunk_size)
    assert self._result_cache is None

with patch.object(QuerySet, "iterator", streaming):
    executor = MigrationExecutor(connections["other"])
    executor.migrate(after)
apps = executor.loader.project_state(after).apps
for name in ("Token", "Auth"):
    model = apps.get_model("indieweb", name)
    assert model.objects.using("default").filter(key__contains=f"-default-{name}-").count() == 1005
    assert model.objects.using("other").filter(key__startswith="hmac-sha256$").count() == 1005
    module = importlib.import_module("indieweb.migrations." + (
        "0020_hash_token_keys_and_webmention_status_tokens" if name == "Token" else "0023_hash_auth_keys"))
    hasher = module._hash_token_key if name == "Token" else module._hash_auth_key
    expected_keys = {
        str(i): hasher(f"{['0', 'A', 'a', 'z'][i % 4]}-other-{name}-{i}") for i in range(1005)
    }
    assert dict(model.objects.using("other").values_list("scope", "key")) == expected_keys
    transform = module.hash_existing_token_keys if name == "Token" else module.hash_existing_auth_keys
    transform(apps, SimpleNamespace(connection=connections["other"]))
    assert dict(model.objects.using("other").values_list("scope", "key")) == expected_keys
assert seen == {"token", "auth"}, seen
assert len(apps.get_model("indieweb", "Webmention").objects.using("other").get().status_token) == 48
# Read default at its own historical schema (0020 has not added status_token there).
old_apps = executor.loader.project_state(before).apps
assert old_apps.get_model("indieweb", "Webmention").objects.using("default").count() == 1
sub = apps.get_model("indieweb", "WebSubSubscription").objects.using("other").get()
m21 = importlib.import_module("indieweb.migrations.0021_encrypt_websub_secrets")
assert m21._decrypt_secret(sub.secret) == "other-secret"
assert m21._decrypt_secret(sub.pending_secret) == "other-pending"
assert old_apps.get_model("indieweb", "WebSubSubscription").objects.using("default").get().secret == "default-secret"
m21.decrypt_websub_secrets(apps, SimpleNamespace(connection=connections["other"]))
assert apps.get_model("indieweb", "WebSubSubscription").objects.using("other").get().secret == "other-secret"
print("SECURITY-MIGRATIONS-OK")
"""


def test_security_migrations_are_isolated_and_stream_credentials():
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(PROBE)],
        cwd=root,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "tests.settings", "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SECURITY-MIGRATIONS-OK" in result.stdout
