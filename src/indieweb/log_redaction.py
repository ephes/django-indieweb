"""Privacy-oriented log redaction helpers.

INDIEWEB_LOG_REDACTION = "passthrough" | "redact"
- "passthrough" (default): values are logged in a log-safe form (see below).
- "redact": helpers return a stable HMAC-SHA256 digest (truncated to 12 hex
  chars) keyed with SECRET_KEY for correlation without disclosure.
- Values are matched case-insensitively; any other value fails closed to
  "redact" and is logged once as a warning.

The digest is one-way and stable per input: log consumers can correlate
events by digest without seeing the URL/state/me values themselves.

Independent of the mode, the package never logs or stores free text that may
carry credentials, and never tries to scrub secrets out of such text:

* exceptions are logged as their class name only; logged tracebacks keep the
  stack but drop every exception message (``exc_info_without_messages()``);
* URLs are logged as ``scheme://host[:port]/path`` (``safe_url()``), without
  userinfo, query, fragment, or path parameters;
* response bodies from remote servers and parse-worker stderr are logged or
  stored as a length and keyed digest (``text_fingerprint()``), next to the
  HTTP status where there is one.
"""

from __future__ import annotations

import hmac
import logging
import re
import sys
from hashlib import sha256
from types import TracebackType
from typing import Literal, cast
from urllib.parse import quote, urlsplit

from django.conf import settings

logger = logging.getLogger(__name__)

Mode = Literal["passthrough", "redact"]

# Leading token characters kept by ``redact_token`` in passthrough mode.
TOKEN_PREFIX_LENGTH = 4

#: What ``safe_url()`` returns for a value that does not parse as a URL.
INVALID_URL = "<invalid URL>"
#: What ``safe_url()`` returns for a relative reference that is not an absolute path.
RELATIVE_URL = "<relative URL>"

_warned_settings: set[str] = set()

# Path parameters (";jsessionid=...") up to the end of their segment.
_PATH_PARAMETERS_RE = re.compile(r";[^/]*")
# Characters kept as they are in a logged host or path; everything else
# (control characters, spaces, quotes, backslashes, non-ASCII) is percent-encoded.
_SAFE_PATH_CHARS = "/%:@!$&'()*+,=-._~"
_SAFE_HOST_CHARS = "%[]:!$&'()*+,=-._~"


def _safe_str(value: object) -> str:
    try:
        return value if isinstance(value, str) else str(value)
    except Exception:
        return ""


def safe_url(url: object) -> str:
    """Return ``scheme://host[:port]/path`` of ``url`` for logs and stored diagnostics (mode-independent).

    Userinfo, query, fragment and path parameters (``;jsessionid=...``) are
    dropped; the host is lower-cased and unsafe characters in host and path
    are percent-encoded, so the result is a single printable line. A URL with
    a scheme but no authority (``mailto:``, ``data:``) is reduced to its
    scheme, a relative reference to its absolute path (or ``RELATIVE_URL``),
    an empty value to ``""``,
    and anything that does not parse (including an invalid port) to
    ``INVALID_URL``. The path itself is kept, so URLs that carry secrets in
    their path are not made safe by this helper.
    """
    text = _safe_str(url)
    if not text:
        return ""
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return INVALID_URL
    # "surrogatepass": lone surrogates are percent-encoded instead of raising.
    path = quote(_PATH_PARAMETERS_RE.sub("", parts.path), safe=_SAFE_PATH_CHARS, errors="surrogatepass")
    if parts.netloc:
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        authority = quote(host, safe=_SAFE_HOST_CHARS, errors="surrogatepass")
        if port is not None:
            authority = f"{authority}:{port}"
        return f"{parts.scheme}://{authority}{path}" if parts.scheme else f"//{authority}{path}"
    if parts.scheme:
        return f"{parts.scheme}:"
    if path.startswith("/"):
        return path
    return RELATIVE_URL


def _digest_bytes(value: bytes) -> str:
    secret_key = settings.SECRET_KEY
    key_bytes = secret_key.encode("utf-8") if isinstance(secret_key, str) else bytes(secret_key)
    return hmac.new(key_bytes, value, sha256).hexdigest()[:12]


def _digest(value: str) -> str:
    return _digest_bytes(value.encode("utf-8", "surrogatepass"))


def text_fingerprint(value: str | bytes) -> str:
    """Return ``"<N> bytes, digest <12 hex>"`` for ``value`` (mode-independent).

    Use it instead of the content of a remote response body, a hub-supplied
    reason, or parse-worker stderr: the length and the keyed HMAC-SHA256
    digest let operators tell failures apart and group identical ones without
    the text itself reaching logs or the database. Strings are measured and
    digested as UTF-8.
    """
    data = value if isinstance(value, bytes) else value.encode("utf-8", "surrogatepass")
    return f"{len(data)} bytes, digest {_digest_bytes(data)}"


def configured_mode() -> Mode:
    """Return the ``INDIEWEB_LOG_REDACTION`` mode, failing closed to ``"redact"``.

    Values are compared case-insensitively after trimming whitespace. Any
    other value (a typo, ``True``, ``"yes"``) is treated as ``"redact"`` and
    logged once as a warning, so a misspelled opt-in never leaks values.
    """
    configured = getattr(settings, "INDIEWEB_LOG_REDACTION", "passthrough")
    if isinstance(configured, str):
        normalized = configured.strip().lower()
        if normalized in ("passthrough", "redact"):
            return cast(Mode, normalized)
    marker = repr(configured)
    if marker not in _warned_settings:
        _warned_settings.add(marker)
        logger.warning(
            'INDIEWEB_LOG_REDACTION=%s is not "passthrough" or "redact"; using "redact"',
            marker[:64],
        )
    return "redact"


def _resolve_mode(mode: Mode | None) -> Mode:
    if mode in ("passthrough", "redact"):
        return mode
    return configured_mode()


_message_free_exception_classes: dict[type[BaseException], type[Exception]] = {}
_MESSAGE_FREE_EXCEPTION_CLASS_CACHE_MAX = 256


def _message_free_exception_class(original: type[BaseException]) -> type[Exception]:
    """Return a stand-in exception class that formats with the original's module and name."""
    cached = _message_free_exception_classes.get(original)
    if cached is not None:
        return cached
    stand_in = type(
        original.__name__,
        (Exception,),
        {"__module__": original.__module__, "__qualname__": original.__qualname__},
    )
    if len(_message_free_exception_classes) < _MESSAGE_FREE_EXCEPTION_CLASS_CACHE_MAX:
        _message_free_exception_classes[original] = stand_in
    return stand_in


def exception_without_messages(exc: BaseException) -> BaseException:
    """Return a copy of ``exc`` (and its cause/context chain) that carries no text.

    Each copy keeps the original traceback and formats with the original
    class name and module, but has no message, arguments or ``__notes__``
    (exception groups lose their member exceptions). A formatted traceback of
    the copy therefore shows the stack and the exception classes, and nothing
    the exception text said.
    """
    # Iterative on purpose: a recursive closure would form a reference cycle
    # that keeps the copied tracebacks (and their frames) alive until the
    # cyclic garbage collector runs.
    originals: list[BaseException] = []
    copies: dict[int, BaseException] = {}
    pending = [exc]
    while pending:
        original = pending.pop()
        if id(original) in copies:
            continue
        copy = _message_free_exception_class(type(original))()
        copy.__traceback__ = original.__traceback__
        copies[id(original)] = copy
        originals.append(original)
        for linked in (original.__cause__, original.__context__):
            if linked is not None and id(linked) not in copies:
                pending.append(linked)
    for original in originals:
        copied = copies[id(original)]
        if original.__cause__ is not None:
            copied.__cause__ = copies[id(original.__cause__)]
        if original.__context__ is not None:
            copied.__context__ = copies[id(original.__context__)]
        copied.__suppress_context__ = original.__suppress_context__
    result = copies[id(exc)]
    originals.clear()
    copies.clear()
    return result


def exc_info_without_messages(
    exc: BaseException | None = None,
) -> tuple[type[BaseException], BaseException, TracebackType | None] | bool:
    """Return an ``exc_info`` tuple for ``exc`` (default: the active exception) without message text.

    See ``exception_without_messages()``. Returns ``False`` when there is no
    exception, so it can be passed directly as
    ``logger.error(..., exc_info=exc_info_without_messages())``.
    """
    if exc is None:
        exc = sys.exc_info()[1]
    if exc is None:
        return False
    copy = exception_without_messages(exc)
    return type(copy), copy, copy.__traceback__


def redact_url(url: str, *, mode: Mode | None = None) -> str:
    """Return a log-safe form of ``url``.

    Passthrough mode returns ``safe_url(url)``: scheme, host, port and path
    only. Redact mode returns a stable 12-hex digest of the full URL.
    """
    if _resolve_mode(mode) == "passthrough":
        return safe_url(url)
    return _digest(url)


def redact_url_origin(url: str, *, mode: Mode | None = None) -> str:
    """Return ``safe_url(url)`` in passthrough mode, or a stable 12-hex digest of scheme+host in redact mode.

    The redacted form is stable for any URL with the same scheme+host pair,
    so log consumers can group events by origin without seeing paths.
    """
    if _resolve_mode(mode) == "passthrough":
        return safe_url(url)
    try:
        parsed = urlsplit(url)
    except ValueError:
        return _digest(url)
    origin = f"{parsed.scheme}://{(parsed.hostname or '').lower()}"
    return _digest(origin)


def redact_state(value: str, *, mode: Mode | None = None) -> str:
    """Return ``value`` unchanged in passthrough mode, or a stable 12-hex digest in redact mode."""
    if _resolve_mode(mode) == "passthrough":
        return value
    return _digest(value)


def redact_text(value: str, *, mode: Mode | None = None) -> str:
    """Return free-form ``value`` unchanged in passthrough mode, or ``<redacted:DIGEST>`` in redact mode.

    Only for text that is known not to carry credentials, such as a Micropub
    query filter; log it with ``%r`` so control characters are escaped. Never
    pass exception text, response bodies or worker output: log the exception
    class name, ``safe_url()`` or ``text_fingerprint()`` instead.
    """
    if _resolve_mode(mode) == "passthrough":
        return value
    return f"<redacted:{_digest(value)}>"


def redact_token(value: str, *, mode: Mode | None = None) -> str:
    """Return a non-secret display form for a bearer token or auth code.

    Bearer tokens and authorization codes must never be logged in full,
    so even in passthrough mode this helper truncates the input to its
    first 4 characters with a trailing ellipsis, enough to tell tokens
    apart in diagnostics without disclosing a useful share of the secret.
    In redact mode the token is replaced
    with a stable 12-hex HMAC digest so events for the same token can
    still be correlated without exposing any leading bytes of the
    secret.
    """
    if _resolve_mode(mode) == "passthrough":
        return f"{value[:TOKEN_PREFIX_LENGTH]}..." if value else ""
    return _digest(value)
