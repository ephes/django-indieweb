"""Explicit no-op saves must not advance WebSub secret key rotation."""

import pytest

from indieweb.models import WebSubSubscription


@pytest.fixture
def old_key_subscription(settings, db):
    settings.SECRET_KEY = "synthetic-old-key"
    settings.SECRET_KEY_FALLBACKS = []
    row = WebSubSubscription.objects.create(
        hub_url="https://hub.example/",
        topic_url="https://topic.example/",
        secret="synthetic-active-secret",
        pending_secret="synthetic-pending-secret",
    )
    settings.SECRET_KEY = "synthetic-new-key"
    settings.SECRET_KEY_FALLBACKS = ["synthetic-old-key"]
    return row


@pytest.mark.parametrize("empty_fields", [set(), [], ()], ids=["set", "list", "tuple"])
def test_empty_update_fields_preserves_secrets_and_modified(
    old_key_subscription, empty_fields, django_assert_num_queries
):
    row = old_key_subscription
    before = WebSubSubscription.objects.values().get(pk=row.pk)
    row.last_request_error = "deliberately unsaved"

    with django_assert_num_queries(0):
        row.save(update_fields=empty_fields)

    assert (row.secret, row.pending_secret, row.modified) == (
        before["secret"],
        before["pending_secret"],
        before["modified"],
    )
    assert WebSubSubscription.objects.values().get(pk=row.pk) == before


def test_real_partial_save_still_migrates_both_secrets(old_key_subscription, settings):
    row = old_key_subscription
    before = (row.secret, row.pending_secret)
    row.last_request_error = "synthetic diagnostic"
    row.save(update_fields=["last_request_error"])

    row.refresh_from_db()
    settings.SECRET_KEY_FALLBACKS = []
    assert row.secret != before[0]
    assert row.pending_secret != before[1]
    assert row.get_secret() == "synthetic-active-secret"
    assert row.get_pending_secret() == "synthetic-pending-secret"
    assert row.last_request_error == "synthetic diagnostic"
