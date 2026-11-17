"""Nested display eligibility cannot borrow a same-PK parent from another DB."""

import pytest
from django.utils import timezone

from indieweb.models import Webmention, WebmentionNestedResponse

pytestmark = pytest.mark.django_db(databases=["default", "other"])


class ReplicaReadRouter:
    def db_for_read(self, model, **hints):
        return "default"


@pytest.mark.parametrize("loading", ["lazy", "select_related", "prefetch_related"])
@pytest.mark.parametrize("child_status", ["verified", "missing", "failed", "spam"])
@pytest.mark.parametrize(
    "default_status,other_status",
    [("verified", "spam"), ("spam", "verified"), ("verified", "pending"), ("verified", "failed")],
)
def test_nested_display_uses_child_database(settings, loading, child_status, default_status, other_status):
    settings.DATABASE_ROUTERS = [ReplicaReadRouter()]
    for alias, status in (("default", default_status), ("other", other_status)):
        Webmention.objects.using(alias).create(
            pk=101, source_url="https://source.example/parent", target_url="https://target.example/post", status=status
        )
    now = timezone.now()
    child = WebmentionNestedResponse.objects.using("other").create(
        webmention_id=101,
        identity="https://source.example/child",
        status=child_status,
        first_seen_at=now,
        last_seen_at=now,
    )
    queryset = WebmentionNestedResponse.objects.using("other")
    if loading != "lazy":
        queryset = getattr(queryset, loading)("webmention")
    loaded = queryset.get(pk=child.pk)
    assert loaded._state.db == "other"
    assert loaded.is_currently_displayable == (child_status == "verified" and other_status == "verified")


@pytest.mark.parametrize("cached_missing", [False, True])
def test_nested_missing_parent_is_not_displayable(cached_missing):
    parent = Webmention.objects.using("default").create(
        pk=101,
        source_url="https://source.example/parent",
        target_url="https://target.example/post",
        status="verified",
    )
    # Unsaved orphan: its parent PK exists only in the unrelated default DB.
    child = WebmentionNestedResponse(webmention_id=parent.pk, status="verified")
    child._state.db = "other"
    if cached_missing:
        child.webmention = None
    assert child.is_currently_displayable is False
