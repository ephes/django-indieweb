"""Webmention receive persistence stays on its authoritative writer database."""

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from queue import Queue
from threading import Event
from unittest.mock import patch

import httpx
import pytest
from django.db import IntegrityError, OperationalError, connection, connections
from django.utils import timezone

from indieweb.models import Webmention, WebmentionNestedResponse, WebmentionSourceSnapshot
from indieweb.processors import WebmentionProcessor, _WebmentionOutcome, process_queued_webmention

SOURCE = "https://source.example/parent"
TARGET = "https://target.example/post"
ONE = "https://source.example/one"
TWO = "https://source.example/two"
THREE = "https://source.example/three"
FAMILY = (Webmention, WebmentionNestedResponse, WebmentionSourceSnapshot)

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "other"])


class ReceiveRouter:
    writer = "other"

    def db_for_read(self, model, **hints):
        return "default"

    def db_for_write(self, model, **hints):
        return self.writer if model is Webmention else "default"

    def allow_relation(self, obj1, obj2, **hints):
        if type(obj1) in FAMILY and type(obj2) in FAMILY:
            return True
        return None


def document(children):
    nested = "".join(
        f'<article class="h-entry"><a class="u-url" href="{url}">child</a>'
        f'<div class="e-content">{content}</div></article>'
        for url, content in children
    )
    return f'<article class="h-entry"><a class="u-in-reply-to" href="{TARGET}">reply</a>{nested}</article>'


OLD = document([(ONE, "old one"), (TWO, "old two")])
NEW = document([(ONE, "new one"), (THREE, "new three")])


def state(alias):
    return [list(model.objects.using(alias).order_by("pk").values()) for model in FAMILY]


@pytest.fixture
def routed_receive(settings):
    router = ReceiveRouter()
    settings.DATABASE_ROUTERS = [router]
    current = [OLD]
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=current[0])
        )
    ) as client:
        processor = WebmentionProcessor(client=client)
        # Same PK and URL pair, deliberately unrelated stored generations.
        for alias in ("default", "other"):
            parent = Webmention.objects.using(alias).create(pk=101, source_url=SOURCE, target_url=TARGET)
            WebmentionSourceSnapshot.objects.using(alias).create(
                webmention=parent,
                raw_source_html="old snapshot",
                final_source_url=SOURCE,
                fetched_at=timezone.now(),
                nested_response_identities=[ONE, TWO] if alias == "other" else [THREE],
            )
            for identity in (ONE, TWO):
                WebmentionNestedResponse.objects.using(alias).create(
                    webmention=parent,
                    identity=identity,
                    content="old content",
                    first_seen_at=timezone.now(),
                    last_seen_at=timezone.now(),
                )
        yield processor, current, router


@pytest.mark.parametrize("flip_router", [False, True])
@pytest.mark.parametrize("status", ["verified", "failed", "spam"])
def test_receive_retains_writer_for_lock_saves_and_notification(routed_receive, monkeypatch, flip_router, status):
    processor, current, router = routed_receive
    current[0] = NEW
    default_before = state("default")
    collect = processor._collect_webmention_outcome
    apply = processor._apply_webmention_outcome
    observed = []
    notifications = []

    def collecting(*args):
        assert not connections["default"].in_atomic_block
        assert not connections["other"].in_atomic_block
        outcome = collect(*args)
        assert outcome.status == "verified"
        assert outcome.previous_nested_identities == {ONE, TWO}
        outcome.status = status
        outcome.spam_result = {"is_spam": status == "spam"}
        if flip_router:
            router.writer = "default"
        return outcome

    def applying(parent, *args):
        observed.append((parent._state.db, connections["other"].in_atomic_block))
        assert not connections["default"].in_atomic_block
        return apply(parent, *args)

    def notified(**kwargs):
        parent = kwargs["webmention"]
        notifications.append((parent._state.db, connections["other"].in_atomic_block))
        assert Webmention.objects.using("other").get(pk=parent.pk).status == "verified"

    monkeypatch.setattr(processor, "_collect_webmention_outcome", collecting)
    monkeypatch.setattr(processor, "_apply_webmention_outcome", applying)
    with patch("indieweb.processors.webmention_received.send_robust", side_effect=notified):
        result = processor.process_webmention(SOURCE, TARGET, vouch_url="https://vouch.example/new")
    assert observed == [("other", True)]
    assert result._state.db == "other"
    result.refresh_from_db(using="other")
    assert result.status == status
    assert result.vouch_url == "https://vouch.example/new"
    assert state("default") == default_before
    assert notifications == ([("other", False)] if status == "verified" else [])
    if status == "verified":
        snapshot = WebmentionSourceSnapshot.objects.using("other").get(webmention_id=result.pk)
        assert snapshot.raw_source_html == NEW
        children = {row.identity: row for row in WebmentionNestedResponse.objects.using("other").all()}
        assert children[ONE].content == "new one"
        assert children[TWO].status == "missing"
        assert children[THREE].content == "new three"


@pytest.mark.parametrize("part", ["children", "snapshot"])
def test_routed_savepoint_rolls_back_partial_writes_and_retry_reconciles(routed_receive, monkeypatch, part):
    processor, current, _router = routed_receive
    current[0] = NEW
    default_before = state("default")
    before = state("other")
    helper = "_sync_nested_responses" if part == "children" else "_store_source_snapshot"
    original = getattr(processor, helper)
    failures = []

    def write_then_fail(**kwargs):
        original(**kwargs)
        assert connections["other"].in_atomic_block
        parent = kwargs["webmention"]
        # A real constraint failure after all helper writes have executed.
        try:
            if part == "children":
                WebmentionNestedResponse.objects.using("other").create(
                    webmention=parent, identity=ONE, first_seen_at=timezone.now(), last_seen_at=timezone.now()
                )
            else:
                WebmentionSourceSnapshot.objects.using("other").create(
                    webmention=parent, raw_source_html="duplicate", final_source_url=SOURCE, fetched_at=timezone.now()
                )
        except IntegrityError:
            failures.append(True)
            raise

    with monkeypatch.context() as scoped:
        scoped.setattr(processor, helper, write_then_fail)
        parent = processor.process_webmention(SOURCE, TARGET)
    assert failures == [True]
    parent.refresh_from_db(using="other")
    assert parent.status == "verified"
    after = state("other")
    if part == "children":
        assert after[1] == before[1]
        assert after[2][0]["raw_source_html"] == NEW
    else:
        assert after[2] == before[2]
        assert {row["identity"] for row in after[1]} == {ONE, TWO, THREE}
    processor.process_webmention(SOURCE, TARGET)
    children = {row.identity: row for row in WebmentionNestedResponse.objects.using("other").all()}
    assert children[ONE].content == "new one"
    assert children[TWO].status == "missing"
    assert children[THREE].status == "verified"
    assert WebmentionSourceSnapshot.objects.using("other").get().raw_source_html == NEW
    assert state("default") == default_before


def test_outer_writer_failure_rolls_back_parent_children_snapshot_and_notification(routed_receive, monkeypatch):
    processor, current, _router = routed_receive
    current[0] = NEW
    before = {alias: state(alias) for alias in ("default", "other")}
    original = processor._apply_webmention_outcome

    def fail_after_apply(*args):
        original(*args)
        raise RuntimeError("synthetic outer failure")

    monkeypatch.setattr(processor, "_apply_webmention_outcome", fail_after_apply)
    with patch("indieweb.processors.webmention_received.send_robust") as notify:
        with pytest.raises(RuntimeError, match="synthetic outer failure"):
            processor.process_webmention(SOURCE, TARGET, vouch_url="https://vouch.example/new")
    notify.assert_not_called()
    assert {alias: state(alias) for alias in before} == before


def test_stale_routed_outcome_waits_for_postgres_writer_lock(routed_receive):
    if connections["other"].vendor != "postgresql":
        pytest.skip("Real routed row-lock overlap requires disposable PostgreSQL")
    processor, _current, _router = routed_receive
    default_before = state("default")
    newer_at = timezone.now()
    older_at = newer_at - timedelta(seconds=10)
    locked, release = Event(), Event()
    backend_pids = Queue()

    def receive(newer):
        try:
            conn = connections["other"]
            with conn.cursor() as cursor:
                cursor.execute("SET statement_timeout = '10s'")
                cursor.execute("SET lock_timeout = '8s'")
                cursor.execute("SELECT pg_backend_pid()")
                backend_pids.put((newer, cursor.fetchone()[0]))
            worker = WebmentionProcessor()
            outcome = _WebmentionOutcome(
                status="spam" if newer else "failed",
                received_at=newer_at if newer else older_at,
                spam_result={"is_spam": True},
                log=("info", "synthetic concurrent receive"),
            )
            apply = worker._apply_webmention_outcome

            def holding(*args):
                if newer:
                    locked.set()
                    assert release.wait(6)
                return apply(*args)

            with (
                patch.object(worker, "_collect_webmention_outcome", return_value=outcome),
                patch.object(worker, "_apply_webmention_outcome", side_effect=holding),
            ):
                return worker.process_webmention(SOURCE, TARGET).status
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(receive, True)
        second = None
        try:
            assert locked.wait(5), "newer receive did not acquire the writer row lock"
            second = pool.submit(receive, False)
            pids = dict(backend_pids.get(timeout=5) for _ in range(2))
            deadline = time.monotonic() + 5
            blocked = False
            while time.monotonic() < deadline:
                with connections["other"].cursor() as cursor:
                    cursor.execute("SELECT pg_blocking_pids(%s)", [pids[False]])
                    blocked = pids[True] in cursor.fetchone()[0]
                if blocked or second.done():
                    break
                time.sleep(0.01)
            assert blocked, "older outcome did not wait on the authoritative parent lock"
        finally:
            release.set()
            assert first.result(timeout=10) == "spam"
            if second is not None:
                assert second.result(timeout=10) == "spam"
    parent = Webmention.objects.using("other").get(pk=101)
    assert parent.last_received_at == newer_at
    assert parent.status == "spam"
    assert state("default") == default_before


@pytest.mark.parametrize("status", ["verified", "failed", "spam"])
def test_newer_routed_outcome_refuses_stale_writes_including_vouch(routed_receive, monkeypatch, status):
    processor, current, _router = routed_receive
    current[0] = NEW
    collect = processor._collect_webmention_outcome
    committed = []

    def collect_then_commit_newer(*args):
        outcome = collect(*args)
        outcome.status = status
        Webmention.objects.using("other").filter(pk=101).update(
            status="spam", last_received_at=outcome.received_at + timedelta(seconds=1), content="newer content"
        )
        committed.append({alias: state(alias) for alias in ("default", "other")})
        return outcome

    monkeypatch.setattr(processor, "_collect_webmention_outcome", collect_then_commit_newer)
    with patch("indieweb.processors.webmention_received.send_robust") as notify:
        result = processor.process_webmention(SOURCE, TARGET, vouch_url="https://vouch.example/stale")
    notify.assert_not_called()
    assert result.status == "spam"
    assert result._state.db == "other"
    assert {alias: state(alias) for alias in committed[0]} == committed[0]


def test_receive_creates_new_parent_and_family_only_on_writer(routed_receive):
    processor, current, _router = routed_receive
    current[0] = NEW
    default_before = state("default")
    parent = processor.process_webmention(SOURCE + "/new", TARGET)
    assert parent._state.db == "other"
    assert parent.status == "verified"
    assert WebmentionSourceSnapshot.objects.using("other").get(webmention_id=parent.pk).raw_source_html == NEW
    assert WebmentionNestedResponse.objects.using("other").filter(webmention_id=parent.pk).count() == 2
    assert state("default") == default_before


@pytest.mark.parametrize("stale_read_row", [False, True])
def test_queued_processing_loads_row_from_writer_not_read_replica(routed_receive, stale_read_row):
    processor, _current, receive_router = routed_receive
    Webmention.objects.using("other").create(
        pk=202, source_url=SOURCE + "/queued", target_url=TARGET, vouch_url="https://vouch.example/current"
    )
    if stale_read_row:
        # A lagging read database still holds an older generation of the row.
        Webmention.objects.using("default").create(
            pk=202, source_url=SOURCE + "/stale", target_url=TARGET, vouch_url="https://vouch.example/stale"
        )
    before = state("default")
    original_route = receive_router.db_for_write

    def switch_after_resolution(model, **hints):
        alias = original_route(model, **hints)
        if model is Webmention:
            receive_router.writer = "default"
        return alias

    with patch.object(receive_router, "db_for_write", switch_after_resolution):
        result = process_queued_webmention(202, client=processor._injected_client)

    assert result.pk == 202
    assert result.source_url == SOURCE + "/queued"
    assert result.vouch_url == "https://vouch.example/current"
    assert Webmention.objects.using("other").get(pk=202).status == "verified"
    assert WebmentionSourceSnapshot.objects.using("other").filter(webmention_id=202).exists()
    assert state("default") == before


def test_queued_processing_does_not_settle_replacement_row(monkeypatch):
    old = Webmention.objects.create(source_url=SOURCE, target_url=TARGET)
    admitted_id = old.pk
    original_init = WebmentionProcessor.__init__

    def replace_after_admission(self, **kwargs):
        original_init(self, **kwargs)
        old.delete()
        Webmention.objects.create(pk=admitted_id + 1, source_url=SOURCE, target_url=TARGET)

    monkeypatch.setattr(WebmentionProcessor, "__init__", replace_after_admission)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=NEW)
        )
    ) as client:
        with pytest.raises(Webmention.DoesNotExist):
            process_queued_webmention(admitted_id, client=client)

    replacement = Webmention.objects.get()
    assert replacement.pk != admitted_id
    assert replacement.status == "pending" and replacement.last_received_at is None
    assert not WebmentionNestedResponse.objects.exists()
    assert not WebmentionSourceSnapshot.objects.exists()


def test_sqlite_reserves_writer_before_reloading_receive(sqlite_wal, monkeypatch):
    Webmention.objects.create(source_url=SOURCE, target_url=TARGET)
    newer_at = timezone.now()
    older_at = newer_at - timedelta(seconds=1)
    older = WebmentionProcessor()
    newer = WebmentionProcessor()
    for processor, received_at in ((older, older_at), (newer, newer_at)):
        outcome = _WebmentionOutcome(status="failed", received_at=received_at, log=("info", "Synthetic outcome"))
        monkeypatch.setattr(processor, "_collect_webmention_outcome", lambda *args, outcome=outcome: outcome)

    main_connection = sqlite_wal.connection

    def competing_receive():
        try:
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA busy_timeout=0")
            assert connection.connection is not main_connection
            return older.process_webmention(SOURCE, TARGET).last_received_at
        except OperationalError as exc:
            # The first competing write must be blocked if the newer receive
            # reserved the writer before taking its read snapshot.
            assert exc.__cause__.sqlite_errorcode == sqlite3.SQLITE_BUSY
            return None
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        competed = []

        def compete_after_reload(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if (
                not competed
                and sqlite_wal.in_atomic_block
                and sql.startswith("SELECT")
                and "indieweb_webmention" in sql
            ):
                competed.append(pool.submit(competing_receive).result(timeout=5))
            return result

        with sqlite_wal.execute_wrapper(compete_after_reload):
            assert newer.process_webmention(SOURCE, TARGET).last_received_at == newer_at
        assert competed == [None]
        assert pool.submit(competing_receive).result(timeout=5) == newer_at

    assert Webmention.objects.get().last_received_at == newer_at
