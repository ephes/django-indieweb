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

Target URL Matching
===================

When receiving a Webmention, django-indieweb fetches the source page and
verifies that it links to the submitted ``target`` URL before marking the
Webmention as verified. Target verification parses HTML ``href`` attributes
from the source page and compares them with a conservative canonical URL
matching policy. The stored ``Webmention.source_url`` and
``Webmention.target_url`` remain the submitted values; canonicalization is
used only while matching.

The same matching policy is also used when parsing microformats2 target
properties such as ``u-in-reply-to``, ``u-like-of``, and ``u-repost-of``, so
reply/like/repost classification still works when the source page uses a
common URL variant.

Supported matching variants:

* URL fragments are ignored, so ``https://mysite.com/post#comments`` matches
  ``https://mysite.com/post``.
* URL scheme and host case are ignored, while path case remains significant.
* A leading ``www.`` hostname is treated as equivalent to the bare hostname.
* One trailing slash on non-root paths is treated as equivalent.
* Query parameters are compared independent of order. Duplicate query
  key/value pairs are preserved and must still match.

The receiver does not resolve relative source links during target verification,
does not follow redirects as part of this matching step, and does not broaden
endpoint domain validation. The submitted ``target`` must still pass the
Webmention endpoint's domain check before processing begins. Userinfo and
explicit ports, if present, must match exactly; default ports are not
normalized away.

HTTP Redirects
==============

django-indieweb follows HTTP redirects explicitly for Webmention network
requests. Redirect handling is bounded to 5 redirects per request and only
continues to ``http`` and ``https`` URLs. Redirect chains that exceed the
limit, redirect to another scheme, loop until the limit is reached, or raise a
network/client error are treated as request failures.

Receive-side source fetches follow redirects before validating the source
document. The submitted ``Webmention.source_url`` and ``Webmention.target_url``
are preserved exactly as submitted, but the final fetched source URL is used as
the microformats2 parsing base URL. This means relative author and photo URLs
from a redirected source page resolve against the page that actually returned
the HTML.

After redirects, the receive-side source response must still be HTTP ``200``
with a ``text/html`` content type and must link to the submitted target under
the target matching policy above. A final ``410 Gone``, non-``200`` response,
non-HTML response, missing target link, unsupported redirect, or excessive
redirect chain marks the Webmention ``failed`` through the same failed-state
path described below.

Send-side endpoint discovery follows redirects for both the initial ``HEAD``
request and the fallback ``GET`` request. Relative Webmention endpoints found
in ``Link`` headers or HTML ``<link rel="webmention">`` / ``<a
rel="webmention">`` elements are resolved against the final target page URL
after redirects, not the originally requested URL.

When sending outgoing Webmentions, source-content fetches also follow the same
bounded redirect policy. Endpoint delivery ``POST`` requests follow redirects
with the original ``POST`` method and ``source``/``target`` form payload
preserved for every followed redirect status (``301``, ``302``, ``303``,
``307``, and ``308``). The final endpoint response is considered successful
only when it returns HTTP ``200``, ``201``, or ``202``; redirect errors return
the existing ``{"success": False, ...}`` result shape.

Authorship Extraction
=====================

When a received Webmention source page contains microformats2, django-indieweb
extracts author details for the selected ``h-entry`` with a local/same-page
authorship fallback chain:

* Explicit ``author`` data on the ``h-entry`` has priority. Nested ``h-card``
  author data is used directly, and URL-valued ``author`` references are
  resolved to matching ``h-card`` items already present in the fetched source
  document. Same-page author ``h-card`` URL matching uses the same
  conservative URL policy described in `Target URL Matching`_, so common
  variants such as fragments, scheme/host case, a leading ``www.``, one
  non-root trailing slash, and query-parameter ordering do not prevent a local
  h-card match.
* If the ``h-entry`` has no explicit author, ``rel=author`` links are resolved
  against the final fetched source URL and matched to ``h-card`` items already
  present in the same parsed document using that same conservative URL policy.
  Same-page fragment links such as ``href="#author"`` can match an ``h-card``
  with the corresponding HTML ``id``.
* If neither explicit author data nor ``rel=author`` yields an author, a single
  unambiguous page-level ``h-card`` outside the ``h-entry`` is used as a
  fallback author. If multiple page-level ``h-card`` items are present, no
  fallback author is guessed.
* If an explicit URL-valued author reference has no matching ``h-card``, the
  resolved author URL is stored as both the author URL and display name for
  backwards compatibility.

Relative author URLs and photo URLs resolve against the final fetched source
URL, not the originally submitted source URL when redirects occurred. If the
resulting author URL matches a local ``Profile`` URL on the configured Django
``Site`` domain, the local profile's name, URL, and photo override the parsed
source-page author fields.

django-indieweb does not fetch remote author pages during Webmention receiving.
``rel=author`` support is limited to author ``h-card`` data already available in
the fetched source document.

Reprocessing and Source Removal
===============================

Incoming Webmentions are keyed by the submitted ``source`` and ``target`` URLs.
When the same pair is processed again, django-indieweb updates the existing
``Webmention`` row rather than creating a duplicate.

If a previously verified source returns ``410 Gone`` during reprocessing, the
row is marked ``failed`` and ``verified_at`` is cleared. The submitted
``source_url`` and ``target_url`` are preserved, and previously parsed fields
such as author, content, HTML content, mention type, and published date are
left intact so applications can keep historical display or moderation context.

The same failed-state update is used when a source fetch succeeds with
``text/html`` but the source page no longer links to the submitted target. This
represents a removed Webmention: it is no longer considered currently verified,
but the stored parsed fields are not destructively cleared.

Other processing failures, including non-``200`` responses, non-HTML responses,
and fetch errors, also mark the Webmention ``failed`` and clear ``verified_at``.
Those failures are not treated as explicit source-removal signals in the
documentation because they may be transient. If the source later returns valid
HTML that links to the target again, reprocessing can mark the existing row
``verified`` and assign a fresh ``verified_at`` timestamp.

Spam reclassification also clears ``verified_at``. The source may still link to
the target, but a ``spam`` row is not advertised as currently verified, and
previously parsed author, content, published, and mention-type fields are
preserved.

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

**Author name shows as URL or profile picture is missing**
  - The source page may use URL references for author data (e.g., ``<data class="p-author" value="https://example.com/author"></data>``)
  - This is valid microformats2 markup following the authorship algorithm
  - Django-indieweb automatically looks for a matching h-card **on the same page** with the referenced URL
  - If the entry has no explicit author, same-page ``rel=author`` links and one unambiguous page-level h-card can also provide author data
  - Ensure the source page includes a separate h-card with matching URL, name, and photo properties
  - The h-card may be nested in structures like h-feeds - the parser searches recursively
  - Example services using this pattern: feed.city, some Mastodon webmention bridges
  - If no matching h-card is found, the URL will be displayed as the name (fallback behavior)
  - **Limitation**: Django-indieweb does not currently fetch remote author URLs; author data must be present in the fetched source document

**Spam checker rejecting valid webmentions**
  - Review your spam checker implementation
  - Check the ``spam_check_result`` field for details

API Reference
=============

See :doc:`api` for detailed API documentation of all webmention-related classes and functions.
