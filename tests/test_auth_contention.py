"""Committed authorization requests on independent database connections."""

import json
from queue import Queue
from threading import Barrier, Event, Thread
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import RequestFactory

from indieweb import views
from indieweb.models import Auth, Token

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def committed_auth(concurrent_database):
    owner = get_user_model().objects.create_user(username="synthetic-owner")
    return Auth.objects.create(
        owner=owner,
        state="synthetic-state",
        me="https://owner.example/",
        client_id="https://client.example/",
        redirect_uri="https://client.example/callback",
        scope="create",
    )


def redeem(auth, endpoint="token"):
    request = RequestFactory().post(
        f"/{endpoint}/",
        {"code": auth.raw_key, "client_id": auth.client_id, "redirect_uri": auth.redirect_uri},
        HTTP_ACCEPT="application/json",
    )
    return (views.TokenView if endpoint == "token" else views.AuthView).as_view()(request)


def approve(auth):
    request = RequestFactory().post(
        "/auth/",
        {
            "action": "approve",
            "state": "new-consent",
            "me": auth.me,
            "client_id": auth.client_id,
            "redirect_uri": auth.redirect_uri,
            "scope": auth.scope,
        },
    )
    request.user = auth.owner
    request._dont_enforce_csrf_checks = True
    return views.AuthView.as_view()(request)


def start_request(results, name, operation, sql_hook=None):
    """Own each connection, propagate every exception, and bound DB lock waits."""

    def run():
        try:
            connection.ensure_connection()
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '5s'")
                    cursor.execute("SET lock_timeout = '5s'")
            raw_connection = connection.connection
            if sql_hook is None:
                response = operation()
            else:
                with connection.execute_wrapper(sql_hook):
                    response = operation()
            results.put((name, raw_connection, response))
        except BaseException as exc:
            results.put((name, connection.connection, exc))
        finally:
            connections.close_all()

    thread = Thread(target=run, name=name, daemon=True)
    thread.start()
    return thread


def finish_requests(threads, results):
    for thread in threads:
        thread.join(timeout=15)
    assert not any(thread.is_alive() for thread in threads), "authorization request did not terminate"
    outcomes = [results.get_nowait() for _ in threads]
    assert len({id(raw) for _, raw, _ in outcomes}) == len(threads), "requests shared a connection"
    for name, _, result in outcomes:
        assert not isinstance(result, BaseException), f"{name}: {result!r}"
    return {name: result for name, _, result in outcomes}


@pytest.mark.parametrize("endpoint", ["token", "auth"])
def test_competing_code_redemptions(committed_auth, monkeypatch, endpoint):
    auth = committed_auth
    both_read = Barrier(2)
    lookup = Auth.get_for_raw_key

    def synchronized_lookup(*args, **kwargs):
        matched = lookup(*args, **kwargs)
        both_read.wait(timeout=10)
        return matched

    monkeypatch.setattr(Auth, "get_for_raw_key", synchronized_lookup)
    results = Queue()
    threads = [
        start_request(results, "exchange", lambda: redeem(auth)),
        start_request(results, "competitor", lambda: redeem(auth, endpoint)),
    ]
    try:
        responses = finish_requests(threads, results)
    finally:
        both_read.abort()
        for thread in threads:
            thread.join(timeout=15)
    statuses = sorted(response.status_code for response in responses.values())
    assert statuses in ([200, 400], [201, 400]) if endpoint == "auth" else statuses == [201, 400]
    for name, response in responses.items():
        if response.status_code == 400:
            loser_endpoint = "token" if name == "exchange" else endpoint
            assert response.content == (
                b"invalid_grant" if loser_endpoint == "token" else b"Invalid authorization code"
            )
            assert response["Content-Type"] == (
                "application/x-www-form-urlencoded" if loser_endpoint == "token" else "text/html; charset=utf-8"
            )
    assert not Auth.objects.exists()
    successful_tokens = [
        r for name, r in responses.items() if (name == "exchange" or endpoint == "token") and r.status_code < 300
    ]
    assert Token.objects.count() == len(successful_tokens)
    for response in successful_tokens:
        bearer = json.loads(response.content)["access_token"]
        assert Token.get_for_raw_key(bearer).owner_id == auth.owner_id


@pytest.mark.parametrize("first", ["consent", "exchange"])
def test_consent_and_exchange_lock_order(committed_auth, monkeypatch, first):
    auth = committed_auth
    # Preload the owner outside either transaction (as session middleware would).
    _ = auth.owner
    looked_up, start_exchange, locked, contender = (Event() for _ in range(4))
    lookup = Auth.get_for_raw_key

    def paused_lookup(*args, **kwargs):
        matched = lookup(*args, **kwargs)
        looked_up.set()
        assert start_exchange.wait(10)
        return matched

    monkeypatch.setattr(Auth, "get_for_raw_key", paused_lookup)

    def hook_for(name):
        def hook(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith("DELETE") and Auth._meta.db_table in sql:
                if name == first:
                    result = execute(sql, params, many, context)
                    locked.set()
                    assert contender.wait(10)
                    return result
                contender.set()
            return execute(sql, params, many, context)

        return hook

    results, threads = Queue(), []
    threads.append(start_request(results, "exchange", lambda: redeem(auth), hook_for("exchange")))
    try:
        assert looked_up.wait(10)
        if first == "exchange":
            start_exchange.set()
            assert locked.wait(10)
        threads.append(start_request(results, "consent", lambda: approve(auth), hook_for("consent")))
        if first == "consent":
            assert locked.wait(10)
            start_exchange.set()
        responses = finish_requests(threads, results)
    finally:
        start_exchange.set()
        contender.set()
        for thread in threads:
            thread.join(timeout=15)
    assert responses["consent"].status_code == 302
    assert responses["exchange"].status_code == (201 if first == "exchange" else 400)
    assert Token.objects.count() == (1 if first == "exchange" else 0)
    replacement = Auth.objects.get()
    assert replacement.state == "new-consent"
    assert replacement.key != auth.key
    new_code = parse_qs(urlsplit(responses["consent"]["Location"]).query)["code"][0]
    assert Auth.get_for_raw_key(new_code).pk == replacement.pk


@pytest.mark.parametrize("endpoint", ["token", "auth"])
@pytest.mark.parametrize("age", [59, 60, 61])
def test_code_expiry_after_delete_lock_wait(committed_auth, monkeypatch, endpoint, age):
    """A real writer blocks DELETE while the clock crosses the code deadline."""
    from datetime import timedelta

    from django.db import transaction

    auth = committed_auth
    now = auth.created
    clock = [now]
    monkeypatch.setattr(views.timezone, "now", lambda: clock[0])
    old = Token.objects.create(
        owner_id=auth.owner_id,
        me=auth.me,
        client_id=auth.client_id,
        scope=auth.scope,
        expires_at=now + timedelta(hours=1),
    )
    prior = Token.objects.values().get(pk=old.pk)
    attempting, deleted = Event(), Event()

    def hook(execute, sql, params, many, context):
        if sql.lstrip().upper().startswith("DELETE") and Auth._meta.db_table in sql:
            attempting.set()
            result = execute(sql, params, many, context)
            deleted.set()
            return result
        return execute(sql, params, many, context)

    results = Queue()
    threads = []
    try:
        with transaction.atomic():
            Auth.objects.filter(pk=auth.pk).update(state=auth.state)
            threads.append(start_request(results, "exchange", lambda: redeem(auth, endpoint), hook))
            assert attempting.wait(10)
            assert not deleted.wait(0.1), "DELETE did not wait for the independent writer"
            clock[0] = now + timedelta(seconds=age)
        response = finish_requests(threads, results)["exchange"]
    finally:
        for thread in threads:
            thread.join(timeout=15)
    assert deleted.is_set()
    assert response.status_code == (400 if age > 60 else 200)
    assert not Auth.objects.filter(pk=auth.pk).exists()
    if age > 60 or endpoint == "auth":
        assert Token.objects.values().get(pk=old.pk) == prior
    else:
        assert Token.objects.get(pk=old.pk).key != prior["key"]


@pytest.mark.parametrize("endpoint", ["token", "auth"])
def test_disable_owner_before_serialized_exchange(committed_auth, monkeypatch, endpoint):
    """An independent connection disables the owner after the code was read."""
    auth = committed_auth
    looked_up, proceed = Event(), Event()
    lookup = Auth.get_for_raw_key

    def paused_lookup(*args, **kwargs):
        matched = lookup(*args, **kwargs)
        assert matched.owner.is_active
        looked_up.set()
        assert proceed.wait(10)
        return matched

    monkeypatch.setattr(Auth, "get_for_raw_key", paused_lookup)
    results = Queue()
    threads = [start_request(results, "exchange", lambda: redeem(auth, endpoint))]
    try:
        assert looked_up.wait(10)
        get_user_model().objects.filter(pk=auth.owner_id).update(is_active=False)
        proceed.set()
        response = finish_requests(threads, results)["exchange"]
    finally:
        proceed.set()
        for thread in threads:
            thread.join(timeout=15)
    assert response.status_code == 400
    assert not Token.objects.exists()
    assert not Auth.objects.exists()
