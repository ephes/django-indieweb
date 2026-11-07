import hashlib
import json
import subprocess
from base64 import urlsafe_b64encode
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from indieweb.models import Token
from tests.doc_examples import ROOT, doc_block


def validate(request):
    namespace = {}
    exec(doc_block("tutorial.rst", "def validate_token"), namespace)
    return namespace["validate_token"](request)


@pytest.fixture
def issued(db):
    user = get_user_model().objects.create_user(username="synthetic")
    return Token.objects.create(owner=user, client_id="https://client.example", me="https://client.example/")


def test_documented_raw_token_validation(issued, rf):
    raw = issued.raw_key
    assert validate(rf.get("/", HTTP_AUTHORIZATION=f"Bearer {raw}")).pk == issued.pk
    issued.refresh_from_db()
    assert validate(rf.get("/", HTTP_AUTHORIZATION=f"Bearer {issued.key}")) is None
    issued.set_key()
    issued.save()
    assert validate(rf.get("/", HTTP_AUTHORIZATION=f"Bearer {raw}")) is None
    raw = issued.raw_key
    issued.delete()
    assert validate(rf.get("/", HTTP_AUTHORIZATION=f"Bearer {raw}")) is None


@pytest.mark.parametrize("header", ["", "Bearer", "Bearer ", "Bearer   ", "Basic abc", "Bearer a b"])
def test_documented_token_malformed_header(header, rf):
    assert validate(rf.get("/", HTTP_AUTHORIZATION=header)) is None


@pytest.mark.parametrize("invalid", ["expired", "inactive"])
def test_documented_token_owner_and_expiry(issued, rf, invalid):
    raw = issued.raw_key
    if invalid == "expired":
        issued.expires_at = timezone.now() - timedelta(seconds=1)
        issued.save()
    else:
        issued.owner.is_active = False
        issued.owner.save()
    assert validate(rf.get("/", HTTP_AUTHORIZATION=f"Bearer {raw}")) is None


def browser(marker, **inputs):
    result = subprocess.run(
        ["node", str(ROOT / "tests/js/tutorial_runner.cjs")],
        input=json.dumps({"script": doc_block("tutorial.rst", marker), **inputs}),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.fixture
def login_attempt():
    return browser("document.getElementById('indieauth-form')")


def callback(attempt, **inputs):
    return browser("async function finishIndieAuthLogin", session=attempt["session"], **inputs)


@pytest.mark.django_db
@pytest.mark.parametrize("verifier", ["correct", "absent", "wrong"])
def test_documented_pkce_flow(client, settings, login_attempt, verifier):
    settings.INDIEWEB_REQUIRE_PKCE_S256 = True
    user = get_user_model().objects.create_user(username="synthetic")
    client.force_login(user)
    query = {k: v[0] for k, v in parse_qs(urlsplit(login_attempt["href"]).query).items()}
    pending = json.loads(login_attempt["session"]["indieauth_pending"])
    assert len(pending["state"]) == 32
    assert len(pending["verifier"]) == 43
    assert pending["state"] != pending["verifier"]
    assert (
        query["code_challenge"]
        == urlsafe_b64encode(hashlib.sha256(pending["verifier"].encode()).digest()).rstrip(b"=").decode()
    )
    authorization = client.get(reverse("indieweb:auth"), query)
    assert authorization.status_code == 200, authorization.content
    consent = client.post(reverse("indieweb:auth"), {**query, "action": "approve"})
    assert consent.status_code == 302
    search = urlsplit(consent.url).query
    prepared = callback(login_attempt, search=search, result={})
    request = prepared["requests"][0]
    body = request["body"]
    if verifier == "absent":
        body.pop("code_verifier")
    elif verifier == "wrong":
        body["code_verifier"] = "x" * 43
    response = client.post(request["url"], body, HTTP_ACCEPT=request["headers"]["Accept"])
    result = response.json() if response.status_code < 400 else {}
    finished = callback(login_attempt, search=search, ok=response.status_code < 400, result=result)
    assert not finished["session"]
    if verifier == "correct":
        assert response.status_code == 201
        assert finished["local"]["micropub_token"] == result["access_token"]
        assert not finished["errors"]
    else:
        assert response.status_code == 400
        assert not finished["local"]
        assert not Token.objects.exists()
    # Both the server code and the browser's pending attempt are single-use.
    assert client.post(request["url"], body).status_code == 400
    replay = callback(finished, search=search, result=result)
    assert not replay["requests"] and not replay["local"]
    failed_replay = callback(login_attempt, search=search, ok=False, result={})
    assert not failed_replay["local"]


@pytest.mark.parametrize("search", ["", "code=x", "state=x", "code=x&state=wrong", "error=denied"])
def test_documented_callback_rejects_missing_or_mismatched_inputs(login_attempt, search):
    result = callback(login_attempt, search=search)
    assert result["errors"] and not result["requests"] and not result["session"] and not result["local"]


@pytest.mark.parametrize("result,network_error", [({}, False), ({"access_token": ""}, False), ({}, True)])
def test_documented_callback_rejects_failed_exchange(login_attempt, result, network_error):
    state = json.loads(login_attempt["session"]["indieauth_pending"])["state"]
    finished = callback(login_attempt, search=f"code=x&state={state}", result=result, networkError=network_error)
    assert finished["errors"] and not finished["local"] and not finished["session"]
