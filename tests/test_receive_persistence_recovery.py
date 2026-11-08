"""Committed receive recovery after partial snapshot and nested-child writes."""

import hashlib
import json

import httpx
import pytest
from django.db import IntegrityError, connection
from django.db.models import QuerySet
from django.utils import timezone

from indieweb.models import WebmentionNestedResponse, WebmentionSourceSnapshot
from indieweb.processors import WebmentionProcessor

SOURCE = "https://source.example/parent"
TARGET = "https://target.example/post"
ONE = "https://source.example/one"
TWO = "https://source.example/two"
THREE = "https://source.example/three"


def document(children):
    nested = "".join(
        f'<article class="h-entry"><a class="u-url" href="{identity}">child</a>'
        f'<div class="e-content">{content}</div></article>'
        for identity, content in children
    )
    return f'<article class="h-entry"><a class="u-in-reply-to" href="{TARGET}">reply</a>{nested}</article>'


OLD = document([(ONE, "old one"), (TWO, "old two")])
NEW = document([(ONE, "new one"), (THREE, "new three")])


@pytest.fixture
def receive_journey(concurrent_database):
    # concurrent_database requires persistent SQLite or PostgreSQL so close()
    # really reopens a connection rather than retaining shared in-memory state.
    current = [OLD]
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=current[0])
        )
    ) as client:
        processor = WebmentionProcessor(client=client)
        parent = processor.process_webmention(SOURCE, TARGET)
        assert parent.status == "verified"
        current[0] = NEW
        yield processor, parent


def children_state(parent):
    return list(WebmentionNestedResponse.objects.filter(webmention=parent).order_by("identity").values())


def assert_converged(parent, old_ids, snapshot_pk):
    parent.refresh_from_db()
    assert parent.status == "verified" and parent.verified_at is not None
    snapshot = WebmentionSourceSnapshot.objects.get(webmention=parent)
    assert snapshot.pk == snapshot_pk
    assert snapshot.raw_source_html == NEW
    assert snapshot.content_digest == hashlib.sha256(NEW.encode()).hexdigest()
    assert snapshot.nested_response_identities == [ONE, THREE]
    assert snapshot.parsed_h_entry["properties"]["in-reply-to"] == [TARGET]
    children = {row.identity: row for row in parent.nested_responses.all()}
    assert set(children) == {ONE, TWO, THREE}
    assert (children[ONE].pk, children[TWO].pk) == (old_ids[ONE], old_ids[TWO])
    assert (children[ONE].content, children[THREE].content) == ("new one", "new three")
    for identity in (ONE, THREE):
        assert children[identity].status == "verified"
        assert children[identity].verified_at is not None
        parsed = children[identity].parsed_h_entry
        assert children[identity].content_digest == processor_digest(parsed)
    assert children[TWO].status == "missing"
    assert children[TWO].verified_at is None
    assert children[TWO].content == "old two"


def processor_digest(parsed):
    return hashlib.sha256(json.dumps(parsed, sort_keys=True).encode()).hexdigest()


@pytest.mark.django_db(transaction=True)
def test_snapshot_write_failure_converges_after_reopen_and_retry(receive_journey, monkeypatch):
    processor, parent = receive_journey
    snapshot = WebmentionSourceSnapshot.objects.get(webmention=parent)
    old_ids = dict(parent.nested_responses.values_list("identity", "pk"))
    original = processor._store_source_snapshot
    injected = []

    def write_then_constraint_failure(**kwargs):
        original(**kwargs)
        # Real unique constraint error after the snapshot update has executed.
        try:
            WebmentionSourceSnapshot.objects.create(
                webmention=parent,
                raw_source_html="duplicate",
                final_source_url=SOURCE,
                content_digest="duplicate",
                fetched_at=timezone.now(),
            )
        except IntegrityError:
            injected.append(True)
            raise

    with monkeypatch.context() as patch:
        patch.setattr(processor, "_store_source_snapshot", write_then_constraint_failure)
        processor.process_webmention(SOURCE, TARGET)
    assert injected == [True]
    connection.close()
    parent.refresh_from_db()
    assert parent.status == "verified" and parent.verified_at is not None
    retained = WebmentionSourceSnapshot.objects.get(webmention=parent)
    assert retained.raw_source_html == OLD
    assert retained.content_digest == snapshot.content_digest
    assert retained.nested_response_identities == [ONE, TWO]
    after_failure = {row.identity: row for row in parent.nested_responses.all()}
    assert after_failure[ONE].content == "new one"
    assert after_failure[TWO].status == "missing"
    assert after_failure[THREE].status == "verified"
    new_id = after_failure[THREE].pk
    processor.process_webmention(SOURCE, TARGET)
    connection.close()
    assert_converged(parent, old_ids, snapshot.pk)
    assert parent.nested_responses.get(identity=THREE).pk == new_id
    assert WebmentionSourceSnapshot.objects.filter(webmention=parent).count() == 1


@pytest.mark.django_db(transaction=True)
def test_partial_child_constraint_failure_rolls_back_then_retries_from_advanced_snapshot(receive_journey, monkeypatch):
    processor, parent = receive_journey
    old_children = children_state(parent)
    old_ids = {child["identity"]: child["id"] for child in old_children}
    snapshot_pk = WebmentionSourceSnapshot.objects.get(webmention=parent).pk
    original = QuerySet.bulk_update
    injected = []

    def update_then_constraint_failure(queryset, *args, **kwargs):
        result = original(queryset, *args, **kwargs)
        if queryset.model is WebmentionNestedResponse:
            assert result == 1
            # The new child was inserted and the retained child updated before
            # an actual uniqueness violation poisons this inner savepoint.
            assert parent.nested_responses.get(identity=ONE).content == "new one"
            assert parent.nested_responses.filter(identity=THREE).exists()
            try:
                WebmentionNestedResponse.objects.create(
                    webmention=parent, identity=ONE, first_seen_at=timezone.now(), last_seen_at=timezone.now()
                )
            except IntegrityError:
                injected.append(True)
                raise
        return result

    with monkeypatch.context() as patch:
        patch.setattr(QuerySet, "bulk_update", update_then_constraint_failure)
        processor.process_webmention(SOURCE, TARGET)
    assert injected == [True]
    connection.close()
    parent.refresh_from_db()
    assert parent.status == "verified" and parent.verified_at is not None
    assert children_state(parent) == old_children  # Complete old set, including timestamps and content.
    snapshot = WebmentionSourceSnapshot.objects.get(webmention=parent)
    assert snapshot.raw_source_html == NEW
    assert snapshot.nested_response_identities == [ONE, THREE]
    processor.process_webmention(SOURCE, TARGET)
    connection.close()
    assert_converged(parent, old_ids, snapshot_pk)
