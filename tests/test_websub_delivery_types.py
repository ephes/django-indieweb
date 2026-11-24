"""Django security checks for the WebSub callback content-type allowlist."""

import httpx
import pytest
from django.core.checks import Error, Tags, run_checks

SETTING = "INDIEWEB_WEBSUB_DELIVERY_ALLOWED_TYPES"


@pytest.fixture
def delivery_type_messages(settings, monkeypatch):
    def unexpected_request(*args, **kwargs):
        pytest.fail("WebSub delivery type checks must not make HTTP requests")

    monkeypatch.setattr(httpx.Client, "send", unexpected_request)

    def messages(overrides):
        for name, value in overrides.items():
            setattr(settings, name, value)
        # By default pytest-django blocks queries in these tests.
        return [message for message in run_checks(tags=[Tags.security]) if message.obj == SETTING]

    return messages


@pytest.mark.parametrize(
    "value",
    [
        False,
        ["application/json", 123],
        ["application/json", "private-config-value"],
        ["application/*"],
        ["application/json; charset=utf-8"],
        "",
    ],
)
def test_security_checks_report_invalid_delivery_types(delivery_type_messages, value):
    (message,) = delivery_type_messages({SETTING: value})

    assert isinstance(message, Error)
    assert message.id == "indieweb.E006"
    assert "private-config-value" not in str(message)


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {SETTING: None},
        {SETTING: []},
        {SETTING: ()},
        {SETTING: "application/rss+xml"},
        {SETTING: ["Application/Atom+XML", "application/vnd.example+json"]},
    ],
)
def test_security_checks_accept_valid_delivery_types(delivery_type_messages, overrides):
    assert delivery_type_messages(overrides) == []


def test_security_checks_do_not_consume_one_shot_allowlist(delivery_type_messages):
    types = iter(["application/json"])

    (message,) = delivery_type_messages({SETTING: types})

    assert message.id == "indieweb.E006"
    assert list(types) == ["application/json"]
