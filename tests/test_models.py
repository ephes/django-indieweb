#!/usr/bin/env python

"""
test_django-indieweb
------------

Tests for `django-indieweb` models module.
"""

import pytest
from django.contrib.auth import get_user_model

from indieweb.models import Auth, Token

User = get_user_model()


@pytest.mark.django_db
def test_token_str_method():
    user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
    token = Token.objects.create(
        owner=user, client_id="https://example.com", me="https://user.example.com", scope="create update"
    )
    expected = "https://example.com https://user.example.com create update testuser"
    assert str(token) == expected


def test_auth_and_token_keys_are_model_unique():
    """Auth and Token bearer/code keys must be unique in model state."""
    assert Auth._meta.get_field("key").unique is True
    assert Token._meta.get_field("key").unique is True


@pytest.mark.django_db
def test_auth_save_hashes_provided_key_at_rest():
    """Saving an Auth with a raw key persists the HMAC hash and exposes the raw value once."""
    user = User.objects.create_user(username="hashed-auth", email="h@example.com", password="x")
    auth = Auth.objects.create(
        owner=user,
        key="rawauthsecret",
        state="state",
        me="http://example.org",
        scope="post",
        client_id="https://webapp.example.org",
    )

    # In-memory instance still exposes the raw value to the issuance flow.
    assert auth.key == "rawauthsecret"

    stored_key = Auth.objects.values_list("key", flat=True).get(pk=auth.pk)
    assert stored_key.startswith("hmac-sha256$")
    assert stored_key == Auth.hash_key("rawauthsecret")
    assert stored_key != "rawauthsecret"


@pytest.mark.django_db
def test_auth_save_generates_random_hashed_key_when_blank():
    """Saving an Auth without a key generates a fresh raw code and stores its hash."""
    user = User.objects.create_user(username="auto-auth", email="a@example.com", password="x")
    auth = Auth(
        owner=user,
        state="state",
        me="http://example.org",
        scope="post",
        client_id="https://webapp.example.org",
    )
    auth.save()

    assert auth.raw_key is not None
    assert auth.key == auth.raw_key

    stored_key = Auth.objects.values_list("key", flat=True).get(pk=auth.pk)
    assert stored_key == Auth.hash_key(auth.raw_key)
    assert stored_key != auth.raw_key


@pytest.mark.django_db
def test_auth_get_for_raw_key_finds_hashed_row():
    """Auth.get_for_raw_key looks up the row by HMAC of the submitted raw value."""
    user = User.objects.create_user(username="lookup-auth", email="l@example.com", password="x")
    auth = Auth.objects.create(
        owner=user,
        key="lookmeup",
        state="state",
        me="http://example.org",
        scope="post",
        client_id="https://webapp.example.org",
    )

    found = Auth.get_for_raw_key("lookmeup", client_id="https://webapp.example.org")
    assert found.pk == auth.pk

    with pytest.raises(Auth.DoesNotExist):
        Auth.get_for_raw_key("wrong", client_id="https://webapp.example.org")


@pytest.mark.django_db
def test_auth_get_for_raw_key_rejects_hashed_input():
    """Submitting the at-rest hash as a raw key must not authenticate."""
    user = User.objects.create_user(username="hash-input", email="hi@example.com", password="x")
    Auth.objects.create(
        owner=user,
        key="rawvalue",
        state="state",
        me="http://example.org",
        scope="post",
        client_id="https://webapp.example.org",
    )
    hashed = Auth.hash_key("rawvalue")
    with pytest.raises(Auth.DoesNotExist):
        Auth.get_for_raw_key(hashed, client_id="https://webapp.example.org")


def test_auth_masked_key_does_not_disclose_raw_value():
    """Auth.masked_key returns a non-secret display form."""
    auth = Auth(key=Auth.hash_key("rawvalue"))
    masked = auth.masked_key()
    assert masked == "hmac-sha256$..."
    assert "rawvalue" not in masked

    legacy = Auth(key="legacycode")
    legacy_masked = legacy.masked_key()
    assert "legacycode" not in legacy_masked

    empty = Auth(key="")
    assert empty.masked_key() == ""


@pytest.mark.django_db
def test_auth_get_for_raw_key_honors_secret_key_fallbacks(settings):
    """A row hashed under a now-fallback secret must still be findable after rotation."""
    from indieweb.models import Token

    user = User.objects.create_user(username="rotation-auth", email="r@example.com", password="x")
    # Encode the row under the OLD secret key.
    settings.SECRET_KEY = "old-secret"
    auth = Auth.objects.create(
        owner=user,
        key="rotationcode",
        state="state",
        me="http://example.org",
        scope="post",
        client_id="https://webapp.example.org",
    )
    stored_under_old = Auth.hash_key("rotationcode")
    # Rotate: new primary, old becomes fallback.
    settings.SECRET_KEY = "new-secret"
    settings.SECRET_KEY_FALLBACKS = ["old-secret"]

    found = Auth.get_for_raw_key("rotationcode", client_id="https://webapp.example.org")
    assert found.pk == auth.pk
    # The stored key on the row must remain the old digest until it is reissued.
    assert found.key == stored_under_old

    # And similarly for Token.
    token = Token.objects.create(
        owner=user,
        key="rotation-token-raw",
        client_id="https://webapp.example.org",
        me="http://example.org",
        scope="create",
    )
    # Token.save hashes under the current primary (now "new-secret"). To
    # exercise fallback resolution, manually re-encode under the old key.
    settings.SECRET_KEY = "old-secret"
    token.key = Token.hash_key("rotation-token-raw")
    token.save(update_fields=["key"])

    settings.SECRET_KEY = "new-secret"
    settings.SECRET_KEY_FALLBACKS = ["old-secret"]
    refound = Token.get_for_raw_key("rotation-token-raw")
    assert refound.pk == token.pk


@pytest.mark.django_db
def test_token_hash_key_uses_only_primary_secret(settings):
    """``hash_key`` must continue to write under the primary secret regardless of fallbacks."""
    from indieweb.models import Token

    settings.SECRET_KEY = "primary-secret"
    settings.SECRET_KEY_FALLBACKS = ["fallback-secret"]
    digest = Token.hash_key("abc")
    settings.SECRET_KEY = "primary-secret"
    settings.SECRET_KEY_FALLBACKS = []
    assert Token.hash_key("abc") == digest


@pytest.mark.django_db
@pytest.mark.parametrize("model", [Auth, Token])
@pytest.mark.parametrize("update_fields", [["me"], [], None])
@pytest.mark.parametrize("rotate_secret", [False, True])
def test_stale_issued_instance_cannot_restore_rotated_key(model, update_fields, rotate_secret, settings):
    settings.SECRET_KEY = "synthetic-original-secret"
    user = User.objects.create_user(username="stale-issuer")
    issued = model.objects.create(owner=user, client_id="https://client.example", me="https://owner.example")
    old_raw = issued.key
    rotated = model.objects.get(pk=issued.pk)
    new_raw = rotated.set_key("synthetic-new-credential")
    rotated.save(update_fields=["key"])
    stored = model.objects.get(pk=issued.pk).key
    if rotate_secret:
        settings.SECRET_KEY = "synthetic-next-secret"
        settings.SECRET_KEY_FALLBACKS = ["synthetic-original-secret"]
    issued.me = "https://updated.example"
    issued.save(update_fields=update_fields)
    saved = model.objects.get(pk=issued.pk)
    assert saved.key == stored
    assert saved.me == ("https://owner.example" if update_fields == [] else "https://updated.example")
    assert model.get_for_raw_key(new_raw).pk == issued.pk
    with pytest.raises(model.DoesNotExist):
        model.get_for_raw_key(old_raw)
    assert issued.key == old_raw  # Issuance compatibility does not imply a write.


@pytest.mark.django_db
@pytest.mark.parametrize("model", [Auth, Token])
@pytest.mark.parametrize("replacement", ["assignment", "set_key"])
def test_issued_instance_explicit_key_replacement(model, replacement):
    user = User.objects.create_user(username="explicit-issuer")
    issued = model.objects.create(owner=user, client_id="https://client.example", me="https://owner.example")
    old_raw = issued.key
    if replacement == "assignment":
        issued.key = "synthetic-replacement"
    else:
        issued.set_key("synthetic-replacement")
    issued.save(update_fields=["me", "key"] if replacement == "set_key" else ["me"])
    assert model.get_for_raw_key("synthetic-replacement").pk == issued.pk
    with pytest.raises(model.DoesNotExist):
        model.get_for_raw_key(old_raw)


@pytest.mark.django_db
@pytest.mark.parametrize("model", [Auth, Token])
def test_issued_instance_full_save_does_not_recreate_consumed_credential(model):
    from django.db import DatabaseError, transaction

    user = User.objects.create_user(username="consumed-issuer")
    issued = model.objects.create(owner=user, client_id="https://client.example", me="https://owner.example")
    model.objects.filter(pk=issued.pk).delete()
    raw = issued.key
    for _ in range(2):
        with pytest.raises(DatabaseError, match="did not affect any rows"), transaction.atomic():
            issued.save()
        assert issued.key == raw
        assert not model.objects.filter(pk=issued.pk).exists()
