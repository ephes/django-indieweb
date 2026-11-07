"""Mutation handler errors must not expose submitted synthetic private values."""

import logging

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from indieweb.handlers import InMemoryMicropubHandler
from indieweb.models import Token

PRIVATE_URL = "http://testserver/private/synthetic-item?secret=invented-query-value"
PRIVATE_BODY = "invented-private-body"


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["create", "update", "delete", "undelete"])
@pytest.mark.parametrize("error_type,status", [(ValueError, 400), (RuntimeError, 500)])
@pytest.mark.parametrize("mode", ["redact", " REDACT ", "typo", "passthrough"])
def test_mutation_diagnostics_respect_privacy(
    client, monkeypatch, settings, caplog, operation, error_type, status, mode
):
    settings.INDIEWEB_LOG_REDACTION = mode
    owner = get_user_model().objects.create_user(username="synthetic-mutation")
    grant = Token.objects.create(
        owner=owner,
        me="https://me.example/",
        client_id="https://client.example/",
        scope="create update delete undelete",
    )
    calls = []

    def fail(self, *args, **kwargs):
        calls.append(operation)
        try:
            raise OSError(PRIVATE_BODY)
        except OSError as cause:
            raise error_type(f"{PRIVATE_URL} {PRIVATE_BODY}" * 1000) from cause

    class BrokenHandler(InMemoryMicropubHandler):
        pass

    setattr(BrokenHandler, f"{operation}_entry", fail)
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: BrokenHandler())
    payload = {"action": operation, "url": PRIVATE_URL}
    options = {}
    if operation == "create":
        payload = {"h": "entry", "content": PRIVATE_BODY}
    elif operation == "update":
        payload["replace"] = {"content": [PRIVATE_BODY]}
        options["content_type"] = "application/json"
    with caplog.at_level(logging.WARNING, logger="indieweb.views"):
        response = client.post(reverse("indieweb:micropub"), payload, Authorization=f"Bearer {grant.key}", **options)
    assert calls == [operation]
    assert response.status_code == status
    assert f"{operation}_entry" in caplog.text
    assert error_type.__name__ in caplog.text
    records = [r for r in caplog.records if r.name == "indieweb.views"]
    assert records
    if mode == "passthrough":
        assert PRIVATE_BODY in caplog.text
        assert PRIVATE_URL in caplog.text
        assert bool(records[-1].exc_info) is (status == 500)
    else:
        for private in (PRIVATE_URL, "/private/synthetic-item", "invented-query-value", PRIVATE_BODY):
            assert private not in caplog.text
        assert all(not r.exc_info for r in records)
        assert all(len(r.getMessage()) < 500 for r in records)
