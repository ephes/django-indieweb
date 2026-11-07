"""Synthetic ORM and bundled-template query budgets."""

from datetime import timedelta

import pytest
from django.template import Context, Template
from django.template.loader import render_to_string
from django.utils import timezone

from indieweb.models import Webmention, WebmentionNestedResponse
from indieweb.templatetags import webmention_tags

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("size", [1, 20])
def test_card_counts_are_batched_and_reused(size, django_assert_num_queries):
    urls = [f"https://target.example/{i}" for i in range(size)]
    for url in urls[:-1]:
        for kind in ("reply", "like", "mention", "repost"):
            Webmention.objects.create(
                source_url=f"https://source.example/{kind}", target_url=url, status="verified", mention_type=kind
            )
        Webmention.objects.create(source_url="https://source.example/pending", target_url=url, status="pending")
    with django_assert_num_queries(1):
        counts = webmention_tags.prepare_webmention_counts(urls)
    context = Context({"webmention_counts": counts})
    with django_assert_num_queries(0):
        for _ in range(2):
            for i, url in enumerate(urls):
                expected = int(i < size - 1)
                assert webmention_tags.webmention_count(context, url) == 4 * expected
                for kind in ("reply", "like", "mention", "repost", "unknown"):
                    value = webmention_tags.webmention_count(context, url, kind)
                    assert type(value) is int
                    assert value == (expected if kind != "unknown" else 0)
    # Unprepared targets still use the legacy fallback.
    with django_assert_num_queries(1):
        assert webmention_tags.webmention_count(context, "https://other.example/") == 0
    with django_assert_num_queries(0):
        assert webmention_tags.prepare_webmention_counts([]) == {}
        assert webmention_tags.webmention_count(context, "") == 0
    template = Template("""{% load webmention_tags %}{% prepare_webmention_counts urls as webmention_counts %}
        {% for url in urls %}{% webmention_count url %},{% webmention_count url 'reply' %};{% endfor %}""")
    with django_assert_num_queries(1):
        output = template.render(Context({"urls": urls}))
    assert output.strip() == "4,1;" * (size - 1) + "0,0;"


@pytest.mark.parametrize("size", [1, 20])
def test_display_defers_payloads_without_lazy_template_queries(size, django_assert_num_queries):
    target = "https://target.example/post"
    parent = Webmention.objects.create(
        source_url="https://source.example/parent",
        target_url=target,
        mention_type="reply",
        status="verified",
        content="Parent",
        spam_check_result={"large": "X" * 100000},
    )
    now = timezone.now()
    for i in range(size):
        WebmentionNestedResponse.objects.create(
            webmention=parent,
            identity=f"https://child.example/{i}",
            response_url=f"https://child.example/{i}",
            content=f"Child {i}",
            mention_type="reply",
            first_seen_at=now + timedelta(seconds=i),
            last_seen_at=now,
            parsed_h_entry={"large": "Y" * 100000},
            content_digest="digest",
        )
    for kind in ("like", "mention", "repost"):
        Webmention.objects.create(
            source_url=f"https://source.example/{kind}",
            target_url=target,
            status="verified",
            mention_type=kind,
            content=kind,
        )
    template = Template("{% load webmention_tags %}{% show_webmentions target %}")
    with django_assert_num_queries(2) as queries:
        output = template.render(Context({"target": target}))
    sql = " ".join(q["sql"] for q in queries.captured_queries).lower()
    for column in ("parsed_h_entry", "content_digest", "spam_check_result", "status_token"):
        assert column not in sql
    assert output.count("webmention-nested webmention-nested-reply") == size
    assert output.index(f"Child {size - 1}") <= output.index("Child 0")
    # Compare the same bundled rendering against fully loaded models.
    eager = list(Webmention.objects.filter(target_url=target).order_by("-published", "-created"))
    for row in eager:
        row._verified_nested_responses = list(row.nested_responses.order_by("-first_seen_at"))
        webmention_tags._prepare_webmention_for_display(row)
    eager = webmention_tags._attach_displayable_nested_responses(eager, {row.source_url for row in eager})
    with django_assert_num_queries(0):
        assert output == render_to_string("indieweb/webmentions.html", {"webmentions": eager, "target_url": target})


@pytest.mark.parametrize("existing", [None, 7, {"url": 3}, {"url": []}, {"url": {"like": "1"}}])
def test_count_context_collision_uses_legacy_fallback(existing, django_assert_num_queries):
    with django_assert_num_queries(1):
        assert webmention_tags.webmention_count({"webmention_counts": existing}, "url") == 0
