"""Parse admission capabilities across process death and unsafe slot objects."""

import os
import stat
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from indieweb import parse_isolation
from indieweb.parse_isolation import WebmentionParseCapacityError, WebmentionSourceRejected


@pytest.fixture(autouse=True)
def parse_worker():
    """These tests exercise the real subprocess admission boundary."""
    pytest.importorskip("fcntl")
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("parse admission requires no-follow descriptor support")


def wait_until(predicate, *, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail("synthetic process did not reach its checkpoint")


WORKER = """
import os, pathlib, sys, time
ready, release, finished = map(pathlib.Path, sys.argv[1:])
ready.write_text(str(os.getpid()))
deadline = time.monotonic() + 20
while not release.exists() and time.monotonic() < deadline:
    time.sleep(0.01)
finished.touch()
print('{}')
"""

PARENT = """
import sys
from django.conf import settings
settings.configure(
    SECRET_KEY='synthetic-parent-death',
    INDIEWEB_WEBMENTION_PARSE_LOCK_DIR=sys.argv[1],
    INDIEWEB_WEBMENTION_PARSE_MAX_CONCURRENT=1,
    INDIEWEB_WEBMENTION_PARSE_WALL_SECONDS=25,
    INDIEWEB_WEBMENTION_PARSE_REQUIRE_OS_LIMITS=False,
)
from indieweb import parse_isolation
parse_isolation._worker_command = lambda limits: [sys.executable, '-c', sys.argv[2], *sys.argv[3:]]
parse_isolation.run_parse_worker({})
"""


def test_slot_survives_death_of_spawning_parent(settings, tmp_path, monkeypatch):
    directory = tmp_path / "slots"
    directory.mkdir(mode=0o700)
    ready, release, finished = (tmp_path / name for name in ("ready", "release", "finished"))
    settings.INDIEWEB_WEBMENTION_PARSE_LOCK_DIR = str(directory)
    settings.INDIEWEB_WEBMENTION_PARSE_MAX_CONCURRENT = 1
    settings.INDIEWEB_WEBMENTION_PARSE_SLOT_WAIT_SECONDS = 0.05
    monkeypatch.setattr(parse_isolation, "_worker_command", lambda limits: [sys.executable, "-c", "print('{}')"])
    parent = subprocess.Popen(
        [sys.executable, "-c", PARENT, str(directory), WORKER, str(ready), str(release), str(finished)],
        env=parse_isolation._worker_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        wait_until(ready.exists)
        assert parent.poll() is None
        parent.kill()
        parent.communicate(timeout=5)  # Reap the actual spawning parent.
        assert not finished.exists()
        # This process is the third contender; only the orphan worker owns the
        # inherited descriptor now. No elapsed-time assumption proves the lock.
        with pytest.raises(WebmentionParseCapacityError):
            parse_isolation.run_parse_worker({})
    finally:
        release.touch()
        if parent.poll() is None:
            parent.kill()
        parent.communicate(timeout=5)
        if ready.exists():
            wait_until(finished.exists)

            # Waiting for slot release proves the bounded orphan has exited its
            # descriptor lifetime; the OS reaps it after its parent was killed.
            def released():
                try:
                    with parse_isolation._parse_slot():
                        return True
                except WebmentionParseCapacityError:
                    return False

            wait_until(released)
    assert parse_isolation.run_parse_worker({}) == {}


def make_suspicious_slot(slot, kind):
    target = slot.with_name("target")
    if kind == "fifo":
        os.mkfifo(slot, 0o600)
    elif kind in ("symlink", "hardlink"):
        target.write_text("synthetic-marker")
        target.chmod(0o600)
        if kind == "symlink":
            slot.symlink_to(target)
        else:
            os.link(target, slot)
    else:
        slot.write_text("synthetic-marker")
        slot.chmod({"public": 0o644, "executable": 0o700, "foreign-owner": 0o600}[kind])
    return target


@pytest.mark.parametrize("kind", ["fifo", "symlink", "hardlink", "public", "executable", "foreign-owner"])
def test_suspicious_slot_objects_refused_without_mutation(settings, tmp_path, monkeypatch, kind):
    settings.INDIEWEB_WEBMENTION_PARSE_LOCK_DIR = str(tmp_path)
    settings.INDIEWEB_WEBMENTION_PARSE_MAX_CONCURRENT = 1
    slot = tmp_path / "0.lock"
    target = make_suspicious_slot(slot, kind)
    before = slot.lstat()
    descriptors = []
    real_open = os.open

    def record_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if path == "0.lock":
            descriptors.append(fd)
        return fd

    monkeypatch.setattr(os, "open", record_open)
    if kind == "foreign-owner":
        real_fstat = os.fstat

        def foreign_owner(fd):
            info = real_fstat(fd)
            if fd in descriptors:
                return SimpleNamespace(st_uid=info.st_uid + 1, st_mode=info.st_mode, st_nlink=info.st_nlink)
            return info

        monkeypatch.setattr(os, "fstat", foreign_owner)
    monkeypatch.setattr(
        parse_isolation, "_worker_command", lambda limits: pytest.fail("unsafe slot admitted a worker")
    )
    with pytest.raises(WebmentionSourceRejected, match="parse capacity unavailable"):
        parse_isolation.run_parse_worker({})
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
    after = slot.lstat()
    assert (after.st_ino, after.st_mode, after.st_nlink) == (before.st_ino, before.st_mode, before.st_nlink)
    if stat.S_ISREG(before.st_mode):
        assert slot.read_text() == "synthetic-marker"
    if target.exists():
        assert target.read_text() == "synthetic-marker"


def test_regular_private_slot_works_and_closes(settings, tmp_path, monkeypatch):
    settings.INDIEWEB_WEBMENTION_PARSE_LOCK_DIR = str(tmp_path)
    settings.INDIEWEB_WEBMENTION_PARSE_MAX_CONCURRENT = 1
    monkeypatch.setattr(parse_isolation, "_worker_command", lambda limits: [sys.executable, "-c", "print('{}')"])
    assert parse_isolation.run_parse_worker({}) == {}
    assert stat.S_IMODE((tmp_path / "0.lock").stat().st_mode) == 0o600
    assert parse_isolation.run_parse_worker({}) == {}
    with parse_isolation._parse_slot() as fd:
        assert stat.S_ISREG(os.fstat(fd).st_mode)
    with pytest.raises(OSError):
        os.fstat(fd)
