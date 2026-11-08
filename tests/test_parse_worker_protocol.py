"""Settings-free child request admission, without touching OS resource limits."""

import io
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from indieweb import webmention_parse_worker as worker

SOURCE = {
    "operation": "source",
    "html": '<a href="https://target.example/post">target</a>',
    "base_url": "https://source.example/post",
    "target_url": "https://target.example/post",
}
VOUCH = {
    "operation": "vouch",
    "html": '<a href="https://source.example/">source</a>',
    "source_url": "https://source.example/post",
}


@pytest.fixture
def run_worker(monkeypatch, capsys):
    monkeypatch.setattr(worker, "apply_resource_limits", lambda **kwargs: True)

    def run(request_data):
        monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(request_data).encode())))
        result = worker.main(["--memory-bytes", "1024", "--cpu-seconds", "1", "--max-result-bytes", "20000"])
        return result, capsys.readouterr()

    return run


INVALID_FIELDS = [
    (request_data, field, invalid)
    for request_data in (SOURCE, VOUCH)
    for field in request_data
    if field != "operation"
    for invalid in (None, [], {"private": "synthetic-secret"}, 42, True)
]
MISSING_FIELDS = [
    {key: value for key, value in request_data.items() if key != field}
    for request_data in (SOURCE, VOUCH)
    for field in request_data
]


@pytest.mark.parametrize("request_data,field,invalid", INVALID_FIELDS)
def test_worker_rejects_nonstring_fields_without_analysis(run_worker, monkeypatch, request_data, field, invalid):
    assert_invalid_request(run_worker, monkeypatch, {**request_data, field: invalid})


@pytest.mark.parametrize(
    "request_data",
    [
        *MISSING_FIELDS,
        None,
        [],
        "synthetic-secret",
        {},
        {**SOURCE, "operation": "synthetic-secret"},
        {**SOURCE, "operation": []},
        {**SOURCE, "extra": "synthetic-secret"},
        {**VOUCH, "target_url": "synthetic-secret"},
    ],
)
def test_worker_rejects_unsupported_shapes_without_analysis(run_worker, monkeypatch, request_data):
    assert_invalid_request(run_worker, monkeypatch, request_data)


def assert_invalid_request(run_worker, monkeypatch, request_data):
    calls = []

    def analyze(*args):
        calls.append(args)
        return {}

    monkeypatch.setattr(worker, "analyze_source", analyze)
    monkeypatch.setattr(worker, "analyze_vouch", analyze)
    result, output = run_worker(request_data)
    assert result == worker.EXIT_FAILED
    assert output.out == ""
    assert output.err == "analysis failed: ValueError\n"
    assert not calls


@pytest.mark.parametrize("request_data,flag", [(SOURCE, "links_to_target"), (VOUCH, "links_to_source_domain")])
def test_worker_valid_requests_reach_real_analysis(run_worker, request_data, flag):
    result, output = run_worker(request_data)
    assert result == 0
    assert json.loads(output.out)[flag] is True
    assert output.err == ""


@pytest.mark.parametrize("request_data,flag", [(SOURCE, "links_to_target"), (VOUCH, "links_to_source_domain")])
def test_worker_empty_html_is_a_valid_string(run_worker, request_data, flag):
    result, output = run_worker({**request_data, "html": ""})
    assert result == 0
    assert json.loads(output.out) == {flag: False}
    assert output.err == ""


def test_worker_import_does_not_configure_django_settings():
    env = {key: value for key, value in os.environ.items() if key != "DJANGO_SETTINGS_MODULE"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from indieweb import webmention_parse_worker; "
            "from django.conf import settings; assert not settings.configured",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
