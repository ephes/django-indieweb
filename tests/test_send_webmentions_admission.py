"""Synthetic command ingress: refuse incomplete/oversized HTML before parsing."""

import os
import time
from io import StringIO
from unittest.mock import Mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from indieweb.management.commands import send_webmentions as command


@pytest.fixture
def sender(monkeypatch):
    sender = Mock()
    sender.extract_urls.return_value = []
    sender.send_webmentions.return_value = []
    sender.resend_salmentions.return_value = []
    monkeypatch.setattr(command, "WebmentionSender", lambda: sender)
    return sender


class CountingInput(StringIO):
    def __init__(self, content):
        super().__init__(content)
        self.requests = []

    def read(self, size=-1):
        self.requests.append(size)
        return super().read(size)


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("resend", [False, True])
@pytest.mark.parametrize("content", [None, "-"])
def test_invalid_source_is_refused_before_resolving_content(monkeypatch, sender, dry_run, resend, content):
    stream = CountingInput("<p>synthetic</p>")
    monkeypatch.setattr(command.sys, "stdin", stream)
    sender.fetch_content.return_value = "<p>synthetic</p>"
    sender.select_target_urls.return_value = []
    sender.preview_salmention_resend_targets.return_value = []

    with pytest.raises(CommandError, match=r"^Source URL must be a valid http:// or https:// URL$"):
        call_command(
            "send_webmentions",
            "https://source.example:invalid/post",
            content=content,
            dry_run=dry_run,
            salmention_resend=resend,
            stdout=StringIO(),
        )

    assert not stream.requests
    assert not sender.mock_calls


@pytest.mark.parametrize("stdin", [False, True])
@pytest.mark.parametrize("resend", [False, True])
@pytest.mark.parametrize("content", ["x" * 9, "é" * 5])
def test_oversize_input_never_reaches_parser(settings, monkeypatch, sender, stdin, resend, content):
    settings.INDIEWEB_WEBMENTION_FETCH_MAX_BYTES = 8
    stream = CountingInput(content * 10000)
    monkeypatch.setattr(command.sys, "stdin", stream)
    with pytest.raises(CommandError, match="Content exceeds byte limit"):
        call_command(
            "send_webmentions",
            "https://source.example/post",
            content="-" if stdin else content,
            salmention_resend=resend,
            stdout=StringIO(),
        )
    sender.extract_urls.assert_not_called()
    sender.send_webmentions.assert_not_called()
    sender.resend_salmentions.assert_not_called()
    sender.fetch_content.assert_not_called()
    if stdin:
        assert stream.requests and all(0 < size <= 9 for size in stream.requests)
        assert stream.tell() <= 9


@pytest.mark.parametrize("stdin", [False, True])
@pytest.mark.parametrize("content", ["", "é" * 4])
def test_exact_limit_and_empty_input_are_admitted(settings, monkeypatch, sender, stdin, content):
    settings.INDIEWEB_WEBMENTION_FETCH_MAX_BYTES = 8
    monkeypatch.setattr(command.sys, "stdin", CountingInput(content))
    call_command(
        "send_webmentions", "https://source.example/post", content="-" if stdin else content, stdout=StringIO()
    )
    sender.extract_urls.assert_called_once_with(content)
    sender.fetch_content.assert_not_called()


def test_trickle_past_source_deadline_never_reaches_parser(settings, monkeypatch, sender):
    clock = [0.0]

    class Trickle(CountingInput):
        def read(self, size=-1):
            clock[0] += 2
            return super().read(size)

    settings.INDIEWEB_WEBMENTION_SOURCE_TOTAL_TIMEOUT_SECONDS = 1
    stream = Trickle("small")
    monkeypatch.setattr(command.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(command.sys, "stdin", stream)
    with pytest.raises(CommandError, match="Source deadline exceeded"):
        call_command("send_webmentions", "https://source.example/post", content="-", stdout=StringIO())
    assert len(stream.requests) == 1
    sender.extract_urls.assert_not_called()
    sender.send_webmentions.assert_not_called()


def test_stalled_pipe_uses_remaining_deadline(settings, monkeypatch, sender):
    settings.INDIEWEB_WEBMENTION_SOURCE_TOTAL_TIMEOUT_SECONDS = 1
    read_fd, write_fd = os.pipe()
    try:
        with os.fdopen(read_fd, encoding="utf-8") as stream:
            monkeypatch.setattr(command.sys, "stdin", stream)
            # Safety oracle: an implementation must wait with a deadline before reading.
            original_read = stream.read
            stream.read = Mock(side_effect=AssertionError("blocking text read"))
            started = time.monotonic()
            with pytest.raises(CommandError, match="Source deadline exceeded"):
                call_command("send_webmentions", "https://source.example/post", content="-", stdout=StringIO())
            assert time.monotonic() - started < 5
            stream.read = original_read
    finally:
        os.close(write_fd)
    sender.extract_urls.assert_not_called()
    sender.send_webmentions.assert_not_called()


@pytest.mark.parametrize("data", ["é".encode() * 4, b"x" * 9, b"\xff"])
def test_binary_pipe_admission(settings, monkeypatch, sender, data):
    settings.INDIEWEB_WEBMENTION_FETCH_MAX_BYTES = 8
    read_fd, write_fd = os.pipe()
    os.write(write_fd, data)
    os.close(write_fd)
    with os.fdopen(read_fd, encoding="utf-8") as stream:
        monkeypatch.setattr(command.sys, "stdin", stream)
        if len(data) > 8 or data == b"\xff":
            with pytest.raises(CommandError):
                call_command("send_webmentions", "https://source.example/post", content="-", stdout=StringIO())
            sender.extract_urls.assert_not_called()
        else:
            call_command("send_webmentions", "https://source.example/post", content="-", stdout=StringIO())
            sender.extract_urls.assert_called_once_with(data.decode())


def test_disabling_network_limit_does_not_disable_command_limit(settings, monkeypatch, sender):
    settings.INDIEWEB_WEBMENTION_FETCH_MAX_BYTES = None
    content = "x" * (1024 * 1024 + 1)
    monkeypatch.setattr(command.sys, "stdin", CountingInput(content))
    with pytest.raises(CommandError, match="Content exceeds byte limit"):
        call_command("send_webmentions", "https://source.example/post", content="-", stdout=StringIO())
    sender.extract_urls.assert_not_called()
