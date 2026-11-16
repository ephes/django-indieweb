"""Transfer parent presentation bytes once regardless of nested response fanout."""

from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from indieweb.models import Webmention, WebmentionNestedResponse
from indieweb.templatetags.webmention_tags import show_webmentions


@pytest.mark.django_db
@pytest.mark.parametrize("size", [1, 40])
def test_parent_body_transferred_once(size):
    target = "https://target.example/large"
    body = "synthetic-parent-body " * 10000
    parent = Webmention.objects.create(
        source_url="https://source.example/parent",
        target_url=target,
        mention_type="reply",
        status="verified",
        content=body,
    )
    now = timezone.now()
    for index in range(size):
        WebmentionNestedResponse.objects.create(
            webmention=parent,
            identity=f"https://child.example/{index}",
            content=f"Child {index}",
            first_seen_at=now + timedelta(seconds=index),
            last_seen_at=now,
        )
    transferred = []

    class ObservedCursor:
        def __init__(self, cursor):
            self.cursor = cursor

        def __getattr__(self, name):
            return getattr(self.cursor, name)

        def observe(self, rows):
            transferred.extend(value for row in rows for value in row if value == body)
            return rows

        def fetchmany(self, *args):
            return self.observe(self.cursor.fetchmany(*args))

        def fetchall(self):
            return self.observe(self.cursor.fetchall())

        def fetchone(self):
            row = self.cursor.fetchone()
            return self.observe([row])[0] if row is not None else None

    def observe(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if sql.lstrip().upper().startswith("SELECT"):
            context["cursor"].cursor = ObservedCursor(context["cursor"].cursor)
        return result

    with connection.execute_wrapper(observe):
        result = show_webmentions(target)
    assert len(transferred) == 1, "joined children must never repeat the parent's large body over the DB boundary"
    assert len(result["webmentions"]) == 1
    row = result["webmentions"][0]
    assert row.content == body
    assert [child.content for child in row.displayable_nested_responses] == [
        f"Child {index}" for index in reversed(range(size))
    ]
