"""Analysis of fetched Webmention HTML, run in a resource-limited child process.

Fetched source and Vouch documents are untrusted. Building a tree from them and
extracting microformats can need far more memory and CPU time than the size of
the document suggests, and that cost is decided by third-party parsers. This
module therefore does all work on fetched HTML, and
:mod:`indieweb.parse_isolation` runs it as ``python -m
indieweb.webmention_parse_worker`` with operating-system limits, so an
expensive document ends its own short-lived process instead of the worker that
received the Webmention.

The module must not need Django settings: the child starts without them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from collections.abc import Sequence
from types import ModuleType
from typing import Any
from urllib.parse import ParseResult, parse_qsl, urlencode, urlparse, urlunparse

import mf2py
from bs4 import BeautifulSoup, Tag

from .sanitizers import sanitize_webmention_html

resource: ModuleType | None
try:
    import resource
except ImportError:  # pragma: no cover - platforms without POSIX resource limits
    resource = None

NON_RENDERED_LINK_ANCESTORS = {"noscript", "template"}

EXIT_FAILED = 1
EXIT_MEMORY_LIMIT = 3
EXIT_RESULT_TOO_LARGE = 4
EXIT_LIMITS_UNAVAILABLE = 5

MEMORY_WATCHDOG_INTERVAL_SECONDS = 0.02


def _canonical_netloc_for_match(parsed: ParseResult) -> str | None:
    """Return a canonical netloc for URL target matching, or ``None`` if malformed."""
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None

    if not host:
        return None

    normalized_host = host.lower()
    if normalized_host.startswith("www."):
        normalized_host = normalized_host[4:]
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"

    userinfo = ""
    if "@" in parsed.netloc:
        userinfo = parsed.netloc.rsplit("@", 1)[0] + "@"

    netloc = f"{userinfo}{normalized_host}"
    if port is not None:
        netloc = f"{netloc}:{port}"
    return netloc


def _canonicalize_url_for_match(value: str) -> str:
    """Return a conservative canonical URL string for Webmention target matching."""
    try:
        parsed = urlparse(value)
    except ValueError:
        return value

    if not parsed.scheme or not parsed.netloc:
        return value

    scheme = parsed.scheme.lower()
    netloc = _canonical_netloc_for_match(parsed)
    if netloc is None:
        return value

    path = parsed.path
    if path not in ("", "/") and path.endswith("/"):
        path = path[:-1]

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query = urlencode(sorted(query_pairs))

    return urlunparse((scheme, netloc, path, parsed.params, query, ""))


def _is_absolute_url_for_match(value: str) -> bool:
    """Return whether ``value`` is eligible for URL canonicalization matching."""
    try:
        parsed = urlparse(value)
        return bool(parsed.scheme and parsed.netloc)
    except ValueError:
        return False


def _urls_match(left: str, right: str) -> bool:
    """Compare two URLs using the conservative Webmention target matching policy."""
    if left == right:
        return True
    if not _is_absolute_url_for_match(left) or not _is_absolute_url_for_match(right):
        return False
    return _canonicalize_url_for_match(left) == _canonicalize_url_for_match(right)


def _rendered_link_tags(html_content: str) -> list[Tag]:
    """Return the ``<a href>`` elements of ``html_content`` that a browser renders.

    Links inside non-rendered containers do not count. Elements arrive in
    document order, so whether an element is hidden follows from its parent
    alone and the scan stays linear in the document size whatever the nesting.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    hidden: set[int] = set()
    links: list[Tag] = []
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        if tag.name in NON_RENDERED_LINK_ANCESTORS or id(tag.parent) in hidden:
            hidden.add(id(tag))
        elif tag.name == "a" and tag.get("href") is not None:
            links.append(tag)
    return links


def _html_links_to_target(html_content: str, target_url: str) -> bool:
    """Return whether ``html_content`` contains an href value matching ``target_url``."""
    for tag in _rendered_link_tags(html_content):
        href = tag.get("href")
        if isinstance(href, str) and _urls_match(href, target_url):
            return True
    return False


def _canonical_domain_for_vouch(value: str) -> str | None:
    """Return a conservative domain string for Vouch matching."""
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if parsed.scheme.lower() not in ("http", "https"):
        return None
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if not host:
        return None
    normalized = host.lower()
    if normalized.startswith("www."):
        normalized = normalized[4:]
    if ":" in normalized and not normalized.startswith("["):
        normalized = f"[{normalized}]"
    if port is not None:
        normalized = f"{normalized}:{port}"
    return normalized


def _href_links_to_domain(href: str, source_domain: str) -> bool:
    """Return whether an href points at the source domain for Vouch verification."""
    return _canonical_domain_for_vouch(href) == source_domain


def _html_links_to_source_domain(html_content: str, source_url: str) -> bool:
    """Return whether ``html_content`` contains an HTTP(S) hyperlink to the source URL's domain."""
    source_domain = _canonical_domain_for_vouch(source_url)
    if source_domain is None:
        return False

    for tag in _rendered_link_tags(html_content):
        href = tag.get("href")
        if isinstance(href, str) and _href_links_to_domain(href, source_domain):
            return True
    return False


def content_html_digest(html_content: str) -> str:
    """Return the key under which a checked ``e-content`` value is reported to the parent."""
    return hashlib.sha256(html_content.encode("utf-8", "surrogatepass")).hexdigest()


def first_property_value(properties: dict[str, Any], key: str) -> str:
    """Return the first value of a microformats property as text."""
    values = properties.get(key, [])
    if values and isinstance(values, list):
        value = values[0]
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            # Handle complex microformats objects
            return value.get("value", "")  # type: ignore[no-any-return]
    return ""


def extract_entry_content(h_entry: dict[str, Any]) -> dict[str, str]:
    """Return the text and the (unsanitized) HTML of the content of an h-entry."""
    properties = h_entry.get("properties", {})
    content_data = properties.get("content", [])

    if not content_data:
        # Try summary as fallback
        summary = first_property_value(properties, "summary")
        if summary:
            return {"text": summary, "html": summary}
        return {"text": "", "html": ""}

    content = content_data[0] if isinstance(content_data, list) else content_data

    if isinstance(content, dict):
        return {
            "text": content.get("value", ""),
            "html": content.get("html") or content.get("value", ""),
        }
    elif isinstance(content, str):
        return {"text": content, "html": content}

    return {"text": "", "html": ""}


def _analyze_entry_content(parsed: dict[str, Any], target_url: str) -> tuple[list[str], dict[str, str]]:
    """Do the HTML work on the content of every h-entry in ``parsed``.

    The parent selects the mentioning h-entry and its nested responses from the
    parse result. Two things it needs for that take another HTML parse, which
    belongs here as well: whether embedded content links to the target, and the
    sanitized form of the content that is stored. Both are returned keyed by
    :func:`content_html_digest` of the HTML in the parse result.
    """
    links: dict[str, bool] = {}
    sanitized: dict[str, str] = {}
    items = parsed.get("items", [])
    stack = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    while stack:
        item = stack.pop()
        children = item.get("children", [])
        if isinstance(children, list):
            stack.extend(child for child in children if isinstance(child, dict))
        types = item.get("type", [])
        properties = item.get("properties", {})
        if not isinstance(types, list) or "h-entry" not in types or not isinstance(properties, dict):
            continue

        contents = properties.get("content", [])
        for content in contents if isinstance(contents, list) else []:
            html_content = content.get("html") if isinstance(content, dict) else None
            if not isinstance(html_content, str):
                continue
            digest = content_html_digest(html_content)
            if digest not in links:
                links[digest] = _html_links_to_target(html_content, target_url)

        stored_html = extract_entry_content(item)["html"]
        if isinstance(stored_html, str) and stored_html:
            digest = content_html_digest(stored_html)
            if digest not in sanitized:
                sanitized[digest] = sanitize_webmention_html(stored_html)
    return sorted(digest for digest, linking in links.items() if linking), sanitized


def analyze_source(html_content: str, base_url: str, target_url: str) -> dict[str, Any]:
    """Verify the link to the target and parse the microformats of a fetched source."""
    if not _html_links_to_target(html_content, target_url):
        return {"links_to_target": False}
    parsed = mf2py.parse(doc=html_content, url=base_url)
    linking_content, sanitized_content = _analyze_entry_content(parsed, target_url)
    return {
        "links_to_target": True,
        "parsed": parsed,
        "linking_content": linking_content,
        "sanitized_content": sanitized_content,
    }


def analyze_vouch(html_content: str, source_url: str) -> dict[str, Any]:
    """Check whether a fetched Vouch document links to the source domain."""
    return {"links_to_source_domain": _html_links_to_source_domain(html_content, source_url)}


def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    """Run one analysis request and return its JSON-serializable result."""
    operation = request.get("operation")
    if operation == "source":
        return analyze_source(str(request["html"]), str(request["base_url"]), str(request["target_url"]))
    if operation == "vouch":
        return analyze_vouch(str(request["html"]), str(request["source_url"]))
    raise ValueError(f"Unknown operation: {operation!r}")


class LimitsUnavailable(RuntimeError):
    """Raised when the required operating-system limits cannot be applied."""


def _lower_limit(resource_module: Any, name: str, value: int, hard_value: int | None = None) -> None:
    """Lower one resource limit, never raising it above the inherited hard limit."""
    kind = getattr(resource_module, name)
    infinity = resource_module.RLIM_INFINITY
    _soft, inherited_hard = resource_module.getrlimit(kind)
    hard = value if hard_value is None else hard_value
    if inherited_hard != infinity:
        hard = min(hard, inherited_hard)
    resource_module.setrlimit(kind, (min(value, hard), hard))


def apply_resource_limits(
    *,
    memory_bytes: int,
    cpu_seconds: int,
    max_file_bytes: int,
    resource_module: Any = resource,
) -> bool:
    """Apply the limits to the current process.

    Returns whether the kernel enforces the memory limit. CPU time and output
    size limits are required; without them :class:`LimitsUnavailable` is
    raised. Some platforms (macOS) refuse address-space and data-segment
    limits; the caller then has to watch the resident set size itself.
    """
    if resource_module is None:
        raise LimitsUnavailable("the resource module is not available on this platform")
    try:
        # The hard limit is one second later: the kernel first asks, then kills.
        _lower_limit(resource_module, "RLIMIT_CPU", cpu_seconds, cpu_seconds + 1)
        _lower_limit(resource_module, "RLIMIT_FSIZE", max_file_bytes)
    except (AttributeError, ValueError, OSError) as exc:
        raise LimitsUnavailable(f"required resource limits could not be applied: {exc}") from exc

    try:
        _lower_limit(resource_module, "RLIMIT_CORE", 0)
    except (AttributeError, ValueError, OSError):
        pass

    memory_limited = False
    for name in ("RLIMIT_AS", "RLIMIT_DATA"):
        try:
            _lower_limit(resource_module, name, memory_bytes)
        except (AttributeError, ValueError, OSError):
            continue
        memory_limited = True
    return memory_limited


def peak_resident_bytes(resource_module: Any = resource) -> int:
    """Return the peak resident set size of the current process in bytes."""
    peak = int(resource_module.getrusage(resource_module.RUSAGE_SELF).ru_maxrss)
    # ``ru_maxrss`` is reported in bytes on macOS and in kibibytes elsewhere.
    return peak if sys.platform == "darwin" else peak * 1024


def start_memory_watchdog(memory_bytes: int) -> threading.Thread:
    """End the process once its peak resident set size exceeds ``memory_bytes``.

    Used where the kernel does not enforce a memory limit. The check runs
    between interpreter switches, so it is a backstop, not a hard limit: one
    long call into C code can overshoot before the thread runs again.
    """

    def watch() -> None:  # pragma: no cover - ends the process it runs in
        while True:
            if peak_resident_bytes() > memory_bytes:
                os._exit(EXIT_MEMORY_LIMIT)
            time.sleep(MEMORY_WATCHDOG_INTERVAL_SECONDS)

    thread = threading.Thread(target=watch, name="memory-watchdog", daemon=True)
    thread.start()
    return thread


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    """Read one request from stdin, write its result to stdout, and return the exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-bytes", type=_positive_int, required=True)
    parser.add_argument("--cpu-seconds", type=_positive_int, required=True)
    parser.add_argument("--max-result-bytes", type=_positive_int, required=True)
    parser.add_argument("--allow-missing-os-limits", action="store_true")
    args = parser.parse_args(argv)

    try:
        memory_limited = apply_resource_limits(
            memory_bytes=args.memory_bytes,
            cpu_seconds=args.cpu_seconds,
            max_file_bytes=args.max_result_bytes,
        )
    except LimitsUnavailable as exc:
        if not args.allow_missing_os_limits:
            print(f"refusing to parse without resource limits: {exc}", file=sys.stderr)
            return EXIT_LIMITS_UNAVAILABLE
    else:
        if not memory_limited:
            start_memory_watchdog(args.memory_bytes)

    try:
        request = json.loads(sys.stdin.buffer.read())
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        payload = json.dumps(handle_request(request)).encode("ascii")
    except MemoryError:
        return EXIT_MEMORY_LIMIT
    except Exception as exc:
        # Only the exception type: the message can quote the untrusted document.
        print(f"analysis failed: {type(exc).__name__}", file=sys.stderr)
        return EXIT_FAILED

    if len(payload) > args.max_result_bytes:
        return EXIT_RESULT_TOO_LARGE
    try:
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()
    except OSError:
        return EXIT_RESULT_TOO_LARGE
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the child process
    status = main()
    # Skip interpreter teardown: freeing a large tree would only burn CPU time.
    os._exit(status)
