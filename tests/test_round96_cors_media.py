"""Configuration domain and owned media-byte snapshot regressions."""

from io import BytesIO
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import UploadedFile
from django.urls import reverse

from indieweb.cors import DEFAULT_CORS_ALLOWED_HEADERS, get_cors_config
from indieweb.views import _MicropubMediaUploadError, _store_micropub_media_uploads
from tests.test_micropub_media import JPEG_BYTES

ORIGIN = "https://client.example.test"


@pytest.mark.parametrize("value", ["false", "true", 1, [], {"enabled": True}])
def test_credentials_require_explicit_boolean(settings, value, caplog):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = [ORIGIN]
    settings.INDIEWEB_CORS_ALLOW_CREDENTIALS = value
    assert get_cors_config().allow_credentials is False
    assert "INDIEWEB_CORS_ALLOW_CREDENTIALS" in caplog.text


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"), 1.5, True])
def test_invalid_max_age_is_omitted_in_preflight(client, settings, value):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = [ORIGIN]
    settings.INDIEWEB_CORS_MAX_AGE = value
    response = client.options(reverse("indieweb:token"), HTTP_ORIGIN=ORIGIN, HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
    assert response.status_code == 204
    assert "Access-Control-Max-Age" not in response


@pytest.mark.parametrize("value", [0, 42, "42", 42.0])
def test_integral_max_age(settings, value):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = [ORIGIN]
    settings.INDIEWEB_CORS_MAX_AGE = value
    assert get_cors_config().max_age == int(value)


@pytest.mark.parametrize("value", ["X-Test\r\nInjected: true", ["X-Test\n"], ["Bad Header"], ["X-é"]])
def test_invalid_advertised_header_falls_back(client, settings, value):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = [ORIGIN]
    settings.INDIEWEB_CORS_ALLOWED_HEADERS = value
    response = client.options(reverse("indieweb:token"), HTTP_ORIGIN=ORIGIN, HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
    assert response.status_code == 204
    assert response["Access-Control-Allow-Headers"] == ", ".join(DEFAULT_CORS_ALLOWED_HEADERS)


@pytest.mark.parametrize(
    "value", ["https://client.test\r\nX: yes", ["https://client.test\n"], ["https://client.test\u2603"]]
)
def test_unsafe_origin_configuration_disables_cors(settings, value):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = value
    assert get_cors_config() is None


class ShortReadStream(BytesIO):
    def read(self, size=-1):
        return super().read(min(size, 3) if size >= 0 else 3)


class ChangingStream(BytesIO):
    """A rewind after reading exposes a different, invented generation."""

    read_started = False

    def read(self, size=-1):
        self.read_started = True
        return super().read(size)

    def seek(self, position, whence=0):
        if self.read_started and position == 0:
            self.read_started = False
            super().seek(0)
            self.truncate()
            self.write(b"<html>changed generation</html>")
        return super().seek(position, whence)


def upload(stream, size=1):
    return UploadedFile(file=stream, name="synthetic.jpg", size=size, content_type="image/jpeg")


@pytest.mark.parametrize("aggregate", [False, True])
def test_actual_upload_size_is_bounded_before_any_storage(settings, rf, aggregate):
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_BYTES = len(JPEG_BYTES) if not aggregate else None
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_TOTAL_BYTES = len(JPEG_BYTES) * 2 - 1 if aggregate else None
    files = [upload(BytesIO(JPEG_BYTES)) for _ in range(2)] if aggregate else [upload(BytesIO(JPEG_BYTES + b"x"))]
    with patch("indieweb.views.default_storage") as storage:
        storage.exists.return_value = False
        with pytest.raises(_MicropubMediaUploadError) as exc:
            _store_micropub_media_uploads(rf.post("/"), files)
    assert exc.value.status_code == 413
    assert not storage.mock_calls


@pytest.mark.parametrize("stream_type", [BytesIO, ShortReadStream, ChangingStream])
def test_only_admitted_snapshot_bytes_reach_storage(settings, rf, stream_type):
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_BYTES = len(JPEG_BYTES)
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_TOTAL_BYTES = len(JPEG_BYTES)
    seen = []
    saved_files = []

    def save(name, content):
        saved_files.append(content)
        seen.append(b"".join(content.chunks()))
        return name

    with patch("indieweb.views.default_storage") as storage:
        storage.exists.return_value = False
        storage.save.side_effect = save
        storage.url.return_value = "/media/synthetic.jpg"
        urls = _store_micropub_media_uploads(rf.post("/"), [upload(stream_type(JPEG_BYTES))])
    assert seen == [JPEG_BYTES]
    assert urls == ["http://testserver/media/synthetic.jpg"]
    assert all(content.closed for content in saved_files)


def test_snapshot_closed_when_later_upload_is_refused(rf):
    snapshots = []
    from indieweb import views

    original = views._validate_micropub_media_upload

    def validate(candidate):
        snapshots.append(candidate)
        return original(candidate)

    with patch.object(views, "_validate_micropub_media_upload", side_effect=validate):
        with pytest.raises(_MicropubMediaUploadError):
            _store_micropub_media_uploads(rf.post("/"), [upload(BytesIO(JPEG_BYTES)), upload(BytesIO(b"invalid"))])
    assert snapshots and all(candidate.closed for candidate in snapshots)


@pytest.mark.parametrize("failure", ["read", "storage"])
def test_owned_spool_closes_on_io_failure(rf, failure):
    from tempfile import SpooledTemporaryFile

    spools = []

    def spool(*args, **kwargs):
        result = SpooledTemporaryFile(*args, **kwargs)
        spools.append(result)
        return result

    class BrokenStream(BytesIO):
        def read(self, size=-1):
            raise OSError("synthetic read failure")

    stream = BrokenStream(JPEG_BYTES) if failure == "read" else BytesIO(JPEG_BYTES)
    with patch("indieweb.views.SpooledTemporaryFile", side_effect=spool):
        with patch("indieweb.views.default_storage") as storage:
            storage.exists.return_value = False
            storage.save.side_effect = OSError("synthetic storage failure")
            with pytest.raises(_MicropubMediaUploadError) as exc:
                _store_micropub_media_uploads(rf.post("/"), [upload(stream)])
    assert exc.value.status_code == 500
    assert spools and all(item.closed for item in spools)


def test_large_snapshot_spools_to_disk_and_closes(settings, rf):
    content = JPEG_BYTES + b"x" * (1024 * 1024)
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_BYTES = len(content)
    settings.INDIEWEB_MEDIA_MAX_UPLOAD_TOTAL_BYTES = len(content)
    saved = []

    def save(name, candidate):
        assert candidate.file._rolled
        assert b"".join(candidate.chunks()) == content
        saved.append(candidate)
        return name

    with patch("indieweb.views.default_storage") as storage:
        storage.exists.return_value = False
        storage.save.side_effect = save
        storage.url.return_value = "/media/synthetic.jpg"
        _store_micropub_media_uploads(rf.post("/"), [upload(BytesIO(content))])
    assert len(saved) == 1 and saved[0].closed
