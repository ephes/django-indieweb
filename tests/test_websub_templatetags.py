import pytest
from django.template import Context, Template


def test_websub_link_tags_use_configured_hubs(settings):
    settings.INDIEWEB_WEBSUB_HUBS = ("https://hub.example/", "https://backup.example/websub")

    rendered = Template('{% load websub_tags %}{% websub_link_tags "https://example.com/feed" %}').render(Context())

    assert rendered == (
        '<link rel="hub" href="https://hub.example/">\n'
        '<link rel="hub" href="https://backup.example/websub">\n'
        '<link rel="self" href="https://example.com/feed">'
    )


def test_websub_link_tags_accept_explicit_hubs():
    rendered = Template(
        '{% load websub_tags %}{% websub_link_tags "https://example.com/feed" "https://hub.example/" %}'
    ).render(Context())

    assert rendered == (
        '<link rel="hub" href="https://hub.example/">\n<link rel="self" href="https://example.com/feed">'
    )


def test_websub_link_tags_escape_values():
    rendered = Template('{% load websub_tags %}{% websub_link_tags topic_url "https://hub.example/" %}').render(
        Context({"topic_url": "https://example.com/feed?name=one&value=two"})
    )

    assert rendered == (
        '<link rel="hub" href="https://hub.example/">\n'
        '<link rel="self" href="https://example.com/feed?name=one&amp;value=two">'
    )


def test_websub_link_tags_raise_when_no_hub_is_configured(settings):
    settings.INDIEWEB_WEBSUB_HUBS = ()

    with pytest.raises(ValueError, match="at least one WebSub hub"):
        Template('{% load websub_tags %}{% websub_link_tags "https://example.com/feed" %}').render(Context())
