"""Synthetic ownership and CORS regressions through Micropub endpoints."""

import pytest
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.urls import reverse

from indieweb.cors import _add_cors_headers, get_cors_config
from indieweb.handlers import InMemoryMicropubHandler
from indieweb.models import Token

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00synthetic"
ORIGIN = "https://client.example/"


def _photo():
    return SimpleUploadedFile("synthetic.jpg", JPEG, content_type="image/jpeg")


@pytest.fixture
def publication(db, settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = tmp_path
    settings.MEDIA_URL = "/media/"
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = [ORIGIN]
    user = User.objects.create(username="synthetic-publication")
    grant = Token.objects.create(owner=user, me="https://source.example/", client_id=ORIGIN, scope="create media")
    handler = InMemoryMicropubHandler()
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler)
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("synthetic pre-existing object")
    return grant, handler, tmp_path, unrelated


def _files(root):
    return {p for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("endpoint,count,fail_at", [("media", 1, 1), ("micropub", 2, 1), ("micropub", 2, 2)])
@pytest.mark.parametrize("failure", ["storage_url", "absolute_url"])
def test_url_failure_compensates_only_owned_uploads(
    client, publication, monkeypatch, endpoint, count, fail_at, failure
):
    grant, handler, root, unrelated = publication
    calls = []
    if failure == "storage_url":
        original = default_storage.url

        def url(name):
            calls.append(name)
            if len(calls) == fail_at:
                raise ValueError("synthetic URL failure")
            return original(name)

        monkeypatch.setattr(default_storage, "url", url)
    else:
        from django.http import HttpRequest

        original = HttpRequest.build_absolute_uri

        def absolute(request, location=None):
            if location and str(location).startswith("/media/"):
                calls.append(location)
                if len(calls) == fail_at:
                    raise ValueError("synthetic absolute URL failure")
            return original(request, location)

        monkeypatch.setattr(HttpRequest, "build_absolute_uri", absolute)
    data = {"file": _photo()} if endpoint == "media" else {"h": "entry", "photo": [_photo() for _ in range(count)]}
    client.raise_request_exception = False
    response = client.post(reverse(f"indieweb:{endpoint}"), data, Authorization=f"Bearer {grant.key}")
    assert response.status_code == 500
    assert len(calls) == fail_at
    assert _files(root) == {unrelated}
    assert handler.entries == {}


@pytest.mark.parametrize("failure", ["validation", "value_error", "unexpected", "success"])
def test_inline_photo_ownership_follows_entry_creation(client, publication, monkeypatch, failure):
    grant, handler, root, unrelated = publication
    calls = []
    original = handler.create_entry

    def create(properties, user):
        calls.append(properties)
        if failure == "value_error":
            raise ValueError("synthetic rejected create")
        if failure == "unexpected":
            raise RuntimeError("synthetic create failure")
        return original(properties, user)

    monkeypatch.setattr(handler, "create_entry", create)
    data = {"h": "entry", "content": "synthetic", "photo": _photo()}
    if failure == "validation":
        data["in-reply-to"] = "javascript:invalid"
    response = client.post(reverse("indieweb:micropub"), data, Authorization=f"Bearer {grant.key}")
    expected = {"validation": 400, "value_error": 400, "unexpected": 500, "success": 201}[failure]
    assert response.status_code == expected
    assert len(calls) == (0 if failure == "validation" else 1)
    assert len(_files(root)) == (2 if failure == "success" else 1)
    assert unrelated.exists()


@pytest.mark.parametrize("endpoint", ["media", "micropub"])
@pytest.mark.parametrize("origin", [ORIGIN, "https://disallowed.example/", None])
def test_created_location_is_exposed_only_for_allowed_origins(client, publication, settings, endpoint, origin):
    grant, handler, root, unrelated = publication
    if origin is None:
        settings.INDIEWEB_CORS_ALLOWED_ORIGINS = []
    data = {"file": _photo()} if endpoint == "media" else {"h": "entry", "content": "synthetic"}
    response = client.post(
        reverse(f"indieweb:{endpoint}"), data, Authorization=f"Bearer {grant.key}", HTTP_ORIGIN=origin or ORIGIN
    )
    assert response.status_code == 201
    assert response["Location"]
    if origin == ORIGIN:
        exposed = response.get("Access-Control-Expose-Headers", "")
        assert "location" in [v.strip().lower() for v in exposed.split(",")]
    else:
        assert "Access-Control-Expose-Headers" not in response
        assert "Access-Control-Allow-Origin" not in response


@pytest.mark.parametrize("existing_origin", [None, ORIGIN])
def test_location_exposure_merges_existing_headers(settings, existing_origin):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = [ORIGIN]
    response = HttpResponse(headers={"Access-Control-Expose-Headers": "ETag, X-Request-ID"})
    if existing_origin:
        response["Access-Control-Allow-Origin"] = existing_origin
    _add_cors_headers(response, get_cors_config(), ORIGIN)
    exposed = [v.strip().lower() for v in response["Access-Control-Expose-Headers"].split(",")]
    assert exposed == ["etag", "x-request-id", "location"]
    _add_cors_headers(response, get_cors_config(), ORIGIN)
    assert [v.strip().lower() for v in response["Access-Control-Expose-Headers"].split(",")].count("location") == 1


def test_created_entry_keeps_photo_if_response_url_fails(client, publication, monkeypatch):
    from django.http import HttpRequest

    grant, handler, root, unrelated = publication
    original = HttpRequest.build_absolute_uri
    failures = []

    def absolute(request, location=None):
        if location and str(location).startswith("/entries/"):
            failures.append(location)
            raise ValueError("synthetic response URL failure")
        return original(request, location)

    monkeypatch.setattr(HttpRequest, "build_absolute_uri", absolute)
    client.raise_request_exception = False
    response = client.post(
        reverse("indieweb:micropub"), {"h": "entry", "photo": _photo()}, Authorization=f"Bearer {grant.key}"
    )
    assert response.status_code == 500
    assert len(failures) == 1
    assert len(handler.entries) == 1
    assert len(_files(root)) == 2
    assert unrelated.exists()
