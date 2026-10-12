"""Django management command to prune old WebSub delivery-attempt diagnostics."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from indieweb.websub import prune_websub_delivery_attempts


class Command(BaseCommand):
    """Delete ``WebSubDeliveryAttempt`` rows older than the retention window."""

    help = (
        "Delete WebSub delivery-attempt diagnostics older than the retention window "
        "(--days or INDIEWEB_WEBSUB_DELIVERY_ATTEMPT_RETENTION_DAYS)"
    )

    def add_arguments(self, parser: Any) -> None:
        """Add command arguments."""
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Retention in days. Defaults to INDIEWEB_WEBSUB_DELIVERY_ATTEMPT_RETENTION_DAYS.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Rows deleted per batch. Defaults to 1000.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the cutoff and the number of matching rows without deleting anything.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Prune attempts and report the cutoff and row count."""
        try:
            result = prune_websub_delivery_attempts(
                retention_days=options["days"],
                batch_size=options["batch_size"],
                dry_run=options["dry_run"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        window = f"received before {result.cutoff.isoformat()} (retention: {result.retention_days} days)"
        if result.dry_run:
            self.stdout.write(f"Dry run: would delete {result.matched} WebSub delivery attempts {window}")
        else:
            self.stdout.write(self.style.SUCCESS(f"Deleted {result.deleted} WebSub delivery attempts {window}"))
