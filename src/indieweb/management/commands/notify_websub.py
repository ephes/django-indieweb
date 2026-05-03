"""Django management command to notify WebSub hubs."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from indieweb.websub import notify_hubs


class Command(BaseCommand):
    """Notify WebSub hubs that a topic URL has changed."""

    help = "Notify configured WebSub hubs that a topic URL has changed"

    def add_arguments(self, parser: Any) -> None:
        """Add command arguments."""
        parser.add_argument("topic", type=str, help="The topic URL that changed")
        parser.add_argument(
            "--hub",
            action="append",
            dest="hubs",
            help="Hub URL to notify. Can be repeated. Defaults to INDIEWEB_WEBSUB_HUBS.",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=None,
            help="Per-request timeout in seconds. Defaults to INDIEWEB_WEBSUB_TIMEOUT.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Notify hubs and print one line per attempted hub."""
        topic_url = options["topic"]
        hubs = options["hubs"]
        timeout = options["timeout"]

        try:
            results = notify_hubs(topic_url, hubs, timeout=timeout)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if not results:
            raise CommandError("No WebSub hubs configured; set INDIEWEB_WEBSUB_HUBS or pass --hub")

        success_count = sum(1 for result in results if result.success)
        self.stdout.write(f"Notified {success_count}/{len(results)} WebSub hubs for {topic_url}")

        for result in results:
            if result.success:
                self.stdout.write(self.style.SUCCESS(f"✓ {result.hub_url} (HTTP {result.status_code})"))
            else:
                detail = f"HTTP {result.status_code}" if result.status_code is not None else result.error
                self.stdout.write(self.style.ERROR(f"✗ {result.hub_url} ({detail})"))
