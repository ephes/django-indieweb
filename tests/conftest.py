"""Shared test fixtures."""

import json

import pytest

from indieweb import parse_isolation, webmention_parse_worker


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
