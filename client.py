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


class Client:
    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.session = requests.Session()

    @property
    def csrftoken(self):
        if not hasattr(self, "_csrftoken"):
            login_url = urljoin(self.base_url, "accounts/login/")
            r = self.session.get(login_url)
            print("login page:", r.status_code)
            self._csrftoken = r.cookies["csrftoken"]
        return self._csrftoken

    def get_csrftoken(self, url):
        r = self.session.get(url)
        return r.cookies["csrftoken"]

    def login(self):
        login_url = urljoin(self.base_url, "accounts/login/")
        payload = {
            "login": self.username,
            "password": self.password,
            "csrfmiddlewaretoken": self.csrftoken,
        }
        r = self.session.post(login_url, payload, headers=dict(Referer=login_url))
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
        r = self.session.post(logout_url, payload, headers=dict(Referer=logout_url))
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
        r = self.session.get(auth_url, allow_redirects=True)
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
        r = self.session.post(auth_url, payload)
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
        r = self.session.post(token_url, payload)
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
        r = self.session.post(micropub_url, payload)
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
