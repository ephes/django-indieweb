"""Test enqueue hooks for Webmention endpoint tests."""

from __future__ import annotations

ENQUEUED_WEBMENTION_IDS: list[int] = []


def reset() -> None:
    """Clear captured enqueue calls."""
    ENQUEUED_WEBMENTION_IDS.clear()


def capture_webmention_id(webmention_id: int) -> None:
    """Capture the queued Webmention ID for assertions."""
    ENQUEUED_WEBMENTION_IDS.append(webmention_id)


def failing_enqueue(webmention_id: int) -> None:
    """Raise to simulate an enqueue backend failure."""
    raise RuntimeError(f"could not enqueue {webmention_id}")
