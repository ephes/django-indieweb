"""Tests for webmention template tags."""

from django.template import Context, Template
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from indieweb.models import Webmention


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
        template = Template("{% load webmention_tags %}{% show_webmentions target_url %}")
        context = Context({"target_url": self.target_url})
        rendered = template.render(context)

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
        template = Template("{% load webmention_tags %}{% show_webmentions target_url %}")
        context = Context({"target_url": "https://example.com/no-mentions/"})
        rendered = template.render(context)

        # Should render empty or with a no mentions message
        self.assertIn("webmentions", rendered)  # Container should still exist

    def test_show_webmentions_by_type(self):
        """Test show_webmentions filtering by type."""
        template = Template('{% load webmention_tags %}{% show_webmentions target_url "like" %}')
        context = Context({"target_url": self.target_url})
        rendered = template.render(context)

        # Should only show likes
        self.assertIn("Alice", rendered)
        self.assertNotIn("Bob", rendered)
        self.assertNotIn("Charlie", rendered)
        self.assertNotIn("News Site", rendered)

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
