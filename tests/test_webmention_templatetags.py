"""Tests for webmention template tags."""

from datetime import timedelta

import pytest
from django.template import Context, Template
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from indieweb.models import Webmention, WebmentionNestedResponse

pytestmark = pytest.mark.django_db


@pytest.fixture
def target_url():
    return "https://example.com/post/1/"


@pytest.fixture
def webmentions(target_url):
    """Create the default top-level Webmentions used by template tag tests."""
    return {
        "like": Webmention.objects.create(
            source_url="https://social.example/likes/123",
            target_url=target_url,
            mention_type="like",
            author_name="Alice",
            author_url="https://alice.example",
            author_photo="https://alice.example/photo.jpg",
            content_html="Alice liked this",
            published=timezone.now(),
            status="verified",
        ),
        "reply": Webmention.objects.create(
            source_url="https://blog.example/reply-post",
            target_url=target_url,
            mention_type="reply",
            author_name="Bob",
            author_url="https://bob.example",
            content="This is a great post!",
            content_html="<p>This is a great post!</p>",
            published=timezone.now(),
            status="verified",
        ),
        "repost": Webmention.objects.create(
            source_url="https://micro.blog/repost/456",
            target_url=target_url,
            mention_type="repost",
            author_name="Charlie",
            author_url="https://charlie.example",
            author_photo="https://charlie.example/avatar.png",
            published=timezone.now(),
            status="verified",
        ),
        "mention": Webmention.objects.create(
            source_url="https://news.example/article",
            target_url=target_url,
            mention_type="mention",
            author_name="News Site",
            author_url="https://news.example",
            content="As mentioned in example.com...",
            published=timezone.now(),
            status="verified",
        ),
        "spam": Webmention.objects.create(
            source_url="https://spam.example/post",
            target_url=target_url,
            mention_type="reply",
            status="spam",
        ),
        "pending": Webmention.objects.create(
            source_url="https://unverified.example/post",
            target_url=target_url,
            mention_type="like",
            status="pending",
        ),
    }


@pytest.fixture
def reply(webmentions):
    return webmentions["reply"]


@pytest.fixture
def render_webmentions(target_url, webmentions):
    """Render the webmentions inclusion tag for tests."""

    def _render_webmentions(target_url_override=None, mention_type=None):
        rendered_target_url = target_url_override or target_url
        if mention_type:
            template = Template("{% load webmention_tags %}{% show_webmentions target_url mention_type %}")
            return template.render(Context({"target_url": rendered_target_url, "mention_type": mention_type}))

        template = Template("{% load webmention_tags %}{% show_webmentions target_url %}")
        return template.render(Context({"target_url": rendered_target_url}))

    return _render_webmentions


@pytest.fixture
def create_nested_response():
    """Create a nested response for template rendering tests."""

    def _create_nested_response(webmention, identity, **kwargs):
        seen_at = kwargs.pop("first_seen_at", timezone.now())
        defaults = {
            "response_url": identity,
            "author_name": "Nested Author",
            "author_url": "https://nested.example/author",
            "content": "Nested response content",
            "content_html": "<p>Nested response content</p>",
            "published": seen_at,
            "mention_type": "reply",
            "status": "verified",
            "last_seen_at": seen_at,
            "verified_at": seen_at,
        }
        defaults.update(kwargs)
        return WebmentionNestedResponse.objects.create(
            webmention=webmention,
            identity=identity,
            first_seen_at=seen_at,
            **defaults,
        )

    return _create_nested_response


def test_webmention_endpoint_link_tag():
    """Test the webmention_endpoint_link tag."""
    template = Template("{% load webmention_tags %}{% webmention_endpoint_link %}")
    rendered = template.render(Context())

    assert '<link rel="webmention"' in rendered
    assert 'href="' in rendered
    assert reverse("indieweb:webmention") in rendered


def test_webmention_endpoint_link_with_custom_endpoint():
    """Test the webmention_endpoint_link tag with a custom endpoint."""
    template = Template(
        '{% load webmention_tags %}{% webmention_endpoint_link "https://custom.endpoint/webmention" %}'
    )
    rendered = template.render(Context())

    assert '<link rel="webmention"' in rendered
    assert 'href="https://custom.endpoint/webmention"' in rendered


def test_webmention_endpoint_link_escapes_custom_endpoint():
    """A custom endpoint argument is escaped inside the generated link tag."""
    template = Template("{% load webmention_tags %}{% webmention_endpoint_link endpoint %}")
    rendered = template.render(Context({"endpoint": 'https://evil.example/" onload="alert(1)'}))

    assert '<link rel="webmention"' in rendered
    assert 'href="https://evil.example/&quot; onload=&quot;alert(1)"' in rendered
    assert '" onload="' not in rendered


def test_show_webmentions_tag(render_webmentions):
    """Test the show_webmentions tag."""
    rendered = render_webmentions()

    assert "Alice" in rendered
    assert "Bob" in rendered
    assert "Charlie" in rendered
    assert "News Site" in rendered

    assert "spam.example" not in rendered
    assert "unverified.example" not in rendered

    assert "h-cite" in rendered
    assert "p-author" in rendered
    assert "u-url" in rendered


def test_show_webmentions_sanitizes_existing_stored_remote_fields(target_url, render_webmentions):
    """Bundled templates sanitize older stored Webmention rows before display."""
    Webmention.objects.create(
        source_url="https://unsafe.example/post",
        target_url=target_url,
        mention_type="reply",
        author_name="Mallory",
        author_url="javascript:alert(1)",
        author_photo="data:image/svg+xml,<svg onload=alert(1)>",
        content="Unsafe content",
        content_html="""
        <p onclick="alert(1)">Safe <strong>formatting</strong>
          <a href="javascript:alert(1)">bad link</a>
          <a href="data:text/html,evil">bad data</a>
        </p>
        <script>alert(1)</script>
        <svg onload="alert(1)"></svg>
        <form><input name="x"></form>
        <iframe src="https://evil.example"></iframe>
        <style>body { color: red; }</style>
        """,
        status="verified",
    )

    rendered = render_webmentions()

    assert "Mallory" in rendered
    assert "<strong>formatting</strong>" in rendered
    assert 'href="javascript:' not in rendered
    assert 'href="data:' not in rendered
    assert 'src="data:' not in rendered
    assert "<script" not in rendered
    assert "<svg" not in rendered
    assert "<form" not in rendered
    assert "<iframe" not in rendered
    assert "<style" not in rendered
    assert "onclick" not in rendered
    assert "onload" not in rendered


def test_show_webmentions_sanitizes_existing_stored_nested_response_fields(
    reply, render_webmentions, create_nested_response
):
    """Bundled nested response output sanitizes stored child rows before display."""
    create_nested_response(
        reply,
        "https://comments.example/unsafe-child",
        author_name="Nested Mallory",
        author_url="data:text/html,evil",
        author_photo="javascript:alert(1)",
        content="Unsafe child",
        content_html="""
        <p onmouseover="alert(1)">Nested <em>reply</em></p>
        <script>alert(1)</script>
        <svg onload="alert(1)"></svg>
        <iframe src="https://evil.example"></iframe>
        <a href="javascript:alert(1)">bad child link</a>
        """,
    )

    rendered = render_webmentions()

    assert "Nested Mallory" in rendered
    assert "<em>reply</em>" in rendered
    assert 'href="javascript:' not in rendered
    assert 'src="javascript:' not in rendered
    assert 'href="data:' not in rendered
    assert "<script" not in rendered
    assert "<svg" not in rendered
    assert "<iframe" not in rendered
    assert "onmouseover" not in rendered
    assert "onload" not in rendered


def test_show_webmentions_sanitizes_nested_response_identity_and_response_url(
    reply, render_webmentions, create_nested_response
):
    """Latent unsafe ``identity`` / ``response_url`` rows must not produce dangerous hrefs.

    The bundled ``nested_response.html`` template renders
    ``firstof response_url identity as nested_response_url`` into the
    response link's ``href``. Ingestion validation should already reject
    bad values, but a display-time pass through
    ``sanitize_remote_webmention_url`` guards against latent rows and any
    future code path that bypasses ingestion validation.
    """
    create_nested_response(
        reply,
        "javascript:alert('latent identity')",
        response_url="data:text/html,evil-response-url",
        author_name="Nested Mallory",
        author_url="https://safe.example/author",
        content="Latent unsafe URL row",
        content_html="<p>Latent unsafe URL row</p>",
    )

    rendered = render_webmentions()

    assert "javascript:" not in rendered
    assert "data:text/html" not in rendered


def test_webmention_templates_harden_outbound_link_attributes(render_webmentions):
    """Bundled Webmention links include outbound safety attributes."""
    rendered = render_webmentions()

    assert 'rel="nofollow noopener ugc"' in rendered
    assert 'referrerpolicy="no-referrer"' in rendered
    assert 'href="https://bob.example" rel="nofollow noopener ugc" referrerpolicy="no-referrer"' in rendered
    assert (
        'href="https://blog.example/reply-post" rel="nofollow noopener ugc" referrerpolicy="no-referrer"'
    ) in rendered


def test_show_webmentions_empty(render_webmentions):
    """Test show_webmentions with no webmentions."""
    rendered = render_webmentions("https://example.com/no-mentions/")

    assert "webmentions" in rendered


def test_show_webmentions_by_type(render_webmentions):
    """Test show_webmentions filtering by type."""
    rendered = render_webmentions(mention_type="like")

    assert "Alice" in rendered
    assert "Bob" not in rendered
    assert "Charlie" not in rendered
    assert "News Site" not in rendered


def test_verified_nested_response_renders_under_verified_parent_reply(
    reply, render_webmentions, create_nested_response
):
    """Verified child rows render inline below their verified parent reply."""
    create_nested_response(
        reply,
        "https://comments.example/reply/1",
        author_name="Nested Carol",
        content="Nested reply body",
        content_html="<p>Nested reply body</p>",
    )

    rendered = render_webmentions()

    assert 'class="webmention-nested-responses"' in rendered
    assert "Nested Carol" in rendered
    assert "Nested reply body" in rendered
    assert rendered.index("This is a great post!") < rendered.index("Nested reply body")


@pytest.mark.parametrize("status", ["failed", "spam", "pending"])
def test_verified_nested_response_does_not_render_under_non_verified_parent(
    status, target_url, render_webmentions, create_nested_response
):
    """A verified child is hidden when the parent Webmention is not verified."""
    parent = Webmention.objects.create(
        source_url=f"https://parent.example/{status}",
        target_url=target_url,
        mention_type="reply",
        content=f"Parent {status}",
        status=status,
    )
    create_nested_response(
        parent,
        f"https://comments.example/{status}",
        content=f"Child under {status}",
        content_html=f"<p>Child under {status}</p>",
    )

    rendered = render_webmentions()

    assert f"Child under {status}" not in rendered


def test_non_verified_nested_response_does_not_render(reply, render_webmentions, create_nested_response):
    """Only verified child rows render inline."""
    create_nested_response(
        reply,
        "https://comments.example/missing",
        status="missing",
        content="Missing child content",
        content_html="<p>Missing child content</p>",
    )

    rendered = render_webmentions()

    assert "Missing child content" not in rendered


def test_direct_top_level_webmention_suppresses_duplicate_nested_response(
    target_url, reply, render_webmentions, create_nested_response
):
    """A direct verified Webmention to the target wins over an inline child copy."""
    create_nested_response(
        reply,
        "https://comments.example/direct-reply",
        response_url="https://comments.example/direct-reply",
        author_name="Inline Duplicate",
        content="Inline duplicate content",
        content_html="<p>Inline duplicate content</p>",
    )
    Webmention.objects.create(
        source_url="https://comments.example/direct-reply",
        target_url=target_url,
        mention_type="reply",
        author_name="Direct Reply",
        content="Direct top-level content",
        content_html="<p>Direct top-level content</p>",
        published=timezone.now() + timedelta(minutes=1),
        status="verified",
    )

    rendered = render_webmentions()

    assert "Direct Reply" in rendered
    assert "Direct top-level content" in rendered
    assert "Inline Duplicate" not in rendered
    assert "Inline duplicate content" not in rendered


def test_direct_top_level_suppression_ignores_current_type_filter(
    target_url, reply, render_webmentions, create_nested_response
):
    """A filtered-out direct top-level Webmention still suppresses a duplicate child."""
    create_nested_response(
        reply,
        "https://comments.example/direct-like",
        response_url="https://comments.example/direct-like",
        author_name="Filtered Inline Duplicate",
        content="Filtered inline duplicate content",
        content_html="<p>Filtered inline duplicate content</p>",
    )
    Webmention.objects.create(
        source_url="https://comments.example/direct-like",
        target_url=target_url,
        mention_type="like",
        author_name="Direct Like",
        published=timezone.now() + timedelta(minutes=1),
        status="verified",
    )

    rendered = render_webmentions(mention_type="reply")

    assert "Bob" in rendered
    assert "Direct Like" not in rendered
    assert "Filtered Inline Duplicate" not in rendered
    assert "Filtered inline duplicate content" not in rendered


def test_duplicate_nested_identity_renders_once_under_first_displayed_parent(
    target_url, render_webmentions, create_nested_response
):
    """The first parent in top-level ordering owns a duplicated nested child."""
    now = timezone.now()
    older_parent = Webmention.objects.create(
        source_url="https://blog.example/older-parent",
        target_url=target_url,
        mention_type="reply",
        author_name="Older Parent",
        content="Older parent content",
        published=now - timedelta(days=2),
        status="verified",
    )
    newer_parent = Webmention.objects.create(
        source_url="https://blog.example/newer-parent",
        target_url=target_url,
        mention_type="reply",
        author_name="Newer Parent",
        content="Newer parent content",
        published=now + timedelta(days=2),
        status="verified",
    )
    shared_identity = "https://comments.example/shared"
    create_nested_response(
        older_parent,
        shared_identity,
        content="Child via older parent",
        content_html="<p>Child via older parent</p>",
    )
    create_nested_response(
        newer_parent,
        shared_identity,
        content="Child via newer parent",
        content_html="<p>Child via newer parent</p>",
    )

    rendered = render_webmentions()

    assert "Child via newer parent" in rendered
    assert "Child via older parent" not in rendered
    assert rendered.index("Newer parent content") < rendered.index("Child via newer parent")


def test_nested_responses_are_ordered_by_published_or_first_seen(reply, render_webmentions, create_nested_response):
    """Children render newest first using published, falling back to first_seen_at."""
    now = timezone.now()
    create_nested_response(
        reply,
        "https://comments.example/older",
        content="Older published child",
        content_html="<p>Older published child</p>",
        published=now - timedelta(days=2),
        first_seen_at=now,
    )
    create_nested_response(
        reply,
        "https://comments.example/fallback",
        content="Fallback first-seen child",
        content_html="<p>Fallback first-seen child</p>",
        published=None,
        first_seen_at=now - timedelta(days=1),
    )
    create_nested_response(
        reply,
        "https://comments.example/newer",
        content="Newer published child",
        content_html="<p>Newer published child</p>",
        published=now,
        first_seen_at=now - timedelta(days=3),
    )

    rendered = render_webmentions()

    assert rendered.index("Newer published child") < rendered.index("Fallback first-seen child")
    assert rendered.index("Fallback first-seen child") < rendered.index("Older published child")


def test_show_webmentions_type_filter_still_filters_top_level_parents(
    reply, render_webmentions, create_nested_response
):
    """Filtering top-level Webmentions by type does not leak nested replies."""
    create_nested_response(
        reply,
        "https://comments.example/reply-filter",
        content="Nested reply for filtered parent",
        content_html="<p>Nested reply for filtered parent</p>",
    )

    rendered = render_webmentions(mention_type="like")

    assert "Alice" in rendered
    assert "Bob" not in rendered
    assert "Nested reply for filtered parent" not in rendered


def test_webmention_count_does_not_include_nested_responses(target_url, reply, create_nested_response):
    """webmention_count keeps its top-level-only count semantics."""
    create_nested_response(reply, "https://comments.example/count-one")
    create_nested_response(reply, "https://comments.example/count-two")

    template = Template("{% load webmention_tags %}{% webmention_count target_url %}")
    rendered = template.render(Context({"target_url": target_url})).strip()

    assert rendered == "4"


def test_show_webmentions_prefetches_nested_responses(
    reply, render_webmentions, create_nested_response, django_assert_num_queries
):
    """Rendering does not issue one query per parent or child."""
    create_nested_response(reply, "https://comments.example/query-one")
    create_nested_response(reply, "https://comments.example/query-two")

    with django_assert_num_queries(2):
        render_webmentions()


def test_webmention_count_tag(target_url, webmentions):
    """Test the webmention_count tag."""
    template = Template("{% load webmention_tags %}{% webmention_count target_url %}")
    context = Context({"target_url": target_url})
    rendered = template.render(context).strip()

    assert rendered == "4"


def test_webmention_count_by_type(target_url, webmentions):
    """Test webmention_count filtering by type."""
    template = Template('{% load webmention_tags %}{% webmention_count target_url "reply" %}')
    context = Context({"target_url": target_url})
    rendered = template.render(context).strip()

    assert rendered == "1"


def test_webmention_count_zero(webmentions):
    """Test webmention_count with no mentions."""
    template = Template("{% load webmention_tags %}{% webmention_count target_url %}")
    context = Context({"target_url": "https://example.com/no-mentions/"})
    rendered = template.render(context).strip()

    assert rendered == "0"


def test_webmention_count_as_variable(target_url, webmentions):
    """Test storing webmention_count in a variable."""
    template = Template("{% load webmention_tags %}{% webmention_count target_url as count %}{{ count }} webmentions")
    context = Context({"target_url": target_url})
    rendered = template.render(context).strip()

    assert rendered == "4 webmentions"


def test_like_template_rendering(render_webmentions):
    """Test that likes use the correct template."""
    rendered = render_webmentions()

    assert 'class="p-like' in rendered
    assert "liked" in rendered.lower()


def test_reply_template_rendering(render_webmentions):
    """Test that replies use the correct template."""
    rendered = render_webmentions()

    assert 'class="p-comment' in rendered
    assert "This is a great post!" in rendered
    assert "e-content" in rendered


def test_repost_template_rendering(render_webmentions):
    """Test that reposts use the correct template."""
    rendered = render_webmentions()

    assert 'class="p-repost' in rendered
    assert "reposted" in rendered.lower()


def test_mention_template_rendering(render_webmentions):
    """Test that generic mentions use the correct template."""
    rendered = render_webmentions()

    assert "As mentioned in example.com" in rendered


@override_settings(DEBUG=True)
def test_template_tag_errors():
    """Test error handling in template tags."""
    template = Template("{% load webmention_tags %}{% webmention_count None %}")
    rendered = template.render(Context()).strip()
    assert rendered == "0"

    template = Template('{% load webmention_tags %}{% webmention_count "" %}')
    rendered = template.render(Context()).strip()
    assert rendered == "0"


def test_webmention_count_template_comparison(target_url, webmentions):
    """Test that webmention_count returns consistent types for template comparisons."""
    template = Template("""
        {% load webmention_tags %}
        {% webmention_count target_url as count_var %}
        Direct output: {% webmention_count target_url %}
        Variable: {{ count_var }}
    """)
    context = Context({"target_url": target_url})
    rendered = template.render(context).strip()

    assert "Direct output: 4" in rendered
    assert "Variable: 4" in rendered

    template = Template("{% load webmention_tags %}{% webmention_count target_url %}")
    direct_output = template.render(context).strip()
    assert isinstance(direct_output, str)
    assert direct_output == "4"

    template = Template("{% load webmention_tags %}{% webmention_count target_url as count %}")
    template.render(context)
    assert isinstance(context["count"], int)
    assert context["count"] == 4


def test_webmention_count_returns_int(target_url, webmentions):
    """Test that webmention_count should always return an integer for consistency."""
    context = Context({"target_url": target_url})

    template = Template("{% load webmention_tags %}{% webmention_count target_url %}")
    rendered = template.render(context).strip()

    assert rendered == "4"

    template_as_var = Template("{% load webmention_tags %}{% webmention_count target_url as count %}{{ count|add:0 }}")
    rendered_as_var = template_as_var.render(context).strip()

    assert rendered_as_var == "4"
