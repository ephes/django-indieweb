"""Source handlers must receive current writer-side bearer authority."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from indieweb import views
from indieweb.handlers import (
    InMemoryMicropubHandler,
    MicropubEntry,
    MicropubEntryList,
    MicropubMediaItem,
    MicropubMediaList,
)
from indieweb.models import Token

OPERATIONS = ["entry", "entries", "media", "media-list"]
CHANGES = ["keep", "revoke", "rotate", "expire", "transfer", "deactivate", "client_id", "me", "scope"]


class SourceHandler(InMemoryMicropubHandler):
    def __init__(self):
        super().__init__()
        self.calls = []

    def get_entry(self, url, user):
        self.calls.append(user)
        return MicropubEntry(url=url, properties={"content": ["private synthetic entry"]})

    def list_entries(self, user, **kwargs):
        self.calls.append(user)
        return MicropubEntryList(entries=[])

    def get_media(self, url, user):
        self.calls.append(user)
        return MicropubMediaItem(url=url, properties={"name": ["private synthetic media"]})

    def list_media(self, user, **kwargs):
        self.calls.append(user)
        return MicropubMediaList(items=[])


@pytest.fixture
def source_handler(settings, monkeypatch):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = ["*"]
    handler = SourceHandler()
    monkeypatch.setattr(views, "get_micropub_handler", lambda: handler)
    return handler


def _grant(using="default"):
    owner = get_user_model().objects.db_manager(using).create_user(username="synthetic-source-owner")
    other = get_user_model().objects.db_manager(using).create_user(username="synthetic-other-owner")
    token = Token.objects.using(using).create(
        owner=owner, client_id="https://client.example/", me="https://owner.example/", scope="update media"
    )
    return token, other


def _change(token, other, change, using="default"):
    rows = Token.objects.using(using).filter(pk=token.pk)
    if change == "revoke":
        rows.delete()
    elif change == "rotate":
        rows.update(key=Token.hash_key("synthetic-replacement"))
    elif change == "expire":
        rows.update(expires_at=timezone.now() - timedelta(seconds=1))
    elif change == "transfer":
        rows.update(owner_id=other.pk)
    elif change == "deactivate":
        get_user_model().objects.using(using).filter(pk=token.owner_id).update(is_active=False)
    elif change == "scope":
        rows.update(scope="create")
    elif change in {"client_id", "me"}:
        rows.update(**{change: "https://changed.example/"})


def _request(operation, raw_key):
    data = {"q": "source"}
    if operation in {"entry", "media"}:
        data["url"] = "https://testserver/synthetic-private/"
    endpoint = "media" if operation.startswith("media") else "micropub"
    return Client().get(
        reverse(f"indieweb:{endpoint}"),
        data,
        HTTP_AUTHORIZATION=f"Bearer {raw_key}",
        HTTP_ORIGIN="https://client.example/",
    )


def _assert_result(response, handler, change, using="default"):
    assert "no-store" in {part.strip() for part in response["Cache-Control"].split(",")}
    assert response["Access-Control-Allow-Origin"] == "*"
    if change == "keep":
        assert response.status_code == 200
        assert len(handler.calls) == 1
        assert handler.calls[0]._state.db == using
    else:
        assert response.status_code == (403 if change == "scope" else 401)
        if response.status_code == 401:
            assert response["WWW-Authenticate"] == "Bearer"
        assert handler.calls == []
        assert b"private synthetic" not in response.content


def allow_client(client_id):
    return True


def allow_url(url, kind, request):
    return True


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("operation", "hook"),
    [
        (operation, hook)
        for operation in OPERATIONS
        for hook in ("setup", "client", "final-client", "url")
        if hook != "url" or operation in {"entry", "media"}
    ],
)
@pytest.mark.parametrize("change", CHANGES)
def test_source_rechecks_authority_after_host_policy(operation, change, hook, source_handler, settings, monkeypatch):
    token, other = _grant()
    calls = 0

    def policy(*args):
        nonlocal calls
        calls += 1
        if calls == (2 if hook == "final-client" else 1):
            _change(token, other, change)
        return True

    if hook == "setup":

        def setup():
            policy()
            return source_handler

        monkeypatch.setattr(views, "get_micropub_handler", setup)
    elif hook == "url":
        settings.INDIEWEB_MICROPUB_URL_POLICY = f"{__name__}.allow_url"
        monkeypatch.setattr(f"{__name__}.allow_url", policy)
    else:
        settings.INDIEWEB_CLIENT_ID_VALIDATOR = f"{__name__}.allow_client"
        monkeypatch.setattr(f"{__name__}.allow_client", policy)
    _assert_result(_request(operation, token.key), source_handler, change)


class SourceReplicaRouter:
    def db_for_read(self, model, **hints):
        return "default"

    def db_for_write(self, model, **hints):
        return "other"


@pytest.mark.django_db(databases=["default", "other"])
@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("change", CHANGES)
def test_source_rechecks_writer_despite_stale_replica(operation, change, source_handler, settings):
    token, other = _grant("other")
    owner = get_user_model().objects.create(pk=token.owner_id, username="synthetic-replica-owner")
    Token.objects.create(
        pk=token.pk, key=token.key, owner=owner, client_id=token.client_id, me=token.me, scope=token.scope
    )
    _change(token, other, change, "other")
    settings.DATABASE_ROUTERS = [SourceReplicaRouter()]
    _assert_result(_request(operation, token.key), source_handler, change, "other")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("change", ["revoke", "scope"])
def test_source_blocked_policy_observes_committed_change(
    operation, change, source_handler, settings, monkeypatch, concurrent_database
):
    token, other = _grant()
    entered, release = Event(), Event()

    def policy(*args):
        entered.set()
        assert release.wait(10)
        return True

    if operation in {"entry", "media"}:
        settings.INDIEWEB_MICROPUB_URL_POLICY = f"{__name__}.allow_url"
        monkeypatch.setattr(f"{__name__}.allow_url", policy)
    else:

        def setup():
            policy()
            return source_handler

        monkeypatch.setattr(views, "get_micropub_handler", setup)

    def request():
        close_old_connections()
        try:
            return _request(operation, token.key)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(request)
        try:
            assert entered.wait(10)
            _change(token, other, change)
        finally:
            release.set()
        _assert_result(pending.result(timeout=15), source_handler, change)
