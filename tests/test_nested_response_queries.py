"""Query and transaction bounds for synthetic nested replies."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from indieweb.models import Webmention, WebmentionNestedResponse
from indieweb.processors import WebmentionProcessor
from tests.test_webmention_processor import _nested_candidate

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("size", [1, 50])
@pytest.mark.parametrize("phase", ["fresh", "unchanged", "changed"])
def test_nested_sync_query_budget(size, phase, django_assert_num_queries):
    parent = Webmention.objects.create(
        source_url="https://source.example/parent", target_url="https://target.example/"
    )
    candidates = [_nested_candidate(f"https://reply.example/{i}") for i in range(size)]
    processor = WebmentionProcessor()
    first = timezone.now() - timedelta(days=1)
    if phase != "fresh":
        processor._sync_nested_responses(
            webmention=parent, candidates=candidates, previous_identities=set(), seen_at=first
        )
    if phase == "changed":
        candidates = [{**row, "content": "Changed", "parsed_h_entry": {"updated": True}} for row in candidates]
    seen = timezone.now()
    with django_assert_num_queries(3 if size == 1 else 4):
        processor._sync_nested_responses(
            webmention=parent, candidates=candidates, previous_identities=set(), seen_at=seen
        )
    rows = list(parent.nested_responses.order_by("identity"))
    assert len(rows) == size
    for row in rows:
        assert row.status == "verified"
        assert row.first_seen_at == (seen if phase == "fresh" else first)
        assert row.last_seen_at == row.verified_at == seen
        assert row.modified >= row.created
        if phase == "changed":
            assert row.content == "Changed"
            assert row.parsed_h_entry == {"updated": True}
            assert row.modified > row.created


def test_nested_bulk_rollback_and_parent_isolation():
    parent = Webmention.objects.create(
        source_url="https://source.example/parent", target_url="https://target.example/"
    )
    sibling = Webmention.objects.create(source_url="https://source.example/sibling", target_url=parent.target_url)
    processor = WebmentionProcessor()
    now = timezone.now()
    old = _nested_candidate("https://reply.example/old")
    processor._sync_nested_responses(webmention=parent, candidates=[old], previous_identities=set(), seen_at=now)
    processor._sync_nested_responses(webmention=sibling, candidates=[old], previous_identities=set(), seen_at=now)
    original_update = QuerySet.bulk_update
    calls = []

    def update_then_fail(self, *args, **kwargs):
        result = original_update(self, *args, **kwargs)
        if self.model is WebmentionNestedResponse:
            calls.append(result)
            raise IntegrityError("synthetic nested write failure")
        return result

    with transaction.atomic(), patch.object(QuerySet, "bulk_update", update_then_fail):
        processor._sync_nested_responses_safely(
            webmention=parent,
            candidates=[{**old, "content": "Changed"}, _nested_candidate("https://reply.example/new")],
            previous_identities={old["identity"]},
            seen_at=now + timedelta(seconds=1),
        )
        parent.status = "verified"
        parent.save(update_fields=["status"])
    assert calls == [1]
    assert list(parent.nested_responses.values_list("identity", "content")) == [(old["identity"], "Nice")]
    parent.refresh_from_db()
    assert parent.status == "verified"
    processor._sync_nested_responses(
        webmention=parent, candidates=[], previous_identities={old["identity"]}, seen_at=now
    )
    retired = parent.nested_responses.get()
    assert retired.status == "missing" and retired.verified_at is None
    assert retired.first_seen_at == now and retired.content == "Nice"
    assert sibling.nested_responses.get().status == "verified"
    # Reappearance preserves the identity/first observation and last candidate wins.
    processor._sync_nested_responses(
        webmention=parent,
        candidates=[old, {**old, "content": "Last"}],
        previous_identities=set(),
        seen_at=now + timedelta(seconds=2),
    )
    current = parent.nested_responses.get()
    assert current.pk == retired.pk and current.first_seen_at == now
    assert current.status == "verified" and current.content == "Last"


def _source_html(target, identities):
    children = "".join(
        f'<div class="h-entry"><a class="u-url" href="{identity}">Reply</a>'
        '<p class="e-content">Synthetic reply</p></div>'
        for identity in identities
    )
    return f'<div class="h-entry"><a href="{target}">Target</a>{children}</div>'


def test_processor_nested_failure_rolls_back_children_only(django_capture_on_commit_callbacks):
    from tests.test_webmention_processor import _processor_client, _source_response

    processor = WebmentionProcessor()
    source, target = "https://source.example/parent", "https://target.example/"
    old, new = "https://reply.example/old", "https://reply.example/new"
    with _processor_client(
        processor, return_value=_source_response(status_code=200, text=_source_html(target, [old]))
    ):
        parent = processor.process_webmention(source, target)
    child = parent.nested_responses.get()
    before = WebmentionNestedResponse.objects.values().get(pk=child.pk)
    original = QuerySet.bulk_update
    calls = []

    def fail_after_update(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if self.model is WebmentionNestedResponse:
            calls.append(result)
            raise IntegrityError("synthetic nested write failure")
        return result

    with (
        patch.object(QuerySet, "bulk_update", fail_after_update),
        _processor_client(
            processor, return_value=_source_response(status_code=200, text=_source_html(target, [old, new]))
        ),
        django_capture_on_commit_callbacks(execute=True),
    ):
        processor.process_webmention(source, target)
    assert calls == [1]
    parent.refresh_from_db()
    assert parent.status == "verified"
    assert list(parent.nested_responses.values()) == [before]


def test_processor_stale_parent_cannot_replace_newer_nested_batch():
    from tests.test_webmention_processor import _processor_client, _source_response

    processor = WebmentionProcessor()
    source, target = "https://source.example/parent", "https://target.example/"
    old, new = "https://reply.example/old", "https://reply.example/new"
    original = processor._collect_webmention_outcome
    collected = []

    def collect_with_interleaved_newer_receive(*args):
        outcome = original(*args)
        collected.append(outcome)
        if len(collected) == 1:
            processor.process_webmention(source, target)
        return outcome

    with (
        patch.object(processor, "_collect_webmention_outcome", side_effect=collect_with_interleaved_newer_receive),
        _processor_client(
            processor,
            side_effect=[
                _source_response(status_code=200, text=_source_html(target, [old])),
                _source_response(status_code=200, text=_source_html(target, [new])),
            ],
        ),
    ):
        parent = processor.process_webmention(source, target)
    assert len(collected) == 2
    assert parent.last_received_at == collected[1].received_at
    assert list(parent.nested_responses.values_list("identity", flat=True)) == [new]
