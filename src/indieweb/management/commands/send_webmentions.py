"""Django management command to send webmentions."""

import os
import re
import select
import sys
import time
from io import StringIO
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import URLValidator

from indieweb.http_client import is_safe_http_url
from indieweb.log_redaction import redact_url, text_fingerprint
from indieweb.senders import (
    DEFAULT_WEBMENTION_SENDER_FETCH_MAX_BYTES,
    WebmentionSender,
    _positive_int_setting,
    _source_deadline,
)

CONTENT_CHUNK_SIZE = 16 * 1024
SAFE_RESULT_ERRORS = frozenset(
    {
        "No endpoint found",
        "Delivery failed",
        "Source deadline exceeded",
        "Historical target skipped during resend cooldown",
        "Historical target dropped after consecutive failures",
        "Historical target skipped after successful resend cutoff",
        "Historical target changed during failure pruning",
        "Historical resend already claimed or history changed",
    }
)
DROPPED_SUFFIX = "; historical target dropped"
# Transport failures are stored as the exception class name (e.g. ConnectError,
# ReadTimeout) or "response too large (<class name>)"; both are code-defined.
EXCEPTION_CATEGORY = re.compile(r"[A-Z][A-Za-z0-9]{0,63}|response too large \([A-Z][A-Za-z0-9]{0,63}\)")


def _error_category(error: object) -> str:
    """Return a fixed or code-defined error category, else a keyed fingerprint."""
    if isinstance(error, str):
        if error in SAFE_RESULT_ERRORS:
            return error
        if EXCEPTION_CATEGORY.fullmatch(error):
            return error
    return text_fingerprint(str(error))


def _result_detail(result: dict[str, Any]) -> str:
    """Keep protocol status/fixed categories; fingerprint all other result text.

    A trailing historical-drop marker is stripped; callers report drops from the
    result's ``dropped`` flag.
    """
    status = result.get("status_code")
    if type(status) is int and 100 <= status <= 599:
        return f"HTTP {status}"
    error = result.get("error", "Unknown error")
    if isinstance(error, str) and error.endswith(DROPPED_SUFFIX):
        error = error.removesuffix(DROPPED_SUFFIX)
    return _error_category(error)


def _provenance(result: dict[str, Any]) -> str:
    value = result.get("provenance")
    return value if value in ("current", "history", "both") else "unknown"


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
        parser.add_argument(
            "--salmention-resend",
            action="store_true",
            help="Resend to the union of current and historical targets for the source URL",
            default=False,
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Handle the command."""
        self.source_deadline = _source_deadline()
        source_url = options["source"]
        html_content = options["content"]
        dry_run = options["dry_run"]
        vouch_url = options["vouch"]
        salmention_resend = options["salmention_resend"]

        if not is_safe_http_url(source_url, resolver=None):
            raise CommandError("Source URL must be a valid http:// or https:// URL")
        if vouch_url:
            try:
                URLValidator(schemes=["http", "https"])(vouch_url)
            except ValidationError:
                raise CommandError("Vouch URL must be a valid http:// or https:// URL") from None

        sender = WebmentionSender()

        if dry_run:
            self.stdout.write("DRY RUN MODE - No webmentions will be sent\n")

        html_content = self._resolve_content(sender, source_url, html_content)
        self._check_source_deadline()
        urls = sender.extract_urls(html_content)
        self.stdout.write(f"Found {len(urls)} URLs in content\n")

        if dry_run:
            if salmention_resend:
                self._handle_salmention_dry_run(sender, source_url, urls)
            else:
                self._handle_dry_run(sender, source_url, urls)
        elif salmention_resend:
            self._handle_salmention_send(sender, source_url, urls, vouch_url)
        else:
            self._handle_send(sender, source_url, urls, vouch_url)

    def _resolve_content(self, sender: WebmentionSender, source_url: str, html_content: str | None) -> str:
        """Resolve HTML content from argument, stdin, or by fetching the source URL."""
        limit = _positive_int_setting("INDIEWEB_WEBMENTION_FETCH_MAX_BYTES", DEFAULT_WEBMENTION_SENDER_FETCH_MAX_BYTES)
        if html_content == "-":
            return self._read_stdin(limit)
        if html_content is not None:
            self._admit_content(html_content, limit)
            return html_content
        self.stdout.write(f"Fetching content from {redact_url(source_url)}...")
        fetched_content = sender.fetch_content(source_url, deadline=self.source_deadline)
        if not fetched_content:
            raise CommandError(f"Failed to fetch content from {redact_url(source_url)}")
        return fetched_content

    def _check_source_deadline(self) -> None:
        if time.monotonic() >= self.source_deadline:
            raise CommandError("Source deadline exceeded; content not parsed or sent")

    def _admit_content(self, content: str, limit: int) -> int:
        """Count UTF-8 bytes in bounded chunks, including for an already allocated argument."""
        size = 0
        for offset in range(0, len(content), CONTENT_CHUNK_SIZE):
            self._check_source_deadline()
            try:
                size += len(content[offset : offset + CONTENT_CHUNK_SIZE].encode("utf-8"))
            except UnicodeError:
                raise CommandError("Content must be valid UTF-8") from None
            if size > limit:
                raise CommandError("Content exceeds byte limit; content not parsed or sent")
        self._check_source_deadline()
        return size

    def _read_stdin(self, limit: int) -> str:
        """Read at most limit+1 bytes; wait for pipe/terminal input only within the source budget."""
        if isinstance(sys.stdin, StringIO):
            # In-memory streams used by call_command need no descriptor readiness wait.
            chunks: list[str] = []
            size = 0
            while True:
                self._check_source_deadline()
                chunk = sys.stdin.read(min(CONTENT_CHUNK_SIZE, limit - size + 1))
                size += self._admit_content(chunk, limit - size)
                if not chunk:
                    return "".join(chunks)
                chunks.append(chunk)
        try:
            fd = sys.stdin.fileno()
            data = bytearray()
            while True:
                self._check_source_deadline()
                ready, _, _ = select.select([fd], [], [], max(0, self.source_deadline - time.monotonic()))
                self._check_source_deadline()
                if not ready:
                    continue
                chunk_bytes = os.read(fd, min(CONTENT_CHUNK_SIZE, limit - len(data) + 1))
                self._check_source_deadline()
                if len(data) + len(chunk_bytes) > limit:
                    raise CommandError("Content exceeds byte limit; content not parsed or sent")
                if not chunk_bytes:
                    return data.decode("utf-8")
                data.extend(chunk_bytes)
        except UnicodeError:
            raise CommandError("Content must be valid UTF-8") from None
        except (OSError, ValueError):
            raise CommandError("Unable to read stdin with a bounded wait; provide --content instead") from None

    def _handle_dry_run(self, sender: WebmentionSender, source_url: str, urls: list[str]) -> None:
        """Discover only targets admitted by the ordinary sender's policy."""
        targets = sender.select_target_urls(source_url, urls)
        self.stdout.write(f"Selected {len(targets)} targets after URL, same-host and fanout policy exclusions")
        for url in targets:
            if time.monotonic() >= self.source_deadline:
                raise CommandError("Source deadline exceeded; remaining targets unattempted")
            endpoint = sender.discover_endpoint(url, deadline=self.source_deadline)
            if endpoint:
                self.stdout.write(f"  - {redact_url(url)} -> {redact_url(endpoint)}")
            else:
                self.stdout.write(f"  - {redact_url(url)} (no endpoint found)")

    def _handle_send(
        self,
        sender: WebmentionSender,
        source_url: str,
        urls: list[str],
        vouch_url: str | None,
    ) -> None:
        """Send webmentions and display results."""
        results = sender.send_webmentions(source_url, urls, vouch_url=vouch_url, deadline=self.source_deadline)

        if not results:
            self.stdout.write("No webmentions were sent (no valid targets found)")
            return

        sent_results = [result for result in results if not result.get("skipped")]
        success_count = sum(1 for r in sent_results if r["success"])
        self.stdout.write(f"\nSent {success_count}/{len(sent_results)} webmentions successfully\n")

        for result in results:
            target = redact_url(result["target"])
            # An absent endpoint must not render as a digest of the empty string in redact mode.
            arrow = f" -> {redact_url(result['endpoint'])}" if result.get("endpoint") else ""
            if result.get("skipped"):
                self.stdout.write(self.style.WARNING(f"- {target} (skipped by policy)"))
            elif result["success"]:
                self.stdout.write(self.style.SUCCESS(f"✓ {target}{arrow} ({_result_detail(result)})"))
            else:
                self.stdout.write(self.style.ERROR(f"✗ {target}{arrow} (Error: {_result_detail(result)})"))

        if success_count < len(sent_results):
            raise CommandError(f"{len(sent_results) - success_count} Webmention deliveries failed")

    def _handle_salmention_dry_run(self, sender: WebmentionSender, source_url: str, urls: list[str]) -> None:
        """Show the Salmention resend target union without sending or recording history."""
        try:
            results = sender.preview_salmention_resend_targets(source_url, urls, deadline=self.source_deadline)
        except ValueError as exc:
            raise CommandError(f"Salmention selection failed ({text_fingerprint(str(exc))})") from None
        if not results:
            self.stdout.write("No Salmention resends would be sent (no current or historical targets found)")
            return

        for result in results:
            target = redact_url(result["target"])
            provenance = _provenance(result)
            if result.get("skipped"):
                self.stdout.write(f"  - {self._format_salmention_result(result)}")
            elif result["endpoint"]:
                self.stdout.write(f"  - [{provenance}] {target} -> {redact_url(result['endpoint'])}")
            else:
                self.stdout.write(f"  - [{provenance}] {target} (no endpoint found)")

    def _handle_salmention_send(
        self,
        sender: WebmentionSender,
        source_url: str,
        urls: list[str],
        vouch_url: str | None,
    ) -> None:
        """Resend Salmentions and display provenance-aware results."""
        try:
            results = sender.resend_salmentions(source_url, urls, vouch_url=vouch_url, deadline=self.source_deadline)
        except ValueError as exc:
            raise CommandError(f"Salmention selection failed ({text_fingerprint(str(exc))})") from None

        if not results:
            self.stdout.write("No Salmention resends were sent (no current or historical targets found)")
            return

        sent_results = [result for result in results if not result.get("skipped") or result.get("attempted")]
        success_count = sum(1 for r in sent_results if r["success"])
        skipped_count = len(results) - len(sent_results)
        summary = f"\nResent {success_count}/{len(sent_results)} Salmention webmentions successfully"
        if skipped_count:
            summary += f" ({skipped_count} skipped by policy)"
        self.stdout.write(f"{summary}\n")

        for result in results:
            line = self._format_salmention_result(result)
            if result.get("skipped") and not result.get("attempted"):
                self.stdout.write(self.style.WARNING(line))
                continue
            if result["success"]:
                self.stdout.write(self.style.SUCCESS(line))
            else:
                self.stdout.write(self.style.ERROR(line))

        if success_count < len(sent_results):
            raise CommandError(f"{len(sent_results) - success_count} Salmention deliveries failed")

    def _format_salmention_result(self, result: dict[str, Any]) -> str:
        """Format one provenance-aware resend result."""
        target = redact_url(result["target"])
        endpoint = redact_url(result["endpoint"]) if result.get("endpoint") else ""
        provenance = _provenance(result)

        if result.get("skipped") and not result.get("attempted"):
            action = "dropped" if result.get("dropped") else "skipped"
            return f"- [{provenance}] {target} ({action}: {_result_detail(result)})"

        if result["success"]:
            return f"✓ [{provenance}] {target} -> {endpoint} ({_result_detail(result)})"

        error = _result_detail(result)
        if result.get("dropped"):
            error += "; historical target dropped"
        if endpoint:
            return f"✗ [{provenance}] {target} -> {endpoint} (Error: {error})"
        return f"✗ [{provenance}] {target} (Error: {error})"
