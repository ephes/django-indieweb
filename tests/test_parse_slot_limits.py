"""Configuration and every admission scan fit a finite filesystem/wait envelope."""

import os

import pytest

from indieweb import parse_isolation
from indieweb.parse_isolation import WebmentionParseCapacityError


@pytest.fixture(autouse=True)
def parse_worker():
    pytest.importorskip("fcntl")


@pytest.mark.parametrize("configured", [10**100, 65, "3", 3.0, 3.2, True, 0, -1, None])
def test_invalid_pool_limit_defaults_before_filesystem_work(settings, tmp_path, monkeypatch, caplog, configured):
    directory = tmp_path / "slots"
    settings.INDIEWEB_WEBMENTION_PARSE_LOCK_DIR = str(directory)
    settings.INDIEWEB_WEBMENTION_PARSE_MAX_CONCURRENT = configured
    real_makedirs = os.makedirs
    real_claim = parse_isolation._claim_parse_slot
    claimed_maxima = []

    def makedirs(*args, **kwargs):
        assert "Ignoring invalid INDIEWEB_WEBMENTION_PARSE_MAX_CONCURRENT" in caplog.text
        return real_makedirs(*args, **kwargs)

    def claim(directory, directory_fd, maximum, *args):
        claimed_maxima.append(maximum)
        return real_claim(directory, directory_fd, maximum, *args)

    monkeypatch.setattr(os, "makedirs", makedirs)
    monkeypatch.setattr(parse_isolation, "_claim_parse_slot", claim)
    with parse_isolation._parse_slot():
        pass
    assert claimed_maxima == [2]
    assert len(list(directory.iterdir())) == 1


@pytest.mark.parametrize("maximum", [1, 2, 64])
def test_supported_pool_limits_retained(settings, tmp_path, monkeypatch, maximum):
    settings.INDIEWEB_WEBMENTION_PARSE_LOCK_DIR = str(tmp_path)
    settings.INDIEWEB_WEBMENTION_PARSE_MAX_CONCURRENT = maximum
    real_claim = parse_isolation._claim_parse_slot
    observed = []

    def claim(directory, directory_fd, configured_maximum, *args):
        observed.append(configured_maximum)
        return real_claim(directory, directory_fd, configured_maximum, *args)

    monkeypatch.setattr(parse_isolation, "_claim_parse_slot", claim)
    with parse_isolation._parse_slot():
        pass
    assert observed == [maximum]


def test_occupied_scan_charged_to_wait_budget(settings, tmp_path, monkeypatch):
    import fcntl

    settings.INDIEWEB_WEBMENTION_PARSE_LOCK_DIR = str(tmp_path)
    settings.INDIEWEB_WEBMENTION_PARSE_MAX_CONCURRENT = 64
    settings.INDIEWEB_WEBMENTION_PARSE_SLOT_WAIT_SECONDS = 0.05
    now = 0.0
    real_open = os.open
    opened = []

    def slow_open(path, *args, **kwargs):
        nonlocal now
        fd = real_open(path, *args, **kwargs)
        if str(path).endswith(".lock"):
            now += 0.03
            opened.append(fd)
        return fd

    def occupied(fd, operation):
        raise BlockingIOError

    monkeypatch.setattr(os, "open", slow_open)
    monkeypatch.setattr(fcntl, "flock", occupied)
    monkeypatch.setattr(parse_isolation.time, "monotonic", lambda: now)
    with pytest.raises(WebmentionParseCapacityError):
        with parse_isolation._parse_slot():
            pytest.fail("occupied pool admitted a worker")
    assert len(opened) <= 2, "the inner scan must stop at the outer deadline"
    assert len(list(tmp_path.iterdir())) <= 2
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_late_lock_acquisition_releases_slot(settings, tmp_path, monkeypatch):
    import fcntl

    settings.INDIEWEB_WEBMENTION_PARSE_LOCK_DIR = str(tmp_path)
    settings.INDIEWEB_WEBMENTION_PARSE_MAX_CONCURRENT = 1
    settings.INDIEWEB_WEBMENTION_PARSE_SLOT_WAIT_SECONDS = 0.05
    now = 0.0
    real_flock = fcntl.flock
    acquired = []

    def late_flock(fd, operation):
        nonlocal now
        real_flock(fd, operation)
        acquired.append(fd)
        now += 0.06

    monkeypatch.setattr(fcntl, "flock", late_flock)
    monkeypatch.setattr(parse_isolation.time, "monotonic", lambda: now)
    with pytest.raises(WebmentionParseCapacityError):
        with parse_isolation._parse_slot():
            pytest.fail("expired admission started a worker")
    assert len(acquired) == 1
    with pytest.raises(OSError):
        os.fstat(acquired[0])
