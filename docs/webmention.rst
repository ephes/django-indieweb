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

    # Optional: Queue incoming Webmention processing outside the request path
    INDIEWEB_WEBMENTION_ENQUEUE = 'myproject.webmention_config.enqueue_webmention'

    # Optional: Verify submitted Vouch URLs from approved voucher domains
    INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS = ('trusted.example',)

    # Optional: Use custom receiver-side Vouch trust logic
    INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY = 'myproject.webmention_config.trust_vouch'

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

Receiving and Queued Processing
===============================

By default, ``POST /indieweb/webmention/`` preserves the historical synchronous
behavior: after validating ``source`` and ``target``, it calls
``WebmentionProcessor.process_webmention()`` in the request path and returns
``201 Created`` with a ``Location`` header pointing to the status endpoint.

For production deployments that use a task queue, set
``INDIEWEB_WEBMENTION_ENQUEUE`` to a dotted path for a callable with this
contract:

.. code-block:: python

    def enqueue_webmention(webmention_id: int) -> None:
        ...

When this setting is configured, the receive endpoint still performs the
normal form validation, URL validation, and configured Django ``Site`` domain
check before any persistence or enqueueing happens. For a valid request, it
creates or reuses the ``Webmention`` row for the submitted ``source`` and
``target`` pair, calls the configured enqueue hook with that row's primary key,
and returns ``202 Accepted`` with a ``Location`` header pointing to
``/indieweb/webmention/<pk>/``. The request path does not fetch the source URL,
parse microformats2, run spam checks, or send ``webmention_received``; those
steps remain owned by ``WebmentionProcessor`` in the worker process.

Queue integrations should call ``process_queued_webmention()`` from the worker:

.. code-block:: python

    # myproject/webmention_config.py
    from myproject.tasks import process_webmention_task

    def enqueue_webmention(webmention_id: int) -> None:
        process_webmention_task.delay(webmention_id)

.. code-block:: python

    # myproject/tasks.py
    from indieweb.processors import process_queued_webmention

    def process_webmention_task(webmention_id: int) -> None:
        process_queued_webmention(webmention_id)

``process_queued_webmention(webmention_id)`` loads the existing row and calls
``WebmentionProcessor().process_webmention(webmention.source_url,
webmention.target_url)``. If the row no longer exists, Django raises
``Webmention.DoesNotExist`` so the queue's retry or failure policy can decide
what to do.

If ``INDIEWEB_WEBMENTION_ENQUEUE`` cannot be imported, is not callable, or the
callable raises, the receive endpoint returns HTTP ``500`` and does not fall
back to inline processing. This fail-closed behavior avoids claiming a
Webmention was queued when processing cannot be scheduled. Missing parameters,
malformed URLs, JSON bodies, and targets outside the configured ``Site`` domain
still return HTTP ``400`` before the enqueue hook is loaded or called.
Import and non-callable configuration failures happen before a row is persisted.
If the callable itself raises, the ``Webmention`` row has already been created
or reused and remains ``pending``; operators should rely on their queue retry
path or manual cleanup to reconcile those rows.

Vouch Support
=============

Vouch is a backwards-compatible Webmention extension for spam and moderation
signals. A sender may include an optional third form parameter, ``vouch``,
whose value is an ``http`` or ``https`` URL on a site the receiver trusts. The
voucher page should link to the source page's domain.

django-indieweb accepts ``vouch`` on incoming Webmention POSTs, validates it as
a URL when present, stores it on ``Webmention.vouch_url``, and exposes it from
the status endpoint. Missing ``vouch`` values do not affect ordinary
Webmentions unless ``INDIEWEB_WEBMENTION_VOUCH_REQUIRED`` is enabled.

Queued receiving preserves the async boundary: the request path validates and
stores the optional ``vouch`` URL, calls the configured enqueue hook, and
returns ``202`` without fetching the source or voucher URL. Voucher fetching
and verification happen only in ``WebmentionProcessor`` or the worker helper
that calls it.

By default, submitted Vouch URLs are stored but not enforced. To verify
submitted vouchers with the built-in domain allowlist policy, configure
``INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS``:

.. code-block:: python

    INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS = ("trusted.example", "events.example")

When verification is enabled and a Webmention includes ``vouch``,
django-indieweb checks that the submitted voucher URL is on the configured
Django ``Site`` domain or one of the trusted domains, fetches the voucher URL
with the same bounded redirect policy used for Webmention source fetches,
requires the final voucher URL to remain on a trusted domain, requires an HTTP
``200`` ``text/html`` response, and verifies that the voucher page contains an
HTTP(S) HTML ``href`` whose domain matches the source URL's domain. A failed
Vouch check marks the Webmention ``failed`` without clearing previously parsed
fields.

For deployments that need a richer receiver-side trust model, configure
``INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY`` with a dotted path to a callable:

.. code-block:: python

    def trust_vouch(
        *,
        webmention,
        source_url: str,
        target_url: str,
        vouch_url: str,
        final_vouch_url: str | None = None,
    ) -> bool:
        ...

When a policy is configured, it owns Vouch URL trust decisions and the domain
allowlist is not applied by django-indieweb. The processor calls the policy
before fetching the voucher with ``final_vouch_url=None`` and again after
allowed redirects with ``final_vouch_url`` set to the final URL; both calls
must return a truthy value. Import failures, non-callable policy values, and
policy exceptions fail closed. The policy is evaluated only in
``WebmentionProcessor`` or queued worker paths, never in the async receive
request path.

Set ``INDIEWEB_WEBMENTION_VOUCH_REQUIRED = True`` to require a verifiable
voucher for incoming Webmentions. When this is enabled, a Webmention with no
stored ``vouch`` is marked ``failed`` by the processor. The endpoint still
validates and queues quickly; required-mode failures happen in processor-owned
logic. If required mode is enabled without a trust policy or trusted domains,
submitted vouchers fail closed; most deployments should configure one of those
trust sources before requiring Vouch.

Outgoing Webmentions can include Vouch metadata explicitly:

.. code-block:: python

    from indieweb.senders import WebmentionSender

    sender = WebmentionSender()
    sender.send_webmention(
        "https://mysite.com/post",
        "https://example.com/article",
        "https://example.com/webmention",
        vouch="https://trusted.example/vouch-for-mysite",
    )

The ``send_webmentions`` management command also accepts ``--vouch`` to include
the same voucher URL with each delivered Webmention.

Salmention Support Status
=========================

Salmention is a Webmention extension for propagating downstream replies and
other interactions upstream. For example, if Bob replies to Alice and later
displays Carol's reply to Bob, Bob's site can resend a Webmention to Alice so
Alice can re-check Bob's page and display Carol's nested response.

django-indieweb does not currently implement Salmention sending or receiving
beyond ordinary Webmention behavior. Duplicate Webmention submissions for the
same ``source``/``target`` pair are supported and reprocess the existing
``Webmention`` row, but they do not store source-page snapshots, compare
previous and current nested ``h-entry`` structures, create child response
records, or render nested responses inline on the original target. That means a
re-received Webmention is treated as normal Webmention reprocessing, not as a
Salmention-specific nested-response update.

Receiving Salmentions requires persistence that this package does not yet own:
the fetched source contents must be stored in a form that can be compared on a
later duplicate receive, newly nested responses inside the source ``h-entry``
must be identified, and those nested responses need display/query semantics
separate from the flattened ``Webmention`` row currently used for one
source/target pair.

Sending Salmentions also needs application-level state that is not currently
tracked here. The protocol expects a site to resend Webmentions to everything
the original post previously sent Webmentions to after a newly received
response has been incorporated into that original post's permalink. The current
``WebmentionSender`` can explicitly send Webmentions for links found in a source
page, and ``send_webmentions`` can be run again after a page changes, but
django-indieweb does not record the prior outbound target set for each original
post or know when an application has updated a rendered permalink with a newly
accepted response.

No Salmention setting is available. Future support needs explicit design for
source snapshot persistence, nested response storage/display, outbound target
tracking, and an operator- or application-driven resend workflow.

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

    # Include a Vouch URL
    python manage.py send_webmentions https://mysite.com/new-post/ \
        --vouch https://trusted.example/vouch-for-mysite

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
* ``vouch_url`` - Optional Vouch URL submitted with the Webmention
* ``status`` - pending, verified, failed, or spam
* ``mention_type`` - mention, like, reply, or repost
* ``author_name``, ``author_url``, ``author_photo`` - Author info
* ``content``, ``content_html`` - The mention content
* ``published`` - When the mention was published
* ``created``, ``modified`` - Timestamps
* ``verified_at`` - When the mention was verified
* ``vouch_verified_at`` - When the configured Vouch check succeeded
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
  - Ensure the source page includes a same-page h-card whose ``u-url`` matches
    the referenced URL under the canonical matching policy above; name and
    photo properties are used when present
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
