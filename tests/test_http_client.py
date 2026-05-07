import httpx
import pytest

from indieweb.http_client import (
    HTTPResponseTooLarge,
    UnsafeHTTPUrlError,
    WebmentionRedirectError,
    request_with_safe_redirects,
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
        if str(request.url) == "https://example.com/post":
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
    assert [str(request.url) for request in requests] == [
        "https://example.com/post",
        "https://example.com/final",
    ]
