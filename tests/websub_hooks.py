from __future__ import annotations

from typing import Any

DELIVERIES: list[dict[str, Any]] = []
ENQUEUED: list[dict[str, Any]] = []


def reset() -> None:
    DELIVERIES.clear()
    ENQUEUED.clear()


def capture_delivery(**kwargs: Any) -> None:
    DELIVERIES.append(kwargs)


def failing_delivery(**kwargs: Any) -> None:
    raise RuntimeError("delivery failed")


def capture_enqueue(**kwargs: Any) -> None:
    ENQUEUED.append(kwargs)


def failing_enqueue(**kwargs: Any) -> None:
    raise RuntimeError("enqueue failed")
