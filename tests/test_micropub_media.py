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
def test_media_upload_location_can_feed_json_micropub_create(
    client, settings, tmp_path, user, media_url, micropub_url, monkeypatch
):
    settings.MEDIA_ROOT = str(tmp_path)
    token = _make_token(user, "create media")

    media_response = client.post(
        media_url,
        data={"file": _upload()},
        Authorization=f"Bearer {token.key}",
    )

    assert media_response.status_code == 201
    assert media_response.content == b""
    media_location = media_response["Location"]
    parsed_media_location = urlparse(media_location)
    assert parsed_media_location.scheme in {"http", "https"}
    assert parsed_media_location.netloc
    assert parsed_media_location.path.startswith(settings.MEDIA_URL)
    stored_name = parsed_media_location.path.removeprefix(settings.MEDIA_URL)
    assert default_storage.exists(stored_name)

    received_properties = None

    class CapturingHandler(InMemoryMicropubHandler):
        def create_entry(self, properties, user):
            nonlocal received_properties
            received_properties = properties
            return super().create_entry(properties, user)

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: CapturingHandler())
    create_response = client.post(
        micropub_url,
        data=json.dumps(
            {
                "type": ["h-entry"],
                "properties": {
                    "content": ["Photo post"],
                    "photo": [media_location],
                },
            }
        ),
        content_type="application/json",
        Authorization=f"Bearer {token.key}",
    )

    assert create_response.status_code == 201
    parsed_create_location = urlparse(create_response["Location"])
    assert parsed_create_location.scheme in {"http", "https"}
    assert parsed_create_location.netloc
    assert received_properties is not None
    assert received_properties["photo"] == [media_location]


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
def test_micropub_create_stores_photo_upload_and_passes_photo_url(
    client, settings, tmp_path, user, micropub_url, monkeypatch
):
    settings.MEDIA_ROOT = str(tmp_path)
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
        data={"h": "entry", "content": "Photo create", "photo": _upload()},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 201
    assert received_properties is not None
    assert received_properties["content"] == ["Photo create"]
    assert len(received_properties["photo"]) == 1
    parsed = urlparse(received_properties["photo"][0])
    assert parsed.scheme in {"http", "https"}
    assert parsed.netloc
    stored_name = parsed.path.removeprefix(settings.MEDIA_URL)
    assert stored_name.startswith("indieweb/media/")
    assert stored_name.endswith(".jpg")
    assert default_storage.exists(stored_name)


@pytest.mark.django_db
def test_micropub_create_stores_multiple_photo_uploads(client, settings, tmp_path, user, micropub_url, monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path)
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
        data={
            "h": "entry",
            "content": "Multiple photos",
            "photo": [
                _upload(name="first.jpg", content=b"first", content_type="image/jpeg"),
                _upload(name="second.png", content=b"second", content_type="image/png"),
            ],
        },
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 201
    assert received_properties is not None
    assert len(received_properties["photo"]) == 2
    stored_names = [
        urlparse(photo_url).path.removeprefix(settings.MEDIA_URL) for photo_url in received_properties["photo"]
    ]
    assert stored_names[0].endswith(".jpg")
    assert stored_names[1].endswith(".png")
    assert all(default_storage.exists(stored_name) for stored_name in stored_names)


@pytest.mark.django_db
def test_micropub_create_preserves_photo_url_and_appends_uploaded_photo(
    client, settings, tmp_path, user, micropub_url, monkeypatch
):
    settings.MEDIA_ROOT = str(tmp_path)
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
        data={
            "h": "entry",
            "content": "Mixed photos",
            "photo": ["https://photos.example.org/existing.jpg", _upload()],
        },
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 201
    assert received_properties is not None
    assert len(received_properties["photo"]) == 2
    assert received_properties["photo"][0] == "https://photos.example.org/existing.jpg"
    uploaded_url = received_properties["photo"][1]
    assert uploaded_url.startswith("http://testserver")
    assert default_storage.exists(urlparse(uploaded_url).path.removeprefix(settings.MEDIA_URL))


@pytest.mark.django_db
def test_micropub_create_rejects_oversized_photo_upload(client, settings, user, micropub_url, monkeypatch):
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_BYTES = 4

    class FailingHandler(InMemoryMicropubHandler):
        def create_entry(self, properties, user):
            raise AssertionError("create_entry must not run after upload validation fails")

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: FailingHandler())
    token = _make_token(user, "create")

    response = client.post(
        micropub_url,
        data={"h": "entry", "content": "Too large", "photo": _upload(content=b"12345")},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 413
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_micropub_create_validates_all_photo_uploads_before_storing(
    client, settings, tmp_path, user, micropub_url, monkeypatch
):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_BYTES = 4

    class FailingHandler(InMemoryMicropubHandler):
        def create_entry(self, properties, user):
            raise AssertionError("create_entry must not run after upload validation fails")

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: FailingHandler())
    token = _make_token(user, "create")

    response = client.post(
        micropub_url,
        data={
            "h": "entry",
            "content": "Partially invalid",
            "photo": [
                _upload(name="valid.jpg", content=b"1234"),
                _upload(name="too-large.jpg", content=b"12345"),
            ],
        },
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 413
    assert response.content.decode("utf-8") == "invalid_request"
    assert not (tmp_path / "indieweb").exists()


@pytest.mark.django_db
def test_micropub_create_rejects_disallowed_photo_content_type(client, user, micropub_url, monkeypatch):
    class FailingHandler(InMemoryMicropubHandler):
        def create_entry(self, properties, user):
            raise AssertionError("create_entry must not run after upload validation fails")

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: FailingHandler())
    token = _make_token(user, "create")

    response = client.post(
        micropub_url,
        data={"h": "entry", "content": "Wrong type", "photo": _upload(name="page.html", content_type="text/html")},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 415
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_micropub_create_storage_os_error_returns_500(client, monkeypatch, user, micropub_url):
    def fail_save(name, content, max_length=None):
        raise OSError("storage unavailable")

    monkeypatch.setattr("indieweb.views.default_storage.save", fail_save)

    class FailingHandler(InMemoryMicropubHandler):
        def create_entry(self, properties, user):
            raise AssertionError("create_entry must not run after storage fails")

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: FailingHandler())
    token = _make_token(user, "create")

    response = client.post(
        micropub_url,
        data={"h": "entry", "content": "Storage failure", "photo": _upload()},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 500


@pytest.mark.django_db
def test_micropub_create_cleans_up_saved_photo_when_later_save_fails(
    client, settings, tmp_path, monkeypatch, user, micropub_url
):
    settings.MEDIA_ROOT = str(tmp_path)
    original_save = default_storage.save
    saved_names = []

    def fail_second_save(name, content, max_length=None):
        if saved_names:
            raise OSError("storage unavailable")
        stored_name = original_save(name, content, max_length=max_length)
        saved_names.append(stored_name)
        return stored_name

    monkeypatch.setattr("indieweb.views.default_storage.save", fail_second_save)

    class FailingHandler(InMemoryMicropubHandler):
        def create_entry(self, properties, user):
            raise AssertionError("create_entry must not run after storage fails")

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: FailingHandler())
    token = _make_token(user, "create")

    response = client.post(
        micropub_url,
        data={
            "h": "entry",
            "content": "Storage failure",
            "photo": [
                _upload(name="first.jpg", content=b"first"),
                _upload(name="second.jpg", content=b"second"),
            ],
        },
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 500
    assert len(saved_names) == 1
    assert not default_storage.exists(saved_names[0])


@pytest.mark.django_db
@pytest.mark.parametrize("scope", ["create", "post"])
def test_micropub_create_photo_upload_uses_create_or_post_scope(client, settings, tmp_path, user, micropub_url, scope):
    settings.MEDIA_ROOT = str(tmp_path)
    token = _make_token(user, scope)

    response = client.post(
        micropub_url,
        data={"h": "entry", "content": "Scoped upload", "photo": _upload()},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_micropub_create_photo_upload_rejects_missing_create_or_post_scope(client, user, micropub_url):
    token = _make_token(user, "media")

    response = client.post(
        micropub_url,
        data={"h": "entry", "content": "Wrong scope", "photo": _upload()},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 403
    assert response.content.decode("utf-8") == "authorization error"
