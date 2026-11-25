"""Shared test fixtures."""

import json

import pytest

from indieweb import parse_isolation, webmention_parse_worker
from indieweb.handlers import reset_in_memory_micropub_handler


def run_parse_worker_inline(request):
    """Run a parse request in the test process instead of a limited child."""
    try:
        return json.loads(json.dumps(webmention_parse_worker.handle_request(json.loads(json.dumps(request)))))
    except Exception as exc:
        raise parse_isolation.WebmentionSourceRejected(f"worker failed: {type(exc).__name__}") from exc


@pytest.fixture(autouse=True)
def parse_worker(monkeypatch):
    """Keep the suite fast: analyse fetched HTML in-process by default.

    The documents used across the suite are small and trusted. Tests of the
    isolation itself override this fixture and start the real child process.
    """
    monkeypatch.setattr(parse_isolation, "run_parse_worker", run_parse_worker_inline)


@pytest.fixture(autouse=True)
def clear_micropub_example():
    """Keep process-local example entries from leaking into the next test."""
    yield
    reset_in_memory_micropub_handler()


@pytest.fixture(scope="session")
def parse_lock_dir(tmp_path_factory):
    """One private parse-slot directory per test session."""
    return str(tmp_path_factory.mktemp("parse-locks"))


@pytest.fixture(autouse=True)
def private_parse_slots(settings, parse_lock_dir):
    """Keep parse slots apart from other test runs on the same host.

    The default directory is shared by every process of one user and
    ``SECRET_KEY``, so suites running in parallel (``tox -p``) would compete
    for the same two slots and fail with ``WebmentionParseCapacityError``.
    """
    settings.INDIEWEB_WEBMENTION_PARSE_LOCK_DIR = parse_lock_dir


@pytest.fixture
def concurrent_database():
    """Shared-cache SQLite cannot wait for locks; required lanes must not skip."""
    import os

    from django.db import connection

    name = str(connection.settings_dict["NAME"])
    if connection.vendor == "sqlite" and (name == ":memory:" or "mode=memory" in name):
        message = "Concurrency requires file SQLite or PostgreSQL; see docs/development.rst"
        if os.environ.get("DJANGO_INDIEWEB_REQUIRE_STORAGE_TESTS") == "1":
            pytest.fail(message)
        pytest.skip(message)


@pytest.fixture
def sqlite_wal(concurrent_database):
    """Enable WAL on a real file and restore the original journal mode."""
    from django.db import connection

    if connection.vendor != "sqlite":
        pytest.skip("SQLite WAL regression")
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode")
        (previous_mode,) = cursor.fetchone()
        cursor.execute("PRAGMA journal_mode=WAL")
        assert cursor.fetchone() == ("wal",)
    yield connection
    with connection.cursor() as cursor:
        cursor.execute(f"PRAGMA journal_mode={previous_mode}")
