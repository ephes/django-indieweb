"""Request-body size limit for the IndieAuth authorization and token endpoints."""

import io
import tempfile
from urllib.parse import parse_qs, urlencode

import pytest
from django.contrib.auth.models import User
from django.test import Client, RequestFactory
from django.urls import reverse

from indieweb import models
from indieweb.views import (
    DEFAULT_INDIEAUTH_MAX_BODY_BYTES,
    AuthView,
    TokenView,
    indieauth_max_body_bytes,
)

VIEWS = [
    pytest.param(AuthView, "indieweb:auth", id="auth"),
    pytest.param(TokenView, "indieweb:token", id="token"),
]


@pytest.fixture
def user(db):
    return User.objects.create_user(username="foo", email="foo@example.org", password="password")


@pytest.fixture
def auth(user):
    return models.Auth.objects.create(
        owner=user,
        key="authkey",
        state=1234567890,
        me="http://example.org",
        scope="post",
        client_id="https://webapp.example.org",
        redirect_uri="https://webapp.example.org/auth/callback",
    )


@pytest.fixture
def token_payload(auth):
    return {
        "redirect_uri": "https://webapp.example.org/auth/callback",
        "code": auth.key,
        "me": auth.me,
        "client_id": auth.client_id,
    }


def _dispatch(view_class, url_name, **extra):
    request = RequestFactory().post(
        reverse(url_name),
        data="code=x",
        content_type="application/x-www-form-urlencoded",
        **extra,
    )
    response = view_class.as_view()(request)
    return request, response


def _assert_rejected_unparsed(request, response):
    assert response.status_code == 413
    assert response["Cache-Control"] == "no-store"
    assert "_post" not in request.__dict__
    assert "_body" not in request.__dict__


def test_default_limit_is_64_kib():
    assert DEFAULT_INDIEAUTH_MAX_BODY_BYTES == 64 * 1024
    assert indieauth_max_body_bytes() == 64 * 1024


@pytest.mark.parametrize(("view_class", "url_name"), VIEWS)
def test_declared_length_over_limit_is_rejected_before_parsing(view_class, url_name):
    request, response = _dispatch(view_class, url_name, CONTENT_LENGTH=str(DEFAULT_INDIEAUTH_MAX_BODY_BYTES + 1))
    _assert_rejected_unparsed(request, response)


@pytest.mark.parametrize(("view_class", "url_name"), VIEWS)
@pytest.mark.parametrize("content_length", ["9" * 5000, "0" * 5000 + "6"])
def test_overlong_declared_length_is_rejected_without_int_conversion(view_class, url_name, content_length):
    request, response = _dispatch(view_class, url_name, CONTENT_LENGTH=content_length)
    _assert_rejected_unparsed(request, response)


@pytest.mark.parametrize(("view_class", "url_name"), VIEWS)
def test_zero_padded_length_under_limit_is_accepted(view_class, url_name, db):
    request, response = _dispatch(view_class, url_name, CONTENT_LENGTH="0006")
    assert response.status_code != 413


@pytest.mark.parametrize(("view_class", "url_name"), VIEWS)
@pytest.mark.parametrize("content_length", ["abc", "-1", "10, 10", "+10", "1_0", "١٠"])
def test_malformed_content_length_is_rejected(view_class, url_name, content_length):
    request, response = _dispatch(view_class, url_name, CONTENT_LENGTH=content_length)
    _assert_rejected_unparsed(request, response)


@pytest.mark.parametrize(("view_class", "url_name"), VIEWS)
@pytest.mark.parametrize("transfer_encoding", ["chunked", ""])
def test_transfer_encoding_is_rejected(view_class, url_name, transfer_encoding):
    request, response = _dispatch(view_class, url_name, HTTP_TRANSFER_ENCODING=transfer_encoding)
    _assert_rejected_unparsed(request, response)


@pytest.mark.parametrize(("view_class", "url_name"), VIEWS)
def test_spooled_buffer_over_limit_is_rejected_despite_understated_length(view_class, url_name):
    """ASGI buffers bodies in a SpooledTemporaryFile (no ``seekable()`` on Python 3.10)."""
    request = RequestFactory().post(reverse(url_name), data="", content_type="application/x-www-form-urlencoded")
    request.META["CONTENT_LENGTH"] = "1"
    spooled = tempfile.SpooledTemporaryFile(max_size=1024)
    spooled.write(b"a" * (DEFAULT_INDIEAUTH_MAX_BODY_BYTES + 1))
    spooled.seek(0)
    request._stream = spooled
    response = view_class.as_view()(request)
    _assert_rejected_unparsed(request, response)
    assert spooled.tell() == 0
    spooled.close()


@pytest.mark.django_db
@pytest.mark.parametrize(("view_class", "url_name"), VIEWS)
def test_empty_content_length_without_body_is_not_rejected(view_class, url_name):
    request = RequestFactory().post(reverse(url_name), data="", content_type="application/x-www-form-urlencoded")
    request.META["CONTENT_LENGTH"] = ""
    response = view_class.as_view()(request)
    assert response.status_code != 413


@pytest.mark.parametrize(("view_class", "url_name"), VIEWS)
def test_buffered_body_over_limit_is_rejected_despite_missing_length(view_class, url_name):
    """ASGI buffers the body in a seekable file; its real size counts even without Content-Length."""
    request = RequestFactory().post(reverse(url_name), data="", content_type="application/x-www-form-urlencoded")
    request.META.pop("CONTENT_LENGTH", None)
    request._stream = io.BytesIO(b"a" * (DEFAULT_INDIEAUTH_MAX_BODY_BYTES + 1))
    response = view_class.as_view()(request)
    _assert_rejected_unparsed(request, response)
    assert request._stream.tell() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(("view_class", "url_name"), VIEWS)
def test_missing_content_length_without_body_is_not_rejected(view_class, url_name):
    request = RequestFactory().post(reverse(url_name), data="", content_type="application/x-www-form-urlencoded")
    request.META.pop("CONTENT_LENGTH", None)
    response = view_class.as_view()(request)
    assert response.status_code != 413


@pytest.mark.django_db
@pytest.mark.parametrize(("view_class", "url_name"), VIEWS)
def test_configured_limit_applies(client, settings, view_class, url_name):
    settings.INDIEWEB_INDIEAUTH_MAX_BODY_BYTES = 10
    response = client.post(reverse(url_name), data={"code": "x" * 20})
    assert response.status_code == 413


@pytest.mark.django_db
def test_limit_can_be_disabled(client, settings, token_payload):
    settings.INDIEWEB_INDIEAUTH_MAX_BODY_BYTES = None
    token_payload["padding"] = "x" * (DEFAULT_INDIEAUTH_MAX_BODY_BYTES + 1)
    response = client.post(reverse("indieweb:token"), data=token_payload)
    assert response.status_code == 201


@pytest.mark.parametrize("value", ["", "abc", 0, -5, True])
def test_invalid_setting_falls_back_to_default(settings, value):
    settings.INDIEWEB_INDIEAUTH_MAX_BODY_BYTES = value
    assert indieauth_max_body_bytes() == DEFAULT_INDIEAUTH_MAX_BODY_BYTES


@pytest.mark.django_db
def test_multipart_token_exchange_under_limit_works(client, token_payload):
    """The test client posts multipart/form-data by default; it stays supported under the limit."""
    response = client.post(reverse("indieweb:token"), data=token_payload)
    assert response.status_code == 201
    assert "access_token" in parse_qs(response.content.decode())


@pytest.mark.django_db
def test_urlencoded_token_exchange_under_limit_works(client, token_payload):
    response = client.post(
        reverse("indieweb:token"),
        data=urlencode(token_payload),
        content_type="application/x-www-form-urlencoded",
    )
    assert response.status_code == 201


@pytest.mark.django_db
def test_multipart_token_exchange_over_limit_is_rejected(client, token_payload):
    token_payload["padding"] = "x" * DEFAULT_INDIEAUTH_MAX_BODY_BYTES
    response = client.post(reverse("indieweb:token"), data=token_payload)
    assert response.status_code == 413
    assert models.Token.objects.count() == 0
    assert models.Auth.objects.count() == 1


@pytest.mark.django_db
def test_multipart_auth_code_verification_under_limit_works(client, auth, token_payload):
    response = client.post(reverse("indieweb:auth"), data=token_payload)
    assert response.status_code == 200
    assert parse_qs(response.content.decode())["me"] == [auth.me]


@pytest.mark.django_db
def test_oversized_consent_post_is_rejected_before_csrf_check(user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(user)
    response = csrf_client.post(
        reverse("indieweb:auth"),
        {"action": "approve", "padding": "x" * DEFAULT_INDIEAUTH_MAX_BODY_BYTES},
    )
    assert response.status_code == 413
    assert models.Auth.objects.count() == 0
