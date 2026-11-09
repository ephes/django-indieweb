"""Policy diagnostics remain useful without disclosing callback context."""

import logging

import httpx
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from indieweb import processors, views
from indieweb.models import Token
from indieweb.processors import WebmentionProcessor

PRIVATE_USER = "invented-private-user"
PRIVATE_BEARER = "invented-private-bearer"
PRIVATE_URL = "https://voucher.example/private?state=invented-private-state"
DETAIL = f"exception-detail {PRIVATE_USER} Bearer {PRIVATE_BEARER} {PRIVATE_URL}"


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["introspection", "redirect", "vouch", "client_id"])
@pytest.mark.parametrize("failure", ["import", "call", "non_callable"])
@pytest.mark.parametrize("mode", ["redact", "passthrough"])
def test_policy_failures_deny_access_and_honor_log_mode(
    client, settings, monkeypatch, caplog, operation, failure, mode
):
    settings.INDIEWEB_LOG_REDACTION = mode
    user = get_user_model().objects.create_user(username=PRIVATE_USER)
    module = processors if operation == "vouch" else views
    setting = {
        "introspection": "INDIEWEB_TOKEN_INTROSPECTION_AUTHORIZER",
        "redirect": "INDIEWEB_REDIRECT_URI_VALIDATOR",
        "vouch": "INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY",
        "client_id": "INDIEWEB_CLIENT_ID_VALIDATOR",
    }[operation]
    setattr(settings, setting, f"synthetic.{PRIVATE_USER}.policy")
    calls = []

    def fail(*args, **kwargs):
        calls.append("call")
        raise RuntimeError(DETAIL)

    def load(path):
        calls.append("import")
        if failure == "import":
            raise ImportError(DETAIL)
        return fail if failure == "call" else object()

    monkeypatch.setattr(module, "import_string", load)
    with caplog.at_level(logging.ERROR):
        if operation == "vouch":
            target = "https://target.example/post"
            with httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200, headers={"Content-Type": "text/html"}, text=f'<a href="{target}">target</a>'
                    )
                )
            ) as http_client:
                result = WebmentionProcessor(client=http_client).process_webmention(
                    "https://source.example/post", target, vouch_url=PRIVATE_URL
                )
            assert result.status == "failed"
            assert result.vouch_verified_at is None
        elif operation == "introspection":
            caller = Token.objects.create(owner=user, client_id="https://client.example/", me="https://me.example/")
            target = Token.objects.create(
                owner=user, client_id="https://client.example/", me="https://me.example/", scope="update"
            )
            response = client.post(
                reverse("indieweb:token-introspection"),
                {"token": target.key},
                HTTP_AUTHORIZATION=f"Bearer {caller.key}",
            )
            assert response.status_code == 200
            assert response.json() == {"active": False}
        else:
            client.force_login(user)
            response = client.get(
                reverse("indieweb:auth"),
                {
                    "client_id": "https://client.example/",
                    "redirect_uri": "https://client.example/callback",
                    "response_type": "code",
                    "state": "synthetic-state",
                    "me": "https://me.example/",
                },
            )
            assert response.status_code == 400
    assert calls == (["import", "call"] if failure == "call" else ["import"])
    records = [
        record for record in caplog.records if record.levelno == logging.ERROR and record.name == module.__name__
    ]
    assert records
    assert setting in records[-1].message
    assert all(not record.exc_info for record in records)
    expected_class = {"import": "ImportError", "call": "RuntimeError"}.get(failure)
    assert expected_class is None or f"({expected_class})" in records[-1].message
    # Exception text never reaches the log, in either mode; redact mode also hides the user and URL.
    private = ["exception-detail", PRIVATE_BEARER, "invented-private-state"]
    if mode == "redact":
        private += [PRIVATE_USER, PRIVATE_URL]
    for marker in private:
        assert marker not in caplog.text
