"""A failed token write must roll back code consumption and prior credentials."""

import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, router
from django.test import RequestFactory
from django.utils import timezone

from indieweb.models import Auth, Token
from indieweb.views import TokenView


class GrantRouter:
    def db_for_read(self, model, **hints):
        return "other"

    def db_for_write(self, model, **hints):
        return "other"


@pytest.mark.django_db(transaction=True, databases=["default", "other"])
@pytest.mark.parametrize("alias", ["default", "other"])
@pytest.mark.parametrize("reissue", [False, True])
def test_failed_token_persistence_restores_code_and_bearer(monkeypatch, settings, reissue, alias):
    if alias == "other":
        settings.DATABASE_ROUTERS = [GrantRouter()]

    owner = get_user_model().objects.db_manager(alias).create_user(username="synthetic-owner")
    identity = {
        "owner": owner,
        "me": "https://owner.example/",
        "client_id": "https://client.example/",
        "scope": "create",
    }
    auth = Auth.objects.using(alias).create(
        **identity, state="synthetic-state", redirect_uri="https://client.example/callback"
    )
    auth_before = Auth.objects.using(alias).values().get(pk=auth.pk)
    old = (
        Token.objects.using(alias).create(**identity, expires_at=timezone.now() + timedelta(minutes=5))
        if reissue
        else None
    )
    old_raw = old.raw_key if old else None
    prior = list(Token.objects.using(alias).values())
    saved = []
    real_save = Token.save

    def failing_save(token, *args, **kwargs):
        # Observe the real deletion and perform a real token INSERT/UPDATE before
        # failure, so both sides of the transaction must actually roll back.
        assert not Auth.objects.using(alias).filter(pk=auth.pk).exists()
        real_save(token, *args, **kwargs)
        saved.append(token.raw_key)
        raise DatabaseError("synthetic persistence failure")

    def exchange():
        request = RequestFactory().post(
            "/token/",
            {"code": auth.raw_key, "client_id": auth.client_id, "redirect_uri": auth.redirect_uri},
            HTTP_ACCEPT="application/json",
        )
        return TokenView.as_view()(request)

    with monkeypatch.context() as patcher:
        patcher.setattr(Token, "save", failing_save)
        with pytest.raises(DatabaseError, match="synthetic persistence failure"):
            exchange()
    if alias == "other":
        assert not Auth.objects.using("default").exists()
        assert not Token.objects.using("default").exists()
    assert len(saved) == 1  # Failure was reached, rather than an early rejection.
    assert Auth.objects.using(alias).values().get(pk=auth.pk) == auth_before
    assert list(Token.objects.using(alias).values()) == prior  # Includes hash, expiry and modified.
    with pytest.raises(Token.DoesNotExist):
        Token.get_for_raw_key(saved[0])
    if old:
        assert Token.get_for_raw_key(old_raw).pk == old.pk

    response = exchange()
    assert response.status_code == (200 if reissue else 201)
    bearer = json.loads(response.content)["access_token"]
    assert Token.get_for_raw_key(bearer).owner_id == owner.pk
    assert not Auth.objects.using(alias).filter(pk=auth.pk).exists()
    assert exchange().status_code == 400
    if old:
        with pytest.raises(Token.DoesNotExist):
            Token.get_for_raw_key(old_raw)


@pytest.mark.django_db
def test_cross_database_grant_refused_before_consumption(monkeypatch):
    owner = get_user_model().objects.create_user(username="synthetic-owner")
    auth = Auth.objects.create(owner=owner, client_id="https://client.example/", state="state")
    monkeypatch.setattr(router, "db_for_write", lambda model, **hints: "other" if model is Token else "default")
    request = RequestFactory().post("/token/", {"code": auth.raw_key, "client_id": auth.client_id})
    with pytest.raises(ImproperlyConfigured, match="same database"):
        TokenView.as_view()(request)
    assert Auth.objects.filter(pk=auth.pk).exists()
    assert not Token.objects.exists()


@pytest.mark.django_db(transaction=True, databases=["default", "other"])
@pytest.mark.parametrize("endpoint", ["token", "auth"])
def test_redemption_uses_write_database_even_with_read_router(settings, endpoint):
    from indieweb.views import AuthView

    class ReplicaRouter(GrantRouter):
        def db_for_read(self, model, **hints):
            return "default"

    settings.DATABASE_ROUTERS = [ReplicaRouter()]
    owner = get_user_model().objects.db_manager("other").create_user(username="synthetic-owner")
    auth = Auth.objects.using("other").create(owner=owner, client_id="https://client.example/", state="state")
    request = RequestFactory().post(
        f"/{endpoint}/", {"code": auth.raw_key, "client_id": auth.client_id}, HTTP_ACCEPT="application/json"
    )
    response = (TokenView if endpoint == "token" else AuthView).as_view()(request)
    assert response.status_code == (201 if endpoint == "token" else 200)
    assert not Auth.objects.using("other").exists()
    assert Token.objects.using("other").count() == (1 if endpoint == "token" else 0)
    assert not Auth.objects.using("default").exists()
    assert not Token.objects.using("default").exists()


@pytest.mark.django_db(transaction=True, databases=["default", "other"])
def test_consent_uses_grant_database(settings):
    from indieweb.views import AuthView

    settings.DATABASE_ROUTERS = [GrantRouter()]
    owner = get_user_model().objects.db_manager("other").create_user(username="synthetic-owner")
    auth = AuthView._replace_auth_code(
        owner=owner, client_id="https://client.example/", me="https://owner.example/", scope="", state="state"
    )
    assert auth._state.db == "other"
    assert Auth.objects.using("other").count() == 1
    assert not Auth.objects.using("default").exists()


@pytest.mark.django_db(databases=["default", "other"])
def test_cross_database_owner_refused(settings):
    from indieweb.views import AuthView

    owner = get_user_model().objects.create_user(username="synthetic-owner")
    settings.DATABASE_ROUTERS = [GrantRouter()]
    with pytest.raises(ImproperlyConfigured, match="same database"):
        AuthView._replace_auth_code(owner=owner, client_id="https://client.example/", scope="", state="state")
    assert not Auth.objects.using("other").exists()
