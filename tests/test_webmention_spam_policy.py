"""Configured spam screening must succeed before publishing a Webmention."""

from collections import UserDict
from types import MappingProxyType
from unittest.mock import patch

import httpx
import pytest

from indieweb.models import WebmentionNestedResponse, WebmentionSourceSnapshot
from indieweb.processors import WebmentionProcessor

SOURCE = "https://source.example/post"
TARGET = "https://target.example/article"
CHECKER = "indieweb.interfaces.NoOpSpamChecker"


class BrokenSpamChecker:
    def __init__(self):
        raise RuntimeError("private constructor details")


def unavailable_checker():
    return None


@pytest.fixture
def spam_processor():
    html = f"""<article class="h-entry"><div class="e-content">New content
        <a href="{TARGET}">Target</a></div>
        <article class="h-entry"><a class="u-url" href="https://source.example/reply">Reply</a>
        <div class="e-content">Nested reply</div></article></article>"""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=html, headers={"content-type": "text/html"})
    )
    with httpx.Client(transport=transport) as client:
        yield WebmentionProcessor(client=client)


@pytest.mark.django_db
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize(
    "checker_path",
    [
        "missing_spam_module.Checker",
        "tests.test_webmention_spam_policy.BrokenSpamChecker",
        "tests.test_webmention_spam_policy.unavailable_checker",
    ],
)
def test_configured_spam_load_failure_refuses_publication(
    spam_processor, settings, django_capture_on_commit_callbacks, existing, checker_path
):
    settings.INDIEWEB_SPAM_CHECKER = None
    if existing:
        with django_capture_on_commit_callbacks(execute=True):
            previous = spam_processor.process_webmention(SOURCE, TARGET)
        previous_snapshot = WebmentionSourceSnapshot.objects.get(webmention=previous).raw_source_html
        previous_children = list(WebmentionNestedResponse.objects.filter(webmention=previous).values())

    settings.INDIEWEB_SPAM_CHECKER = checker_path
    # Loading also has to be safe when the processor is created with broken settings.
    processor = WebmentionProcessor(client=spam_processor._injected_client)
    with (
        patch("indieweb.processors.webmention_received.send_robust") as signal,
        django_capture_on_commit_callbacks(execute=True),
    ):
        mention = processor.process_webmention(SOURCE, TARGET)
    mention.refresh_from_db()
    assert mention.status == "failed"
    assert mention.verified_at is None
    assert mention.last_received_at is not None
    signal.assert_not_called()
    if existing:
        assert mention.content == previous.content
        assert WebmentionSourceSnapshot.objects.get(webmention=mention).raw_source_html == previous_snapshot
        assert list(WebmentionNestedResponse.objects.filter(webmention=mention).values()) == previous_children
    else:
        assert not WebmentionSourceSnapshot.objects.exists()
        assert not WebmentionNestedResponse.objects.exists()

    # Correcting configuration permits an explicit retry on the same processor/row.
    settings.INDIEWEB_SPAM_CHECKER = CHECKER
    with (
        patch("indieweb.processors.webmention_received.send_robust") as signal,
        django_capture_on_commit_callbacks(execute=True),
    ):
        retried = processor.process_webmention(SOURCE, TARGET)
    assert retried.pk == mention.pk
    assert retried.status == "verified"
    assert retried.verified_at is not None
    signal.assert_called_once()


@pytest.mark.django_db
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize(
    "result",
    [
        {},
        {"is_spam": "false"},
        {"is_spam": None},
        {"is_spam": 0},
        {"is_spam": 1},
        None,
        [],
        "false",
        {"is_spam": False, "extra": object()},
        {"is_spam": True, "extra": float("nan")},
        {"is_spam": False, "details": "a\x00b"},
        {"is_spam": True, "details": {"nested\x00key": "value"}},
        {"is_spam": False, "details": ["ok", ("tuple", "\x00")]},
        {"is_spam": False, "details": "\ud800"},
        {"is_spam": True, "details": {"\udfff": "value"}},
        *(
            {"is_spam": decision, "confidence": confidence}
            for decision in (False, True)
            for confidence in (float("nan"), float("inf"), -float("inf"), -0.1, 1.1, True, "0.5", None, 10**400)
        ),
    ],
)
def test_malformed_spam_decision_refuses_publication(
    spam_processor, settings, django_capture_on_commit_callbacks, existing, result
):
    settings.INDIEWEB_SPAM_CHECKER = CHECKER
    if existing:
        with django_capture_on_commit_callbacks(execute=True):
            previous = spam_processor.process_webmention(SOURCE, TARGET)
        old_snapshot = WebmentionSourceSnapshot.objects.get(webmention=previous).raw_source_html
        old_children = list(WebmentionNestedResponse.objects.filter(webmention=previous).values())
        old_result = previous.spam_check_result

    with (
        patch("indieweb.interfaces.NoOpSpamChecker.check", return_value=result),
        patch("indieweb.processors.webmention_received.send_robust") as signal,
        django_capture_on_commit_callbacks(execute=True),
    ):
        mention = spam_processor.process_webmention(SOURCE, TARGET)
    mention.refresh_from_db()
    assert mention.status == "failed"
    assert mention.verified_at is None
    signal.assert_not_called()
    if existing:
        assert mention.content == previous.content
        assert mention.spam_check_result == old_result
        assert WebmentionSourceSnapshot.objects.get(webmention=mention).raw_source_html == old_snapshot
        assert list(WebmentionNestedResponse.objects.filter(webmention=mention).values()) == old_children
    else:
        assert mention.spam_check_result is None
        assert not WebmentionSourceSnapshot.objects.exists()
        assert not WebmentionNestedResponse.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("is_spam", [False, True])
@pytest.mark.parametrize("confidence", [None, 0, 0.5, 1])
@pytest.mark.parametrize("mapping_type", [dict, UserDict, MappingProxyType])
def test_valid_spam_mapping_preserves_metadata(
    spam_processor, settings, django_capture_on_commit_callbacks, is_spam, confidence, mapping_type
):
    settings.INDIEWEB_SPAM_CHECKER = CHECKER
    result = {"is_spam": is_spam, "details": "Synthetic decision", "extra": {"rules": ["local"]}}
    if confidence is not None:
        result["confidence"] = confidence
    with (
        patch("indieweb.interfaces.NoOpSpamChecker.check", return_value=mapping_type(result)),
        patch("indieweb.processors.webmention_received.send_robust") as signal,
        django_capture_on_commit_callbacks(execute=True),
    ):
        mention = spam_processor.process_webmention(SOURCE, TARGET)
    mention.refresh_from_db()
    assert mention.status == ("spam" if is_spam else "verified")
    assert mention.spam_check_result == result
    assert isinstance(mention.spam_check_result, dict)
    assert (mention.verified_at is None) == is_spam
    assert signal.call_count == (0 if is_spam else 1)
    assert WebmentionSourceSnapshot.objects.exists() == (not is_spam)


@pytest.mark.django_db
@pytest.mark.parametrize("configured", [None, ""])
def test_unconfigured_spam_screening_keeps_verification(spam_processor, settings, configured):
    settings.INDIEWEB_SPAM_CHECKER = configured
    mention = spam_processor.process_webmention(SOURCE, TARGET)
    assert mention.status == "verified"
    assert mention.spam_check_result is None


class FalsySpamChecker:
    def __bool__(self):
        return False

    def check(self, webmention):
        return {"is_spam": True}


@pytest.mark.django_db
def test_falsy_configured_checker_is_still_executed(spam_processor, settings):
    settings.INDIEWEB_SPAM_CHECKER = "tests.test_webmention_spam_policy.FalsySpamChecker"
    mention = spam_processor.process_webmention(SOURCE, TARGET)
    assert mention.status == "spam"


@pytest.mark.django_db(transaction=True)
def test_spam_policy_failure_logs_no_private_details(spam_processor, settings, caplog):
    settings.INDIEWEB_SPAM_CHECKER = "tests.test_webmention_spam_policy.BrokenSpamChecker"
    mention = spam_processor.process_webmention(SOURCE, TARGET)
    assert mention.status == "failed"
    assert "spam screening unavailable or invalid" in caplog.text
    assert "private constructor details" not in caplog.text
    assert "BrokenSpamChecker" not in caplog.text
