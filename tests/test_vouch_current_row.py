"""Vouch preservation across independent committed receive connections."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest
from django.contrib.sites.models import Site
from django.db import connections
from django.urls import reverse
from django.utils import timezone

from indieweb.models import Webmention
from indieweb.processors import WebmentionProcessor

SOURCE = "https://source.example/reply"
TARGET = "https://target.example/post"
VOUCH = "https://trusted.example/current"
REPLACEMENT = "https://trusted.example/replacement"


def commit_verification(pk, verified_at, *, received_at=None):
    """Use another connection; returning proves the competing write committed."""

    def write():
        try:
            Webmention.objects.filter(pk=pk).update(
                vouch_url=VOUCH, vouch_verified_at=verified_at, last_received_at=received_at
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(write).result(timeout=10)


@pytest.mark.django_db(transaction=True)
def test_submission_preserves_vouch_verified_after_lookup(client, settings, monkeypatch):
    settings.INDIEWEB_WEBMENTION_ENQUEUE = "tests.webmention_enqueue_hooks.capture_webmention_id"
    Site.objects.update_or_create(pk=settings.SITE_ID, defaults={"domain": "target.example", "name": "test"})
    Site.objects.clear_cache()
    existing = Webmention.objects.create(source_url=SOURCE, target_url=TARGET)
    verified_at = timezone.now()
    manager = Webmention.objects
    original = manager.get_or_create

    def lookup_then_verify(*args, **kwargs):
        stale, created = original(*args, **kwargs)
        assert stale.vouch_verified_at is None
        commit_verification(stale.pk, verified_at)
        return stale, created

    monkeypatch.setattr(manager, "get_or_create", lookup_then_verify)
    response = client.post(reverse("indieweb:webmention"), {"source": SOURCE, "target": TARGET, "vouch": REPLACEMENT})
    assert response.status_code == 202
    existing.refresh_from_db()
    assert (existing.vouch_url, existing.vouch_verified_at) == (VOUCH, verified_at)


@pytest.mark.django_db(transaction=True)
def test_processor_preserves_verification_committed_during_failed_replacement():
    existing = Webmention.objects.create(source_url=SOURCE, target_url=TARGET)
    verified_at = timezone.now()

    def fetch(request):
        # B started before A but settles while A is collecting. A's newer
        # watermark must not give it permission to erase B's verified Vouch.
        commit_verification(existing.pk, verified_at, received_at=verified_at - timedelta(seconds=10))
        return httpx.Response(410)

    with httpx.Client(transport=httpx.MockTransport(fetch)) as client:
        result = WebmentionProcessor(client=client).process_webmention(SOURCE, TARGET, vouch_url=REPLACEMENT)
    existing.refresh_from_db()
    assert result.status == "failed"  # A settled, rather than being skipped as stale.
    assert existing.last_received_at > verified_at - timedelta(seconds=10)
    assert (existing.vouch_url, existing.vouch_verified_at) == (VOUCH, verified_at)
