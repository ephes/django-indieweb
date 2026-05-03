"""Django management command for WebSub subscriber lease inspection."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from indieweb.websub import summarize_websub_leases


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
        if renewal_window_hours < 0:
            raise CommandError("--renewal-window-hours must be non-negative")

        summaries = summarize_websub_leases(within=timedelta(hours=renewal_window_hours))
        if not summaries:
            self.stdout.write("No WebSub subscriptions require lease attention")
            return

        self.stdout.write(
            f"WebSub subscriptions requiring lease attention at {timezone.now().isoformat()} "
            f"(window: {renewal_window_hours:g} hours)"
        )
        for summary in summaries:
            status = "expired" if summary.expired else "renewal_due"
            expires = summary.lease_expires_at.isoformat() if summary.lease_expires_at else "unknown"
            self.stdout.write(
                f"{status}: #{summary.subscription_id} {summary.topic_url} via {summary.hub_url} "
                f"lease_expires_at={expires}"
            )
