"""Fetched Webmention HTML is analysed in a resource-limited child process."""

import io
import json
import subprocess
import sys
import time
from types import SimpleNamespace

import httpx
import pytest
from django.contrib.sites.models import Site
from django.test import override_settings
from django.urls import reverse

from indieweb import parse_isolation, webmention_parse_worker
from indieweb.models import Webmention, WebmentionNestedResponse, WebmentionSourceSnapshot
from indieweb.parse_isolation import WebmentionSourceRejected
from indieweb.processors import WebmentionProcessor, _html_links_to_source_domain, _html_links_to_target

SOURCE_URL = "https://example.com/post"
TARGET_URL = "https://mysite.com/article"
MIB = 1024 * 1024
TARGET_LINK = f'<a href="{TARGET_URL}">target</a>'
REPLY = (
    f'<article class="h-entry"><a class="u-in-reply-to" href="{TARGET_URL}">re</a>'
    '<div class="e-content">A real reply</div>'
    '<a class="p-author h-card" href="https://example.com/">Author</a></article>'
)
LONG_BASE = '<base href="https://example.com/' + "b" * 3000 + '/">'

# Small limits keep the expensive documents below cheap to reject. The
# documents need many times these limits when parsed without them.
SMALL_LIMITS = {
    "INDIEWEB_WEBMENTION_PARSE_MEMORY_BYTES": 128 * MIB,
    "INDIEWEB_WEBMENTION_PARSE_CPU_SECONDS": 1,
    "INDIEWEB_WEBMENTION_PARSE_WALL_SECONDS": 10,
    "INDIEWEB_WEBMENTION_PARSE_MAX_RESULT_BYTES": 200_000,
}


def nested_embedded_document(depth, payload_bytes):
    return (
        f'<article class="h-entry"><a class="u-in-reply-to" href="{TARGET_URL}">re</a>'
        + '<span class="e-content">' * depth
        + "A" * payload_bytes
        + "</span>" * depth
        + '<a class="p-author h-card" href="https://example.com/">Author</a></article>'
    )


EXPENSIVE_SOURCES = {
    "nested embedded properties": nested_embedded_document(depth=80, payload_bytes=500_000),
    "deep nesting": TARGET_LINK + "<div>" * 40_000 + '<a class="h-entry" href="/x">x</a>',
    "open formatting elements": (
        TARGET_LINK + "<p>" + "".join(f"<b id=b{n}>" for n in range(100)) + "</p><p>x" * 5000
    ),
    "microformat nested once per property class": (
        TARGET_LINK + '<div class="h-entry">' + '<div class="p-a p-b h-cite">' * 22 + "x" + "</div>" * 23
    ),
    "links resolved against a long base": (
        LONG_BASE + TARGET_LINK + '<div class="h-entry">' + '<a class="u-x" href="a">l</a>' * 300 + "</div>"
    ),
    "srcset candidates separated by whitespace only": (
        LONG_BASE
        + TARGET_LINK
        + '<div class="h-entry"><img class="u-photo" src="s" srcset="'
        + " ".join(f"a {n + 1}x" for n in range(1000))
        + '"></div>'
    ),
    "classic nested properties": (
        TARGET_LINK + '<div class="hentry">' + '<div class="entry-content">' * 40 + "B" * 100_000 + "</div>" * 41
    ),
}


@pytest.fixture(autouse=True)
def parse_worker():
    """Override the suite default: these tests start the real child process."""


def processor_serving(*documents):
    """Return a processor whose fetches return ``documents`` in order (the last one repeats)."""
    remaining = list(documents)

    def handler(request):
        text = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return httpx.Response(200, headers={"content-type": "text/html"}, text=text)

    return WebmentionProcessor(client=httpx.Client(transport=httpx.MockTransport(handler)))


def assert_nothing_stored(webmention):
    webmention = Webmention.objects.get(pk=webmention.pk)
    assert webmention.status == "failed"
    assert webmention.verified_at is None
    assert (webmention.content, webmention.content_html, webmention.author_name) == ("", "", "")
    assert not WebmentionSourceSnapshot.objects.filter(webmention=webmention).exists()
    assert not WebmentionNestedResponse.objects.filter(webmention=webmention).exists()


def worker_command_running(code):
    return lambda limits: [sys.executable, "-c", code]


# --- ordinary sources -------------------------------------------------------


@pytest.mark.django_db
def test_ordinary_webmention_is_processed_through_the_child_process():
    webmention = processor_serving(REPLY).process_webmention(SOURCE_URL, TARGET_URL)

    assert webmention.status == "verified"
    assert (webmention.mention_type, webmention.author_name, webmention.content) == ("reply", "Author", "A real reply")
    assert webmention.source_snapshot.parsed_h_entry["properties"]["in-reply-to"] == [TARGET_URL]


def test_source_analysis_keeps_html5lib_semantics():
    # ``html.parser`` would nest the second paragraph inside the first one.
    html = TARGET_LINK + '<div class="h-entry"><div class="e-content"><p>one<p>two</div></div>'

    analysis = parse_isolation.analyze_source(html, SOURCE_URL, TARGET_URL)

    assert analysis.links_to_target is True
    assert analysis.parsed["items"][0]["properties"]["content"][0]["html"] == "<p>one</p><p>two</p>"


def test_source_analysis_reports_the_entry_content_that_links_to_the_target():
    html = (
        '<div class="h-entry"><div class="e-content">no link</div></div>'
        f'<div class="h-entry"><div class="e-content">see {TARGET_LINK}</div></div>'
    )

    analysis = parse_isolation.analyze_source(html, SOURCE_URL, TARGET_URL)

    linking = [
        item["properties"]["content"][0]["html"]
        for item in analysis.parsed["items"]
        if webmention_parse_worker.content_html_digest(item["properties"]["content"][0]["html"])
        in analysis.linking_content
    ]
    assert linking == [f"see {TARGET_LINK}"]


def test_source_without_a_link_to_the_target_is_not_parsed():
    analysis = parse_isolation.analyze_source('<div class="h-entry">nothing</div>', SOURCE_URL, TARGET_URL)

    assert analysis == parse_isolation.SourceAnalysis(
        links_to_target=False, parsed={}, linking_content=frozenset(), sanitized_content={}
    )


@pytest.mark.django_db
def test_content_is_sanitized_in_the_child_process(monkeypatch):
    comment = (
        '<div class="h-entry"><a class="u-url" href="/c1">c</a>'
        '<div class="e-content">nested <i onclick="x()">comment</i><script>y()</script></div></div>'
    )
    html = (
        f'<article class="h-entry"><a class="u-in-reply-to" href="{TARGET_URL}">re</a>'
        f'<div class="e-content">a <b onclick="x()">reply</b><script>y()</script></div>{comment}</article>'
    )
    monkeypatch.setattr(
        "indieweb.processors.sanitize_webmention_html",
        lambda value: pytest.fail("fetched content must not be sanitized in the receiving process"),
    )

    webmention = processor_serving(html).process_webmention(SOURCE_URL, TARGET_URL)

    assert webmention.status == "verified"
    assert webmention.content_html == "a <b>reply</b>"
    assert [nested.content_html for nested in webmention.nested_responses.all()] == ["nested <i>comment</i>"]


@pytest.mark.django_db
def test_summary_fallback_content_is_sanitized_in_the_child_process(monkeypatch):
    html = (
        f'<article class="h-entry"><a class="u-in-reply-to" href="{TARGET_URL}">re</a>'
        '<p class="p-summary">1 &lt; 2 &amp; so on</p></article>'
    )
    monkeypatch.setattr("indieweb.processors.sanitize_webmention_html", lambda value: pytest.fail("in-process"))

    webmention = processor_serving(html).process_webmention(SOURCE_URL, TARGET_URL)

    assert (webmention.content, webmention.content_html) == ("1 < 2 & so on", "1 &lt; 2 &amp; so on")


def test_content_missing_from_the_analysis_is_not_sanitized_in_the_receiving_process():
    analysis = parse_isolation.SourceAnalysis(
        links_to_target=True, parsed={}, linking_content=frozenset(), sanitized_content={}
    )

    assert analysis.sanitized_html("") == ""
    with pytest.raises(WebmentionSourceRejected):
        analysis.sanitized_html("<b>not analysed</b>")


@pytest.mark.parametrize("sanitized_content", [None, [], {"digest": 1}])
def test_malformed_sanitized_content_is_an_unreadable_result(monkeypatch, sanitized_content):
    result = {"links_to_target": True, "parsed": {}, "linking_content": [], "sanitized_content": sanitized_content}
    monkeypatch.setattr(parse_isolation, "run_parse_worker", lambda request: result)

    with pytest.raises(WebmentionSourceRejected):
        parse_isolation.analyze_source(REPLY, SOURCE_URL, TARGET_URL)


def test_vouch_documents_are_checked_in_the_child_process():
    assert parse_isolation.vouch_links_to_source_domain('<a href="https://example.com/x">x</a>', SOURCE_URL) is True
    assert parse_isolation.vouch_links_to_source_domain('<a href="https://other.example/">x</a>', SOURCE_URL) is False


def test_large_ordinary_article_fits_the_default_limits():
    html = (
        '<div class="h-feed"><article class="h-entry"><h1 class="p-name">Title</h1><div class="e-content">'
        + TARGET_LINK
        + '<p class="lead">paragraph <a href="/x">link</a> text text text text</p>' * 4000
        + '</div><a class="p-author h-card" href="/a"><img class="u-photo" src="/p.jpg" alt="">A</a></article></div>'
    )

    analysis = parse_isolation.analyze_source(html, SOURCE_URL, TARGET_URL)

    assert analysis.parsed["items"]
    assert len(analysis.linking_content) == 1


# --- expensive sources ------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("html", EXPENSIVE_SOURCES.values(), ids=EXPENSIVE_SOURCES.keys())
def test_expensive_source_is_rejected_within_the_limits_and_nothing_is_stored(html, caplog):
    assert len(html) < MIB
    started = time.monotonic()

    with override_settings(**SMALL_LIMITS):
        webmention = processor_serving(html).process_webmention(SOURCE_URL, TARGET_URL)

    assert time.monotonic() - started < SMALL_LIMITS["INDIEWEB_WEBMENTION_PARSE_WALL_SECONDS"] + 5
    assert_nothing_stored(webmention)
    assert "source too expensive to process" in caplog.text


@pytest.mark.django_db
def test_source_that_becomes_expensive_keeps_the_earlier_snapshot_unchanged():
    expensive = EXPENSIVE_SOURCES["nested embedded properties"]
    processor = processor_serving(REPLY, expensive)
    first = processor.process_webmention(SOURCE_URL, TARGET_URL)
    assert first.status == "verified"

    with override_settings(**SMALL_LIMITS):
        processor.process_webmention(SOURCE_URL, TARGET_URL)

    webmention = Webmention.objects.get(pk=first.pk)
    assert webmention.status == "failed"
    assert webmention.content == "A real reply"
    assert webmention.source_snapshot.raw_source_html == REPLY


def test_memory_limit_ends_the_analysis():
    limits = {**SMALL_LIMITS, "INDIEWEB_WEBMENTION_PARSE_CPU_SECONDS": 20}

    with override_settings(**limits), pytest.raises(WebmentionSourceRejected) as rejected:
        parse_isolation.analyze_source(EXPENSIVE_SOURCES["nested embedded properties"], SOURCE_URL, TARGET_URL)

    assert rejected.value.reason == "memory limit"


def test_cpu_time_limit_ends_the_analysis():
    with override_settings(**SMALL_LIMITS), pytest.raises(WebmentionSourceRejected) as rejected:
        parse_isolation.analyze_source(EXPENSIVE_SOURCES["deep nesting"], SOURCE_URL, TARGET_URL)

    assert rejected.value.reason == "CPU time limit"


def test_wall_clock_limit_ends_the_analysis():
    limits = {**SMALL_LIMITS, "INDIEWEB_WEBMENTION_PARSE_CPU_SECONDS": 20, "INDIEWEB_WEBMENTION_PARSE_WALL_SECONDS": 1}
    started = time.monotonic()

    with override_settings(**limits), pytest.raises(WebmentionSourceRejected) as rejected:
        parse_isolation.analyze_source(EXPENSIVE_SOURCES["deep nesting"], SOURCE_URL, TARGET_URL)

    assert rejected.value.reason == "wall-clock limit"
    assert time.monotonic() - started < 5


def test_result_size_limit_ends_the_analysis():
    html = TARGET_LINK + '<div class="h-entry"><p class="p-name">' + "n" * 5000 + "</p></div>"

    assert parse_isolation.analyze_source(html, SOURCE_URL, TARGET_URL).parsed["items"]
    with override_settings(INDIEWEB_WEBMENTION_PARSE_MAX_RESULT_BYTES=2000):
        with pytest.raises(WebmentionSourceRejected) as rejected:
            parse_isolation.analyze_source(html, SOURCE_URL, TARGET_URL)

    assert rejected.value.reason == "result size limit"


def test_result_larger_than_the_limit_is_not_read(monkeypatch):
    monkeypatch.setattr(
        parse_isolation, "_worker_command", worker_command_running("import sys; sys.stdout.write('1' * 5000)")
    )

    with override_settings(INDIEWEB_WEBMENTION_PARSE_MAX_RESULT_BYTES=2000):
        with pytest.raises(WebmentionSourceRejected) as rejected:
            parse_isolation.run_parse_worker({"operation": "vouch", "html": "", "source_url": SOURCE_URL})

    assert rejected.value.reason == "result size limit"


@pytest.mark.django_db
def test_vouch_document_over_the_limits_fails_the_webmention(caplog):
    vouch_url = "https://trusted.example/vouch"
    vouch_html = '<a href="https://example.com/">vouched</a>'
    expensive_vouch_html = vouch_html + "<a>" * 300_000
    trusted = {"INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS": ["trusted.example"]}

    with override_settings(**trusted):
        accepted = processor_serving(REPLY, vouch_html).process_webmention(
            "https://example.com/other", TARGET_URL, vouch_url=vouch_url
        )
    assert accepted.status == "verified"
    assert accepted.vouch_verified_at is not None

    with override_settings(**SMALL_LIMITS, **trusted):
        webmention = processor_serving(REPLY, expensive_vouch_html).process_webmention(
            SOURCE_URL, TARGET_URL, vouch_url=vouch_url
        )

    assert "source too expensive to process" in caplog.text
    assert webmention.status == "failed"
    assert webmention.vouch_verified_at is None
    assert not WebmentionSourceSnapshot.objects.filter(webmention=webmention).exists()


def stored_bytes(webmention):
    """Return the encoded size of the parsed data stored for ``webmention``."""

    def text_bytes(row):
        return sum(
            len(getattr(row, name).encode())
            for name in ("author_name", "author_url", "author_photo", "content", "content_html", "mention_type")
        )

    total = len(json.dumps(webmention.source_snapshot.parsed_h_entry)) + text_bytes(webmention)
    for nested in webmention.nested_responses.all():
        total += len(json.dumps(nested.parsed_h_entry)) + text_bytes(nested)
        total += len(nested.identity.encode()) + len(nested.response_url.encode()) + len(nested.content_digest)
    return total


def assert_stored_size_limit_is_exact(html):
    """A source is accepted with a limit of exactly what it stores and rejected one byte below."""
    accepted = processor_serving(html).process_webmention(SOURCE_URL, TARGET_URL)
    assert accepted.status == "verified"
    size = stored_bytes(Webmention.objects.get(pk=accepted.pk))

    with override_settings(INDIEWEB_WEBMENTION_MAX_STORED_BYTES=size):
        again = processor_serving(html).process_webmention("https://example.com/again", TARGET_URL)
    with override_settings(INDIEWEB_WEBMENTION_MAX_STORED_BYTES=size - 1):
        rejected = processor_serving(html).process_webmention("https://example.com/other", TARGET_URL)

    assert again.status == "verified"
    assert_nothing_stored(rejected)
    return accepted


@pytest.mark.django_db
def test_stored_size_limit_counts_nested_responses():
    comments = "".join(
        f'<div class="h-entry"><a class="u-url" href="/c{n}">c</a><p class="e-content">{"comment " * 200}</p></div>'
        for n in range(20)
    )
    html = f'<article class="h-entry"><a class="u-in-reply-to" href="{TARGET_URL}">re</a>{comments}</article>'

    accepted = assert_stored_size_limit_is_exact(html)

    assert accepted.nested_responses.count() == 20
    assert stored_bytes(accepted) > 2 * len(json.dumps(accepted.source_snapshot.parsed_h_entry))


@pytest.mark.django_db
def test_stored_size_limit_does_not_count_nested_entries_that_are_not_stored():
    # Nested entries without a stable identity and repeated identities get no row.
    comments = '<div class="h-entry"><p class="e-content">anonymous</p></div>' * 10
    comments += '<div class="h-entry"><a class="u-url" href="/same">c</a><p class="e-content">twice</p></div>' * 5
    html = f'<article class="h-entry"><a class="u-in-reply-to" href="{TARGET_URL}">re</a>{comments}</article>'

    accepted = assert_stored_size_limit_is_exact(html)

    assert accepted.nested_responses.count() == 1


@pytest.mark.django_db
def test_stored_size_limit_counts_encoded_bytes():
    emoji = "\N{GRINNING FACE}"
    html = (
        f'<article class="h-entry"><a class="u-in-reply-to" href="{TARGET_URL}">re</a>'
        f'<div class="e-content">{emoji * 500} gr\u00fc\u00dfe</div>'
        '<a class="p-author h-card" href="https://example.com/">J\u00f6rg \N{SNOWMAN}</a></article>'
    )

    accepted = assert_stored_size_limit_is_exact(html)

    assert len(accepted.content.encode()) > 2000 > len(accepted.content)


# --- worker failures --------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "code, reason",
    [
        ("import os, signal; os.kill(os.getpid(), signal.SIGKILL)", "killed, CPU time or memory limit"),
        ("import os, signal; os.kill(os.getpid(), signal.SIGTERM)", "worker ended by signal 15"),
        ("raise SystemExit(7)", "worker failed with status 7"),
        ("print('not json')", "worker returned an unreadable result"),
        ("print('[1, 2]')", "worker returned an unreadable result"),
        ("print('{}')", "worker returned an unreadable result"),
        ("print('[' * 100000)", "worker returned an unreadable result"),
    ],
)
def test_worker_failure_is_handled_as_a_rejection(monkeypatch, caplog, code, reason):
    monkeypatch.setattr(parse_isolation, "_worker_command", worker_command_running(code))

    webmention = processor_serving(REPLY).process_webmention(SOURCE_URL, TARGET_URL)

    assert_nothing_stored(webmention)
    assert f"source too expensive to process ({reason})" in caplog.text


@pytest.mark.django_db
def test_worker_that_cannot_be_started_is_handled_as_a_rejection(caplog):
    with override_settings(INDIEWEB_WEBMENTION_PARSE_PYTHON="/nonexistent/python"):
        webmention = processor_serving(REPLY).process_webmention(SOURCE_URL, TARGET_URL)

    assert_nothing_stored(webmention)
    assert "worker could not be started" in caplog.text


def test_worker_error_output_is_logged_without_the_document(caplog):
    html = TARGET_LINK + "<div>" * 3000 + "secret-marker"

    with pytest.raises(WebmentionSourceRejected) as rejected:
        parse_isolation.analyze_source(html, SOURCE_URL, TARGET_URL)

    assert rejected.value.reason == "worker failed with status 1"
    assert "analysis failed: RecursionError" in caplog.text
    assert "secret-marker" not in caplog.text
    assert "Traceback" not in caplog.text


@pytest.mark.django_db
def test_receive_endpoint_reports_no_details_of_a_rejected_source(client, monkeypatch):
    Site.objects.update(domain="mysite.com")
    html = EXPENSIVE_SOURCES["deep nesting"]
    monkeypatch.setattr("indieweb.views.WebmentionProcessor", lambda: processor_serving(html))

    with override_settings(**SMALL_LIMITS):
        response = client.post(reverse("indieweb:webmention"), {"source": SOURCE_URL, "target": TARGET_URL})

    assert response.status_code == 201
    assert response.content == b""
    assert_nothing_stored(Webmention.objects.get())


def test_child_does_not_inherit_the_application_environment(monkeypatch):
    monkeypatch.setenv("DJANGO_SECRET_KEY", "do-not-leak")
    monkeypatch.setenv("LANG", "C.UTF-8")
    code = "import json, os; print(json.dumps({'names': sorted(os.environ)}))"
    monkeypatch.setattr(parse_isolation, "_worker_command", worker_command_running(code))

    names = parse_isolation.run_parse_worker({})["names"]

    assert "DJANGO_SECRET_KEY" not in names
    assert {"PYTHONPATH", "LANG"} <= set(names)


# --- platforms without resource limits --------------------------------------


def test_missing_resource_limits_fail_closed_by_default(monkeypatch, caplog):
    monkeypatch.setattr(webmention_parse_worker, "resource", None)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("worker must not be started"))

    with pytest.raises(WebmentionSourceRejected) as rejected:
        parse_isolation.analyze_source(REPLY, SOURCE_URL, TARGET_URL)

    assert rejected.value.reason == "resource limits unavailable"
    assert "INDIEWEB_WEBMENTION_PARSE_REQUIRE_OS_LIMITS" in caplog.text


@pytest.mark.parametrize("configured", [None, 0, "", "false"])
def test_only_an_explicit_false_makes_resource_limits_optional(configured):
    with override_settings(INDIEWEB_WEBMENTION_PARSE_REQUIRE_OS_LIMITS=configured):
        assert parse_isolation.parse_limits().require_os_limits is True
        assert "--allow-missing-os-limits" not in parse_isolation._worker_command(parse_isolation.parse_limits())


def test_opt_out_runs_the_child_without_required_resource_limits(monkeypatch):
    monkeypatch.setattr(webmention_parse_worker, "resource", None)

    with override_settings(INDIEWEB_WEBMENTION_PARSE_REQUIRE_OS_LIMITS=False):
        command = parse_isolation._worker_command(parse_isolation.parse_limits())
        analysis = parse_isolation.analyze_source(REPLY, SOURCE_URL, TARGET_URL)

    assert command[-1] == "--allow-missing-os-limits"
    assert analysis.links_to_target is True


def run_main(monkeypatch, capsys, request, *extra_arguments, limits=None):
    """Run the worker entry point in this process without touching its limits."""
    applied = []

    def apply_resource_limits(**kwargs):
        applied.append(kwargs)
        if isinstance(limits, Exception):
            raise limits
        return bool(limits)

    watchdogs = []
    monkeypatch.setattr(webmention_parse_worker, "apply_resource_limits", apply_resource_limits)
    monkeypatch.setattr(webmention_parse_worker, "start_memory_watchdog", watchdogs.append)
    stdin = SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode()))
    monkeypatch.setattr(sys, "stdin", stdin)
    arguments = ["--memory-bytes", "1000", "--cpu-seconds", "2", "--max-result-bytes", "3000", *extra_arguments]
    status = webmention_parse_worker.main(arguments)
    return status, capsys.readouterr(), applied, watchdogs


VOUCH_REQUEST = {"operation": "vouch", "html": '<a href="https://example.com/">x</a>', "source_url": SOURCE_URL}


def test_worker_main_applies_the_limits_and_writes_the_result(monkeypatch, capsys):
    status, output, applied, watchdogs = run_main(monkeypatch, capsys, VOUCH_REQUEST, limits=True)

    assert status == 0
    assert json.loads(output.out) == {"links_to_source_domain": True}
    assert applied == [{"memory_bytes": 1000, "cpu_seconds": 2, "max_file_bytes": 3000}]
    assert watchdogs == []


def test_worker_main_watches_memory_itself_when_the_kernel_does_not(monkeypatch, capsys):
    status, _output, _applied, watchdogs = run_main(monkeypatch, capsys, VOUCH_REQUEST, limits=False)

    assert status == 0
    assert watchdogs == [1000]


def test_worker_main_refuses_to_run_without_limits(monkeypatch, capsys):
    unavailable = webmention_parse_worker.LimitsUnavailable("no limits here")

    status, output, _applied, _watchdogs = run_main(monkeypatch, capsys, VOUCH_REQUEST, limits=unavailable)

    assert status == webmention_parse_worker.EXIT_LIMITS_UNAVAILABLE
    assert output.out == ""
    assert "no limits here" in output.err


def test_worker_main_runs_without_limits_only_when_told_to(monkeypatch, capsys):
    unavailable = webmention_parse_worker.LimitsUnavailable("no limits here")

    status, output, _applied, watchdogs = run_main(
        monkeypatch, capsys, VOUCH_REQUEST, "--allow-missing-os-limits", limits=unavailable
    )

    assert status == 0
    assert json.loads(output.out) == {"links_to_source_domain": True}
    assert watchdogs == []


@pytest.mark.parametrize(
    "request_data, status",
    [
        ({"operation": "unknown"}, webmention_parse_worker.EXIT_FAILED),
        (["not", "an", "object"], webmention_parse_worker.EXIT_FAILED),
        ({"operation": "vouch", "html": '<a href="https://example.com/">x</a>' * 200, "source_url": SOURCE_URL}, 0),
        (
            {
                "operation": "source",
                "html": REPLY.replace("A real", "p" * 4000),
                "base_url": SOURCE_URL,
                "target_url": TARGET_URL,
            },
            webmention_parse_worker.EXIT_RESULT_TOO_LARGE,
        ),
    ],
    ids=["unknown operation", "malformed request", "large input small result", "result too large"],
)
def test_worker_main_exit_status(monkeypatch, capsys, request_data, status):
    assert run_main(monkeypatch, capsys, request_data, limits=True)[0] == status


def test_worker_main_reports_memory_errors_as_the_memory_limit(monkeypatch, capsys):
    def out_of_memory(request):
        raise MemoryError

    monkeypatch.setattr(webmention_parse_worker, "handle_request", out_of_memory)

    assert run_main(monkeypatch, capsys, VOUCH_REQUEST, limits=True)[0] == webmention_parse_worker.EXIT_MEMORY_LIMIT


class FakeResource:
    RLIM_INFINITY = -1
    RLIMIT_CPU, RLIMIT_FSIZE, RLIMIT_CORE, RLIMIT_AS, RLIMIT_DATA = range(5)
    RUSAGE_SELF = 0

    def __init__(self, *, hard=RLIM_INFINITY, refused=()):
        self.hard = hard
        self.refused = set(refused)
        self.limits = {}

    def getrlimit(self, kind):
        return (self.hard, self.hard)

    def setrlimit(self, kind, limits):
        if kind in self.refused:
            raise ValueError("current limit exceeds maximum limit")
        self.limits[kind] = limits


def apply_fake_limits(fake):
    return webmention_parse_worker.apply_resource_limits(
        memory_bytes=1000, cpu_seconds=5, max_file_bytes=300, resource_module=fake
    )


def test_resource_limits_are_applied_to_cpu_output_and_memory():
    fake = FakeResource()

    assert apply_fake_limits(fake) is True
    assert fake.limits == {
        fake.RLIMIT_CPU: (5, 6),
        fake.RLIMIT_FSIZE: (300, 300),
        fake.RLIMIT_CORE: (0, 0),
        fake.RLIMIT_AS: (1000, 1000),
        fake.RLIMIT_DATA: (1000, 1000),
    }


def test_resource_limits_never_exceed_an_inherited_hard_limit():
    fake = FakeResource(hard=4)

    assert apply_fake_limits(fake) is True
    assert fake.limits[fake.RLIMIT_CPU] == (4, 4)
    assert fake.limits[fake.RLIMIT_AS] == (4, 4)


def test_refused_memory_limits_are_reported_to_the_caller():
    fake = FakeResource(refused={FakeResource.RLIMIT_AS, FakeResource.RLIMIT_DATA, FakeResource.RLIMIT_CORE})

    assert apply_fake_limits(fake) is False
    assert fake.limits[fake.RLIMIT_CPU] == (5, 6)


def test_one_accepted_memory_limit_is_enough():
    assert apply_fake_limits(FakeResource(refused={FakeResource.RLIMIT_AS})) is True


@pytest.mark.parametrize("fake", [None, FakeResource(refused={FakeResource.RLIMIT_CPU})], ids=["missing", "refused"])
def test_missing_required_limits_are_an_error(fake):
    with pytest.raises(webmention_parse_worker.LimitsUnavailable):
        apply_fake_limits(fake)


def test_peak_resident_bytes_uses_the_platform_unit(monkeypatch):
    fake = SimpleNamespace(RUSAGE_SELF=0, getrusage=lambda who: SimpleNamespace(ru_maxrss=2048))

    monkeypatch.setattr(sys, "platform", "darwin")
    assert webmention_parse_worker.peak_resident_bytes(fake) == 2048
    monkeypatch.setattr(sys, "platform", "linux")
    assert webmention_parse_worker.peak_resident_bytes(fake) == 2048 * 1024


# --- settings ---------------------------------------------------------------


def test_default_limits():
    assert parse_isolation.parse_limits() == parse_isolation.ParseLimits(
        memory_bytes=512 * MIB,
        cpu_seconds=20,
        wall_seconds=30,
        max_result_bytes=2 * MIB,
        require_os_limits=True,
    )


@pytest.mark.parametrize("value", [0, -1, "big", None, True, float("inf"), float("nan")])
def test_invalid_limits_fall_back_to_the_defaults(value):
    configured = {
        "INDIEWEB_WEBMENTION_PARSE_MEMORY_BYTES": value,
        "INDIEWEB_WEBMENTION_PARSE_CPU_SECONDS": value,
        "INDIEWEB_WEBMENTION_PARSE_WALL_SECONDS": value,
        "INDIEWEB_WEBMENTION_PARSE_MAX_RESULT_BYTES": value,
    }

    with override_settings(**configured):
        limits = parse_isolation.parse_limits()

    assert (limits.memory_bytes, limits.cpu_seconds, limits.wall_seconds, limits.max_result_bytes) == (
        512 * MIB,
        20,
        30,
        2 * MIB,
    )


def test_limits_are_configurable():
    with override_settings(**{**SMALL_LIMITS, "INDIEWEB_WEBMENTION_PARSE_WALL_SECONDS": 2.5}):
        limits = parse_isolation.parse_limits()
        command = parse_isolation._worker_command(limits)

    assert limits.wall_seconds == 2.5
    assert command[1:] == [
        "-m",
        "indieweb.webmention_parse_worker",
        "--memory-bytes",
        str(128 * MIB),
        "--cpu-seconds",
        "1",
        "--max-result-bytes",
        "200000",
    ]


# --- link verification ------------------------------------------------------


def test_link_verification_is_linear_in_nesting():
    count = 30_000
    html = "<div>" * count + '<a href="https://other.example/">' * count

    started = time.process_time()
    assert _html_links_to_target(html, TARGET_URL) is False
    assert _html_links_to_source_domain(html, "https://source.example/post") is False

    # The ancestor walk this replaces needed minutes for this input.
    assert time.process_time() - started < 20


def test_links_in_nested_non_rendered_containers_do_not_verify():
    hidden = (
        "<template><div><noscript>"
        f'<a href="{TARGET_URL}">hidden</a>'
        "</noscript></div></template>"
        f'<noscript><p><a href="{TARGET_URL}">hidden</a></p></noscript>'
    )

    assert _html_links_to_target(hidden, TARGET_URL) is False
    assert _html_links_to_source_domain(hidden, TARGET_URL) is False
    assert _html_links_to_target(hidden + f'<a href="{TARGET_URL}">shown</a>', TARGET_URL) is True
    assert _html_links_to_source_domain(hidden + f'<a href="{TARGET_URL}">shown</a>', TARGET_URL) is True


@pytest.mark.django_db
def test_quadratic_link_document_is_answered_quickly():
    html = "<div>" * 30_000 + '<a href="https://other.example/">' * 30_000
    started = time.monotonic()

    webmention = processor_serving(html).process_webmention(SOURCE_URL, TARGET_URL)

    assert time.monotonic() - started < 20
    assert_nothing_stored(webmention)
