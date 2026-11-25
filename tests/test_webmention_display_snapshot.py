"""One rendering generation under committed moderation on another connection."""

from threading import Thread

import pytest
from django.db import connection, connections, transaction
from django.template.loader import render_to_string
from django.utils import timezone

from indieweb.models import Webmention, WebmentionNestedResponse
from indieweb.templatetags.webmention_tags import show_webmentions


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind", [None, "reply"])
@pytest.mark.parametrize("size", [1, 20])
def test_render_is_one_statement_snapshot(concurrent_database, kind, size):
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL")
            assert cursor.fetchone()[0] == "wal"
    target = "https://target.example/post"
    parent = Webmention.objects.create(
        source_url="https://source.example/parent", target_url=target, status="verified", mention_type="reply"
    )
    children = []
    direct = []
    for i in range(size):
        url = f"https://source.example/child/{i}"
        children.append(
            WebmentionNestedResponse.objects.create(
                webmention=parent,
                identity=url,
                content=f"Child {i}",
                first_seen_at=timezone.now(),
                last_seen_at=timezone.now(),
            ).pk
        )
        direct.append(
            Webmention.objects.create(source_url=url, target_url=target, status="pending", mention_type="like").pk
        )
    committed = []
    errors = []
    statements = []

    def moderate():
        try:
            with transaction.atomic():
                Webmention.objects.filter(pk=parent.pk).update(status="pending")
                Webmention.objects.filter(pk__in=direct).update(status="verified")
            committed.append(connection.connection)
        except BaseException as exc:
            errors.append(exc)
        finally:
            connections.close_all()

    def after_select(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if sql.lstrip(" \t\n(").upper().startswith("SELECT"):
            statements.append(sql)
            if len(statements) == 1:
                worker = Thread(target=moderate, daemon=True)
                worker.start()
                worker.join(10)
                assert not worker.is_alive(), "moderation did not commit"
                assert not errors, errors
                assert committed[0] is not connection.connection
        return result

    with connection.execute_wrapper(after_select):
        result = show_webmentions(target, kind)
        output = render_to_string("indieweb/webmentions.html", result)
    actual = (
        {row.pk for row in result["webmentions"]},
        {child.pk for row in result["webmentions"] for child in row.displayable_nested_responses},
    )
    before = ({parent.pk}, set(children))
    after = (set(direct) if kind is None else set(), set())
    assert actual in (before, after), "mixed parent/child/direct-source moderation generations"
    assert len(statements) == 1, "rendering must retain a constant single-statement query budget"
    assert len(committed) == 1
    if actual == before:
        assert all(f"Child {i}" in output for i in range(size))
    fresh = show_webmentions(target, kind)
    assert {row.pk for row in fresh["webmentions"]} == after[0]
    assert not any(row.displayable_nested_responses for row in fresh["webmentions"])


@pytest.mark.django_db(databases=["default", "other"])
def test_display_snapshot_deferred_fields_use_the_statement_database(settings, django_assert_num_queries):
    target = "https://target.example/routed-post"
    now = timezone.now()
    for alias in ("default", "other"):
        Webmention.objects.using(alias).create(
            pk=201,
            source_url="https://source.example/parent",
            target_url=target,
            status="verified",
            mention_type="reply",
            content=f"Projected from {alias}",
            spam_check_result={"replica": alias},
        )
        WebmentionNestedResponse.objects.using(alias).create(
            pk=202,
            webmention_id=201,
            identity="https://source.example/child",
            first_seen_at=now,
            last_seen_at=now,
            parsed_h_entry={"replica": alias},
        )

    class ChangingReadRouter:
        def __init__(self):
            self.lookups = []

        def db_for_read(self, model, **hints):
            if "instance" in hints:
                return None  # Deferred loads fall back to the hydrated instance's database.
            self.lookups.append(model)
            # Allow the unpinned iterator to choose the same alias for cursor
            # settings and for SQL, then simulate a change of preferred replica.
            return "other" if len(self.lookups) <= 2 else "default"

    router = ChangingReadRouter()
    settings.DATABASE_ROUTERS = [router]

    with django_assert_num_queries(1, using="other"), django_assert_num_queries(0, using="default"):
        (parent,) = show_webmentions(target)["webmentions"]
    (child,) = parent.displayable_nested_responses
    assert parent.content == "Projected from other"
    assert "spam_check_result" in parent.get_deferred_fields()
    assert "parsed_h_entry" in child.get_deferred_fields()
    assert (parent.spam_check_result, child.parsed_h_entry) == ({"replica": "other"}, {"replica": "other"})
    assert router.lookups == [Webmention]
