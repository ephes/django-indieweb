"""A failed token write must roll back code consumption and prior credentials."""

import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import RequestFactory
from django.utils import timezone

from indieweb.models import Auth, Token
from indieweb.views import TokenView


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("reissue", [False, True])
def test_failed_token_persistence_restores_code_and_bearer(monkeypatch, reissue):
    owner = get_user_model().objects.create_user(username="synthetic-owner")
    identity = {
        "owner": owner,
        "me": "https://owner.example/",
        "client_id": "https://client.example/",
        "scope": "create",
    }
    auth = Auth.objects.create(**identity, state="synthetic-state", redirect_uri="https://client.example/callback")
    auth_before = Auth.objects.values().get(pk=auth.pk)
    old = Token.objects.create(**identity, expires_at=timezone.now() + timedelta(minutes=5)) if reissue else None
    old_raw = old.raw_key if old else None
    prior = list(Token.objects.values())
    saved = []
    real_save = Token.save

    def failing_save(token, *args, **kwargs):
        # Observe the real deletion and perform a real token INSERT/UPDATE before
        # failure, so both sides of the transaction must actually roll back.
        assert not Auth.objects.filter(pk=auth.pk).exists()
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
    assert len(saved) == 1  # Failure was reached, rather than an early rejection.
    assert Auth.objects.values().get(pk=auth.pk) == auth_before
    assert list(Token.objects.values()) == prior  # Includes hash, expiry and modified.
    with pytest.raises(Token.DoesNotExist):
        Token.get_for_raw_key(saved[0])
    if old:
        assert Token.get_for_raw_key(old_raw).pk == old.pk

    response = exchange()
    assert response.status_code == (200 if reissue else 201)
    bearer = json.loads(response.content)["access_token"]
    assert Token.get_for_raw_key(bearer).owner_id == owner.pk
    assert not Auth.objects.filter(pk=auth.pk).exists()
    assert exchange().status_code == 400
    if old:
        with pytest.raises(Token.DoesNotExist):
            Token.get_for_raw_key(old_raw)
