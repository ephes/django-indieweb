#!/usr/bin/env python
"""Debug helper that walks the IndieAuth and Micropub flow against a dev server.

The helper never prints credentials. Cookies, the authorization code and the
access token stay in memory; diagnostics show HTTP status codes, parameter
names and short SHA-256 fingerprints only.
"""

import hashlib
import os
import sys
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from django.utils.http import urlencode


def fingerprint(secret):
    """Return a short one-way fingerprint that identifies ``secret`` without revealing it."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]


def credential_origin(url: str) -> tuple[str, str, int]:
    """Admit a plain HTTP(S) URL and compare scheme, host and effective port."""
    try:
        parsed = urlparse(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "\\" in url
            or "%" in parsed.netloc
            or any(ord(char) <= 32 or ord(char) == 127 for char in url)
        ):
            raise ValueError
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        port = parsed.port if parsed.port is not None else {"http": 80, "https": 443}[parsed.scheme]
        return parsed.scheme, host, port
    except (ValueError, UnicodeError):
        raise ValueError("Invalid debug client base URL") from None


class Client:
    def __init__(self, base_url, username, password):
        self.origin = credential_origin(base_url)
        if urlparse(base_url).query or urlparse(base_url).fragment:
            raise ValueError("Invalid debug client base URL")
        self.base_url = base_url
        self.username = username
        self.password = password
        self.session = requests.Session()

    def _redirect_target(self, response: requests.Response, url: str) -> str:
        try:
            target = urljoin(url, response.headers.get("Location", ""))
            if not response.headers.get("Location") or credential_origin(target) != self.origin:
                raise ValueError
        except ValueError:
            raise ValueError("Debug client refused redirect") from None
        return target

    def _get(self, url: str) -> requests.Response:
        # Even GET redirects can carry the session cookie or an auth code.
        for _ in range(31):
            if credential_origin(url) != self.origin:
                raise ValueError("Debug client refused redirect")
            response = self.session.get(url, allow_redirects=False)
            if not 300 <= response.status_code < 400:
                return response
            try:
                url = self._redirect_target(response, url)
            finally:
                response.close()
        raise ValueError("Debug client refused redirect")

    def _post(
        self, url: str, payload: dict[str, str], *, navigation: bool = False, headers: dict[str, str] | None = None
    ) -> requests.Response:
        if credential_origin(url) != self.origin:
            raise ValueError("Debug client refused redirect")
        response = self.session.post(url, payload, allow_redirects=False, headers=headers)
        if 300 <= response.status_code < 400:
            try:
                self._redirect_target(response, url)
                # Login/logout commonly finish with a same-origin 302/303.
                # Their destination need not be fetched; never replay a POST.
                if not navigation or response.status_code not in {302, 303}:
                    raise ValueError("Debug client refused redirect")
            finally:
                response.close()
        return response

    @property
    def csrftoken(self):
        if not hasattr(self, "_csrftoken"):
            login_url = urljoin(self.base_url, "accounts/login/")
            r = self._get(login_url)
            print("login page:", r.status_code)
            self._csrftoken = r.cookies["csrftoken"]
        return self._csrftoken

    def get_csrftoken(self, url):
        r = self._get(url)
        return r.cookies["csrftoken"]

    def login(self):
        login_url = urljoin(self.base_url, "accounts/login/")
        payload = {
            "login": self.username,
            "password": self.password,
            "csrfmiddlewaretoken": self.csrftoken,
        }
        r = self._post(login_url, payload, navigation=True, headers=dict(Referer=login_url))
        print("login:", r.status_code)
        # Login response HTML is intentionally not persisted: writing it to a
        # fixed filesystem path was a debugging hack that would clobber files
        # owned by other users on a shared host. If you need the body for
        # debugging, capture ``r.content`` from a Python REPL. Cookies are
        # session credentials and are not printed either.

    def logout(self):
        logout_url = urljoin(self.base_url, "accounts/logout/")
        csrftoken = self.get_csrftoken(logout_url)
        payload = {"csrfmiddlewaretoken": csrftoken}
        r = self._post(logout_url, payload, navigation=True, headers=dict(Referer=logout_url))
        print("logout:", r.status_code)

    def get_auth(self):
        url_params = {
            "me": f"{self.base_url}/jochen/",
            "client_id": "testclient",
            "redirect_uri": self.base_url,
            "state": "1234567890foo",
            "scope": "post",
        }
        auth_url = "{}?{}".format(urljoin(self.base_url, "indieweb/auth/"), urlencode(url_params))
        r = self._get(auth_url)
        data = parse_qs(urlparse(r.url).query)
        # The redirect query carries the authorization code: print names only.
        print("auth redirect:", r.status_code, "params:", sorted(data))
        return data["code"][0]

    def post_auth(self, auth_code):
        auth_url = urljoin(self.base_url, "indieweb/auth/")
        payload = {
            "code": auth_code,
            "client_id": "testclient",
            "redirect_uri": self.base_url,
        }
        r = self._post(auth_url, payload)
        data = parse_qs(unquote(r.content.decode("utf-8")))
        return data

    def get_token(self, auth_code):
        token_url = urljoin(self.base_url, "indieweb/token/")
        payload = {
            "me": f"{self.base_url}/jochen/",
            "client_id": "testclient",
            "redirect_uri": self.base_url,
            "state": "1234567890foo",
            "scope": "post",
            "code": auth_code,
        }
        r = self._post(token_url, payload)
        print("token:", r.status_code)
        data = parse_qs(unquote(r.content.decode("utf-8")))
        return data["access_token"][0]

    def post_entry(self, token):
        micropub_url = urljoin(self.base_url, "indieweb/micropub/")
        payload = {
            "Authorization": token,
            "h": "entry",
            "content": "blub bla",
        }
        r = self._post(micropub_url, payload)
        print("micropub:", r.status_code)


def main(args):
    username = os.environ["USERNAME"]
    password = os.environ["PASSWORD"]
    base_url = os.environ["BASE_URL"]
    client = Client(base_url, username, password)
    client.login()
    auth_code = client.get_auth()
    print("auth code fingerprint:", fingerprint(auth_code))
    token = client.get_token(auth_code)
    print("access token fingerprint:", fingerprint(token))
    client.post_entry(token)
    # new client to test auth verification without login
    print("logout..")
    client.logout()
    # client = Client(base_url, username, password)
    data = client.post_auth(auth_code)
    print("auth verification params:", sorted(data))


if __name__ == "__main__":
    main(sys.argv)
