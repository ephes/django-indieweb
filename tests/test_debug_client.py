"""The root ``client.py`` debug helper must never print credentials."""

import importlib.util
from pathlib import Path
from urllib.parse import urlencode

import pytest

BASE_URL = "http://dev.test/"
SESSION_COOKIE = "session-cookie-SECRET-7f3a"
CSRF_COOKIE = "csrf-cookie-SECRET-91bc"
AUTH_CODE = "auth-code-SECRET-55de"
ACCESS_TOKEN = "access-token-SECRET-c0ffee"
PASSWORD = "password-SECRET-4242"
SECRETS = (SESSION_COOKIE, CSRF_COOKIE, AUTH_CODE, ACCESS_TOKEN, PASSWORD)


class FakeResponse:
    def __init__(self, url, content=b"", status_code=200):
        self.url = url
        self.content = content
        self.status_code = status_code
        self.cookies = {"csrftoken": CSRF_COOKIE, "sessionid": SESSION_COOKIE}


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, None))
        if "indieweb/auth/" in url:
            query = urlencode({"code": AUTH_CODE, "state": "1234567890foo", "me": f"{BASE_URL}/jochen/"})
            return FakeResponse(f"{BASE_URL}?{query}")
        return FakeResponse(url)

    def post(self, url, payload, **kwargs):
        self.calls.append(("POST", url, payload))
        if url.endswith("indieweb/token/"):
            body = urlencode({"access_token": ACCESS_TOKEN, "me": f"{BASE_URL}/jochen/", "scope": "post"})
            return FakeResponse(url, body.encode("utf-8"), status_code=201)
        if url.endswith("indieweb/auth/"):
            return FakeResponse(url, urlencode({"me": f"{BASE_URL}/jochen/"}).encode("utf-8"))
        return FakeResponse(url)

    def payload_for(self, suffix):
        return next(payload for method, url, payload in self.calls if method == "POST" and url.endswith(suffix))


@pytest.fixture
def debug_client():
    path = Path(__file__).resolve().parent.parent / "client.py"
    spec = importlib.util.spec_from_file_location("indieweb_debug_client", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_session(debug_client, monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(debug_client.requests, "Session", lambda: session)
    monkeypatch.setenv("USERNAME", "jochen")
    monkeypatch.setenv("PASSWORD", PASSWORD)
    monkeypatch.setenv("BASE_URL", BASE_URL)
    return session


def test_debug_client_flow_prints_no_credentials(debug_client, fake_session, capsys):
    debug_client.main([])

    captured = capsys.readouterr()
    output = captured.out + captured.err
    for secret in SECRETS:
        assert secret not in output
    assert "login: 200" in output
    assert "token: 201" in output
    assert f"auth code fingerprint: {debug_client.fingerprint(AUTH_CODE)}" in output
    assert f"access token fingerprint: {debug_client.fingerprint(ACCESS_TOKEN)}" in output
    assert "auth redirect: 200 params: ['code', 'me', 'state']" in output


def test_debug_client_flow_still_passes_credentials_to_the_next_call(debug_client, fake_session, capsys):
    debug_client.main([])

    assert fake_session.payload_for("accounts/login/")["csrfmiddlewaretoken"] == CSRF_COOKIE
    assert fake_session.payload_for("indieweb/token/")["code"] == AUTH_CODE
    assert fake_session.payload_for("indieweb/micropub/")["Authorization"] == ACCESS_TOKEN
    assert fake_session.payload_for("indieweb/auth/")["code"] == AUTH_CODE


def test_fingerprint_is_stable_and_does_not_contain_the_secret(debug_client):
    first = debug_client.fingerprint(ACCESS_TOKEN)

    assert first == debug_client.fingerprint(ACCESS_TOKEN)
    assert first != debug_client.fingerprint(AUTH_CODE)
    assert len(first) == 12
    assert ACCESS_TOKEN not in first
