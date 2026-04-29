from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from indieweb import models


@pytest.fixture
def user(db):
    return User.objects.create_user(username="foo", email="foo@example.org", password="password")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(username="bar", email="bar@example.org", password="password")


def _make_token(
    user: User,
    *,
    client_id: str = "https://webapp.example.org",
    me: str = "https://example.org/",
    scope: str | None = "create",
    key: str | None = None,
    expires_at: datetime | None = None,
) -> models.Token:
    return models.Token.objects.create(
        owner=user,
        client_id=client_id,
        me=me,
        scope=scope,
        key=key or "",
        expires_at=expires_at,
    )


@pytest.fixture
def tokens_url():
    return reverse("indieweb:tokens")


@pytest.fixture
def micropub_url():
    return reverse("indieweb:micropub")


@pytest.mark.django_db
def test_token_management_requires_authentication(client, tokens_url):
    response = client.get(tokens_url)

    assert response.status_code == 302
    assert response.url == f"/accounts/login/?next={tokens_url}"


@pytest.mark.django_db
def test_token_management_lists_only_current_users_tokens(client, user, other_user, tokens_url):
    owned = _make_token(
        user,
        client_id="https://owned.example.org",
        me="https://owner.example.org/",
        scope="create update",
        key="ownedtokensecretvalue",
    )
    foreign = _make_token(
        other_user,
        client_id="https://foreign.example.org",
        me="https://foreign.example.org/",
        scope="delete",
        key="foreigntokensecretvalue",
    )
    client.login(username=user.username, password="password")

    response = client.get(tokens_url)

    assert response.status_code == 200
    assert list(response.context["tokens"]) == [owned]
    body = response.content.decode("utf-8")
    assert "https://owned.example.org" in body
    assert "https://owner.example.org/" in body
    assert "create update" in body
    assert "https://foreign.example.org" not in body
    assert owned.key not in body
    assert foreign.key not in body


@pytest.mark.django_db
def test_token_management_renders_empty_list(client, user, tokens_url):
    client.login(username=user.username, password="password")

    response = client.get(tokens_url)

    assert response.status_code == 200
    assert "No access tokens have been issued for your account." in response.content.decode("utf-8")


@pytest.mark.django_db
def test_token_management_shows_active_and_expired_statuses(client, user, tokens_url):
    active = _make_token(
        user,
        client_id="https://active.example.org",
        expires_at=timezone.now() + timedelta(hours=1),
    )
    expired = _make_token(
        user,
        client_id="https://expired.example.org",
        scope="update",
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    client.login(username=user.username, password="password")

    response = client.get(tokens_url)

    assert response.status_code == 200
    assert {token.pk for token in response.context["tokens"]} == {active.pk, expired.pk}
    body = response.content.decode("utf-8")
    assert "Active" in body
    assert "Expired" in body


@pytest.mark.django_db
def test_token_revoke_post_deletes_owned_token(client, user, tokens_url):
    token = _make_token(user)
    client.login(username=user.username, password="password")

    response = client.post(reverse("indieweb:token-revoke", args=[token.pk]))

    assert response.status_code == 302
    assert response.url == tokens_url
    assert not models.Token.objects.filter(pk=token.pk).exists()


@pytest.mark.django_db
def test_token_revoke_is_csrf_protected(user, tokens_url):
    csrf_client = Client(enforce_csrf_checks=True)
    token = _make_token(user)
    csrf_client.force_login(user)

    blocked = csrf_client.post(reverse("indieweb:token-revoke", args=[token.pk]))

    assert blocked.status_code == 403
    assert models.Token.objects.filter(pk=token.pk).exists()

    page = csrf_client.get(tokens_url)
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode("utf-8"))
    assert match is not None
    allowed = csrf_client.post(
        reverse("indieweb:token-revoke", args=[token.pk]),
        {"csrfmiddlewaretoken": match.group(1)},
    )

    assert allowed.status_code == 302
    assert not models.Token.objects.filter(pk=token.pk).exists()


@pytest.mark.django_db
def test_revoked_bearer_token_no_longer_authenticates(client, user, micropub_url):
    token = _make_token(user, scope="create", key="revokedtokensecret")
    auth_header = f"Bearer {token.key}"

    before = client.get(micropub_url, Authorization=auth_header)
    token.delete()
    after = client.get(micropub_url, Authorization=auth_header)

    assert before.status_code == 200
    assert after.status_code == 401


@pytest.mark.django_db
def test_token_revoke_cannot_delete_foreign_token(client, user, other_user):
    foreign = _make_token(other_user, client_id="https://foreign.example.org")
    client.login(username=user.username, password="password")

    response = client.post(reverse("indieweb:token-revoke", args=[foreign.pk]))

    assert response.status_code == 404
    assert models.Token.objects.filter(pk=foreign.pk).exists()


@pytest.mark.django_db
def test_token_revoke_get_does_not_delete_token(client, user):
    token = _make_token(user)
    client.login(username=user.username, password="password")

    response = client.get(reverse("indieweb:token-revoke", args=[token.pk]))

    assert response.status_code == 405
    assert models.Token.objects.filter(pk=token.pk).exists()
