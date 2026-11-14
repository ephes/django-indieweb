"""Request-owned media and current bearer authority at mutation handoff."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from indieweb import views
from indieweb.handlers import MicropubEntry
from indieweb.models import Token


@pytest.mark.django_db
@pytest.mark.parametrize("error", [OSError, RuntimeError])
def test_partial_save_compensates_requested_and_previous_alternate(error, monkeypatch, rf, caplog):
    diagnostic = "secret-token /private/storage/path"
    objects = {"unrelated": b"keep"}
    requested = iter(["owned-one.jpg", "owned-two.jpg"])
    monkeypatch.setattr(views, "_micropub_media_storage_name", lambda suffix: next(requested))
    monkeypatch.setattr(views.default_storage, "exists", lambda name: name in objects)

    def save(name, upload):
        if name == "owned-one.jpg":
            objects["alternate.jpg"] = b"first"
            return "alternate.jpg"
        objects[name] = b"partial"
        raise error(diagnostic)

    monkeypatch.setattr(views.default_storage, "save", save)
    monkeypatch.setattr(views.default_storage, "delete", lambda name: objects.pop(name, None))
    uploads = [SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF\x00", "image/jpeg") for _ in range(2)]
    with pytest.raises(views._MicropubMediaUploadError) as exc:
        views._store_micropub_media_uploads(rf.post("/"), uploads)
    assert exc.value.status_code == 500
    assert objects == {"unrelated": b"keep"}
    assert "secret-token" not in caplog.text and "/private/storage/path" not in caplog.text


@pytest.mark.django_db
def test_preexisting_requested_name_is_never_owned(monkeypatch, rf):
    monkeypatch.setattr(views, "_micropub_media_storage_name", lambda suffix: "existing.jpg")
    monkeypatch.setattr(views.default_storage, "exists", lambda name: True)
    save, delete = Mock(), Mock()
    monkeypatch.setattr(views.default_storage, "save", save)
    monkeypatch.setattr(views.default_storage, "delete", delete)
    upload = SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF\x00", "image/jpeg")
    with pytest.raises(views._MicropubMediaUploadError):
        views._store_micropub_media_uploads(rf.post("/"), [upload])
    save.assert_not_called()
    delete.assert_not_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("operation", ["create", "update", "delete", "undelete", "delete_media"])
@pytest.mark.parametrize("change", ["revoke", "rotate", "expire", "deactivate", "scope", "client"])
def test_mutation_rechecks_after_handler_setup(operation, change, monkeypatch, concurrent_database):
    owner = get_user_model().objects.create_user(username="synthetic")
    scope = "media" if operation == "delete_media" else operation
    token = Token.objects.create(
        owner=owner, me="https://testserver/", client_id="https://client.example/", scope=scope
    )
    entered, release = Event(), Event()
    handler = Mock()
    handler.create_entry.return_value = MicropubEntry(url="/new/", properties={})
    handler.update_entry.return_value = MicropubEntry(url="/entry/", properties={})
    handler.undelete_entry.return_value = MicropubEntry(url="/entry/", properties={})
    handler.delete_media.return_value = True

    def setup():
        entered.set()
        assert release.wait(10)
        return handler

    monkeypatch.setattr(views, "get_micropub_handler", setup)
    monkeypatch.setattr(views.MicropubMediaView, "_handler_overrides", staticmethod(lambda *args: True))

    def request():
        close_old_connections()
        try:
            data = (
                {"h": "entry", "content": "synthetic"}
                if operation == "create"
                else {
                    "action": "delete" if operation == "delete_media" else operation,
                    "url": "http://testserver/entry/",
                    "replace": {"content": ["synthetic"]},
                }
            )
            endpoint = "media" if operation == "delete_media" else "micropub"
            return Client().post(
                reverse(f"indieweb:{endpoint}"),
                data,
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {token.key}",
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(request)
        try:
            assert entered.wait(10)
            if change == "revoke":
                Token.objects.filter(pk=token.pk).delete()
            elif change == "rotate":
                Token.objects.filter(pk=token.pk).update(key=Token.hash_key("replacement"))
            elif change == "expire":
                Token.objects.filter(pk=token.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
            elif change == "deactivate":
                get_user_model().objects.filter(pk=owner.pk).update(is_active=False)
            elif change == "client":
                Token.objects.filter(pk=token.pk).update(client_id="https://changed.example/")
            else:
                Token.objects.filter(pk=token.pk).update(scope="read")
        finally:
            release.set()
        response = pending.result(timeout=15)
    assert response.status_code in {401, 403}
    getattr(handler, f"{operation}_entry" if operation != "delete_media" else operation).assert_not_called()
