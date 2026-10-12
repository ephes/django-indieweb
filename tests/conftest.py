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
