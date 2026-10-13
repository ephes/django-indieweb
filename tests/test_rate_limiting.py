from __future__ import annotations

import hashlib
import time
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.urls import reverse

from indieweb import models
from indieweb.rate_limit import (
    UNSUPPORTED_METHOD_BUCKET,
    _cache_key,
    _retry_after,
    check_rate_limit,
    get_rate_limit_config,
)
from indieweb.views import TokenAuthMixin


@pytest.fixture(autouse=True)
def clear_rate_limit_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="ratelimit", email="ratelimit@example.org", password="password")


@pytest.fixture
def token(user):
    return models.Token.objects.create(
        me="https://example.org",
        client_id="https://client.example.org",
        scope="create media update",
        owner=user,
    )


@pytest.fixture
def auth(user):
    return models.Auth.objects.create(
        owner=user,
        key="rateauthkey",
        state="state",
        me="https://example.org",
        scope="create",
        client_id="https://client.example.org",
        redirect_uri="https://client.example.org/callback",
    )


def _valid_webmention_payload() -> dict[str, str]:
    site = Site.objects.get_current()
    return {
        "source": "https://source.example.org/reply",
        "target": f"https://{site.domain}/post",
    }


@pytest.mark.django_db
def test_rate_limiting_is_disabled_by_default(client):
    url = reverse("indieweb:token")

    first = client.post(url, data={"code": "wrong", "client_id": "https://client.example.org"})
    second = client.post(url, data={"code": "wrong", "client_id": "https://client.example.org"})

    assert first.status_code == 400
    assert second.status_code == 400
    assert "Retry-After" not in second


@pytest.mark.django_db
def test_configured_token_limit_returns_429_with_retry_after(client, settings):
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": 1, "window": 60}}
    url = reverse("indieweb:token")

    allowed = client.post(url, data={"code": "wrong", "client_id": "https://client.example.org"})
    limited = client.post(url, data={"code": "wrong", "client_id": "https://client.example.org"})

    assert allowed.status_code == 400
    assert limited.status_code == 429
    assert limited.content.decode("utf-8") == "rate limit exceeded"
    assert 1 <= int(limited["Retry-After"]) <= 60


def test_rate_limit_retry_after_falls_back_to_window_when_reset_key_is_missing():
    counter_key = "indieweb:rate-limit:test:missing-reset"
    cache.delete(f"{counter_key}:reset")

    assert _retry_after(counter_key, time.time(), fallback_window=60) == 60


def test_rate_limit_cache_key_uses_secret_keyed_hmac(settings):
    settings.SECRET_KEY = "first-secret"
    key = _cache_key("token", "POST", "203.0.113.7")
    bare_digest = hashlib.sha256(b"203.0.113.7").hexdigest()

    settings.SECRET_KEY = "second-secret"
    changed_secret_key = _cache_key("token", "POST", "203.0.113.7")

    assert bare_digest not in key
    assert ":v2:" in key
    assert key != changed_secret_key


@pytest.mark.django_db
def test_successful_token_request_under_limit_keeps_existing_response(client, settings, auth):
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": 2, "window": 60}}
    url = reverse("indieweb:token")

    response = client.post(
        url,
        data={
            "code": auth.key,
            "client_id": auth.client_id,
            "redirect_uri": auth.redirect_uri,
        },
    )

    assert response.status_code == 201
    assert response["Content-Type"] == "application/x-www-form-urlencoded"
    assert b"access_token=" in response.content


@pytest.mark.django_db
def test_configured_token_introspection_limit_returns_429(client, settings, token):
    settings.INDIEWEB_RATE_LIMITS = {"token_introspection": {"limit": 1, "window": 60}}
    url = reverse("indieweb:token-introspection")

    allowed = client.post(url, data={"token": "wrong"}, Authorization=f"Bearer {token.key}")
    limited = client.post(url, data={"token": "wrong"}, Authorization=f"Bearer {token.key}")

    assert allowed.status_code == 200
    assert allowed.json() == {"active": False}
    assert limited.status_code == 429
    assert limited.content.decode("utf-8") == "rate limit exceeded"


@pytest.mark.django_db
def test_limits_are_scoped_by_endpoint_key(client, settings, token):
    settings.INDIEWEB_RATE_LIMITS = {
        "token": {"limit": 1, "window": 60},
        "token_introspection": {"limit": 1, "window": 60},
        "micropub": {"limit": 1, "window": 60},
    }
    token_url = reverse("indieweb:token")
    introspection_url = reverse("indieweb:token-introspection")
    micropub_url = reverse("indieweb:micropub")

    token_response = client.post(token_url, data={"code": "wrong", "client_id": "https://client.example.org"})
    introspection_response = client.post(
        introspection_url,
        data={"token": token.key},
        Authorization=f"Bearer {token.key}",
    )
    micropub_response = client.get(micropub_url, Authorization=f"Bearer {token.key}")
    limited_token_response = client.post(
        token_url,
        data={"code": "wrong", "client_id": "https://client.example.org"},
    )

    assert token_response.status_code == 400
    assert introspection_response.status_code == 200
    assert micropub_response.status_code == 200
    assert limited_token_response.status_code == 429


@pytest.mark.django_db
def test_limits_are_scoped_by_remote_addr(client, settings):
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": 1, "window": 60}}
    url = reverse("indieweb:token")
    payload = {"code": "wrong", "client_id": "https://client.example.org"}

    first = client.post(url, data=payload, REMOTE_ADDR="203.0.113.1")
    same_client = client.post(url, data=payload, REMOTE_ADDR="203.0.113.1")
    other_client = client.post(url, data=payload, REMOTE_ADDR="203.0.113.2")

    assert first.status_code == 400
    assert same_client.status_code == 429
    assert other_client.status_code == 400


@pytest.mark.django_db
def test_x_forwarded_for_is_not_trusted_by_default(client, settings):
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": 1, "window": 60}}
    url = reverse("indieweb:token")
    payload = {"code": "wrong", "client_id": "https://client.example.org"}

    first = client.post(
        url,
        data=payload,
        REMOTE_ADDR="203.0.113.1",
        HTTP_X_FORWARDED_FOR="198.51.100.1",
    )
    spoofed_forwarded_for = client.post(
        url,
        data=payload,
        REMOTE_ADDR="203.0.113.1",
        HTTP_X_FORWARDED_FOR="198.51.100.2",
    )

    assert first.status_code == 400
    assert spoofed_forwarded_for.status_code == 429


@pytest.mark.django_db
def test_malformed_rate_limit_config_is_ignored(client, settings):
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": "bad", "window": 60}}
    url = reverse("indieweb:token")

    first = client.post(url, data={"code": "wrong", "client_id": "https://client.example.org"})
    second = client.post(url, data={"code": "wrong", "client_id": "https://client.example.org"})

    assert get_rate_limit_config("token") is None
    assert first.status_code == 400
    assert second.status_code == 400


@pytest.mark.django_db
def test_micropub_limit_short_circuits_before_token_authentication(client, settings):
    settings.INDIEWEB_RATE_LIMITS = {"micropub": {"limit": 1, "window": 60}}
    url = reverse("indieweb:micropub")

    with patch.object(TokenAuthMixin, "authenticated", return_value=False) as authenticated:
        first = client.get(url, Authorization="Bearer wrong")
        second = client.get(url, Authorization="Bearer wrong")

    assert first.status_code == 401
    assert second.status_code == 429
    assert authenticated.call_count == 1


@pytest.mark.django_db
def test_webmention_limit_short_circuits_before_processing(client, settings):
    settings.INDIEWEB_RATE_LIMITS = {"webmention": {"limit": 1, "window": 60}}
    url = reverse("indieweb:webmention")
    payload = _valid_webmention_payload()

    with patch("indieweb.views.WebmentionProcessor") as processor_class:
        processor = MagicMock()
        processor_class.return_value = processor
        processor.process_webmention.return_value = models.Webmention(id=123)

        first = client.post(url, data=payload)
        second = client.post(url, data=payload)

    assert first.status_code == 201
    assert second.status_code == 429
    processor.process_webmention.assert_called_once_with(
        payload["source"],
        payload["target"],
        vouch_url=None,
    )


@pytest.mark.django_db
def test_auth_media_and_webmention_status_endpoint_keys_are_limited(client, settings):
    webmention = models.Webmention.objects.create(
        source_url="https://source.example.org/post",
        target_url="https://example.com/post",
        status="verified",
    )
    settings.INDIEWEB_RATE_LIMITS = {
        "auth": {"limit": 1, "window": 60},
        "media": {"limit": 1, "window": 60},
        "webmention_status": {"limit": 1, "window": 60},
    }
    auth_url = reverse("indieweb:auth")
    media_url = reverse("indieweb:media")
    status_url = reverse("indieweb:webmention-status", args=[webmention.status_token])

    assert client.get(auth_url).status_code == 302
    assert client.get(auth_url).status_code == 429

    assert client.post(media_url, data={}).status_code == 401
    assert client.post(media_url, data={}).status_code == 429

    assert client.get(media_url).status_code == 401
    assert client.get(media_url).status_code == 429

    assert client.get(status_url).status_code == 200
    assert client.get(status_url).status_code == 429


@pytest.mark.django_db
def test_websub_callback_endpoint_key_is_limited(client, settings):
    subscription = models.WebSubSubscription.objects.create(
        hub_url="https://hub.example/sub",
        topic_url="https://source.example/feed",
        state=models.WebSubSubscription.STATE_ACTIVE,
    )
    settings.INDIEWEB_RATE_LIMITS = {"websub_callback": {"limit": 1, "window": 60}}
    url = reverse("indieweb:websub-callback", args=[subscription.callback_token])
    headers = {"HTTP_LINK": f'<{subscription.topic_url}>; rel="self"'}

    assert client.post(url, data=b"<feed/>", content_type="application/atom+xml", **headers).status_code == 204
    assert client.post(url, data=b"<feed/>", content_type="application/atom+xml", **headers).status_code == 429


# ----------------------------------------------------------------------------
# Method buckets: implemented methods keep their documented per-method budget;
# every other method shares one bucket and one cache key.
# ----------------------------------------------------------------------------


def _counter(endpoint_key: str, bucket: str, identity: str = "127.0.0.1") -> int | None:
    return cache.get(_cache_key(endpoint_key, bucket, identity))


@pytest.mark.django_db
def test_unsupported_methods_share_one_bucket(client, settings):
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": 2, "window": 60}}
    url = reverse("indieweb:token")

    statuses = [client.generic(method, url).status_code for method in ("PROPFIND", "MKCOL", "INVENTED", "PUT")]

    assert statuses == [405, 405, 429, 429]
    assert _counter("token", UNSUPPORTED_METHOD_BUCKET) == 4
    for method in ("PROPFIND", "MKCOL", "INVENTED", "PUT"):
        assert _counter("token", method) is None


@pytest.mark.django_db
def test_unsupported_methods_do_not_multiply_the_allowance(client, settings):
    """Invented methods cannot each obtain a fresh allowance of rejected requests."""
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": 1, "window": 60}}
    url = reverse("indieweb:token")

    statuses = [client.generic(f"METHOD{index}", url).status_code for index in range(5)]

    assert statuses == [405, 429, 429, 429, 429]


@pytest.mark.django_db
def test_unsupported_method_bucket_is_separate_from_implemented_methods(client, settings):
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": 1, "window": 60}}
    url = reverse("indieweb:token")
    payload = {"code": "wrong", "client_id": "https://client.example.org"}

    assert client.generic("PROPFIND", url).status_code == 405
    assert client.generic("PROPFIND", url).status_code == 429
    assert client.post(url, data=payload).status_code == 400
    assert client.post(url, data=payload).status_code == 429
    assert _counter("token", "POST") == 2


@pytest.mark.django_db
def test_implemented_methods_keep_independent_budgets(client, settings):
    """The documented per-method budget is unchanged for methods the view implements."""
    settings.INDIEWEB_RATE_LIMITS = {"micropub": {"limit": 1, "window": 60}}
    url = reverse("indieweb:micropub")

    assert client.get(url).status_code == 401
    assert client.post(url).status_code == 401
    assert client.get(url).status_code == 429
    assert client.post(url).status_code == 429
    assert (_counter("micropub", "GET"), _counter("micropub", "POST")) == (2, 2)
    assert _counter("micropub", UNSUPPORTED_METHOD_BUCKET) is None


@pytest.mark.django_db
def test_method_buckets_are_case_insensitive(client, settings):
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": 5, "window": 60}}
    url = reverse("indieweb:token")

    client.generic("post", url)
    client.generic("propfind", url)

    assert _counter("token", "POST") == 1
    assert _counter("token", UNSUPPORTED_METHOD_BUCKET) == 1


# ----------------------------------------------------------------------------
# Counter eviction: a vanished counter is re-created with add/incr, never reset
# with an unconditional set that would discard other requests' increments.
# ----------------------------------------------------------------------------


class ScriptedCache:
    """In-memory cache whose ``incr`` can run a hook first, to script an interleaving."""

    def __init__(self):
        self.values: dict[str, object] = {}
        self.before_incr: list = []
        self.set_calls: list[str] = []

    def add(self, key, value, timeout=None):
        if key in self.values:
            return False
        self.values[key] = value
        return True

    def set(self, key, value, timeout=None):
        self.set_calls.append(key)
        self.values[key] = value

    def get(self, key, default=None):
        return self.values.get(key, default)

    def incr(self, key, delta=1):
        if self.before_incr:
            self.before_incr.pop(0)()
        if key not in self.values:
            raise ValueError(f"Key {key!r} not found")
        self.values[key] += delta
        return self.values[key]


@pytest.fixture
def scripted_cache(settings):
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": 5, "window": 60}}
    scripted = ScriptedCache()
    with patch("indieweb.rate_limit.cache", scripted):
        yield scripted


def _request(method: str = "POST", remote_addr: str = "203.0.113.9") -> MagicMock:
    request = MagicMock()
    request.method = method
    request.META = {"REMOTE_ADDR": remote_addr}
    return request


def test_evicted_counter_retry_keeps_a_concurrent_increment(scripted_cache):
    """Eviction between add and incr, then another request counts first: both are counted."""
    counter_key = _cache_key("token", "POST", "203.0.113.9")

    def evict():
        del scripted_cache.values[counter_key]

    def other_request_recreates_and_counts():
        scripted_cache.values.pop(counter_key, None)
        scripted_cache.add(counter_key, 0, 60)
        scripted_cache.values[counter_key] += 1

    scripted_cache.before_incr.extend([evict, other_request_recreates_and_counts])

    result = check_rate_limit(_request(), "token")

    # Attempt 1: the counter is evicted before incr. Attempt 2: another request has
    # re-created it with one increment before ours. Neither increment is lost.
    assert result.allowed is True
    assert scripted_cache.values[counter_key] == 2
    assert counter_key not in scripted_cache.set_calls


def test_evicted_counter_is_recreated_with_a_matching_reset_time(scripted_cache):
    counter_key = _cache_key("token", "POST", "203.0.113.9")
    reset_key = f"{counter_key}:reset"
    scripted_cache.values[reset_key] = 1.0  # stale reset time left over from an evicted counter

    before = time.time()
    result = check_rate_limit(_request(), "token")

    assert result.allowed is True
    assert scripted_cache.values[counter_key] == 1
    assert before + 60 <= scripted_cache.values[reset_key] <= time.time() + 60


def test_existing_counter_keeps_its_reset_time(scripted_cache):
    counter_key = _cache_key("token", "POST", "203.0.113.9")
    check_rate_limit(_request(), "token")
    first_reset = scripted_cache.values[f"{counter_key}:reset"]

    check_rate_limit(_request(), "token")

    assert scripted_cache.values[counter_key] == 2
    assert scripted_cache.values[f"{counter_key}:reset"] == first_reset


def test_counter_that_cannot_be_stored_fails_closed(scripted_cache, caplog):
    counter_key = _cache_key("token", "POST", "203.0.113.9")
    scripted_cache.before_incr.extend([lambda: scripted_cache.values.pop(counter_key)] * 10)

    with caplog.at_level("WARNING", logger="indieweb.rate_limit"):
        result = check_rate_limit(_request(), "token")

    assert result.allowed is False
    assert result.retry_after == 60
    assert "could not be stored" in caplog.text
    assert counter_key not in scripted_cache.set_calls
    assert len(scripted_cache.before_incr) == 7  # exactly three bounded attempts


@pytest.mark.django_db
def test_endpoint_returns_429_when_the_counter_cannot_be_stored(client, settings):
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": 5, "window": 60}}

    with patch("indieweb.rate_limit.cache.incr", side_effect=ValueError("evicted")):
        response = client.post(reverse("indieweb:token"), data={"code": "wrong"})

    assert response.status_code == 429
    assert response["Retry-After"] == "60"


@pytest.mark.django_db
def test_dummy_cache_disables_rate_limiting_instead_of_rejecting(client, settings):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": 1, "window": 60}}
    url = reverse("indieweb:token")
    payload = {"code": "wrong", "client_id": "https://client.example.org"}

    statuses = [client.post(url, data=payload).status_code for _ in range(3)]

    assert statuses == [400, 400, 400]


@pytest.mark.parametrize("hops", [0, 1, 2])
def test_proxy_hops_select_client_bucket(settings, rf, hops):
    settings.INDIEWEB_RATE_LIMITS = {"auth": {"limit": 1, "window": 60}}
    settings.INDIEWEB_RATE_LIMIT_TRUSTED_PROXY_HOPS = hops

    def request(address, spoof="192.0.2.99"):
        chain = f"{spoof}, {address}" + (", 192.0.2.10" if hops == 2 else "")
        return rf.get("/", REMOTE_ADDR="192.0.2.1", HTTP_X_FORWARDED_FOR=chain)

    assert check_rate_limit(request("198.51.100.1"), "auth").allowed
    assert check_rate_limit(request("198.51.100.2"), "auth").allowed is (hops > 0)
    assert not check_rate_limit(request("198.51.100.1", spoof="192.0.2.98"), "auth").allowed


@pytest.mark.parametrize(
    "hops,header",
    [(1, "bad"), (2, "198.51.100.1"), (1, ""), (-1, "198.51.100.1"), (True, "198.51.100.1"), ("1", "198.51.100.1")],
)
def test_invalid_forwarded_identity_falls_back(settings, rf, hops, header):
    settings.INDIEWEB_RATE_LIMITS = {"auth": {"limit": 1, "window": 60}}
    settings.INDIEWEB_RATE_LIMIT_TRUSTED_PROXY_HOPS = hops
    request = rf.get("/", REMOTE_ADDR="192.0.2.1", HTTP_X_FORWARDED_FOR=header)
    assert check_rate_limit(request, "auth").allowed
    assert not check_rate_limit(rf.get("/", REMOTE_ADDR="192.0.2.1"), "auth").allowed


@pytest.mark.parametrize("value", [True, -1, "1"])
def test_invalid_proxy_hops_logs_warning(settings, rf, caplog, value):
    settings.INDIEWEB_RATE_LIMITS = {"auth": {"limit": 1, "window": 60}}
    settings.INDIEWEB_RATE_LIMIT_TRUSTED_PROXY_HOPS = value
    assert check_rate_limit(rf.get("/"), "auth").allowed
    assert "Invalid INDIEWEB_RATE_LIMIT_TRUSTED_PROXY_HOPS" in caplog.text


def test_forwarded_ipv6_notation_uses_same_bucket(settings, rf):
    settings.INDIEWEB_RATE_LIMITS = {"auth": {"limit": 1, "window": 60}}
    settings.INDIEWEB_RATE_LIMIT_TRUSTED_PROXY_HOPS = 1
    assert check_rate_limit(rf.get("/", HTTP_X_FORWARDED_FOR="2001:DB8::1"), "auth").allowed
    assert not check_rate_limit(rf.get("/", HTTP_X_FORWARDED_FOR="2001:db8:0:0:0:0:0:1"), "auth").allowed
