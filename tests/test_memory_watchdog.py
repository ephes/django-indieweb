"""Exercise the real watchdog loop using deterministic RSS, sleep and exit seams."""

import pytest

from indieweb import webmention_parse_worker as worker


class WatchStopped(BaseException):
    """Stop the infinite loop without exiting the process or sleeping."""


@pytest.mark.parametrize(
    "rss,expected_sleeps,exit_code",
    [
        ([99, 99], 2, None),
        ([100, 100], 2, None),
        ([101], 0, worker.EXIT_MEMORY_LIMIT),
        ([99, 100, 101], 2, worker.EXIT_MEMORY_LIMIT),
    ],
)
def test_watchdog_threshold_and_sampling(monkeypatch, rss, expected_sleeps, exit_code):
    samples = iter(rss)
    observed = []
    sleeps = []
    exits = []
    threads = []

    def peak():
        value = next(samples)
        observed.append(value)
        return value

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= len(rss):
            raise WatchStopped

    def exit_process(code):
        exits.append(code)
        raise WatchStopped

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            self.target, self.name, self.daemon = target, name, daemon
            self.started = False
            threads.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(worker.threading, "Thread", FakeThread)
    monkeypatch.setattr(worker, "peak_resident_bytes", peak)
    monkeypatch.setattr(worker.time, "sleep", sleep)
    monkeypatch.setattr(worker.os, "_exit", exit_process)

    thread = worker.start_memory_watchdog(100)
    assert threads == [thread]
    assert thread.started is True
    assert thread.daemon is True
    assert thread.name == "memory-watchdog"
    with pytest.raises(WatchStopped):
        thread.target()
    assert observed == rss
    assert sleeps == [worker.MEMORY_WATCHDOG_INTERVAL_SECONDS] * expected_sleeps
    assert exits == ([] if exit_code is None else [exit_code])
