"""Django management command to send webmentions."""

import sys
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import URLValidator

from indieweb.senders import WebmentionSender


class Command(BaseCommand):
    """Send webmentions from a source URL to all linked URLs."""

    help = "Send webmentions from a source URL to all linked URLs"

    def add_arguments(self, parser: Any) -> None:
        """Add command arguments."""
        parser.add_argument("source", type=str, help="The source URL (your post)")
        parser.add_argument(
            "--content", type=str, help="HTML content (if not provided, will be fetched from source URL)", default=None
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Show what would be sent without actually sending", default=False
        )
        parser.add_argument(
            "--vouch", type=str, help="Optional Vouch URL to include with sent webmentions", default=None
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Handle the command."""
        source_url = options["source"]
        html_content = options["content"]
        dry_run = options["dry_run"]
        vouch_url = options["vouch"]

        # Validate source URL
        if not source_url.startswith(("http://", "https://")):
            raise CommandError("Source URL must start with http:// or https://")
        if vouch_url:
            try:
                URLValidator(schemes=["http", "https"])(vouch_url)
            except ValidationError as exc:
                raise CommandError("Vouch URL must be a valid http:// or https:// URL") from exc

        sender = WebmentionSender()

        if dry_run:
            self.stdout.write("DRY RUN MODE - No webmentions will be sent\n")

        html_content = self._resolve_content(sender, source_url, html_content)
        urls = sender.extract_urls(html_content)
        self.stdout.write(f"Found {len(urls)} URLs in content\n")

        if dry_run:
            self._handle_dry_run(sender, source_url, urls)
        else:
            self._handle_send(sender, source_url, html_content, vouch_url)

    def _resolve_content(self, sender: WebmentionSender, source_url: str, html_content: str | None) -> str:
        """Resolve HTML content from argument, stdin, or by fetching the source URL."""
        if html_content == "-":
            return sys.stdin.read()
        if html_content:
            return html_content
        self.stdout.write(f"Fetching content from {source_url}...")
        fetched_content = sender.fetch_content(source_url)
        if not fetched_content:
            raise CommandError(f"Failed to fetch content from {source_url}")
        return fetched_content

    def _handle_dry_run(self, sender: WebmentionSender, source_url: str, urls: list[str]) -> None:
        """Show what webmentions would be sent without actually sending."""
        from urllib.parse import urlparse

        source_domain = urlparse(source_url).netloc

        for url in urls:
            if not url.startswith(("http://", "https://")):
                continue

            target_domain = urlparse(url).netloc
            if target_domain == source_domain:
                self.stdout.write(f"  - {url} (skipped: same domain)")
                continue

            endpoint = sender.discover_endpoint(url)
            if endpoint:
                self.stdout.write(f"  - {url} -> {endpoint}")
            else:
                self.stdout.write(f"  - {url} (no endpoint found)")

    def _handle_send(
        self,
        sender: WebmentionSender,
        source_url: str,
        html_content: str,
        vouch_url: str | None,
    ) -> None:
        """Send webmentions and display results."""
        results = sender.send_webmentions(source_url, html_content, vouch_url=vouch_url)

        if not results:
            self.stdout.write("No webmentions were sent (no valid targets found)")
            return

        success_count = sum(1 for r in results if r["success"])
        self.stdout.write(f"\nSent {success_count}/{len(results)} webmentions successfully\n")

        for result in results:
            if result["success"]:
                self.stdout.write(
                    self.style.SUCCESS(f"✓ {result['target']} -> {result['endpoint']} (HTTP {result['status_code']})")
                )
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ {result['target']} -> {result['endpoint']} (Error: {result.get('error', 'Unknown error')})"
                    )
                )
