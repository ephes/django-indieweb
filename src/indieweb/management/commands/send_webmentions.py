"""Django management command to send webmentions."""

import sys
from typing import Any

from django.core.management.base import BaseCommand, CommandError

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

    def handle(self, *args: Any, **options: Any) -> None:
        """Handle the command."""
        source_url = options["source"]
        html_content = options["content"]
        dry_run = options["dry_run"]

        # Validate source URL
        if not source_url.startswith(("http://", "https://")):
            raise CommandError("Source URL must start with http:// or https://")

        sender = WebmentionSender()

        if dry_run:
            self.stdout.write("DRY RUN MODE - No webmentions will be sent\n")

        # If content provided via stdin
        if html_content == "-":
            html_content = sys.stdin.read()

        # Extract URLs first to show what we'll process
        if html_content:
            urls = sender.extract_urls(html_content)
        else:
            self.stdout.write(f"Fetching content from {source_url}...")
            fetched_content = sender.fetch_content(source_url)
            if not fetched_content:
                raise CommandError(f"Failed to fetch content from {source_url}")
            urls = sender.extract_urls(fetched_content)
            html_content = fetched_content

        self.stdout.write(f"Found {len(urls)} URLs in content\n")

        if dry_run:
            # In dry run mode, just show what would be done
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
        else:
            # Actually send webmentions
            results = sender.send_webmentions(source_url, html_content)

            if not results:
                self.stdout.write("No webmentions were sent (no valid targets found)")
                return

            # Display results
            success_count = sum(1 for r in results if r["success"])
            self.stdout.write(f"\nSent {success_count}/{len(results)} webmentions successfully\n")

            for result in results:
                if result["success"]:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"✓ {result['target']} -> {result['endpoint']} (HTTP {result['status_code']})"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(
                            f"✗ {result['target']} -> {result['endpoint']} "
                            f"(Error: {result.get('error', 'Unknown error')})"
                        )
                    )
