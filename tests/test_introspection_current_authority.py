"""Introspection must not publish authority admitted before host policy ran."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from indieweb.models import Token


@pytest.fixture
def grants(db, settings):
    settings.INDIEWEB_CORS_ALLOWED_ORIGINS = ["*"]
    owner = get_user_model().objects.create_user(username="synthetic-owner")
    other = get_user_model().objects.create_user(username="synthetic-other")
    tokens = [
        Token.objects.create(
            owner=owner,
            me="https://owner.example/",
            client_id="https://client.example/",
            scope=scope,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        for scope in ("read", "create")
    ]
    return tokens, other


def _change_authority(token, other, change):
    rows = Token.objects.filter(pk=token.pk)
    if change == "revoke":
        rows.delete()
    elif change == "rotate":
        rows.update(key=Token.hash_key("synthetic-replacement"))
    elif change == "expire":
        rows.update(expires_at=timezone.now() - timedelta(seconds=1))
    elif change == "transfer":
        rows.update(owner=other)
    elif change == "deactivate":
        get_user_model().objects.filter(pk=token.owner_id).update(is_active=False)
    else:
        rows.update(**{change: "https://changed.example/" if change in {"client_id", "me"} else "delete"})


def _introspect(caller, target):
    return Client().post(
        reverse("indieweb:token-introspection"),
        {"token": target.key},
        HTTP_AUTHORIZATION=f"Bearer {caller.key}",
        HTTP_ORIGIN="https://resource.example",
    )


def _assert_refused(response):
    assert response.status_code in {200, 401}
    if response.status_code == 200:
        assert response.json() == {"active": False}
    else:
        assert response.content == b"authentication error"
    assert response["Cache-Control"] == "no-store"
    assert response["Access-Control-Allow-Origin"] == "*"
    assert b"client_id" not in response.content


@pytest.mark.django_db
@pytest.mark.parametrize("side", [0, 1])
@pytest.mark.parametrize(
    "change", ["revoke", "rotate", "expire", "transfer", "deactivate", "client_id", "me", "scope"]
)
def test_introspection_rechecks_authority_after_policy(grants, settings, side, change):
    tokens, other = grants
    settings.INDIEWEB_TOKEN_INTROSPECTION_AUTHORIZER = "tests.test_token_endpoint.allow_any_introspection"

    def authorizer(caller, target):
        _change_authority(tokens[side], other, change)
        return True

    with patch("tests.test_token_endpoint.allow_any_introspection", authorizer):
        _assert_refused(_introspect(*tokens))


@pytest.mark.django_db
@pytest.mark.parametrize("same_token", [False, True])
def test_introspection_rejects_both_grants_transferred_together(grants, settings, same_token):
    tokens, other = grants
    settings.INDIEWEB_TOKEN_INTROSPECTION_AUTHORIZER = "tests.test_token_endpoint.allow_any_introspection"

    def authorizer(caller, target):
        Token.objects.filter(pk__in=[t.pk for t in tokens]).update(owner=other)
        return True

    with patch("tests.test_token_endpoint.allow_any_introspection", authorizer):
        _assert_refused(_introspect(tokens[0], tokens[0] if same_token else tokens[1]))


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("side", [0, 1])
@pytest.mark.parametrize("change", ["revoke", "expire", "transfer"])
def test_introspection_blocked_policy_observes_committed_authority(
    grants, settings, concurrent_database, side, change
):
    tokens, other = grants
    settings.INDIEWEB_TOKEN_INTROSPECTION_AUTHORIZER = "tests.test_token_endpoint.allow_any_introspection"
    entered, release = Event(), Event()

    def authorizer(caller, target):
        entered.set()
        assert release.wait(10)
        return True

    def request():
        close_old_connections()
        try:
            return _introspect(*tokens)
        finally:
            close_old_connections()

    with (
        patch("tests.test_token_endpoint.allow_any_introspection", authorizer),
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        pending = pool.submit(request)
        try:
            assert entered.wait(10)
            _change_authority(tokens[side], other, change)
        finally:
            release.set()
        _assert_refused(pending.result(timeout=15))


@pytest.mark.django_db
@pytest.mark.parametrize("side", ["caller", "target"])
def test_introspection_rechecks_client_policy_after_authorizer(grants, settings, side):
    """Policy that starts refusing a client during the hook is applied before metadata."""
    tokens, _ = grants
    # Keep the in-memory plaintext bearer key; refresh_from_db would load the stored hash.
    Token.objects.filter(pk=tokens[1].pk).update(client_id="https://target.example/")
    settings.INDIEWEB_TOKEN_INTROSPECTION_AUTHORIZER = "tests.test_token_endpoint.allow_any_introspection"
    kept = "https://target.example/" if side == "caller" else "https://client.example/"

    def authorizer(caller, target):
        settings.INDIEWEB_ALLOWED_CLIENT_IDS = [kept]
        return True

    with patch("tests.test_token_endpoint.allow_any_introspection", authorizer):
        response = _introspect(*tokens)
    _assert_refused(response)
    if side == "caller":
        assert response.status_code == 401
    else:
        assert response.status_code == 200
        assert response.json() == {"active": False}
