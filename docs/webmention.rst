===========
Webmentions
===========

Webmention is a W3C recommendation that enables cross-site conversations. When you link to someone else's content, you can send them a webmention to notify them. Similarly, when others link to your content, they can send you webmentions that you can display as comments, likes, or reposts.

Features
========

* **Receiving webmentions**: Accept and validate incoming webmentions
* **Sending webmentions**: Automatically discover and notify linked sites
* **Microformats2 parsing**: Extract semantic content from webmentions
* **Spam protection**: Pluggable spam checker interface
* **Display templates**: Show webmentions as comments, likes, and reposts
* **Management commands**: Send webmentions from the command line

Quick Start
===========

1. Add the webmention endpoint to your base template:

.. code-block:: django

    {% load webmention_tags %}
    <head>
        {% webmention_endpoint_link %}
    </head>

2. Display webmentions on your pages:

.. code-block:: django

    {% load webmention_tags %}

    {% show_webmentions request.build_absolute_uri %}

3. Send webmentions when you publish content:

.. code-block:: bash

    python manage.py send_webmentions https://mysite.com/new-post/

Configuration
=============

Add these settings to your Django settings:

.. code-block:: python

    # Required: URL resolver to map URLs to content objects
    INDIEWEB_URL_RESOLVER = 'myproject.webmention_config.MyURLResolver'

    # Required: Spam checker (use default or implement your own)
    INDIEWEB_SPAM_CHECKER = 'indieweb.interfaces.NoOpSpamChecker'

    # Optional: Comment adapter to convert webmentions to comments
    INDIEWEB_COMMENT_ADAPTER = 'myproject.webmention_config.MyCommentAdapter'

Implementing URL Resolution
===========================

Create a URL resolver to map target URLs to your content objects:

.. code-block:: python

    # myproject/webmention_config.py
    from indieweb.interfaces import URLResolver
    from myapp.models import BlogPost
    from urllib.parse import urlparse

    class MyURLResolver(URLResolver):
        def resolve(self, target_url: str) -> Any | None:
            """Resolve a URL to a content object."""
            parsed = urlparse(target_url)
            path = parsed.path

            # Example: match /blog/post-slug/
            if path.startswith('/blog/'):
                slug = path.strip('/').split('/')[-1]
                try:
                    return BlogPost.objects.get(slug=slug)
                except BlogPost.DoesNotExist:
                    pass

            return None

        def get_absolute_url(self, content_object: Any) -> str:
            """Get the absolute URL for a content object."""
            if hasattr(content_object, 'get_absolute_url'):
                return content_object.get_absolute_url()
            return ''

Implementing Spam Protection
============================

Create a custom spam checker:

.. code-block:: python

    from indieweb.interfaces import SpamChecker
    from indieweb.models import Webmention

    class MySpamChecker(SpamChecker):
        def check(self, webmention: Webmention) -> dict[str, Any]:
            """Check if a webmention is spam."""
            # Implement your spam detection logic
            spam_keywords = ['casino', 'viagra', 'lottery']
            content_lower = webmention.content.lower()

            is_spam = any(kw in content_lower for kw in spam_keywords)

            return {
                'is_spam': is_spam,
                'confidence': 0.9 if is_spam else 0.1,
                'details': 'Keyword-based detection'
            }

Template Usage
==============

Basic Usage
-----------

.. code-block:: django

    {% load webmention_tags %}

    {# Add endpoint discovery to your base template #}
    {% webmention_endpoint_link %}

    {# Show all webmentions for current page #}
    {% show_webmentions request.build_absolute_uri %}

    {# Show only replies #}
    {% show_webmentions request.build_absolute_uri mention_type="reply" %}

    {# Get webmention count #}
    {% webmention_count request.build_absolute_uri as count %}
    <p>This post has {{ count }} responses.</p>

Custom Templates
----------------

You can override the default templates by creating your own:

* ``indieweb/webmentions.html`` - Main container
* ``indieweb/webmention_types/like.html`` - Like template
* ``indieweb/webmention_types/reply.html`` - Reply template
* ``indieweb/webmention_types/repost.html`` - Repost template
* ``indieweb/webmention_types/mention.html`` - Generic mention template

Management Commands
===================

send_webmentions
----------------

Send webmentions for all links in a post:

.. code-block:: bash

    # Send webmentions for a URL
    python manage.py send_webmentions https://mysite.com/new-post/

    # Provide content directly
    python manage.py send_webmentions https://mysite.com/new-post/ \
        --content '<p>Check out <a href="https://example.com">this site</a>!</p>'

    # Dry run to see what would be sent
    python manage.py send_webmentions https://mysite.com/new-post/ --dry-run

Signals
=======

The ``webmention_received`` signal is sent when a webmention is processed:

.. code-block:: python

    from django.dispatch import receiver
    from indieweb.signals import webmention_received

    @receiver(webmention_received)
    def handle_webmention(sender, webmention, created, **kwargs):
        if created and webmention.status == 'verified':
            # Send notification, update cache, etc.
            print(f"New webmention from {webmention.source_url}")

Models
======

The ``Webmention`` model stores all webmention data:

.. code-block:: python

    from indieweb.models import Webmention

    # Get all verified webmentions for a URL
    webmentions = Webmention.objects.filter(
        target_url='https://mysite.com/post/',
        status='verified'
    )

    # Get webmentions by type
    likes = webmentions.filter(mention_type='like')
    replies = webmentions.filter(mention_type='reply')

Fields:

* ``source_url`` - The URL that links to your content
* ``target_url`` - Your URL that was linked to
* ``status`` - pending, verified, failed, or spam
* ``mention_type`` - mention, like, reply, or repost
* ``author_name``, ``author_url``, ``author_photo`` - Author info
* ``content``, ``content_html`` - The mention content
* ``published`` - When the mention was published
* ``created``, ``modified`` - Timestamps
* ``verified_at`` - When the mention was verified
* ``spam_check_result`` - JSON field with spam check details

Testing Webmentions
===================

You can test your webmention implementation using webmention.rocks:

1. Visit https://webmention.rocks/
2. Follow the test suite to verify your implementation
3. Use the discovery tests to check endpoint detection
4. Use the receiving tests to verify your endpoint

Troubleshooting
===============

Common issues and solutions:

**Webmentions not being received**
  - Check that your webmention endpoint is discoverable
  - Verify the endpoint URL is correct in your Link header/tag
  - Check Django logs for any errors

**Target URL validation failing**
  - Ensure ``django.contrib.sites`` is configured correctly
  - Check that the Site domain matches your production domain

**Microformats not being parsed**
  - Verify the source page has proper microformats2 markup
  - Use a validator like https://indiewebify.me/

**Spam checker rejecting valid webmentions**
  - Review your spam checker implementation
  - Check the ``spam_check_result`` field for details

API Reference
=============

See :doc:`api` for detailed API documentation of all webmention-related classes and functions.
