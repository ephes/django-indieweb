"""Django management command for WebSub subscriber lease inspection."""

from __future__ import annotations

import math
from datetime import timedelta
from itertools import chain
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from indieweb.websub import iter_websub_lease_summaries


def _describe_url(value: str) -> str:
    """Describe origin/path without terminal controls or URL credentials."""
    if any(not char.isprintable() for char in value):
        return "[invalid URL]"
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not host:
            return "[invalid URL]"
        authority = f"[{host}]" if ":" in host else host
        if parsed.port is not None:
            authority += f":{parsed.port}"
        return urlunsplit((parsed.scheme, authority, parsed.path, "", ""))
    except ValueError:
        return "[invalid URL]"


class Command(BaseCommand):
    """List WebSub subscriptions that need operator lease attention."""

    help = "Inspect active WebSub subscriber leases without making hub network calls"

    def add_arguments(self, parser: Any) -> None:
        """Add command arguments."""
        parser.add_argument(
            "--renewal-window-hours",
            type=float,
            default=24.0,
            help="List active subscriptions expiring within this many hours. Defaults to 24.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Print expired subscriptions and renewal candidates."""
        renewal_window_hours = options["renewal_window_hours"]
        if not math.isfinite(renewal_window_hours) or renewal_window_hours < 0:
            raise CommandError("--renewal-window-hours must be finite and non-negative")

        try:
            summaries = iter_websub_lease_summaries(within=timedelta(hours=renewal_window_hours))
            first = next(summaries, None)
        except (ValueError, OverflowError) as exc:
            raise CommandError("--renewal-window-hours exceeds the supported datetime range") from exc
        if first is None:
            self.stdout.write("No WebSub subscriptions require lease attention")
            return

        self.stdout.write(
            f"WebSub subscriptions requiring lease attention at {timezone.now().isoformat()} "
            f"(window: {renewal_window_hours:g} hours)"
        )
        for summary in chain((first,), summaries):
            status = "expired" if summary.expired else "renewal_due"
            expires = summary.lease_expires_at.isoformat() if summary.lease_expires_at else "unknown"
            self.stdout.write(
                f"{status}: #{summary.subscription_id} {_describe_url(summary.topic_url)} "
                f"via {_describe_url(summary.hub_url)} "
                f"lease_expires_at={expires}"
            )
