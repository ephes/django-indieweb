"""The root ``client.py`` debug helper must never print credentials."""

import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
import requests
from requests.adapters import BaseAdapter

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
    assert "Authorization" not in fake_session.payload_for("indieweb/micropub/")
    assert fake_session.payload_for("indieweb/auth/")["code"] == AUTH_CODE


def test_fingerprint_is_stable_and_does_not_contain_the_secret(debug_client):
    first = debug_client.fingerprint(ACCESS_TOKEN)

    assert first == debug_client.fingerprint(ACCESS_TOKEN)
    assert first != debug_client.fingerprint(AUTH_CODE)
    assert len(first) == 12
    assert ACCESS_TOKEN not in first


class RedirectAdapter(BaseAdapter):
    """Exercise Requests' real redirect machinery without opening a socket."""

    def __init__(self, target, status=307):
        self.target = target
        self.status = status
        self.calls = []

    def send(self, request, **kwargs):
        self.calls.append(request)
        response = requests.Response()
        response.request = request
        response.url = request.url
        response.status_code = 200
        response._content = b""
        response.cookies.set("csrftoken", CSRF_COOKIE)
        if request.method == "POST" or "indieweb/auth/" in request.url:
            response.status_code = self.status
            response.headers["Location"] = self.target
        return response

    def close(self):
        pass


def mount_adapter(debug_client, monkeypatch, adapter):
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    monkeypatch.setattr(debug_client.requests, "Session", lambda: session)
    return session


@pytest.mark.parametrize("status", [307, 308])
@pytest.mark.parametrize("target", ["http://other.test/", "http://dev.test:8081/", "https://dev.test/"])
@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("login", ()),
        ("logout", ()),
        ("post_auth", (AUTH_CODE,)),
        ("get_token", (AUTH_CODE,)),
        ("post_entry", (ACCESS_TOKEN,)),
    ],
)
def test_credential_posts_refuse_redirects(debug_client, monkeypatch, capsys, status, target, method, args):
    adapter = RedirectAdapter(target, status)
    mount_adapter(debug_client, monkeypatch, adapter)
    helper = debug_client.Client(BASE_URL, "synthetic", PASSWORD)

    with pytest.raises(ValueError, match="Debug client refused redirect") as exc:
        getattr(helper, method)(*args)

    assert all(request.url.startswith(BASE_URL) for request in adapter.calls)
    assert sum(request.method == "POST" for request in adapter.calls) == 1
    output = str(exc.value) + str(capsys.readouterr())
    assert not any(secret in output for secret in SECRETS)


def test_refused_login_stops_flow(debug_client, monkeypatch, capsys):
    adapter = RedirectAdapter("http://other.test/", 302)
    mount_adapter(debug_client, monkeypatch, adapter)
    monkeypatch.setenv("USERNAME", "synthetic")
    monkeypatch.setenv("PASSWORD", PASSWORD)
    monkeypatch.setenv("BASE_URL", BASE_URL)

    with pytest.raises(ValueError, match="Debug client refused redirect"):
        debug_client.main([])

    assert [request.method for request in adapter.calls] == ["GET", "POST"]
    assert not any(secret in str(capsys.readouterr()) for secret in SECRETS)


@pytest.mark.parametrize("status", [302, 303])
def test_login_accepts_same_origin_navigation_without_reposting(debug_client, monkeypatch, status):
    adapter = RedirectAdapter("/home/", status)
    mount_adapter(debug_client, monkeypatch, adapter)

    debug_client.Client(BASE_URL, "synthetic", PASSWORD).login()

    assert [request.method for request in adapter.calls] == ["GET", "POST"]


@pytest.mark.parametrize("target", ["http://other.test/", "http://dev.test:81/", "https://dev.test/"])
def test_auth_navigation_stays_on_credential_origin(debug_client, monkeypatch, target):
    adapter = RedirectAdapter(target, 302)
    mount_adapter(debug_client, monkeypatch, adapter)

    with pytest.raises(ValueError, match="Debug client refused redirect"):
        debug_client.Client(BASE_URL, "synthetic", PASSWORD).get_auth()

    assert len(adapter.calls) == 1


@pytest.mark.parametrize(
    "base_url",
    [
        "//dev.test/",
        "ftp://dev.test/",
        "http:///",
        "http://user:pass@dev.test/",
        "http://dev.test/?token=private",
        "http://dev.test/#private",
        "http://dev.test:bad/",
        "http://dev.test:99999/",
        "http://dev.test/\nprivate",
        "http://dev.test\\@other.test/",
    ],
)
def test_invalid_credential_origin_is_rejected(debug_client, base_url):
    with pytest.raises(ValueError, match="Invalid debug client base URL"):
        debug_client.Client(base_url, "synthetic", PASSWORD)


@pytest.mark.parametrize("target", ["/", "http://DEV.test:80/"])
def test_same_origin_auth_navigation_returns_code(debug_client, monkeypatch, target):
    adapter = RedirectAdapter(f"{target}?{urlencode({'code': AUTH_CODE})}", 302)
    mount_adapter(debug_client, monkeypatch, adapter)

    assert debug_client.Client(BASE_URL, "synthetic", PASSWORD).get_auth() == AUTH_CODE
    assert [request.method for request in adapter.calls] == ["GET", "GET"]


@pytest.mark.parametrize("status", [307, 308])
def test_same_origin_login_never_replays_password(debug_client, monkeypatch, status):
    adapter = RedirectAdapter("/", status)
    mount_adapter(debug_client, monkeypatch, adapter)

    with pytest.raises(ValueError, match="Debug client refused redirect"):
        debug_client.Client(BASE_URL, "synthetic", PASSWORD).login()

    assert [request.method for request in adapter.calls] == ["GET", "POST"]


def test_redirect_loop_stops(debug_client, monkeypatch):
    adapter = RedirectAdapter("/indieweb/auth/", 302)
    mount_adapter(debug_client, monkeypatch, adapter)

    with pytest.raises(ValueError, match="Debug client refused redirect"):
        debug_client.Client(BASE_URL, "synthetic", PASSWORD).get_auth()

    assert len(adapter.calls) == 31


@pytest.mark.parametrize("status", [307, 308])
def test_requests_redirect_preparation_errors_are_private(debug_client, monkeypatch, capsys, status):
    canary = "redirect-target-PRIVATE"
    adapter = RedirectAdapter(f"http://dev.test:{canary}/", status)
    mount_adapter(debug_client, monkeypatch, adapter)
    helper = debug_client.Client(BASE_URL, "synthetic", PASSWORD)

    with pytest.raises(ValueError, match="Debug client request failed") as exc:
        helper.post_entry(ACCESS_TOKEN)

    assert len(adapter.calls) == 1
    assert canary not in str(exc.value) + str(capsys.readouterr())


class DjangoAdapter(BaseAdapter):
    """Pass prepared HTTP bytes and headers through the real Django endpoint."""

    def __init__(self, django_client):
        self.client = django_client
        self.calls = []
        self.responses = []

    def send(self, request, **kwargs):
        self.calls.append(request)
        headers = {
            "HTTP_" + key.upper().replace("-", "_"): value
            for key, value in request.headers.items()
            if key.lower() not in {"content-type", "content-length"}
        }
        headers["HTTP_HOST"] = urlparse(request.url).netloc
        result = self.client.generic(
            request.method,
            request.path_url,
            data=request.body or b"",
            content_type=request.headers.get("Content-Type", ""),
            **headers,
        )
        self.responses.append(result)
        response = requests.Response()
        response.request = request
        response.url = request.url
        response.status_code = result.status_code
        response.headers.update(result.items())
        response._content = result.content
        return response

    def close(self):
        pass


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("authority", "expected_status"),
    [("create", 201), ("missing", 401), ("revoked", 401), ("wrong_scope", 403), ("inactive", 401)],
)
def test_debug_client_real_micropub_contract(
    debug_client, monkeypatch, client, django_user_model, settings, capsys, authority, expected_status
):
    from indieweb.handlers import InMemoryMicropubHandler
    from indieweb.models import Token

    settings.ALLOWED_HOSTS = ["dev.test"]
    user = django_user_model.objects.create_user(username="synthetic-debug", is_active=authority != "inactive")
    token = Token.objects.create(
        key=ACCESS_TOKEN,
        owner=user,
        me="http://dev.test/synthetic/",
        client_id=BASE_URL,
        scope="update" if authority == "wrong_scope" else "create",
    )
    raw_token = "" if authority == "missing" else token.key
    if authority == "revoked":
        token.delete()
    handler = InMemoryMicropubHandler()
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler)
    adapter = DjangoAdapter(client)
    mount_adapter(debug_client, monkeypatch, adapter)

    debug_client.Client(BASE_URL, "synthetic", PASSWORD).post_entry(raw_token)

    assert len(adapter.calls) == 1
    assert adapter.responses[0].status_code == expected_status
    assert adapter.calls[0].headers["Authorization"] == f"Bearer {raw_token}"
    properties = parse_qs(adapter.calls[0].body)
    assert properties == {"h": ["entry"], "content": ["blub bla"]}
    if expected_status == 201:
        entry = handler.entries[urlparse(adapter.responses[0]["Location"]).path]
        assert entry.properties == {"content": ["blub bla"]}
    else:
        assert not handler.entries
    output = str(capsys.readouterr())
    assert f"micropub: {expected_status}" in output
    assert not any(secret in output for secret in SECRETS)


NETRC_PASSWORD = "netrc-password-SECRET-6b6b"


class RecordingAdapter(BaseAdapter):
    """Record prepared requests without opening a socket."""

    def __init__(self):
        self.calls = []
        self.kwargs = []

    def send(self, request, **kwargs):
        self.calls.append(request)
        self.kwargs.append(kwargs)
        response = requests.Response()
        response.request = request
        response.url = request.url
        response.status_code = 200
        response._content = b""
        response.cookies.set("csrftoken", CSRF_COOKIE)
        return response

    def close(self):
        pass


def test_netrc_cannot_replace_bearer_or_leak_its_password(debug_client, monkeypatch, tmp_path):
    netrc = tmp_path / "netrc"
    netrc.write_text(f"machine dev.test login netrc-user password {NETRC_PASSWORD}\n")
    netrc.chmod(0o600)
    monkeypatch.setenv("NETRC", str(netrc))
    monkeypatch.setenv("HTTP_PROXY", "http://proxy-user:proxy-SECRET@proxy.invalid:3128")
    monkeypatch.setenv("http_proxy", "http://proxy-user:proxy-SECRET@proxy.invalid:3128")
    adapter = RecordingAdapter()
    mount_adapter(debug_client, monkeypatch, adapter)
    client = debug_client.Client(BASE_URL, "synthetic", PASSWORD)

    client.login()
    client.post_entry(ACCESS_TOKEN)

    assert adapter.calls[-1].headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"
    for request in adapter.calls:
        assert not request.headers.get("Authorization", "").startswith("Basic")
        assert "Proxy-Authorization" not in request.headers
    assert all(NETRC_PASSWORD not in str(request.headers) for request in adapter.calls)
    assert all(not any(kwargs["proxies"].values()) for kwargs in adapter.kwargs)


@pytest.mark.parametrize("variable", ["REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"])
def test_private_ca_bundle_still_verifies_https(debug_client, monkeypatch, tmp_path, variable):
    bundle = tmp_path / "dev-ca.pem"
    bundle.write_text("synthetic\n")
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    monkeypatch.setenv(variable, str(bundle))
    adapter = RecordingAdapter()
    mount_adapter(debug_client, monkeypatch, adapter)

    debug_client.Client("https://dev.test/", "synthetic", PASSWORD).post_entry(ACCESS_TOKEN)

    assert adapter.kwargs[-1]["verify"] == str(bundle)


def test_https_verification_defaults_on(debug_client, monkeypatch):
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    adapter = RecordingAdapter()
    mount_adapter(debug_client, monkeypatch, adapter)

    debug_client.Client("https://dev.test/", "synthetic", PASSWORD).post_entry(ACCESS_TOKEN)

    assert adapter.kwargs[-1]["verify"] is True
