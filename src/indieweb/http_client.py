"""Shared HTTP helpers for IndieWeb protocol clients."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

WEBMENTION_ALLOWED_REDIRECT_SCHEMES = ("http", "https")
WEBMENTION_MAX_REDIRECTS = 5
WEBMENTION_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
SAFE_HTTP_ALLOWED_SCHEMES = ("http", "https")
SAFE_HTTP_DEFAULT_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=2.0)

AddressResolver = Callable[[str, int], Iterable[str]]


class WebmentionRedirectError(Exception):
    """Raised when a Webmention HTTP redirect cannot be followed safely."""


class UnsafeHTTPUrlError(ValueError):
    """Raised when an outbound protocol URL is not safe to request."""


class HTTPResponseTooLarge(ValueError):
    """Raised when a fetched response exceeds the configured decoded byte limit."""


@dataclass(frozen=True)
class RedirectedResponse:
    """HTTP response plus the URL reached after following redirects."""

    response: httpx.Response
    final_url: str


def default_address_resolver(host: str, port: int) -> Iterable[str]:
    """Resolve ``host`` for outbound safety checks."""
    results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return {str(result[4][0]) for result in results}


def _canonical_host(host: str) -> str:
    stripped = host.strip("[]").rstrip(".").lower()
    try:
        return str(ipaddress.ip_address(stripped))
    except ValueError:
        pass
    try:
        return stripped.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UnsafeHTTPUrlError("URL host is not valid IDNA") from exc


NAT64_WELL_KNOWN_PREFIX = ipaddress.IPv6Network("64:ff9b::/96")
NAT64_LOCAL_USE_PREFIX = ipaddress.IPv6Network("64:ff9b:1::/48")


def _blocked_ip_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError as exc:
        raise UnsafeHTTPUrlError(f"resolved address is not a valid IP address: {address}") from exc
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if isinstance(ip, ipaddress.IPv6Address):
        if ip in NAT64_WELL_KNOWN_PREFIX or ip in NAT64_LOCAL_USE_PREFIX:
            embedded_v4 = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
            return _blocked_ip_address(str(embedded_v4))
    if not ip.is_global:
        return True
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.is_private:
        return True
    return False


def _validate_parsed_http_url(url: str) -> tuple[str, int]:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeHTTPUrlError("URL is malformed") from exc

    if parsed.scheme.lower() not in SAFE_HTTP_ALLOWED_SCHEMES or not parsed.netloc:
        raise UnsafeHTTPUrlError("URL must be absolute HTTP(S)")
    if "@" in parsed.netloc:
        raise UnsafeHTTPUrlError("URL userinfo is not supported")
    if not parsed.hostname:
        raise UnsafeHTTPUrlError("URL host is required")

    host = _canonical_host(parsed.hostname)
    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeHTTPUrlError("localhost URLs are not allowed")

    port = port if port is not None else (443 if parsed.scheme.lower() == "https" else 80)
    return host, port


def validate_safe_http_url(url: str, *, resolver: AddressResolver | None = default_address_resolver) -> None:
    """Validate that ``url`` is an absolute HTTP(S) URL safe for outbound protocol use.

    When ``resolver`` is provided, hostnames are resolved and every returned IP
    address must be globally routable. Passing ``resolver=None`` keeps the same
    syntactic and IP-literal checks but skips DNS, which is useful for callers
    using a fully mocked ``httpx`` transport in tests.
    """
    host, port = _validate_parsed_http_url(url)

    try:
        ipaddress.ip_address(host)
    except ValueError:
        if resolver is None:
            return
        try:
            addresses = tuple(resolver(host, port))
        except OSError as exc:
            raise UnsafeHTTPUrlError(f"URL host could not be resolved: {host}") from exc
        if not addresses:
            raise UnsafeHTTPUrlError(f"URL host did not resolve: {host}") from None
        for address in addresses:
            if _blocked_ip_address(address):
                raise UnsafeHTTPUrlError(f"URL resolves to a blocked address: {address}") from None
        return

    if _blocked_ip_address(host):
        raise UnsafeHTTPUrlError(f"URL host is a blocked address: {host}")


def is_safe_http_url(url: str, *, resolver: AddressResolver | None = None) -> bool:
    """Return whether ``url`` passes the shared outbound safety checks.

    By default this performs syntactic and IP-literal checks only; pass
    ``resolver=default_address_resolver`` for DNS-based blocking.
    """
    try:
        validate_safe_http_url(url, resolver=resolver)
    except UnsafeHTTPUrlError:
        return False
    return True


def resolve_safe_http_url(url: str, *, resolver: AddressResolver) -> tuple[str, int, str]:
    """Validate ``url`` and resolve its host to one safe IP literal.

    Returns ``(host, port, ip)`` where ``host`` is the canonical original
    hostname (or the IP literal when the URL already targets one), ``port`` is
    the effective destination port, and ``ip`` is a globally-routable address
    selected from the resolver's response. Every address returned by the
    resolver must pass :func:`_blocked_ip_address`; if any one fails, the call
    raises :class:`UnsafeHTTPUrlError`. This is the building block for binding
    the SSRF policy to the actual socket connection (DNS rebinding / TOCTOU
    protection): callers that resolve once with this helper and then connect to
    the returned IP cannot be tricked by a second DNS lookup that returns a
    different (blocked) address.
    """
    host, port = _validate_parsed_http_url(url)
    host_is_ip_literal = True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        host_is_ip_literal = False
    if host_is_ip_literal:
        if _blocked_ip_address(host):
            raise UnsafeHTTPUrlError(f"URL host is a blocked address: {host}")
        return host, port, host
    try:
        addresses = tuple(resolver(host, port))
    except OSError as exc:
        raise UnsafeHTTPUrlError(f"URL host could not be resolved: {host}") from exc
    if not addresses:
        raise UnsafeHTTPUrlError(f"URL host did not resolve: {host}") from None
    for address in addresses:
        if _blocked_ip_address(address):
            raise UnsafeHTTPUrlError(f"URL resolves to a blocked address: {address}") from None
    return host, port, addresses[0]


def _ip_url_replacement(url: str, ip: str) -> str:
    """Return ``url`` with its host replaced by ``ip`` (bracketed when IPv6)."""
    parsed = urlparse(url)
    port_suffix = f":{parsed.port}" if parsed.port is not None else ""
    new_netloc = f"[{ip}]{port_suffix}" if ":" in ip else f"{ip}{port_suffix}"
    return parsed._replace(netloc=new_netloc).geturl()


def _host_header_value(original_host: str, scheme: str, port: int) -> str:
    """Return the RFC 7230 §5.4 authority form for the ``Host`` header.

    Includes the port when it is not the scheme default (RFC-strict servers
    and virtual hosts on non-standard ports rely on this), brackets bare IPv6
    literals, and otherwise returns the bare hostname.
    """
    default_port = 443 if scheme == "https" else 80
    bracketed_host = original_host
    try:
        ip_obj = ipaddress.ip_address(original_host)
    except ValueError:
        ip_obj = None
    if isinstance(ip_obj, ipaddress.IPv6Address):
        bracketed_host = f"[{original_host}]"
    if port == default_port:
        return bracketed_host
    return f"{bracketed_host}:{port}"


def _build_pinned_request_kwargs(
    *, original_host: str, scheme: str, port: int, request_kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Return a copy of ``request_kwargs`` with the original Host header and TLS SNI preserved.

    The connection is made to a URL whose host has been replaced by a checked
    IP literal; for HTTP correctness the original hostname is restored as the
    ``Host`` header (including the port when it is not the scheme default,
    per RFC 7230 §5.4), and for HTTPS the same hostname (without port) is
    forwarded as the TLS SNI / certificate-verification hostname through
    ``extensions["sni_hostname"]``.
    """
    new_kwargs = dict(request_kwargs)
    headers = dict(new_kwargs.get("headers") or {})
    for key in [k for k in headers if k.lower() == "host"]:
        del headers[key]
    headers["Host"] = _host_header_value(original_host, scheme, port)
    new_kwargs["headers"] = headers
    if scheme == "https":
        extensions = dict(new_kwargs.get("extensions") or {})
        extensions.setdefault("sni_hostname", original_host)
        new_kwargs["extensions"] = extensions
    return new_kwargs


def request_with_webmention_redirects(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_bytes: int | None = None,
    **request_kwargs: Any,
) -> RedirectedResponse:
    """Run a safe HTTP request with explicit bounded Webmention redirect handling.

    Redirects are followed only to absolute ``http`` and ``https`` URLs after
    resolving relative ``Location`` values against the URL that produced the
    redirect. The original method and request body are preserved across all
    followed redirects, including Webmention endpoint ``POST`` delivery. Each
    request URL and redirect target is screened with the shared SSRF checks.

    When ``max_bytes`` is provided the response is streamed and decoded bytes are
    bounded so a hostile Webmention endpoint cannot force the sender to buffer
    an unbounded reply; oversized responses surface as
    :class:`HTTPResponseTooLarge`.
    """
    return request_with_safe_redirects(client, method, url, max_bytes=max_bytes, **request_kwargs)


def request_with_safe_redirects(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    resolver: AddressResolver | None = default_address_resolver,
    max_bytes: int | None = None,
    pin_to_resolved_ip: bool = True,
    **request_kwargs: Any,
) -> RedirectedResponse:
    """Run an HTTP request after SSRF checks, re-checking every redirect.

    When ``max_bytes`` is provided, the request is routed through streaming so the
    decoded body is bounded before it is fully buffered, giving callers
    decompression-bomb protection on the non-streaming helper too.

    When ``pin_to_resolved_ip`` is True (default) and a ``resolver`` is
    configured, the URL host is resolved once and the request is connected to
    the resolved IP address while the original hostname is preserved as the
    ``Host`` header and the TLS SNI / certificate-verification hostname.
    This binds the SSRF safety decision to the actual socket connection so a
    DNS rebinding host cannot resolve to a public address during validation
    and to a private address during the connect.
    """
    if max_bytes is not None:
        return stream_with_safe_redirects(
            client,
            method,
            url,
            max_bytes=max_bytes,
            resolver=resolver,
            pin_to_resolved_ip=pin_to_resolved_ip,
            **request_kwargs,
        )

    current_url = url
    request_method = getattr(client, method.lower())

    for redirects_followed in range(WEBMENTION_MAX_REDIRECTS + 1):
        try:
            connect_url, connect_kwargs = _prepare_pinned_request(
                current_url,
                resolver=resolver,
                pin_to_resolved_ip=pin_to_resolved_ip,
                request_kwargs=request_kwargs,
            )
        except UnsafeHTTPUrlError as exc:
            if redirects_followed == 0:
                raise
            raise WebmentionRedirectError(f"unsupported Webmention redirect target: {current_url}") from exc
        response = request_method(connect_url, **connect_kwargs)
        if response.status_code not in WEBMENTION_REDIRECT_STATUS_CODES:
            return RedirectedResponse(response=response, final_url=current_url)

        location = response.headers.get("location") or response.headers.get("Location")
        if not location:
            return RedirectedResponse(response=response, final_url=current_url)

        if redirects_followed >= WEBMENTION_MAX_REDIRECTS:
            raise WebmentionRedirectError(f"exceeded {WEBMENTION_MAX_REDIRECTS} Webmention redirects")

        next_url = urljoin(current_url, location)
        try:
            validate_safe_http_url(next_url, resolver=resolver)
        except UnsafeHTTPUrlError as exc:
            raise WebmentionRedirectError(f"unsupported Webmention redirect target: {next_url}") from exc

        current_url = next_url

    raise WebmentionRedirectError(f"exceeded {WEBMENTION_MAX_REDIRECTS} Webmention redirects")


def _prepare_pinned_request(
    url: str,
    *,
    resolver: AddressResolver | None,
    pin_to_resolved_ip: bool,
    request_kwargs: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Validate ``url`` and, when pinning is enabled, return an IP-rewritten URL plus updated kwargs.

    When ``pin_to_resolved_ip`` is False, behavior matches the legacy
    pre-flight: validate (with resolver if given) and return the URL/kwargs
    unchanged. When True and a resolver is configured, the host is resolved to
    one safe IP, the URL host is replaced with that IP literal, the ``Host``
    header is set to the original hostname, and HTTPS requests gain
    ``extensions["sni_hostname"]`` so TLS SNI / certificate verification still
    target the original hostname.
    """
    if not pin_to_resolved_ip or resolver is None:
        validate_safe_http_url(url, resolver=resolver)
        return url, request_kwargs

    host, port, ip = resolve_safe_http_url(url, resolver=resolver)
    if ip == host:
        return url, request_kwargs

    parsed_scheme = urlparse(url).scheme.lower()
    pinned_url = _ip_url_replacement(url, ip)
    pinned_kwargs = _build_pinned_request_kwargs(
        original_host=host, scheme=parsed_scheme, port=port, request_kwargs=request_kwargs
    )
    return pinned_url, pinned_kwargs


def _decoded_response_content_with_limit(response: httpx.Response, *, max_bytes: int | None) -> bytes:
    """Read decoded response bytes while enforcing ``max_bytes``."""
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if max_bytes is not None and total > max_bytes:
            raise HTTPResponseTooLarge(f"response exceeded {max_bytes} decoded bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _copy_response_with_content(response: httpx.Response, content: bytes) -> httpx.Response:
    """Return a standalone response with already-decoded ``content``."""
    headers = httpx.Headers(response.headers)
    for header_name in ("content-encoding", "content-length"):
        if header_name in headers:
            del headers[header_name]
    copied = httpx.Response(
        response.status_code,
        headers=headers,
        content=content,
        request=response.request,
        extensions=response.extensions,
    )
    if response.encoding is not None:
        copied.encoding = response.encoding
    return copied


def stream_with_safe_redirects(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_bytes: int | None,
    resolver: AddressResolver | None = default_address_resolver,
    pin_to_resolved_ip: bool = True,
    **request_kwargs: Any,
) -> RedirectedResponse:
    """Stream an HTTP response after SSRF checks, re-checking every redirect.

    The original method and request body are intentionally preserved across all
    redirect statuses, including 301/302/303 for Webmention endpoint delivery
    compatibility. This differs from browser-style POST redirect rewriting.

    See :func:`request_with_safe_redirects` for the ``pin_to_resolved_ip``
    semantics. The same logic applies for streamed requests.
    """
    current_url = url

    for redirects_followed in range(WEBMENTION_MAX_REDIRECTS + 1):
        try:
            connect_url, connect_kwargs = _prepare_pinned_request(
                current_url,
                resolver=resolver,
                pin_to_resolved_ip=pin_to_resolved_ip,
                request_kwargs=request_kwargs,
            )
        except UnsafeHTTPUrlError as exc:
            if redirects_followed == 0:
                raise
            raise WebmentionRedirectError(f"unsupported Webmention redirect target: {current_url}") from exc
        with client.stream(method, connect_url, **connect_kwargs) as response:
            if response.status_code not in WEBMENTION_REDIRECT_STATUS_CODES:
                content = _decoded_response_content_with_limit(response, max_bytes=max_bytes)
                return RedirectedResponse(
                    response=_copy_response_with_content(response, content),
                    final_url=current_url,
                )

            location = response.headers.get("location") or response.headers.get("Location")
            if not location:
                return RedirectedResponse(response=_copy_response_with_content(response, b""), final_url=current_url)

        if redirects_followed >= WEBMENTION_MAX_REDIRECTS:
            raise WebmentionRedirectError(f"exceeded {WEBMENTION_MAX_REDIRECTS} Webmention redirects")

        next_url = urljoin(current_url, location)
        try:
            validate_safe_http_url(next_url, resolver=resolver)
        except UnsafeHTTPUrlError as exc:
            raise WebmentionRedirectError(f"unsupported Webmention redirect target: {next_url}") from exc

        current_url = next_url

    raise WebmentionRedirectError(f"exceeded {WEBMENTION_MAX_REDIRECTS} Webmention redirects")


def response_text_with_limit(response: httpx.Response, *, max_bytes: int | None) -> str:
    """Return decoded response text, aborting if decoded bytes exceed ``max_bytes``."""
    if max_bytes is None:
        return response.text

    if isinstance(response, httpx.Response):
        content = _decoded_response_content_with_limit(response, max_bytes=max_bytes)
        encoding = response.encoding or "utf-8"
        return content.decode(encoding, errors="replace")

    text = response.text
    if len(text.encode("utf-8")) > max_bytes:
        raise HTTPResponseTooLarge(f"response exceeded {max_bytes} decoded bytes")
    return text
