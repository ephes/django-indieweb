"""Lifetime admission is shared by both redemption paths and system checks."""

from datetime import UTC, datetime

import pytest
from django.contrib.auth import get_user_model
from django.core.checks import run_checks
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory

from indieweb import views
from indieweb.models import Auth, Token


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ["token", "auth"])
@pytest.mark.parametrize(
    "name", ["INDIWEB_AUTH_CODE_TIMEOUT", "INDIEWEB_AUTH_CODE_TIMEOUT", "INDIEWEB_TOKEN_EXPIRES_IN"]
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, 1.5, 10**30, 0, -1, "60", None])
def test_invalid_lifetime_does_not_change_grants(settings, endpoint, name, value):
    owner = get_user_model().objects.create_user(username="synthetic-owner")
    identity = dict(owner=owner, client_id="https://client.example/", me="https://owner.example/", scope="create")
    auth = Auth.objects.create(**identity, state="state")
    Token.objects.create(**identity)
    before = (list(Auth.objects.values()), list(Token.objects.values()))
    setattr(settings, name, value)
    request = RequestFactory().post(f"/{endpoint}/", {"code": auth.raw_key, "client_id": auth.client_id})
    with pytest.raises(ImproperlyConfigured, match=name):
        (views.TokenView if endpoint == "token" else views.AuthView).as_view()(request)
    assert (list(Auth.objects.values()), list(Token.objects.values())) == before
    assert any(
        error.obj == name and error.id in {"indieweb.E002", "indieweb.E003"} for error in run_checks(tags=["security"])
    )


def test_valid_lifetime_limits_and_historical_alias(settings):
    from indieweb.auth_settings import auth_lifetimes

    settings.INDIWEB_AUTH_CODE_TIMEOUT = 1
    settings.INDIEWEB_TOKEN_EXPIRES_IN = 2**31 - 1
    assert auth_lifetimes() == (1, 2**31 - 1)
    settings.INDIEWEB_AUTH_CODE_TIMEOUT = 120
    assert auth_lifetimes()[0] == 120
    assert not [error for error in run_checks(tags=["security"]) if error.id in {"indieweb.E002", "indieweb.E003"}]


@pytest.mark.django_db
def test_lifetime_datetime_overflow_is_configuration_error(monkeypatch, settings):
    settings.INDIEWEB_TOKEN_EXPIRES_IN = 60
    monkeypatch.setattr(views.timezone, "now", lambda: datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC))
    from indieweb.auth_settings import auth_lifetimes

    with pytest.raises(ImproperlyConfigured, match="INDIEWEB_TOKEN_EXPIRES_IN"):
        auth_lifetimes()
