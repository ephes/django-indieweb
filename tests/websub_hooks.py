from __future__ import annotations

from typing import Any

DELIVERIES: list[dict[str, Any]] = []
ENQUEUED: list[dict[str, Any]] = []


def reset() -> None:
    DELIVERIES.clear()
    ENQUEUED.clear()


def capture_delivery(**kwargs: Any) -> None:
    DELIVERIES.append(kwargs)


def capture_delivery_with_digest(
    *,
    subscription_id: int,
    hub_url: str,
    topic_url: str,
    body: bytes,
    headers: dict[str, Any],
    body_digest: str,
) -> None:
    """Hook with an explicit ``body_digest`` parameter to exercise the kwargs probe."""
    DELIVERIES.append(
        {
            "subscription_id": subscription_id,
            "hub_url": hub_url,
            "topic_url": topic_url,
            "body": body,
            "headers": headers,
            "body_digest": body_digest,
        }
    )


def capture_delivery_legacy(
    *,
    subscription_id: int,
    hub_url: str,
    topic_url: str,
    body: bytes,
    headers: dict[str, Any],
) -> None:
    """Legacy hook signature without ``body_digest`` and without ``**kwargs``."""
    DELIVERIES.append(
        {
            "subscription_id": subscription_id,
            "hub_url": hub_url,
            "topic_url": topic_url,
            "body": body,
            "headers": headers,
        }
    )


def failing_delivery(**kwargs: Any) -> None:
    raise RuntimeError("delivery failed")


def capture_enqueue(**kwargs: Any) -> None:
    ENQUEUED.append(kwargs)


def failing_enqueue(**kwargs: Any) -> None:
    raise RuntimeError("enqueue failed")
