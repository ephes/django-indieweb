"""HTML profile parsing uses the shared bounded child, never the application parser."""

import sys

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from indieweb import parse_isolation, webmention_parse_worker
from indieweb.h_card import parse_h_card
from indieweb.models import Profile


@pytest.fixture(autouse=True)
def parse_worker():
    """Exercise the real child boundary instead of the suite's inline fixture."""
    pytest.importorskip("fcntl")


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["hang", "expand"])
def test_hcard_worker_refusal_preserves_profile(settings, tmp_path, monkeypatch, caplog, mode):
    profile = Profile.objects.create(
        user=get_user_model().objects.create_user(username="synthetic-card"), h_card={"name": ["Before"]}
    )
    marker = tmp_path / "started"
    script = """
import pathlib, sys, time
from indieweb import webmention_parse_worker as worker
def parse(**kwargs):
    pathlib.Path(sys.argv[1]).touch()
    print('synthetic-private-html', file=sys.stderr)
    if sys.argv[2] == 'hang':
        time.sleep(30)
    return {'items': [{'type': ['h-card'], 'properties': {'name': ['x' * 100000]}}]}
worker.mf2py.parse = parse
raise SystemExit(worker.main(sys.argv[3:]))
"""
    real_command = parse_isolation._worker_command
    monkeypatch.setattr(
        parse_isolation,
        "_worker_command",
        lambda limits: [sys.executable, "-c", script, str(marker), mode, *real_command(limits)[3:]],
    )
    settings.INDIEWEB_WEBMENTION_PARSE_WALL_SECONDS = 1
    settings.INDIEWEB_WEBMENTION_PARSE_MAX_RESULT_BYTES = 4096
    monkeypatch.setattr(
        webmention_parse_worker.mf2py, "parse", lambda **kwargs: pytest.fail("application parsed HTML")
    )
    with pytest.raises(ValidationError) as caught:
        profile.h_card = parse_h_card('<div class="h-card">synthetic-private-html</div>')
        profile.save()
    assert caught.value.code == "invalid_h_card"
    assert marker.exists(), "the synthetic expensive parser must run in the child"
    assert "synthetic-private-html" not in str(caught.value) + caplog.text
    profile.refresh_from_db()
    assert profile.h_card == {"name": ["Before"]}
    assert profile.name == "Before"
    # Timeout/failure reaps the child and releases admission capacity.
    settings.INDIEWEB_WEBMENTION_PARSE_MAX_CONCURRENT = 1
    with parse_isolation._parse_slot():
        pass


def test_hcard_real_worker_preserves_normalized_properties(monkeypatch):
    monkeypatch.setattr(
        webmention_parse_worker.mf2py, "parse", lambda **kwargs: pytest.fail("application parsed HTML")
    )
    result = parse_h_card(
        '<div class="h-card"><a class="p-name u-url" href="/person">Synthetic</a>'
        '<span class="p-custom-key">Value</span></div>',
        url="https://synthetic.example/",
    )
    assert result == {"name": ["Synthetic"], "url": ["https://synthetic.example/person"], "custom_key": ["Value"]}


@pytest.mark.parametrize("properties", [None, [], "private-html"])
def test_hcard_malformed_worker_result_is_invalid(monkeypatch, properties):
    monkeypatch.setattr(parse_isolation, "run_parse_worker", lambda request: {"properties": properties})
    with pytest.raises(ValidationError) as caught:
        parse_h_card("<div></div>")
    assert caught.value.code == "invalid_h_card"
