"""Run the analysis of Webmention and h-card HTML in a resource-limited child process.

The caller never builds a tree from this HTML in its own process. Each
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
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import IO, Any

from django.conf import settings
from django.utils.crypto import salted_hmac

from . import webmention_parse_worker
from .log_redaction import text_fingerprint

logger = logging.getLogger(__name__)

MIB = 1024 * 1024
DEFAULT_PARSE_MEMORY_BYTES = 512 * MIB
DEFAULT_PARSE_CPU_SECONDS = 20
DEFAULT_PARSE_WALL_SECONDS = 30
DEFAULT_PARSE_MAX_RESULT_BYTES = 2 * MIB
DEFAULT_PARSE_MAX_CONCURRENT = 2
MAX_PARSE_CONCURRENT = 64
WORKER_MODULE = "indieweb.webmention_parse_worker"
# Largest failed-worker stderr that is digested for the log; larger stderr is
# logged by size only. Stderr content itself is never logged.
STDERR_DIGEST_BYTES = 256 * 1024
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
    """Fetched HTML was too expensive to process, or its analysis failed.

    ``reason`` is always a fixed phrase written in this package (never source,
    worker or exception text), so the message may be logged.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"source too expensive to process ({reason})")
        self.reason = reason


class WebmentionParseCapacityError(WebmentionSourceRejected):
    """Temporary parse capacity exhaustion; callers should retry without changing stored state."""


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


def _parse_max_concurrent() -> int:
    name = "INDIEWEB_WEBMENTION_PARSE_MAX_CONCURRENT"
    configured = getattr(settings, name, DEFAULT_PARSE_MAX_CONCURRENT)
    if type(configured) is not int or not 1 <= configured <= MAX_PARSE_CONCURRENT:
        logger.warning("Ignoring invalid %s value; using default %s", name, DEFAULT_PARSE_MAX_CONCURRENT)
        return DEFAULT_PARSE_MAX_CONCURRENT
    return configured


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


def _private_slot_info(candidate: int) -> os.stat_result:
    info = os.fstat(candidate)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        raise OSError("parse slot must be a private regular file owned by this user with one link")
    return info


def _check_parse_directory(directory: str, directory_fd: int) -> None:
    info = os.fstat(directory_fd)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or not os.path.samestat(info, os.stat(directory, follow_symlinks=False))
    ):
        raise OSError("parse lock directory must retain its private named identity")


def _claim_parse_slot(directory: str, directory_fd: int, maximum: int, locks: Any, deadline: float) -> int | None:
    for index in range(maximum):
        if time.monotonic() >= deadline:
            raise WebmentionParseCapacityError("parse capacity")
        name = f"{index}.lock"
        candidate = os.open(name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory_fd)
        try:
            _private_slot_info(candidate)
            locks.flock(candidate, locks.LOCK_EX | locks.LOCK_NB)
            # flock protects the descriptor, not the pathname. A displaced
            # directory or slot would otherwise create an independent pool.
            _check_parse_directory(directory, directory_fd)
            if not os.path.samestat(
                _private_slot_info(candidate), os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            ):
                raise OSError("parse slot must retain its locked named identity")
            if time.monotonic() >= deadline:
                raise WebmentionParseCapacityError("parse capacity")
        except BlockingIOError:
            os.close(candidate)
        except BaseException:
            os.close(candidate)
            raise
        else:
            return candidate
    return None


def _close_parse_slot(slot: int | None, directory_fd: int | None) -> OSError | None:
    """Attempt each close once and retain the first error for diagnostics."""
    close_error = None
    for fd in (slot, directory_fd):
        if fd is not None:
            try:
                os.close(fd)
            except OSError as exc:
                close_error = close_error or exc
    return close_error


@contextmanager
def _parse_slot() -> Iterator[int]:
    """Hold a host-local slot across child execution and result validation."""
    try:
        import fcntl
    except ImportError:
        raise WebmentionSourceRejected("parse capacity unavailable") from None
    maximum = _parse_max_concurrent()
    wait = _positive_number_setting("INDIEWEB_WEBMENTION_PARSE_SLOT_WAIT_SECONDS", 1, integer=False)
    deployment = salted_hmac("indieweb.parse-slots", "deployment", algorithm="sha256").hexdigest()[:16]
    directory = getattr(settings, "INDIEWEB_WEBMENTION_PARSE_LOCK_DIR", None) or os.path.join(
        tempfile.gettempdir(), f"indieweb-parse-{os.getuid()}-{deployment}"
    )
    slot = None
    directory_fd = None
    work_completed = False
    try:
        try:
            deadline = time.monotonic() + wait
            os.makedirs(directory, mode=0o700, exist_ok=True)
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            _check_parse_directory(directory, directory_fd)
            while slot is None:
                slot = _claim_parse_slot(directory, directory_fd, maximum, fcntl, deadline)
                if slot is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise WebmentionParseCapacityError("parse capacity")
                    time.sleep(min(0.02, remaining))
        except OSError as exc:
            logger.error("Webmention parse capacity unavailable: %s", type(exc).__name__)
            raise WebmentionSourceRejected("parse capacity unavailable") from None
        yield slot
        work_completed = True
    finally:
        close_error = _close_parse_slot(slot, directory_fd)
        if close_error is not None:
            with suppress(Exception):
                logger.error("Webmention parse slot cleanup failed: %s", type(close_error).__name__)
            if work_completed:
                raise WebmentionSourceRejected("parse capacity unavailable") from None


def _log_worker_stderr(reason: str, stderr: IO[bytes]) -> None:
    """Log the length and keyed digest of a failed worker's stderr, never its content.

    Stderr larger than ``STDERR_DIGEST_BYTES`` is logged by size only.
    """
    size = os.fstat(stderr.fileno()).st_size
    if not size:
        return
    if size > STDERR_DIGEST_BYTES:
        logger.warning("Webmention parse worker: %s: stderr %d bytes", reason, size)
        return
    stderr.seek(0)
    logger.warning("Webmention parse worker: %s: stderr %s", reason, text_fingerprint(stderr.read()))


def _remaining_parse_time(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise WebmentionSourceRejected("wall-clock limit")
    return remaining


def _receive_worker_result(request: dict[str, Any], limits: ParseLimits, slot: int, deadline: float) -> dict[str, Any]:
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        command = _worker_command(limits)
        payload = json.dumps(request).encode("ascii")
        environment = _worker_environment()
        _remaining_parse_time(deadline)
        try:
            with subprocess.Popen(  # noqa: S603 - fixed command, no shell
                command,
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                env=environment,
                pass_fds=(slot,),
            ) as worker:
                try:
                    worker.communicate(input=payload, timeout=_remaining_parse_time(deadline))
                except BaseException:
                    # The context manager reaps the child after it is killed.
                    worker.kill()
                    raise
        except subprocess.TimeoutExpired:
            raise WebmentionSourceRejected("wall-clock limit") from None
        except OSError as exc:
            logger.error("Webmention parse worker could not be started: %s", type(exc).__name__)
            raise WebmentionSourceRejected("worker could not be started") from None

        _remaining_parse_time(deadline)
        if worker.returncode != 0:
            reason = _exit_reason(worker.returncode)
            _log_worker_stderr(reason, stderr)
            raise WebmentionSourceRejected(reason)

        if os.fstat(stdout.fileno()).st_size > limits.max_result_bytes:
            raise WebmentionSourceRejected("result size limit")
        stdout.seek(0)
        payload = stdout.read(limits.max_result_bytes + 1)
        _remaining_parse_time(deadline)

        try:
            result = json.loads(payload)
        except (ValueError, RecursionError):
            result = None
        _remaining_parse_time(deadline)
        if not isinstance(result, dict):
            raise WebmentionSourceRejected("worker returned an unreadable result")
        return result


def run_parse_worker(request: dict[str, Any]) -> dict[str, Any]:
    """Run one analysis request in a limited child process and return its result.

    Raises :class:`WebmentionSourceRejected` if the child exceeded a limit,
    returned an invalid result, or capacity could not be acquired or retired.
    """
    limits = parse_limits()
    if limits.require_os_limits and webmention_parse_worker.resource is None:
        logger.error(
            "Webmention sources cannot be parsed: this platform has no POSIX resource limits. "
            "See INDIEWEB_WEBMENTION_PARSE_REQUIRE_OS_LIMITS."
        )
        raise WebmentionSourceRejected("resource limits unavailable")

    with _parse_slot() as slot:
        deadline = time.monotonic() + limits.wall_seconds
        return _receive_worker_result(request, limits, slot, deadline)


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
