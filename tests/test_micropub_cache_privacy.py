"""Private source queries must reauthenticate even with site-wide caching."""

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse

from indieweb.handlers import InMemoryMicropubHandler, MicropubEntry, MicropubEntryList
from indieweb.models import Token

DRAFT = "invented-unpublished-draft"
ENTRY_URL = "http://testserver/private/synthetic-entry"


@pytest.fixture
def private_source(client, settings, monkeypatch, db):
    settings.MIDDLEWARE = [
        "django.middleware.cache.UpdateCacheMiddleware",
        *settings.MIDDLEWARE,
        "django.middleware.cache.FetchFromCacheMiddleware",
    ]
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.CACHE_MIDDLEWARE_SECONDS = 600
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = ["https://client.example"]
    cache.clear()
    user = get_user_model().objects.create_user(username="synthetic-source-owner")
    access_grant = Token.objects.create(
        owner=user, client_id="https://client.example", me="https://me.example", scope="update"
    )
    calls = []
    entry = MicropubEntry(url=ENTRY_URL, properties={"content": [DRAFT], "post-status": ["draft"]})

    class SourceHandler(InMemoryMicropubHandler):
        error = None

        def get_entry(self, url, user):
            calls.append("source")
            if self.error:
                raise self.error("invented-handler-failure")
            return entry

        def list_entries(self, user, **kwargs):
            calls.append("list")
            if self.error:
                raise self.error("invented-handler-failure")
            return MicropubEntryList(entries=[entry], total=1)

    handler = SourceHandler()
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler)
    headers = {"Authorization": f"Bearer {access_grant.key}", "Origin": "https://client.example"}
    yield access_grant, headers, calls, handler
    cache.clear()


def assert_private(response):
    directives = {part.strip() for part in response["Cache-Control"].split(",")}
    assert {"private", "no-store", "no-cache", "max-age=0", "must-revalidate"} <= directives
    assert "authorization" in {part.strip().lower() for part in response["Vary"].split(",")}


@pytest.mark.django_db
@pytest.mark.parametrize("single", [False, True])
def test_source_cache_rechecks_authentication_after_revocation(client, private_source, single):
    access_grant, headers, calls, _ = private_source
    params = {"q": "source"}
    if single:
        params["url"] = ENTRY_URL
    endpoint = reverse("indieweb:micropub")
    first = client.get(endpoint, params, headers=headers)
    assert first.status_code == 200
    assert DRAFT.encode() in first.content
    # A second success must call the handler again rather than use the cache.
    second = client.get(endpoint, params, headers=headers)
    assert second.status_code == 200
    access_grant.delete()
    revoked = client.get(endpoint, params, headers=headers)
    assert revoked.status_code == 401
    assert DRAFT.encode() not in revoked.content
    assert len(calls) == 2
    for response in (first, second, revoked):
        assert_private(response)
        assert "origin" in response["Vary"].lower()


@pytest.mark.django_db
@pytest.mark.parametrize("single", [False, True])
@pytest.mark.parametrize("error,expected_status", [(ValueError, 400), (RuntimeError, 500)])
def test_source_handler_errors_have_private_cache_policy(client, private_source, single, error, expected_status):
    _, headers, calls, handler = private_source
    handler.error = error
    params = {"q": "source"}
    if single:
        params["url"] = ENTRY_URL
    response = client.get(reverse("indieweb:micropub"), params, headers=headers)
    assert response.status_code == expected_status
    assert calls == ["source" if single else "list"]
    assert DRAFT.encode() not in response.content
    assert_private(response)


def test_public_metadata_keeps_its_separate_cache_policy(client):
    response = client.get(reverse("indieweb:auth-metadata"))
    assert response.status_code == 200
    assert "private" not in response.get("Cache-Control", "")
    assert "authorization" not in response.get("Vary", "").lower()
