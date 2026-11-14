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
def test_token_management_blocks_framing(client, user, tokens_url):
    """Token management page emits frame protections to prevent clickjacking."""
    client.login(username=user.username, password="password")

    response = client.get(tokens_url)

    assert response.status_code == 200
    assert response["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]


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


def assert_private_inventory(response):
    directives = {part.strip() for part in response["Cache-Control"].split(",")}
    assert {"private", "no-store", "no-cache", "max-age=0", "must-revalidate"} <= directives
    assert response["X-Frame-Options"] == "DENY"


@pytest.mark.django_db
@pytest.mark.parametrize("outcome", ["owner", "empty", "anonymous", "revoke", "foreign", "missing", "method"])
def test_token_browser_outcomes_are_private(client, user, other_user, tokens_url, outcome):
    foreign = _make_token(other_user, client_id="https://foreign.example.org", key="synthetic-foreign-key")
    if outcome != "anonymous":
        client.force_login(user)
    if outcome == "owner":
        _make_token(user, client_id="https://owned.example.org", key="synthetic-owned-key")
    if outcome in {"owner", "empty", "anonymous"}:
        response = client.get(tokens_url)
        assert response.status_code == (302 if outcome == "anonymous" else 200)
    else:
        token = _make_token(user)
        pk = foreign.pk if outcome == "foreign" else token.pk + foreign.pk + 100 if outcome == "missing" else token.pk
        url = reverse("indieweb:token-revoke", args=[pk])
        response = client.get(url) if outcome == "method" else client.post(url)
        assert response.status_code == (
            405 if outcome == "method" else 404 if outcome in {"foreign", "missing"} else 302
        )
    assert_private_inventory(response)
    assert b"https://foreign.example.org" not in response.content
    assert b"synthetic-owned-key" not in response.content
    assert b"synthetic-foreign-key" not in response.content
    assert models.Token.objects.filter(pk=foreign.pk).exists()


@pytest.mark.django_db
def test_inventory_is_not_replayed_from_shared_cache(client, settings, user, tokens_url):
    from django.core.cache import cache

    settings.MIDDLEWARE = [
        "django.middleware.cache.UpdateCacheMiddleware",
        *settings.MIDDLEWARE,
        "django.middleware.cache.FetchFromCacheMiddleware",
    ]
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    cache.clear()
    try:
        client.force_login(user)
        token = _make_token(user, client_id="https://removed.example.org")
        first = client.get(tokens_url)
        token.delete()
        second = client.get(tokens_url)
        assert b"https://removed.example.org" in first.content
        assert b"https://removed.example.org" not in second.content
        assert_private_inventory(first)
        assert_private_inventory(second)
    finally:
        cache.clear()


@pytest.mark.django_db
def test_revoke_checks_owner_in_delete_statement(client, user, other_user):
    """Transfer just before SQL DELETE; a previously fetched instance is stale."""
    from django.db import connection

    token = _make_token(user)
    client.force_login(user)
    deletes = []

    def transfer_before_delete(execute, sql, params, many, context):
        if sql.lstrip().upper().startswith("DELETE") and models.Token._meta.db_table in sql:
            deletes.append(sql)
            models.Token.objects.filter(pk=token.pk).update(owner=other_user)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(transfer_before_delete):
        response = client.post(reverse("indieweb:token-revoke", args=[token.pk]))

    assert deletes
    assert response.status_code == 404
    assert_private_inventory(response)
    assert models.Token.objects.get(pk=token.pk).owner_id == other_user.pk


@pytest.fixture
def many_grants(user, other_user):
    owned = [_make_token(user, client_id=f"https://client-{i}.example/") for i in range(113)]
    foreign = _make_token(other_user, client_id="https://foreign.example/")
    # A timestamp tie must not duplicate or omit rows across adjacent pages.
    models.Token.objects.all().update(created=timezone.now())
    return owned, foreign


@pytest.mark.django_db
def test_inventory_paginates_tied_grants_with_bounded_queries(client, user, tokens_url, many_grants):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    owned, foreign = many_grants
    client.force_login(user)
    seen = []
    for number, expected_size in [(1, 50), (2, 50), (3, 13)]:
        with CaptureQueriesContext(connection) as queries:
            response = client.get(tokens_url, {"page": number})
        assert response.status_code == 200
        rows = list(response.context["tokens"])
        assert len(rows) == expected_size
        assert response.context["page_obj"].number == number
        assert response.context["paginator"].num_pages == 3
        seen.extend(token.pk for token in rows)
        assert_private_inventory(response)
        body = response.content.decode()
        assert body.count('<form method="post"') == expected_size
        assert "https://foreign.example/" not in body
        assert foreign.key not in body
        assert all(token.key not in body for token in owned)
        assert (f"?page={number - 1}" in body) == (number > 1)
        assert (f"?page={number + 1}" in body) == (number < 3)
        token_queries = [q["sql"] for q in queries if '"indieweb_token"' in q["sql"]]
        assert len(token_queries) == 2  # COUNT plus one bounded row SELECT.
        assert "COUNT(" in token_queries[0]
        assert f"LIMIT {expected_size}" in token_queries[1]
    assert seen == sorted((token.pk for token in owned), reverse=True)


@pytest.mark.django_db
@pytest.mark.parametrize("page, expected", [("invalid", 1), ("1.5", 1), ("0", 3), ("-1", 3), ("999999999", 3)])
def test_inventory_invalid_pages_are_private(client, user, tokens_url, many_grants, page, expected):
    client.force_login(user)
    response = client.get(tokens_url, {"page": page})
    assert response.status_code == 200
    assert response.context["page_obj"].number == expected
    assert len(response.context["tokens"]) <= 50
    assert_private_inventory(response)


@pytest.mark.django_db(transaction=True)
def test_revoke_cannot_delete_grant_transferred_on_another_connection(client, user, other_user, concurrent_database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from django.db import close_old_connections, connection

    token = _make_token(user)
    client.force_login(user)
    entered, release = Event(), Event()
    request_connections = []

    def pause_delete(execute, sql, params, many, context):
        # Pause at the first statement touching the grant (the locking SELECT
        # with the fix, the DELETE before it) and transfer the row meanwhile.
        if models.Token._meta.db_table in sql and not request_connections:
            request_connections.append(connection.connection)
            entered.set()
            assert release.wait(10)
        return execute(sql, params, many, context)

    def request():
        close_old_connections()
        try:
            with connection.execute_wrapper(pause_delete):
                return client.post(reverse("indieweb:token-revoke", args=[token.pk]))
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(request)
        try:
            assert entered.wait(10)
            models.Token.objects.filter(pk=token.pk).update(owner=other_user)
            assert request_connections[0] is not connection.connection
        finally:
            release.set()
        response = pending.result(timeout=15)
    assert response.status_code == 404
    assert_private_inventory(response)
    assert models.Token.objects.get(pk=token.pk).owner_id == other_user.pk


def _collector_receiver(sender, instance, **kwargs):
    """Host-style delete signal that disables Django's fast-delete path."""


@pytest.mark.django_db(transaction=True)
def test_revoke_locks_grant_on_collector_delete_path(client, user, other_user, concurrent_database):
    """A Token delete receiver makes Django SELECT then ``DELETE ... WHERE id IN``.

    Without a row lock, an owner transfer committed between those statements is
    deleted by the former owner. With the lock, the transfer waits for the
    revocation and then finds no row to move.
    """
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from django.db import close_old_connections, connection
    from django.db.models.signals import pre_delete

    if connection.vendor != "postgresql":
        pytest.skip("Row locks need PostgreSQL; SQLite serializes writers instead")

    token = _make_token(user)
    client.force_login(user)
    entered, release = Event(), Event()

    def pause_delete(execute, sql, params, many, context):
        if sql.lstrip().upper().startswith("DELETE") and models.Token._meta.db_table in sql:
            entered.set()
            assert release.wait(10)
        return execute(sql, params, many, context)

    def request():
        close_old_connections()
        try:
            with connection.execute_wrapper(pause_delete):
                return client.post(reverse("indieweb:token-revoke", args=[token.pk]))
        finally:
            close_old_connections()

    def transfer():
        close_old_connections()
        try:
            return models.Token.objects.filter(pk=token.pk).update(owner=other_user)
        finally:
            close_old_connections()

    pre_delete.connect(_collector_receiver, sender=models.Token)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(request)
            try:
                assert entered.wait(10)
                moved = pool.submit(transfer)
                with pytest.raises(TimeoutError):
                    moved.result(timeout=0.5)
            finally:
                release.set()
            response = pending.result(timeout=15)
            assert moved.result(timeout=15) == 0
    finally:
        pre_delete.disconnect(_collector_receiver, sender=models.Token)
    assert response.status_code == 302
    assert_private_inventory(response)
    assert not models.Token.objects.filter(pk=token.pk).exists()
