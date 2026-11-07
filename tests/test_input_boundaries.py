"""Malformed numeric JSON and strict full-string PKCE endpoint boundaries."""

import base64
import hashlib
import json
import sys
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.urls import reverse

from indieweb import models


@pytest.fixture
def owner(db):
    return User.objects.create_user(username="boundary-owner")


@pytest.mark.parametrize("route", ["micropub", "media"])
def test_integer_decoder_failure_is_invalid_request(client, owner, monkeypatch, route):
    grant = models.Token.objects.create(
        owner=owner, me="https://me.example/", client_id="https://client.example/", scope="create media"
    )
    handler = Mock()
    storage_save = Mock()
    monkeypatch.setattr("indieweb.views.get_micropub_handler", handler)
    monkeypatch.setattr(default_storage, "save", storage_save)
    body = '{"number":' + "9" * 700 + "}"
    previous_limit = sys.get_int_max_str_digits()
    try:
        sys.set_int_max_str_digits(640)
        with pytest.raises(ValueError):
            json.loads(body)
        response = client.post(
            reverse(f"indieweb:{route}"),
            body,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {grant.key}",
        )
    finally:
        sys.set_int_max_str_digits(previous_limit)
    assert response.status_code == 400
    assert response.content == b"invalid_request"
    handler.assert_not_called()
    storage_save.assert_not_called()


@pytest.mark.parametrize("method", ["plain", "S256"])
@pytest.mark.parametrize("transport", ["get", "post"])
@pytest.mark.parametrize("suffix", ["\n", "\r", "\x00", "é"])
def test_authorization_rejects_non_unreserved_suffix(client, owner, method, transport, suffix):
    client.force_login(owner)
    payload = {
        "action": "approve",
        "me": "https://me.example/",
        "client_id": "https://client.example/",
        "redirect_uri": "https://client.example/callback",
        "state": "test",
        "scope": "create",
        "code_challenge": "A" * 42 + suffix,
        "code_challenge_method": method,
    }
    response = getattr(client, transport)(reverse("indieweb:auth"), payload)
    assert response.status_code == 400
    assert not models.Auth.objects.exists()


def _challenge(verifier, method):
    if method == "plain":
        return verifier
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest()).rstrip(b"=").decode()


@pytest.mark.parametrize("route", ["auth", "token"])
@pytest.mark.parametrize("method", ["plain", "S256"])
@pytest.mark.parametrize("suffix", ["\n", "\r", "\x00", "é"])
def test_redemption_rejects_non_unreserved_verifier(client, owner, route, method, suffix):
    verifier = "A" * 42 + suffix
    # Model legacy/malformed stored challenges too: lexical validation must run before comparison.
    auth = models.Auth.objects.create(
        owner=owner,
        me="https://me.example/",
        client_id="https://client.example/",
        redirect_uri="https://client.example/callback",
        scope="create",
        code_challenge=_challenge(verifier, method),
        code_challenge_method=method,
    )
    response = client.post(
        reverse(f"indieweb:{route}"),
        {
            "code": auth.key,
            "client_id": auth.client_id,
            "redirect_uri": auth.redirect_uri,
            "code_verifier": verifier,
        },
    )
    assert response.status_code == 400
    assert b"invalid_grant" in response.content
    assert not models.Token.objects.exists()


@pytest.mark.parametrize("length", [43, 128])
@pytest.mark.parametrize("method", ["plain", "S256"])
def test_valid_pkce_boundary_round_trip(client, owner, length, method):
    verifier = ("aZ0-._~" * 19)[:length]
    client.force_login(owner)
    response = client.post(
        reverse("indieweb:auth"),
        {
            "action": "approve",
            "me": "https://me.example/",
            "client_id": "https://client.example/",
            "redirect_uri": "https://client.example/callback",
            "state": "test",
            "scope": "create",
            "code_challenge": _challenge(verifier, method),
            "code_challenge_method": method,
        },
    )
    assert response.status_code == 302
    auth = models.Auth.objects.get()
    response = client.post(
        reverse("indieweb:token"),
        {
            "code": parse_qs(urlparse(response["Location"]).query)["code"][0],
            "client_id": auth.client_id,
            "redirect_uri": auth.redirect_uri,
            "code_verifier": verifier,
        },
    )
    assert response.status_code == 201
    assert models.Token.objects.count() == 1
