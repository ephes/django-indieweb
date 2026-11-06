"""Adapter failure diagnostics must honor the configured URL privacy policy."""

import logging

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from indieweb.handlers import InMemoryMicropubHandler
from indieweb.log_redaction import redact_url
from indieweb.models import Token

PRIVATE_URL = "http://testserver/private/synthetic-item?secret=invented-query-value"
PRIVATE_FILTER = "invented-private-filter"
EXCEPTION_DETAIL = "invented-exception-detail"


@pytest.fixture(params=["get_entry", "list_entries", "get_media", "list_media", "delete_media"])
def failing_query(request, client, db, monkeypatch):
    user = User.objects.create_user(username="log-user")
    access_grant = Token.objects.create(
        owner=user, me="https://example.org/", client_id="https://client.example.org/", scope="update media"
    )
    calls = []

    def run(exception_type):
        def fail(self, *args, **kwargs):
            calls.append(request.param)
            try:
                raise OSError(f"chained {PRIVATE_URL}")
            except OSError as cause:
                raise exception_type(f"{PRIVATE_URL} {PRIVATE_FILTER} {EXCEPTION_DETAIL}") from cause

        class BrokenHandler(InMemoryMicropubHandler):
            pass

        setattr(BrokenHandler, request.param, fail)
        monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: BrokenHandler())
        endpoint = "micropub" if request.param.endswith("entries") or request.param == "get_entry" else "media"
        params = {"q": "source", "filter": PRIVATE_FILTER}
        if not request.param.startswith("list_"):
            params["url"] = PRIVATE_URL
        if request.param == "delete_media":
            params["action"] = "delete"
            response = client.post(reverse(f"indieweb:{endpoint}"), params, Authorization=f"Bearer {access_grant.key}")
        else:
            response = client.get(reverse(f"indieweb:{endpoint}"), params, Authorization=f"Bearer {access_grant.key}")
        assert calls == [request.param]
        return response

    return run, request.param


@pytest.mark.django_db
@pytest.mark.parametrize("exception_type,status", [(ValueError, 400), (RuntimeError, 500)])
@pytest.mark.parametrize("mode", ["redact", " REDACT ", "typo"])
def test_handler_errors_redact_urls_messages_and_tracebacks(
    failing_query, settings, caplog, exception_type, status, mode
):
    settings.INDIEWEB_LOG_REDACTION = mode
    run, operation = failing_query
    with caplog.at_level(logging.WARNING, logger="indieweb.views"):
        response = run(exception_type)
    assert response.status_code == status
    assert response.content == (b"invalid_request" if status == 400 else b"")
    assert operation in caplog.text
    assert exception_type.__name__ in caplog.text
    if not operation.startswith("list_"):
        assert redact_url(PRIVATE_URL) in caplog.text
    for private in (PRIVATE_URL, "/private/synthetic-item", "invented-query-value", PRIVATE_FILTER, EXCEPTION_DETAIL):
        assert private not in caplog.text
    records = [record for record in caplog.records if record.name == "indieweb.views"]
    assert records
    assert all(not record.exc_info for record in records)


@pytest.mark.django_db
@pytest.mark.parametrize("exception_type,status", [(ValueError, 400), (RuntimeError, 500)])
def test_handler_errors_preserve_passthrough_diagnostics(failing_query, settings, caplog, exception_type, status):
    settings.INDIEWEB_LOG_REDACTION = "passthrough"
    run, operation = failing_query
    response = run(exception_type)
    assert response.status_code == status
    assert operation in caplog.text
    assert PRIVATE_URL in caplog.text
    assert EXCEPTION_DETAIL in caplog.text
    records = [record for record in caplog.records if record.name == "indieweb.views"]
    assert bool(records[-1].exc_info) is (status == 500)
