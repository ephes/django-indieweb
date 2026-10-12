"""Run the analysis of fetched Webmention HTML in a resource-limited child process.

The receiver never builds a tree from fetched HTML in its own process. Each
analysis runs :mod:`indieweb.webmention_parse_worker` in a short-lived child
that limits its own memory and CPU time; this module adds the wall-clock
timeout and the cap on the size of the result. Whatever goes wrong in the child
(a limit, a parser error, a crash) is reported as
:class:`WebmentionSourceRejected`, so the caller has one outcome to handle and
nothing from an over-expensive document reaches the database.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from . import webmention_parse_worker

logger = logging.getLogger(__name__)

MIB = 1024 * 1024
DEFAULT_PARSE_MEMORY_BYTES = 512 * MIB
DEFAULT_PARSE_CPU_SECONDS = 20
DEFAULT_PARSE_WALL_SECONDS = 30
DEFAULT_PARSE_MAX_RESULT_BYTES = 2 * MIB
WORKER_MODULE = "indieweb.webmention_parse_worker"
STDERR_LOG_BYTES = 2000
WORKER_ENVIRONMENT_NAMES = (
    "PATH",
    "PYTHONHOME",
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
    "SYSTEMROOT",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
)


class WebmentionSourceRejected(Exception):
    """Fetched HTML was too expensive to process, or its analysis failed."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"source too expensive to process ({reason})")
        self.reason = reason


@dataclass(frozen=True)
class SourceAnalysis:
    """What the receiver needs to know about a fetched source document."""

    links_to_target: bool
    parsed: dict[str, Any]
    # Digests (``content_html_digest``) of h-entry content that links to the target.
    linking_content: frozenset[str]
    # Sanitized h-entry content HTML by the digest of the HTML in ``parsed``.
    sanitized_content: dict[str, str]

    def sanitized_html(self, html_content: str) -> str:
        """Return the sanitized form of content HTML taken from ``parsed``."""
        if not html_content:
            return ""
        try:
            return self.sanitized_content[webmention_parse_worker.content_html_digest(html_content)]
        except KeyError:
            raise WebmentionSourceRejected("worker returned no sanitized content") from None


@dataclass(frozen=True)
class ParseLimits:
    memory_bytes: int
    cpu_seconds: int
    wall_seconds: float
    max_result_bytes: int
    require_os_limits: bool


def _positive_number_setting(name: str, default: int, *, integer: bool = True) -> Any:
    configured = getattr(settings, name, default)
    try:
        if isinstance(configured, bool):
            raise TypeError("booleans are not limits")
        parsed = int(configured) if integer else float(configured)
        if not 0 < parsed < float("inf"):
            raise ValueError("limits must be positive and finite")
    except (TypeError, ValueError, OverflowError):
        logger.warning("Ignoring invalid %s value; using default %s", name, default)
        return default
    return parsed


def parse_limits() -> ParseLimits:
    """Return the configured limits for one analysis of fetched HTML."""
    return ParseLimits(
        memory_bytes=_positive_number_setting("INDIEWEB_WEBMENTION_PARSE_MEMORY_BYTES", DEFAULT_PARSE_MEMORY_BYTES),
        cpu_seconds=_positive_number_setting("INDIEWEB_WEBMENTION_PARSE_CPU_SECONDS", DEFAULT_PARSE_CPU_SECONDS),
        wall_seconds=_positive_number_setting(
            "INDIEWEB_WEBMENTION_PARSE_WALL_SECONDS", DEFAULT_PARSE_WALL_SECONDS, integer=False
        ),
        max_result_bytes=_positive_number_setting(
            "INDIEWEB_WEBMENTION_PARSE_MAX_RESULT_BYTES", DEFAULT_PARSE_MAX_RESULT_BYTES
        ),
        # Anything but an explicit ``False`` keeps the limits required.
        require_os_limits=getattr(settings, "INDIEWEB_WEBMENTION_PARSE_REQUIRE_OS_LIMITS", True) is not False,
    )


def _worker_command(limits: ParseLimits) -> list[str]:
    executable = getattr(settings, "INDIEWEB_WEBMENTION_PARSE_PYTHON", None) or sys.executable
    command = [
        str(executable),
        "-m",
        WORKER_MODULE,
        "--memory-bytes",
        str(limits.memory_bytes),
        "--cpu-seconds",
        str(limits.cpu_seconds),
        "--max-result-bytes",
        str(limits.max_result_bytes),
    ]
    if not limits.require_os_limits:
        command.append("--allow-missing-os-limits")
    return command


def _worker_environment() -> dict[str, str]:
    """Return the environment of the child.

    The child imports what this process imports, and it gets only the
    variables an interpreter needs to start: a process that parses untrusted
    documents has no use for the application's secrets.
    """
    environment = {name: os.environ[name] for name in WORKER_ENVIRONMENT_NAMES if name in os.environ}
    environment["PYTHONPATH"] = os.pathsep.join(entry for entry in sys.path if entry)
    return environment


def _exit_reason(returncode: int) -> str:
    if returncode == webmention_parse_worker.EXIT_MEMORY_LIMIT:
        return "memory limit"
    if returncode == webmention_parse_worker.EXIT_RESULT_TOO_LARGE:
        return "result size limit"
    if returncode == webmention_parse_worker.EXIT_LIMITS_UNAVAILABLE:
        return "resource limits unavailable"
    if returncode < 0:
        if -returncode == getattr(signal, "SIGXCPU", None):
            return "CPU time limit"
        if -returncode == getattr(signal, "SIGKILL", None):
            return "killed, CPU time or memory limit"
        return f"worker ended by signal {-returncode}"
    return f"worker failed with status {returncode}"


def run_parse_worker(request: dict[str, Any]) -> dict[str, Any]:
    """Run one analysis request in a limited child process and return its result.

    Raises :class:`WebmentionSourceRejected` unless the child finished within
    all limits and returned a well-formed result.
    """
    limits = parse_limits()
    if limits.require_os_limits and webmention_parse_worker.resource is None:
        logger.error(
            "Webmention sources cannot be parsed: this platform has no POSIX resource limits. "
            "See INDIEWEB_WEBMENTION_PARSE_REQUIRE_OS_LIMITS."
        )
        raise WebmentionSourceRejected("resource limits unavailable")

    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            completed = subprocess.run(  # noqa: S603 - fixed command, no shell
                _worker_command(limits),
                input=json.dumps(request).encode("ascii"),
                stdout=stdout,
                stderr=stderr,
                timeout=limits.wall_seconds,
                env=_worker_environment(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            # ``subprocess.run`` has killed and reaped the child.
            raise WebmentionSourceRejected("wall-clock limit") from None
        except OSError as exc:
            logger.error("Webmention parse worker could not be started: %s", exc)
            raise WebmentionSourceRejected("worker could not be started") from None

        if completed.returncode != 0:
            reason = _exit_reason(completed.returncode)
            stderr.seek(0)
            detail = stderr.read(STDERR_LOG_BYTES).decode("utf-8", "replace").strip()
            if detail:
                logger.warning("Webmention parse worker: %s: %s", reason, detail)
            raise WebmentionSourceRejected(reason)

        if os.fstat(stdout.fileno()).st_size > limits.max_result_bytes:
            raise WebmentionSourceRejected("result size limit")
        stdout.seek(0)
        payload = stdout.read(limits.max_result_bytes + 1)

    try:
        result = json.loads(payload)
    except (ValueError, RecursionError):
        raise WebmentionSourceRejected("worker returned an unreadable result") from None
    if not isinstance(result, dict):
        raise WebmentionSourceRejected("worker returned an unreadable result")
    return result


def analyze_source(html_content: str, base_url: str, target_url: str) -> SourceAnalysis:
    """Verify the link to the target and parse the microformats of a fetched source."""
    result = run_parse_worker(
        {"operation": "source", "html": html_content, "base_url": base_url, "target_url": target_url}
    )
    links_to_target = result.get("links_to_target")
    if links_to_target is False:
        return SourceAnalysis(links_to_target=False, parsed={}, linking_content=frozenset(), sanitized_content={})
    parsed = result.get("parsed")
    linking_content = result.get("linking_content")
    sanitized_content = result.get("sanitized_content")
    if (
        links_to_target is not True
        or not isinstance(parsed, dict)
        or not isinstance(linking_content, list)
        or not all(isinstance(digest, str) for digest in linking_content)
        or not isinstance(sanitized_content, dict)
        or not all(isinstance(value, str) for value in sanitized_content.values())
    ):
        raise WebmentionSourceRejected("worker returned an unreadable result")
    return SourceAnalysis(
        links_to_target=True,
        parsed=parsed,
        linking_content=frozenset(linking_content),
        sanitized_content=sanitized_content,
    )


def vouch_links_to_source_domain(html_content: str, source_url: str) -> bool:
    """Return whether a fetched Vouch document links to the domain of ``source_url``."""
    result = run_parse_worker({"operation": "vouch", "html": html_content, "source_url": source_url})
    links = result.get("links_to_source_domain")
    if not isinstance(links, bool):
        raise WebmentionSourceRejected("worker returned an unreadable result")
    return links
