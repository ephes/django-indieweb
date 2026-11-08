"""Handler configuration regressions using a synthetic file-backed adapter."""

import json
from dataclasses import asdict

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from indieweb.handlers import InMemoryMicropubHandler, MicropubEntry, get_micropub_handler
from indieweb.models import Token


class FileHandler(InMemoryMicropubHandler):
    """Test-only adapter: each fresh instance reloads a temporary entry file."""

    def __init__(self):
        super().__init__()
        self.path = settings.INDIEWEB_TEST_ENTRY_FILE
        if self.path.exists():
            self.entries = {url: MicropubEntry(**data) for url, data in json.loads(self.path.read_text()).items()}

    def _persist(self):
        self.path.write_text(json.dumps({url: asdict(entry) for url, entry in self.entries.items()}))

    def create_entry(self, properties, user):
        entry = super().create_entry(properties, user)
        del self.entries[entry.url]
        entry.url = "http://testserver" + entry.url
        self.entries[entry.url] = entry
        self._persist()
        return entry

    def update_entry(self, url, updates, user):
        entry = super().update_entry(url, updates, user)
        self._persist()
        return entry


@pytest.fixture
def grant(db):
    user = get_user_model().objects.create_user(username="handler-configuration")
    return Token.objects.create(
        owner=user,
        client_id="https://client.example",
        me="https://owner.example",
        scope="create update delete undelete",
    )


@pytest.mark.parametrize("action", ["create", "update", "delete", "undelete"])
@pytest.mark.parametrize("configuration", [None, "absent"])
def test_unconfigured_handler_refuses_writes(client, grant, settings, action, configuration):
    if configuration == "absent":
        if hasattr(settings, "INDIEWEB_MICROPUB_HANDLER"):
            del settings.INDIEWEB_MICROPUB_HANDLER
    else:
        settings.INDIEWEB_MICROPUB_HANDLER = configuration
    payload = {"h": "entry", "content": "synthetic note"}
    if action != "create":
        payload = {"action": action, "url": "http://testserver/entries/synthetic/"}
        if action == "update":
            payload["replace"] = {"content": ["replacement"]}
    response = client.post(
        reverse("indieweb:micropub"),
        data=json.dumps(payload),
        content_type="application/json",
        Authorization=f"Bearer {grant.key}",
    )
    assert response.status_code == 500
    assert "Location" not in response
    assert response.content == b""


def test_configured_handler_persists_across_requests(client, grant, settings, tmp_path):
    settings.INDIEWEB_MICROPUB_HANDLER = "tests.test_handler_configuration.FileHandler"
    settings.INDIEWEB_TEST_ENTRY_FILE = tmp_path / "entries.json"
    assert get_micropub_handler() is not get_micropub_handler()
    url = reverse("indieweb:micropub")
    headers = {"Authorization": f"Bearer {grant.key}"}
    created = client.post(url, {"h": "entry", "content": "original synthetic note"}, **headers)
    assert created.status_code == 201
    entry_url = created["Location"]
    source = client.get(url, {"q": "source", "url": entry_url}, **headers)
    assert source.status_code == 200
    assert source.json()["properties"]["content"] == ["original synthetic note"]
    updated = client.post(
        url,
        json.dumps(
            {
                "action": "update",
                "url": entry_url,
                "replace": {"content": ["updated synthetic note"]},
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert updated.status_code == 204
    source = client.get(url, {"q": "source", "url": entry_url}, **headers)
    assert source.json()["properties"]["content"] == ["updated synthetic note"]


def test_unconfigured_create_cleans_inline_upload(client, grant, settings, tmp_path):
    settings.INDIEWEB_MICROPUB_HANDLER = None
    settings.MEDIA_ROOT = tmp_path
    photo = SimpleUploadedFile(
        "synthetic.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00synthetic", content_type="image/jpeg"
    )
    response = client.post(
        reverse("indieweb:micropub"), {"h": "entry", "photo": photo}, Authorization=f"Bearer {grant.key}"
    )
    assert response.status_code == 500
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_unconfigured_discovery_stays_available(client, grant, settings):
    settings.INDIEWEB_MICROPUB_HANDLER = None
    response = client.get(reverse("indieweb:micropub"), {"q": "config"}, Authorization=f"Bearer {grant.key}")
    assert response.status_code == 200
    assert response.json()["media-endpoint"]
