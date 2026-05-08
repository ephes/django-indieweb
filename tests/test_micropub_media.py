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
from indieweb.handlers import InMemoryMicropubHandler, MicropubMediaItem, MicropubMediaList

JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00jpeg"
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRpng"
GIF_BYTES = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff"


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
    name: str = "sunset.jpg", content: bytes = JPEG_BYTES, content_type: str = "image/jpeg"
) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type=content_type)


class _MediaHookHandler(InMemoryMicropubHandler):
    def __init__(self):
        super().__init__()
        self.media_items = [
            MicropubMediaItem(
                url="https://example.org/media/photo.jpg",
                properties={
                    "url": ["https://example.org/media/photo.jpg"],
                    "name": ["photo.jpg"],
                    "media-type": ["photo"],
                },
            ),
            MicropubMediaItem(
                url="https://example.org/media/audio.mp3",
                properties={
                    "url": ["https://example.org/media/audio.mp3"],
                    "name": ["audio.mp3"],
                    "media-type": ["audio"],
                },
            ),
        ]
        self.deleted_urls: list[str] = []

    def list_media(self, user, *, limit=None, offset=0, filter=None):
        items = list(self.media_items)
        if filter:
            needle = filter.lower()
            items = [item for item in items if needle in json.dumps(item.properties, sort_keys=True).lower()]
        total = len(items)
        if offset:
            items = items[offset:]
        if limit is not None:
            items = items[:limit]
        return MicropubMediaList(items=items, total=total)

    def get_media(self, url, user):
        for item in self.media_items:
            if item.url == url:
                return item
        return None

    def delete_media(self, url, user):
        if self.get_media(url, user) is None:
            return False
        self.deleted_urls.append(url)
        return True


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
        assert stored_file.read() == JPEG_BYTES


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
def test_media_upload_without_filename_suffix_uses_validated_content_type_suffix(
    client, settings, tmp_path, user, media_url
):
    settings.MEDIA_ROOT = str(tmp_path)
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": _upload(name="upload", content=PNG_BYTES, content_type="image/png")},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 201
    stored_name = urlparse(response["Location"]).path.removeprefix(settings.MEDIA_URL)
    assert stored_name.startswith("indieweb/media/")
    assert stored_name.endswith(".png")
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
@pytest.mark.parametrize("scope", [None, "", "create", "post", "update", "delete", "mediaXYZ", "create_media"])
def test_media_source_query_requires_media_scope(client, user, media_url, scope):
    token = _make_token(user, scope)

    response = client.get(f"{media_url}?q=source", Authorization=f"Bearer {token.key}")

    assert response.status_code == 403
    assert response.content.decode("utf-8") == "authorization error"


@pytest.mark.django_db
@pytest.mark.parametrize("scope", [None, "", "create", "post", "update", "delete", "mediaXYZ", "create_media"])
def test_media_delete_action_requires_media_scope(client, user, media_url, scope):
    token = _make_token(user, scope)

    response = client.post(
        media_url,
        data={"action": "delete", "url": "https://example.org/media/photo.jpg"},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 403
    assert response.content.decode("utf-8") == "authorization error"


@pytest.mark.django_db
def test_media_source_query_requires_q_parameter(client, user, media_url):
    token = _make_token(user, "media")

    response = client.get(media_url, Authorization=f"Bearer {token.key}")

    assert response.status_code == 400
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_media_source_query_rejects_unsupported_query(client, user, media_url):
    token = _make_token(user, "media")

    response = client.get(f"{media_url}?q=config", Authorization=f"Bearer {token.key}")

    assert response.status_code == 501
    assert response.content.decode("utf-8") == "not_implemented"


@pytest.mark.django_db
def test_media_source_query_without_hook_returns_not_implemented(client, user, media_url):
    token = _make_token(user, "media")

    response = client.get(f"{media_url}?q=source", Authorization=f"Bearer {token.key}")

    assert response.status_code == 501
    assert response.content.decode("utf-8") == "not_implemented"


@pytest.mark.django_db
def test_media_source_query_list_returns_media_items(client, monkeypatch, user, media_url):
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: _MediaHookHandler())
    token = _make_token(user, "media")

    response = client.get(
        f"{media_url}?q=source&filter=photo&limit=1&offset=0",
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response.json() == {
        "items": [
            {
                "properties": {
                    "url": ["https://example.org/media/photo.jpg"],
                    "name": ["photo.jpg"],
                    "media-type": ["photo"],
                }
            }
        ],
        "paging": {"limit": 1, "offset": 0, "total": 1},
    }


@pytest.mark.django_db
def test_media_source_query_list_omits_total_when_unknown(client, monkeypatch, user, media_url):
    class NoTotalMediaHandler(_MediaHookHandler):
        def list_media(self, user, *, limit=None, offset=0, filter=None):
            return MicropubMediaList(items=self.media_items[:1])

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: NoTotalMediaHandler())
    token = _make_token(user, "media")

    response = client.get(f"{media_url}?q=source", Authorization=f"Bearer {token.key}")

    assert response.status_code == 200
    assert response.json()["paging"] == {"limit": None, "offset": 0}


@pytest.mark.django_db
def test_media_source_query_by_url_returns_media_metadata(client, monkeypatch, user, media_url):
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: _MediaHookHandler())
    token = _make_token(user, "media")

    response = client.get(
        f"{media_url}?q=source&url=https://example.org/media/photo.jpg",
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response.json() == {
        "properties": {
            "url": ["https://example.org/media/photo.jpg"],
            "name": ["photo.jpg"],
            "media-type": ["photo"],
        }
    }


@pytest.mark.django_db
def test_media_source_query_by_url_adds_url_property_when_missing(client, monkeypatch, user, media_url):
    class MissingUrlPropertyHandler(_MediaHookHandler):
        def get_media(self, url, user):
            return MicropubMediaItem(url=url, properties={"name": ["photo.jpg"]})

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: MissingUrlPropertyHandler())
    token = _make_token(user, "media")

    response = client.get(
        f"{media_url}?q=source&url=https://example.org/media/photo.jpg",
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 200
    assert response.json() == {"properties": {"name": ["photo.jpg"], "url": ["https://example.org/media/photo.jpg"]}}


@pytest.mark.django_db
def test_media_source_query_by_url_without_hook_returns_not_implemented(client, user, media_url):
    token = _make_token(user, "media")

    response = client.get(
        f"{media_url}?q=source&url=https://example.org/media/photo.jpg",
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 501
    assert response.content.decode("utf-8") == "not_implemented"


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["url=", "limit=bad", "limit=-1", "offset=bad", "offset=-1"])
def test_media_source_query_rejects_empty_url_or_malformed_paging(client, monkeypatch, user, media_url, query):
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: _MediaHookHandler())
    token = _make_token(user, "media")

    response = client.get(f"{media_url}?q=source&{query}", Authorization=f"Bearer {token.key}")

    assert response.status_code == 400
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_media_source_query_rejects_unknown_url(client, monkeypatch, user, media_url):
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: _MediaHookHandler())
    token = _make_token(user, "media")

    response = client.get(
        f"{media_url}?q=source&url=https://example.org/media/missing.jpg",
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 400
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_media_source_query_returns_invalid_request_for_hook_value_error(client, monkeypatch, user, media_url):
    class RejectingMediaHandler(_MediaHookHandler):
        def get_media(self, url, user):
            raise ValueError("not host-owned")

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: RejectingMediaHandler())
    token = _make_token(user, "media")

    response = client.get(
        f"{media_url}?q=source&url=https://example.org/media/photo.jpg",
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 400
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_media_source_query_unexpected_hook_exception_returns_500(client, caplog, monkeypatch, user, media_url):
    class BrokenMediaHandler(_MediaHookHandler):
        def list_media(self, user, *, limit=None, offset=0, filter=None):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: BrokenMediaHandler())
    token = _make_token(user, "media")

    response = client.get(f"{media_url}?q=source", Authorization=f"Bearer {token.key}")

    assert response.status_code == 500
    assert "Unexpected error in list_media" in caplog.text


@pytest.mark.django_db
def test_media_delete_without_hook_returns_not_implemented(client, user, media_url):
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"action": "delete", "url": "https://example.org/media/photo.jpg"},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 501
    assert response.content.decode("utf-8") == "not_implemented"


@pytest.mark.django_db
def test_media_delete_with_hook_returns_no_content(client, monkeypatch, user, media_url):
    handler = _MediaHookHandler()
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler)
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"action": "delete", "url": "https://example.org/media/photo.jpg"},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 204
    assert response.content == b""
    assert handler.deleted_urls == ["https://example.org/media/photo.jpg"]


@pytest.mark.django_db
def test_media_delete_accepts_json_body(client, monkeypatch, user, media_url):
    handler = _MediaHookHandler()
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler)
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data=json.dumps({"action": "delete", "url": "https://example.org/media/photo.jpg"}),
        content_type="application/json",
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 204
    assert handler.deleted_urls == ["https://example.org/media/photo.jpg"]


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [{"action": "delete"}, {"action": "delete", "url": ""}])
def test_media_delete_rejects_missing_or_empty_url(client, monkeypatch, user, media_url, payload):
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: _MediaHookHandler())
    token = _make_token(user, "media")

    response = client.post(media_url, data=payload, Authorization=f"Bearer {token.key}")

    assert response.status_code == 400
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_media_delete_rejects_unknown_url(client, monkeypatch, user, media_url):
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: _MediaHookHandler())
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"action": "delete", "url": "https://example.org/media/missing.jpg"},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 400
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_media_delete_returns_invalid_request_for_hook_value_error(client, monkeypatch, user, media_url):
    class RejectingMediaHandler(_MediaHookHandler):
        def delete_media(self, url, user):
            raise ValueError("not host-owned")

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: RejectingMediaHandler())
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"action": "delete", "url": "https://example.org/media/photo.jpg"},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 400
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_media_delete_unexpected_hook_exception_returns_500(client, caplog, monkeypatch, user, media_url):
    class BrokenMediaHandler(_MediaHookHandler):
        def delete_media(self, url, user):
            raise RuntimeError("storage unavailable")

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: BrokenMediaHandler())
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"action": "delete", "url": "https://example.org/media/photo.jpg"},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 500
    assert "Unexpected error in delete_media" in caplog.text


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
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_BYTES = len(JPEG_BYTES)
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": _upload()},
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
        data={"file": _upload()},
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
def test_media_upload_rejects_declared_and_sniffed_mismatch(client, settings, tmp_path, user, media_url):
    settings.MEDIA_ROOT = str(tmp_path)
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": _upload(name="photo.png", content=JPEG_BYTES, content_type="image/png")},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 415
    assert response.content.decode("utf-8") == "invalid_request"
    assert not (tmp_path / "indieweb").exists()


@pytest.mark.django_db
def test_media_upload_rejects_filename_suffix_mismatch_before_storage(client, settings, tmp_path, user, media_url):
    settings.MEDIA_ROOT = str(tmp_path)
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": _upload(name="photo.phtml", content=JPEG_BYTES, content_type="image/jpeg")},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 415
    assert response.content.decode("utf-8") == "invalid_request"
    assert not (tmp_path / "indieweb").exists()


@pytest.mark.django_db
def test_media_upload_rejects_svg_disguised_as_allowed_media(client, settings, tmp_path, user, media_url):
    settings.MEDIA_ROOT = str(tmp_path)
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={
            "file": _upload(
                name="image.jpg",
                content=b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
                content_type="image/jpeg",
            )
        },
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 415
    assert response.content.decode("utf-8") == "invalid_request"
    assert not (tmp_path / "indieweb").exists()


@pytest.mark.django_db
def test_media_upload_uses_preferred_suffix_from_validated_content_type(client, settings, tmp_path, user, media_url):
    settings.MEDIA_ROOT = str(tmp_path)
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": _upload(name="photo.jpeg", content=JPEG_BYTES, content_type="image/jpeg")},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 201
    stored_name = urlparse(response["Location"]).path.removeprefix(settings.MEDIA_URL)
    assert stored_name.endswith(".jpg")
    assert not stored_name.endswith(".jpeg")


@pytest.mark.django_db
def test_media_upload_rejects_upload_count_over_configured_limit(client, settings, user, media_url):
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_COUNT = 1
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": [_upload(name="one.jpg"), _upload(name="two.jpg")]},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 413
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_media_upload_rejects_aggregate_size_over_configured_limit(client, settings, user, media_url):
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_TOTAL_BYTES = len(JPEG_BYTES) - 1
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": _upload()},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 413
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_media_upload_allows_configured_sniffed_content_type(client, settings, tmp_path, user, media_url):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.INDIEWEB_MEDIA_ALLOWED_TYPES = ("image/gif",)
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": _upload(name="note.gif", content=GIF_BYTES, content_type="image/gif")},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_media_upload_can_disable_allowlist_for_valid_sniffed_media(client, settings, tmp_path, user, media_url):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.INDIEWEB_MEDIA_ALLOWED_TYPES = None
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": _upload()},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_media_upload_disabling_allowlist_still_rejects_unsniffable_html(client, settings, tmp_path, user, media_url):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.INDIEWEB_MEDIA_ALLOWED_TYPES = None
    token = _make_token(user, "media")

    response = client.post(
        media_url,
        data={"file": _upload(name="page.html", content=b"<!doctype html><h1>x</h1>", content_type="text/html")},
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 415
    assert response.content.decode("utf-8") == "invalid_request"
    assert not (tmp_path / "indieweb").exists()


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
                _upload(name="first.jpg", content=JPEG_BYTES, content_type="image/jpeg"),
                _upload(name="second.png", content=PNG_BYTES, content_type="image/png"),
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
def test_micropub_create_rejects_photo_upload_count_over_configured_limit(
    client, settings, user, micropub_url, monkeypatch
):
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_COUNT = 1

    class FailingHandler(InMemoryMicropubHandler):
        def create_entry(self, properties, user):
            raise AssertionError("create_entry must not run after upload validation fails")

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: FailingHandler())
    token = _make_token(user, "create")

    response = client.post(
        micropub_url,
        data={
            "h": "entry",
            "content": "Too many photos",
            "photo": [_upload(name="one.jpg"), _upload(name="two.jpg")],
        },
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 413
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_micropub_create_rejects_photo_aggregate_size_over_configured_limit(
    client, settings, user, micropub_url, monkeypatch
):
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_TOTAL_BYTES = (len(JPEG_BYTES) * 2) - 1

    class FailingHandler(InMemoryMicropubHandler):
        def create_entry(self, properties, user):
            raise AssertionError("create_entry must not run after upload validation fails")

    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: FailingHandler())
    token = _make_token(user, "create")

    response = client.post(
        micropub_url,
        data={
            "h": "entry",
            "content": "Too large together",
            "photo": [_upload(name="one.jpg"), _upload(name="two.jpg")],
        },
        Authorization=f"Bearer {token.key}",
    )

    assert response.status_code == 413
    assert response.content.decode("utf-8") == "invalid_request"


@pytest.mark.django_db
def test_micropub_create_validates_all_photo_uploads_before_storing(
    client, settings, tmp_path, user, micropub_url, monkeypatch
):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_BYTES = len(JPEG_BYTES)

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
                _upload(name="valid.jpg", content=JPEG_BYTES),
                _upload(name="too-large.jpg", content=JPEG_BYTES + b"extra"),
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
                _upload(name="first.jpg", content=JPEG_BYTES),
                _upload(name="second.jpg", content=JPEG_BYTES),
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


@pytest.mark.django_db
def test_media_source_by_url_rejected_by_policy(client, monkeypatch, user, media_url, settings):
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: _MediaHookHandler())
    settings.INDIEWEB_MICROPUB_URL_POLICY = "tests.micropub_policies.reject_all"
    token = _make_token(user, "media")
    response = client.get(
        media_url,
        data={"q": "source", "url": "https://outside.example/media/photo.jpg"},
        Authorization=f"Bearer {token.key}",
    )
    assert response.status_code == 400
    assert b"invalid_request" in response.content


@pytest.mark.django_db
def test_media_source_by_url_policy_runtime_error_returns_500(client, monkeypatch, user, media_url, settings, caplog):
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: _MediaHookHandler())
    settings.INDIEWEB_MICROPUB_URL_POLICY = "tests.micropub_policies.raise_runtime"
    token = _make_token(user, "media")
    with caplog.at_level("ERROR"):
        response = client.get(
            media_url,
            data={"q": "source", "url": "https://outside.example/media/photo.jpg"},
            Authorization=f"Bearer {token.key}",
        )
    assert response.status_code == 500
    assert b"policy explosion" not in response.content
    assert "policy explosion" in caplog.text


@pytest.mark.django_db
def test_media_source_by_url_policy_import_error_returns_500(client, monkeypatch, user, media_url, settings):
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: _MediaHookHandler())
    settings.INDIEWEB_MICROPUB_URL_POLICY = "tests.does_not_exist.missing_callable"
    token = _make_token(user, "media")
    response = client.get(
        media_url,
        data={"q": "source", "url": "https://outside.example/media/photo.jpg"},
        Authorization=f"Bearer {token.key}",
    )
    assert response.status_code == 500


@pytest.mark.django_db
def test_media_delete_by_url_rejected_by_policy(client, monkeypatch, user, media_url, settings):
    handler = _MediaHookHandler()
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler)
    settings.INDIEWEB_MICROPUB_URL_POLICY = "tests.micropub_policies.reject_all"
    token = _make_token(user, "media")
    response = client.post(
        media_url,
        data={"action": "delete", "url": "https://example.org/media/photo.jpg"},
        Authorization=f"Bearer {token.key}",
    )
    assert response.status_code == 400
    assert b"invalid_request" in response.content
    # Policy must reject before the handler runs.
    assert handler.deleted_urls == []


@pytest.mark.django_db
def test_media_delete_by_url_policy_runtime_error_returns_500(client, monkeypatch, user, media_url, settings, caplog):
    handler = _MediaHookHandler()
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler)
    settings.INDIEWEB_MICROPUB_URL_POLICY = "tests.micropub_policies.raise_runtime"
    token = _make_token(user, "media")
    with caplog.at_level("ERROR"):
        response = client.post(
            media_url,
            data={"action": "delete", "url": "https://example.org/media/photo.jpg"},
            Authorization=f"Bearer {token.key}",
        )
    assert response.status_code == 500
    assert b"policy explosion" not in response.content
    assert "policy explosion" in caplog.text
    assert handler.deleted_urls == []
