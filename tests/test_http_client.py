import httpx
import pytest

from indieweb.http_client import (
    HTTPResponseTooLarge,
    UnsafeHTTPUrlError,
    WebmentionRedirectError,
    request_with_safe_redirects,
    request_with_webmention_redirects,
    resolve_safe_http_url,
    response_text_with_limit,
    stream_with_safe_redirects,
    validate_safe_http_url,
)


def public_resolver(host: str, port: int) -> tuple[str, ...]:
    return ("93.184.216.34",)


def private_resolver(host: str, port: int) -> tuple[str, ...]:
    return ("10.0.0.5",)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "ftp://example.com/file",
        "http://user@example.com/",
        "http://[broken",
    ],
)
def test_validate_safe_http_url_rejects_unsafe_urls(url):
    with pytest.raises(UnsafeHTTPUrlError):
        validate_safe_http_url(url, resolver=public_resolver)


def test_validate_safe_http_url_rejects_dns_to_private_address():
    with pytest.raises(UnsafeHTTPUrlError, match="blocked address"):
        validate_safe_http_url("https://attacker.example/post", resolver=private_resolver)


def test_validate_safe_http_url_allows_public_ipv6_literal_without_dns():
    validate_safe_http_url("https://[2001:4860:4860::8888]/", resolver=private_resolver)


def test_request_with_safe_redirects_rejects_redirect_to_private_address():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(WebmentionRedirectError):
        request_with_safe_redirects(client, "GET", "https://example.com/post", resolver=public_resolver)

    assert len(requests) == 1


def test_request_with_safe_redirects_allows_public_mocked_url():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    result = request_with_safe_redirects(client, "GET", "https://example.com/post", resolver=public_resolver)

    assert result.response.status_code == 200
    assert result.final_url == "https://example.com/post"


def test_request_with_safe_redirects_enforces_max_bytes():
    """Passing max_bytes routes through streaming and raises HTTPResponseTooLarge."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 1024)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(HTTPResponseTooLarge):
        request_with_safe_redirects(
            client,
            "GET",
            "https://example.com/post",
            resolver=public_resolver,
            max_bytes=64,
        )


def test_request_with_safe_redirects_max_bytes_allows_small_responses():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    result = request_with_safe_redirects(
        client,
        "GET",
        "https://example.com/post",
        resolver=public_resolver,
        max_bytes=1024,
    )

    assert result.response.status_code == 200
    assert result.response.content == b"ok"


def test_response_text_with_limit_counts_decoded_bytes():
    response = httpx.Response(200, content=b"0123456789")

    with pytest.raises(HTTPResponseTooLarge):
        response_text_with_limit(response, max_bytes=4)


def test_request_with_webmention_redirects_enforces_max_bytes():
    """Webmention POST helper bounds decoded response bytes when max_bytes is set."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 4096)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(HTTPResponseTooLarge):
        request_with_webmention_redirects(
            client,
            "POST",
            "https://example.com/webmention",
            data={"source": "https://src/", "target": "https://dst/"},
            max_bytes=64,
            resolver=public_resolver,
        )


def test_request_with_webmention_redirects_allows_small_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, content=b"ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    result = request_with_webmention_redirects(
        client,
        "POST",
        "https://example.com/webmention",
        data={"source": "https://src/", "target": "https://dst/"},
        max_bytes=4096,
        resolver=public_resolver,
    )

    assert result.response.status_code == 202
    assert result.response.content == b"ok"


def test_stream_with_safe_redirects_aborts_while_reading_chunks():
    chunks_read = 0

    class CountingStream(httpx.SyncByteStream):
        def __iter__(self):
            nonlocal chunks_read
            for chunk in (b"1234", b"5678", b"90", b"never-read"):
                chunks_read += 1
                yield chunk

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=CountingStream())

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(HTTPResponseTooLarge):
        stream_with_safe_redirects(
            client,
            "GET",
            "https://example.com/post",
            max_bytes=5,
            resolver=public_resolver,
        )

    assert chunks_read == 2


def test_stream_with_safe_redirects_rechecks_redirect_target():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(WebmentionRedirectError):
        stream_with_safe_redirects(
            client,
            "GET",
            "https://example.com/post",
            max_bytes=1024,
            resolver=public_resolver,
        )

    assert len(requests) == 1


def test_stream_with_safe_redirects_allows_public_redirect():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/post":
            return httpx.Response(302, headers={"Location": "https://example.com/final"})
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    result = stream_with_safe_redirects(
        client,
        "GET",
        "https://example.com/post",
        max_bytes=1024,
        resolver=public_resolver,
    )

    assert result.response.status_code == 200
    assert result.response.text == "ok"
    assert result.final_url == "https://example.com/final"
    # Pinning rewrites the connection URL host to the resolved IP literal but
    # preserves the original hostname in the Host header and TLS SNI.
    assert [request.url.host for request in requests] == ["93.184.216.34", "93.184.216.34"]
    assert [request.headers["host"] for request in requests] == ["example.com", "example.com"]
    assert [request.url.path for request in requests] == ["/post", "/final"]


def test_resolve_safe_http_url_returns_safe_address():
    host, port, ip = resolve_safe_http_url("https://example.com/", resolver=public_resolver)
    assert host == "example.com"
    assert port == 443
    assert ip == "93.184.216.34"


def test_resolve_safe_http_url_passes_through_ip_literal():
    host, port, ip = resolve_safe_http_url("https://93.184.216.34/", resolver=private_resolver)
    assert host == "93.184.216.34"
    assert port == 443
    assert ip == "93.184.216.34"


def test_resolve_safe_http_url_rejects_dns_to_private():
    with pytest.raises(UnsafeHTTPUrlError, match="blocked address"):
        resolve_safe_http_url("https://attacker.example/", resolver=private_resolver)


def test_resolve_safe_http_url_rejects_private_ip_literal():
    with pytest.raises(UnsafeHTTPUrlError, match="blocked address"):
        resolve_safe_http_url("https://10.0.0.5/", resolver=public_resolver)


def test_request_with_safe_redirects_pins_connection_to_resolved_ip():
    """Production callers connect to the resolved IP and preserve the original Host header."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    result = request_with_safe_redirects(
        client,
        "GET",
        "https://example.com/post",
        resolver=public_resolver,
    )

    assert result.response.status_code == 200
    assert result.final_url == "https://example.com/post"
    assert len(requests) == 1
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "example.com"
    assert requests[0].extensions.get("sni_hostname") == "example.com"


def test_request_with_safe_redirects_skips_pinning_for_ip_literal_url():
    """When the URL already targets an IP literal, no rewrite is needed."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    request_with_safe_redirects(
        client,
        "GET",
        "https://93.184.216.34/post",
        resolver=public_resolver,
    )

    assert requests[0].url.host == "93.184.216.34"
    # No SNI override required when the original URL already targets an IP literal.
    assert "sni_hostname" not in requests[0].extensions


def test_request_with_safe_redirects_pin_to_resolved_ip_can_be_disabled():
    """Tests and callers that need the legacy hostname-on-the-wire behavior can opt out."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    request_with_safe_redirects(
        client,
        "GET",
        "https://example.com/post",
        resolver=public_resolver,
        pin_to_resolved_ip=False,
    )

    assert requests[0].url.host == "example.com"
    assert "sni_hostname" not in requests[0].extensions


def test_request_with_safe_redirects_resists_dns_rebinding():
    """A rebinding resolver returning a private address on the second lookup is rejected.

    Each redirect hop runs the resolver again, so a rebinding host that is
    public during the first request and private during the redirect target's
    pre-flight is caught before any second connection is attempted.
    """
    call_count = {"value": 0}

    def rebinding_resolver(host: str, port: int) -> tuple[str, ...]:
        call_count["value"] += 1
        # First two calls (initial + redirect target preflight) succeed; later calls
        # rebind to a private address.
        if call_count["value"] >= 3:
            return ("10.0.0.5",)
        return ("93.184.216.34",)

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://example.com/two"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(WebmentionRedirectError):
        request_with_safe_redirects(
            client,
            "GET",
            "https://example.com/one",
            resolver=rebinding_resolver,
        )

    # Only the first hop's connection happened; the rebinding lookup on the
    # second hop blocked the second connection before it was attempted.
    assert len(requests) == 1
    assert requests[0].url.host == "93.184.216.34"
    assert call_count["value"] >= 3


def test_request_with_safe_redirects_preserves_port_in_host_header():
    """Non-default ports must be preserved in the Host header (RFC 7230 §5.4)."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    request_with_safe_redirects(
        client,
        "GET",
        "https://example.com:8443/post",
        resolver=public_resolver,
    )

    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].url.port == 8443
    assert requests[0].headers["host"] == "example.com:8443"
    # SNI and certificate verification target the bare hostname, no port.
    assert requests[0].extensions.get("sni_hostname") == "example.com"


def test_request_with_safe_redirects_omits_default_port_from_host_header():
    """Default ports for the scheme must NOT appear in the Host header."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    request_with_safe_redirects(
        client,
        "GET",
        "https://example.com:443/post",
        resolver=public_resolver,
    )

    assert requests[0].headers["host"] == "example.com"


def test_stream_with_safe_redirects_rejects_dns_to_private_address():
    """A host whose DNS resolves only to private addresses is rejected before the connection."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(UnsafeHTTPUrlError, match="blocked address"):
        stream_with_safe_redirects(
            client,
            "GET",
            "https://attacker.example/",
            max_bytes=1024,
            resolver=private_resolver,
        )

    assert requests == []


def test_stream_with_safe_redirects_rejects_private_ip_literal():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(UnsafeHTTPUrlError, match="blocked address"):
        stream_with_safe_redirects(
            client,
            "GET",
            "http://10.0.0.5/admin",
            max_bytes=1024,
            resolver=public_resolver,
        )

    assert requests == []


def test_stream_with_safe_redirects_rejects_redirect_to_private_under_pinning():
    """Redirect targets are re-validated and reject DNS-to-private addresses on every hop."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://internal.attacker.example/"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    def split_resolver(host: str, port: int) -> tuple[str, ...]:
        if host == "example.com":
            return ("93.184.216.34",)
        return ("10.0.0.5",)

    with pytest.raises(WebmentionRedirectError):
        stream_with_safe_redirects(
            client,
            "GET",
            "https://example.com/post",
            max_bytes=1024,
            resolver=split_resolver,
        )

    assert len(requests) == 1
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "example.com"


def test_stream_with_safe_redirects_pins_https_sni_to_original_host():
    """HTTPS streamed requests forward the original hostname as TLS SNI."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    stream_with_safe_redirects(
        client,
        "GET",
        "https://example.com/post",
        max_bytes=1024,
        resolver=public_resolver,
    )

    assert requests[0].extensions.get("sni_hostname") == "example.com"
    assert requests[0].headers["host"] == "example.com"
    assert requests[0].url.host == "93.184.216.34"


def test_stream_with_safe_redirects_does_not_set_sni_for_http_scheme():
    """Plain HTTP requests do not need a TLS SNI override."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    stream_with_safe_redirects(
        client,
        "GET",
        "http://example.com/post",
        max_bytes=1024,
        resolver=public_resolver,
    )

    assert "sni_hostname" not in requests[0].extensions
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "example.com"
