"""A locked descriptor admits work only while its directory and name remain authoritative."""

import os

import pytest

from indieweb import parse_isolation
from indieweb.parse_isolation import WebmentionSourceRejected


@pytest.fixture(autouse=True)
def parse_worker():
    """Use real POSIX admission without the suite's inline parser replacement."""
    pytest.importorskip("fcntl")


@pytest.mark.parametrize("replacement", ["slot", "directory", "permissions"])
def test_displaced_slot_never_starts_worker(settings, tmp_path, monkeypatch, replacement):
    import fcntl

    directory = tmp_path / "slots"
    directory.mkdir(mode=0o700)
    settings.INDIEWEB_WEBMENTION_PARSE_LOCK_DIR = str(directory)
    settings.INDIEWEB_WEBMENTION_PARSE_MAX_CONCURRENT = 1
    real_flock = fcntl.flock
    real_open = os.open
    descriptors = []

    def record_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        descriptors.append(fd)
        return fd

    def replace_after_lock(fd, operation):
        real_flock(fd, operation)
        if replacement == "directory":
            directory.rename(tmp_path / "displaced")
            directory.mkdir(mode=0o700)
        elif replacement == "slot":
            (directory / "0.lock").rename(directory / "displaced.lock")
            new_fd = real_open(directory / "0.lock", os.O_CREAT | os.O_RDWR, 0o600)
            os.close(new_fd)
        else:
            os.chmod(directory / "0.lock", 0o644)

    monkeypatch.setattr(os, "open", record_open)
    monkeypatch.setattr(fcntl, "flock", replace_after_lock)
    monkeypatch.setattr(
        parse_isolation, "_worker_command", lambda limits: pytest.fail("displaced pool admitted worker")
    )
    with pytest.raises(WebmentionSourceRejected, match="parse capacity unavailable"):
        parse_isolation.run_parse_worker({})
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
