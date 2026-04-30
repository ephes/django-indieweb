"""Tests for webmention template tags."""

from datetime import timedelta

from django.template import Context, Template
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from indieweb.models import Webmention, WebmentionNestedResponse


class WebmentionTemplateTagsTestCase(TestCase):
    """Test webmention template tags."""

    def setUp(self):
        """Set up test data."""
        self.target_url = "https://example.com/post/1/"

        # Create various types of webmentions
        self.like = Webmention.objects.create(
            source_url="https://social.example/likes/123",
            target_url=self.target_url,
            mention_type="like",
            author_name="Alice",
            author_url="https://alice.example",
            author_photo="https://alice.example/photo.jpg",
            content_html="Alice liked this",
            published=timezone.now(),
            status="verified",
        )

        self.reply = Webmention.objects.create(
            source_url="https://blog.example/reply-post",
            target_url=self.target_url,
            mention_type="reply",
            author_name="Bob",
            author_url="https://bob.example",
            content="This is a great post!",
            content_html="<p>This is a great post!</p>",
            published=timezone.now(),
            status="verified",
        )

        self.repost = Webmention.objects.create(
            source_url="https://micro.blog/repost/456",
            target_url=self.target_url,
            mention_type="repost",
            author_name="Charlie",
            author_url="https://charlie.example",
            author_photo="https://charlie.example/avatar.png",
            published=timezone.now(),
            status="verified",
        )

        self.mention = Webmention.objects.create(
            source_url="https://news.example/article",
            target_url=self.target_url,
            mention_type="mention",
            author_name="News Site",
            author_url="https://news.example",
            content="As mentioned in example.com...",
            published=timezone.now(),
            status="verified",
        )

        # Create spam and pending webmentions (should not show)
        self.spam = Webmention.objects.create(
            source_url="https://spam.example/post", target_url=self.target_url, mention_type="reply", status="spam"
        )

        self.pending = Webmention.objects.create(
            source_url="https://unverified.example/post",
            target_url=self.target_url,
            mention_type="like",
            status="pending",
        )

    def render_webmentions(self, target_url=None, mention_type=None):
        """Render the webmentions inclusion tag for tests."""
        target_url = target_url or self.target_url
        if mention_type:
            template = Template("{% load webmention_tags %}{% show_webmentions target_url mention_type %}")
            return template.render(Context({"target_url": target_url, "mention_type": mention_type}))

        template = Template("{% load webmention_tags %}{% show_webmentions target_url %}")
        return template.render(Context({"target_url": target_url}))

    def create_nested_response(self, webmention, identity, **kwargs):
        """Create a verified nested response for template rendering tests."""
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

    def test_webmention_endpoint_link_tag(self):
        """Test the webmention_endpoint_link tag."""
        template = Template("{% load webmention_tags %}{% webmention_endpoint_link %}")
        rendered = template.render(Context())

        # Should render a link tag with the webmention endpoint
        self.assertIn('<link rel="webmention"', rendered)
        self.assertIn('href="', rendered)
        self.assertIn(reverse("indieweb:webmention"), rendered)

    def test_webmention_endpoint_link_with_custom_endpoint(self):
        """Test the webmention_endpoint_link tag with a custom endpoint."""
        template = Template(
            '{% load webmention_tags %}{% webmention_endpoint_link "https://custom.endpoint/webmention" %}'
        )
        rendered = template.render(Context())

        self.assertIn('<link rel="webmention"', rendered)
        self.assertIn('href="https://custom.endpoint/webmention"', rendered)

    def test_show_webmentions_tag(self):
        """Test the show_webmentions tag."""
        rendered = self.render_webmentions()

        # Should show approved and verified webmentions
        self.assertIn("Alice", rendered)
        self.assertIn("Bob", rendered)
        self.assertIn("Charlie", rendered)
        self.assertIn("News Site", rendered)

        # Should not show spam or pending
        self.assertNotIn("spam.example", rendered)
        self.assertNotIn("unverified.example", rendered)

        # Should have proper microformats2 classes
        self.assertIn("h-cite", rendered)
        self.assertIn("p-author", rendered)
        self.assertIn("u-url", rendered)

    def test_show_webmentions_empty(self):
        """Test show_webmentions with no webmentions."""
        rendered = self.render_webmentions("https://example.com/no-mentions/")

        # Should render empty or with a no mentions message
        self.assertIn("webmentions", rendered)  # Container should still exist

    def test_show_webmentions_by_type(self):
        """Test show_webmentions filtering by type."""
        rendered = self.render_webmentions(mention_type="like")

        # Should only show likes
        self.assertIn("Alice", rendered)
        self.assertNotIn("Bob", rendered)
        self.assertNotIn("Charlie", rendered)
        self.assertNotIn("News Site", rendered)

    def test_verified_nested_response_renders_under_verified_parent_reply(self):
        """Verified child rows render inline below their verified parent reply."""
        self.create_nested_response(
            self.reply,
            "https://comments.example/reply/1",
            author_name="Nested Carol",
            content="Nested reply body",
            content_html="<p>Nested reply body</p>",
        )

        rendered = self.render_webmentions()

        self.assertIn('class="webmention-nested-responses"', rendered)
        self.assertIn("Nested Carol", rendered)
        self.assertIn("Nested reply body", rendered)
        self.assertLess(rendered.index("This is a great post!"), rendered.index("Nested reply body"))

    def test_verified_nested_response_does_not_render_under_non_verified_parent(self):
        """A verified child is hidden when the parent Webmention is not verified."""
        for status in ("failed", "spam", "pending"):
            with self.subTest(status=status):
                parent = Webmention.objects.create(
                    source_url=f"https://parent.example/{status}",
                    target_url=self.target_url,
                    mention_type="reply",
                    content=f"Parent {status}",
                    status=status,
                )
                self.create_nested_response(
                    parent,
                    f"https://comments.example/{status}",
                    content=f"Child under {status}",
                    content_html=f"<p>Child under {status}</p>",
                )

        rendered = self.render_webmentions()

        self.assertNotIn("Child under failed", rendered)
        self.assertNotIn("Child under spam", rendered)
        self.assertNotIn("Child under pending", rendered)

    def test_non_verified_nested_response_does_not_render(self):
        """Only verified child rows render inline."""
        self.create_nested_response(
            self.reply,
            "https://comments.example/missing",
            status="missing",
            content="Missing child content",
            content_html="<p>Missing child content</p>",
        )

        rendered = self.render_webmentions()

        self.assertNotIn("Missing child content", rendered)

    def test_direct_top_level_webmention_suppresses_duplicate_nested_response(self):
        """A direct verified Webmention to the target wins over an inline child copy."""
        self.create_nested_response(
            self.reply,
            "https://comments.example/direct-reply",
            response_url="https://comments.example/direct-reply",
            author_name="Inline Duplicate",
            content="Inline duplicate content",
            content_html="<p>Inline duplicate content</p>",
        )
        Webmention.objects.create(
            source_url="https://comments.example/direct-reply",
            target_url=self.target_url,
            mention_type="reply",
            author_name="Direct Reply",
            content="Direct top-level content",
            content_html="<p>Direct top-level content</p>",
            published=timezone.now() + timedelta(minutes=1),
            status="verified",
        )

        rendered = self.render_webmentions()

        self.assertIn("Direct Reply", rendered)
        self.assertIn("Direct top-level content", rendered)
        self.assertNotIn("Inline Duplicate", rendered)
        self.assertNotIn("Inline duplicate content", rendered)

    def test_direct_top_level_suppression_ignores_current_type_filter(self):
        """A filtered-out direct top-level Webmention still suppresses a duplicate child."""
        self.create_nested_response(
            self.reply,
            "https://comments.example/direct-like",
            response_url="https://comments.example/direct-like",
            author_name="Filtered Inline Duplicate",
            content="Filtered inline duplicate content",
            content_html="<p>Filtered inline duplicate content</p>",
        )
        Webmention.objects.create(
            source_url="https://comments.example/direct-like",
            target_url=self.target_url,
            mention_type="like",
            author_name="Direct Like",
            published=timezone.now() + timedelta(minutes=1),
            status="verified",
        )

        rendered = self.render_webmentions(mention_type="reply")

        self.assertIn("Bob", rendered)
        self.assertNotIn("Direct Like", rendered)
        self.assertNotIn("Filtered Inline Duplicate", rendered)
        self.assertNotIn("Filtered inline duplicate content", rendered)

    def test_duplicate_nested_identity_renders_once_under_first_displayed_parent(self):
        """The first parent in top-level ordering owns a duplicated nested child."""
        now = timezone.now()
        older_parent = Webmention.objects.create(
            source_url="https://blog.example/older-parent",
            target_url=self.target_url,
            mention_type="reply",
            author_name="Older Parent",
            content="Older parent content",
            published=now - timedelta(days=2),
            status="verified",
        )
        newer_parent = Webmention.objects.create(
            source_url="https://blog.example/newer-parent",
            target_url=self.target_url,
            mention_type="reply",
            author_name="Newer Parent",
            content="Newer parent content",
            published=now + timedelta(days=2),
            status="verified",
        )
        shared_identity = "https://comments.example/shared"
        self.create_nested_response(
            older_parent,
            shared_identity,
            content="Child via older parent",
            content_html="<p>Child via older parent</p>",
        )
        self.create_nested_response(
            newer_parent,
            shared_identity,
            content="Child via newer parent",
            content_html="<p>Child via newer parent</p>",
        )

        rendered = self.render_webmentions()

        self.assertIn("Child via newer parent", rendered)
        self.assertNotIn("Child via older parent", rendered)
        self.assertLess(rendered.index("Newer parent content"), rendered.index("Child via newer parent"))

    def test_nested_responses_are_ordered_by_published_or_first_seen(self):
        """Children render newest first using published, falling back to first_seen_at."""
        now = timezone.now()
        self.create_nested_response(
            self.reply,
            "https://comments.example/older",
            content="Older published child",
            content_html="<p>Older published child</p>",
            published=now - timedelta(days=2),
            first_seen_at=now,
        )
        self.create_nested_response(
            self.reply,
            "https://comments.example/fallback",
            content="Fallback first-seen child",
            content_html="<p>Fallback first-seen child</p>",
            published=None,
            first_seen_at=now - timedelta(days=1),
        )
        self.create_nested_response(
            self.reply,
            "https://comments.example/newer",
            content="Newer published child",
            content_html="<p>Newer published child</p>",
            published=now,
            first_seen_at=now - timedelta(days=3),
        )

        rendered = self.render_webmentions()

        self.assertLess(rendered.index("Newer published child"), rendered.index("Fallback first-seen child"))
        self.assertLess(rendered.index("Fallback first-seen child"), rendered.index("Older published child"))

    def test_show_webmentions_type_filter_still_filters_top_level_parents(self):
        """Filtering top-level Webmentions by type does not leak nested replies."""
        self.create_nested_response(
            self.reply,
            "https://comments.example/reply-filter",
            content="Nested reply for filtered parent",
            content_html="<p>Nested reply for filtered parent</p>",
        )

        rendered = self.render_webmentions(mention_type="like")

        self.assertIn("Alice", rendered)
        self.assertNotIn("Bob", rendered)
        self.assertNotIn("Nested reply for filtered parent", rendered)

    def test_webmention_count_does_not_include_nested_responses(self):
        """webmention_count keeps its top-level-only count semantics."""
        self.create_nested_response(self.reply, "https://comments.example/count-one")
        self.create_nested_response(self.reply, "https://comments.example/count-two")

        template = Template("{% load webmention_tags %}{% webmention_count target_url %}")
        rendered = template.render(Context({"target_url": self.target_url})).strip()

        self.assertEqual(rendered, "4")

    def test_show_webmentions_prefetches_nested_responses(self):
        """Rendering does not issue one query per parent or child."""
        self.create_nested_response(self.reply, "https://comments.example/query-one")
        self.create_nested_response(self.reply, "https://comments.example/query-two")

        with self.assertNumQueries(2):
            self.render_webmentions()

    def test_webmention_count_tag(self):
        """Test the webmention_count tag."""
        template = Template("{% load webmention_tags %}{% webmention_count target_url %}")
        context = Context({"target_url": self.target_url})
        rendered = template.render(context).strip()

        # Should count only verified status
        self.assertEqual(rendered, "4")

    def test_webmention_count_by_type(self):
        """Test webmention_count filtering by type."""
        template = Template('{% load webmention_tags %}{% webmention_count target_url "reply" %}')
        context = Context({"target_url": self.target_url})
        rendered = template.render(context).strip()

        self.assertEqual(rendered, "1")

    def test_webmention_count_zero(self):
        """Test webmention_count with no mentions."""
        template = Template("{% load webmention_tags %}{% webmention_count target_url %}")
        context = Context({"target_url": "https://example.com/no-mentions/"})
        rendered = template.render(context).strip()

        self.assertEqual(rendered, "0")

    def test_webmention_count_as_variable(self):
        """Test storing webmention_count in a variable."""
        template = Template(
            "{% load webmention_tags %}{% webmention_count target_url as count %}{{ count }} webmentions"
        )
        context = Context({"target_url": self.target_url})
        rendered = template.render(context).strip()

        self.assertEqual(rendered, "4 webmentions")

    def test_like_template_rendering(self):
        """Test that likes use the correct template."""
        template = Template("{% load webmention_tags %}{% show_webmentions target_url %}")
        context = Context({"target_url": self.target_url})
        rendered = template.render(context)

        # Check for like-specific markup
        self.assertIn('class="p-like', rendered)
        self.assertIn("liked", rendered.lower())

    def test_reply_template_rendering(self):
        """Test that replies use the correct template."""
        template = Template("{% load webmention_tags %}{% show_webmentions target_url %}")
        context = Context({"target_url": self.target_url})
        rendered = template.render(context)

        # Check for reply-specific markup and content
        self.assertIn('class="p-comment', rendered)
        self.assertIn("This is a great post!", rendered)
        self.assertIn("e-content", rendered)

    def test_repost_template_rendering(self):
        """Test that reposts use the correct template."""
        template = Template("{% load webmention_tags %}{% show_webmentions target_url %}")
        context = Context({"target_url": self.target_url})
        rendered = template.render(context)

        # Check for repost-specific markup
        self.assertIn('class="p-repost', rendered)
        self.assertIn("reposted", rendered.lower())

    def test_mention_template_rendering(self):
        """Test that generic mentions use the correct template."""
        template = Template("{% load webmention_tags %}{% show_webmentions target_url %}")
        context = Context({"target_url": self.target_url})
        rendered = template.render(context)

        # Check for mention-specific markup
        self.assertIn("As mentioned in example.com", rendered)

    @override_settings(DEBUG=True)
    def test_template_tag_errors(self):
        """Test error handling in template tags."""
        # Test with None URL
        template = Template("{% load webmention_tags %}{% webmention_count None %}")
        rendered = template.render(Context()).strip()
        self.assertEqual(rendered, "0")

        # Test with empty string
        template = Template('{% load webmention_tags %}{% webmention_count "" %}')
        rendered = template.render(Context()).strip()
        self.assertEqual(rendered, "0")

    def test_webmention_count_template_comparison(self):
        """Test that webmention_count returns consistent types for template comparisons."""
        # Test that webmention_count without as_var returns a string that can't be compared numerically
        # This test demonstrates the bug

        # First, show that the tag outputs correctly
        template = Template("""
            {% load webmention_tags %}
            {% webmention_count target_url as count_var %}
            Direct output: {% webmention_count target_url %}
            Variable: {{ count_var }}
        """)
        context = Context({"target_url": self.target_url})
        rendered = template.render(context).strip()

        # Both should show the same value
        self.assertIn("Direct output: 4", rendered)
        self.assertIn("Variable: 4", rendered)

        # Now test that direct output returns string "4" while as_var returns int 4
        template = Template("{% load webmention_tags %}{% webmention_count target_url %}")
        direct_output = template.render(context).strip()
        self.assertIsInstance(direct_output, str)
        self.assertEqual(direct_output, "4")

        # Test with as_var - need to check the actual context variable
        template = Template("{% load webmention_tags %}{% webmention_count target_url as count %}")
        template.render(context)
        self.assertIsInstance(context["count"], int)
        self.assertEqual(context["count"], 4)

    def test_webmention_count_returns_int(self):
        """Test that webmention_count should always return an integer for consistency."""
        context = Context({"target_url": self.target_url})

        # Test via template rendering to ensure integer is returned
        template = Template("{% load webmention_tags %}{% webmention_count target_url %}")
        rendered = template.render(context).strip()

        # The rendered output should be "4" (string representation of int)
        self.assertEqual(rendered, "4")

        # Test with as_var to ensure the variable is an integer
        template_as_var = Template(
            "{% load webmention_tags %}{% webmention_count target_url as count %}{{ count|add:0 }}"
        )
        rendered_as_var = template_as_var.render(context).strip()

        # The |add:0 filter will work correctly only if count is an integer
        self.assertEqual(rendered_as_var, "4")
