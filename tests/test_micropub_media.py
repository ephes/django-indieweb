import json
from datetime import timedelta
from urllib.parse import urlparse

import pytest
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from indieweb import models
from indieweb.handlers import InMemoryMicropubHandler


@pytest.fixture
def user(db):
    return User.objects.create_user(username="mediauser", email="media@example.org", password="password")


@pytest.fixture
def media_url():
    return reverse("indieweb:media")


@pytest.fixture
def micropub_url():
    return reverse("indieweb:micropub")


def _make_token(user, scope: str | None = "media") -> models.Token:
    return models.Token.objects.create(
        me="https://example.org",
        client_id="https://client.example.org",
        scope=scope,
        owner=user,
    )


def _upload(
    name: str = "sunset.jpg", content: bytes = b"image bytes", content_type: str = "image/jpeg"
) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type=content_type)


@pytest.mark.django_db
def test_media_upload_stores_file_and_returns_absolute_location(client, settings, tmp_path, user, media_url):
    settings.MEDIA_ROOT = str(tmp_path)
    token = _make_token(user, "create media update")

    response = client.post(media_url, data={"file": _upload()}, Authorization=f"Bearer {token.key}")

    assert response.status_code == 201
    assert response.content == b""
    location = response["Location"]
    parsed = urlparse(location)
    assert parsed.scheme in {"http", "https"}
    assert parsed.netloc
    assert parsed.path.startswith(settings.MEDIA_URL)
    stored_name = parsed.path.removeprefix(settings.MEDIA_URL)
    assert stored_name.startswith("indieweb/media/")
    assert stored_name.endswith(".jpg")
    assert "sunset" not in stored_name
    assert default_storage.exists(stored_name)
    with default_storage.open(stored_name, "rb") as stored_file:
        assert stored_file.read() == b"image bytes"


@pytest.mark.django_db
def test_media_upload_without_filename_suffix_stores_extensionless_name(client, settings, tmp_path, user, media_url):
    settings.MEDIA_ROOT = str(tmp_path)
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": _upload(name="upload", content_type="image/png")},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 201
    stored_name = urlparse(response["Location"]).path.removeprefix(settings.MEDIA_URL)
    assert stored_name.startswith("indieweb/media/")
    assert "." not in stored_name.removeprefix("indieweb/media/")
    assert default_storage.exists(stored_name)


@pytest.mark.django_db
def test_media_upload_requires_token(client, media_url):
    response = client.post(media_url, data={"file": _upload()})

    assert response.status_code == 401
    assert response.content.decode("utf-8") == "authentication error"


@pytest.mark.django_db
def test_media_upload_rejects_wrong_token(client, media_url):
    response = client.post(media_url, data={"file": _upload()}, Authorization="Bearer wrong")

    assert response.status_code == 401
    assert response.content.decode("utf-8") == "authentication error"


@pytest.mark.django_db
def test_media_upload_rejects_expired_token(client, user, media_url):
    token = _make_token(user, "media")
    token.expires_at = timezone.now() - timedelta(seconds=1)
    token.save()

    response = client.post(media_url, data={"file": _upload()}, Authorization=f"Bearer {token.key}")

    assert response.status_code == 401
    assert response.content.decode("utf-8") == "authentication error"


@pytest.mark.django_db
def test_media_upload_rejects_inactive_owner(client, user, media_url):
    token = _make_token(user, "media")
    user.is_active = False
    user.save()

    response = client.post(media_url, data={"file": _upload()}, Authorization=f"Bearer {token.key}")

    assert response.status_code == 401
    assert response.content.decode("utf-8") == "authentication error"


@pytest.mark.django_db
def test_media_upload_rejects_disallowed_client_id(client, settings, user, media_url):
    settings.INDIEWEB_CLIENT_ID_VALIDATOR = "tests.client_id_validators.deny_all"
    token = _make_token(user, "media")

    response = client.post(media_url, data={"file": _upload()}, Authorization=f"Bearer {token.key}")

    assert response.status_code == 403
    assert response.content.decode("utf-8") == "invalid_client"


@pytest.mark.django_db
@pytest.mark.parametrize("scope", [None, "", "create", "post", "update", "delete", "mediaXYZ", "create_media"])
def test_media_upload_requires_media_scope(client, user, media_url, scope):
    token = _make_token(user, scope)

    response = client.post(media_url, data={"file": _upload()}, Authorization=f"Bearer {token.key}")

    assert response.status_code == 403
    assert response.content.decode("utf-8") == "authorization error"


@pytest.mark.django_db
def test_media_upload_rejects_missing_file(client, user, media_url):
    token = _make_token(user, "media")

    response = client.post(media_url, data={}, Authorization=f"Bearer {token.key}")

    assert response.status_code == 400
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_media_upload_rejects_non_multipart_request(client, user, media_url):
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data=b"not multipart",
        content_type="application/octet-stream",
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 400
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_media_upload_rejects_files_over_configured_size(client, settings, user, media_url):
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_BYTES = 4
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": _upload(content=b"12345")},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 413
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_media_upload_accepts_file_exactly_at_configured_size(client, settings, tmp_path, user, media_url):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_BYTES = 5
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": _upload(content=b"12345")},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_media_upload_can_disable_size_limit(client, settings, tmp_path, user, media_url):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_BYTES = None
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": _upload(content=b"12345")},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_media_upload_rejects_disallowed_content_type(client, user, media_url):
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": _upload(name="page.html", content_type="text/html")},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 415
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_media_upload_allows_configured_content_type(client, settings, tmp_path, user, media_url):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.INDIEWEB_MEDIA_ALLOWED_TYPES = ("text/plain",)
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": _upload(name="note.txt", content_type="text/plain")},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_media_upload_can_disable_content_type_check(client, settings, tmp_path, user, media_url):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.INDIEWEB_MEDIA_ALLOWED_TYPES = None
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": _upload(name="page.html", content_type="text/html")},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_media_upload_storage_os_error_returns_500(client, monkeypatch, user, media_url):
    def fail_save(name, content, max_length=None):
        raise OSError("storage unavailable")

    monkeypatch.setattr("indieweb.views.default_storage.save", fail_save)
    token = _make_token(user, "media")

    response = client.post(media_url, data={"file": _upload()}, Authorization=f"Bearer {token.key}")

    assert response.status_code == 500


@pytest.mark.django_db
def test_micropub_config_advertises_absolute_media_endpoint(client, user, micropub_url):
    token = _make_token(user, None)

    response = client.get(f"{micropub_url}?q=config", Authorization=f"Bearer {token.key}")

    assert response.status_code == 200
    config = json.loads(response.content)
    assert config["media-endpoint"] == "http://testserver/indieweb/media/"


@pytest.mark.django_db
def test_micropub_config_injects_media_endpoint_for_custom_handler(client, user, micropub_url, monkeypatch):
    class CustomConfigHandler(InMemoryMicropubHandler):
        def get_config(self, user):
            return {"syndicate-to": [], "custom": True}

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: CustomConfigHandler())
    token = _make_token(user, None)

    response = client.get(f"{micropub_url}?q=config", Authorization=f"Bearer {token.key}")

    assert response.status_code == 200
    config = json.loads(response.content)
    assert config["custom"] is True
    assert config["media-endpoint"] == "http://testserver/indieweb/media/"


@pytest.mark.django_db
def test_micropub_config_preserves_custom_handler_media_endpoint(client, user, micropub_url, monkeypatch):
    class CustomConfigHandler(InMemoryMicropubHandler):
        def get_config(self, user):
            return {"media-endpoint": "https://cdn.example.org/micropub-media/"}

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: CustomConfigHandler())
    token = _make_token(user, None)

    response = client.get(f"{micropub_url}?q=config", Authorization=f"Bearer {token.key}")

    assert response.status_code == 200
    config = json.loads(response.content)
    assert config["media-endpoint"] == "https://cdn.example.org/micropub-media/"


@pytest.mark.django_db
def test_micropub_create_still_ignores_multipart_files(client, user, micropub_url, monkeypatch):
    received_properties = None

    class CapturingHandler(InMemoryMicropubHandler):
        def create_entry(self, properties, user):
            nonlocal received_properties
            received_properties = properties
            return super().create_entry(properties, user)

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: CapturingHandler())
    token = _make_token(user, "create")

    response = client.post(
        micropub_url,
        data={"h": "entry", "content": "Still a normal create", "photo": _upload()},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 201
    assert received_properties == {"content": ["Still a normal create"]}
