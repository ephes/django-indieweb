WebSub Support
==============

Overview
--------

django-indieweb provides publisher-side WebSub helpers for Django applications
that own their own feeds or topic resources. It also provides a minimal
subscriber callback implementation for host applications that want to receive
hub deliveries for external topics. It does not run a WebSub hub.

This shape fits reusable Django apps: your project decides which pages or feeds
are WebSub topics, renders those resources, and calls django-indieweb helpers to
advertise hub discovery links and notify hubs after content changes.

WebSub publisher flow
---------------------

1. Configure one or more hub URLs with ``INDIEWEB_WEBSUB_HUBS`` or pass hub URLs
   explicitly to the helper you call.
2. Add WebSub discovery links to each topic response:

   - one ``rel="hub"`` link for each hub
   - exactly one ``rel="self"`` link for the canonical topic URL

3. Notify each hub after the topic changes.

Discovery in Templates
----------------------

Load ``websub_tags`` and place the generated links in the HTML ``head`` of the
topic page or feed template:

.. code-block:: django

   {% load websub_tags %}
   {% websub_link_tags "https://example.com/feed/" %}

With ``INDIEWEB_WEBSUB_HUBS = ("https://hub.example/",)`` this renders:

.. code-block:: html

   <link rel="hub" href="https://hub.example/">
   <link rel="self" href="https://example.com/feed/">

You can also pass hubs explicitly:

.. code-block:: django

   {% load websub_tags %}
   {% websub_link_tags "https://example.com/feed/" "https://hub.example/" %}

If no hub is configured or passed, the tag raises ``ValueError``. That prevents
a template from silently rendering an invalid WebSub publisher advertisement.

Discovery in HTTP Headers
-------------------------

Use ``add_websub_link_header()`` when you control the view response:

.. code-block:: python

   from django.http import HttpResponse
   from indieweb.websub import add_websub_link_header

   def feed(request):
       topic_url = request.build_absolute_uri("/feed/")
       response = HttpResponse(render_feed(), content_type="application/atom+xml")
       add_websub_link_header(response, topic_url)
       return response

The helper appends to an existing ``Link`` header if one is already present.
Use ``websub_link_header(topic_url)`` if you need the combined header value
without mutating a response.

Notifying Hubs
--------------

Call ``notify_hubs(topic_url)`` after publishing, updating, or deleting content
that changes a topic:

.. code-block:: python

   from indieweb.websub import notify_hubs

   results = notify_hubs("https://example.com/feed/")
   for result in results:
       if not result.success:
           logger.warning("WebSub notification failed: %s", result)

The helper sends ``application/x-www-form-urlencoded`` POST requests with
``hub.mode=publish`` and ``hub.url=<topic_url>`` to each configured hub. This is
the publisher notification shape documented by the WebSub Recommendation for
existing public hubs.

``notify_hubs()`` returns one result per attempted hub. Network failures and
non-2xx hub responses are captured in the result instead of being raised, so
host applications can log, retry, or ignore individual failures without
crashing their publish workflow. Configuration and validation errors, such as
malformed topic or hub URLs, raise ``ValueError`` before any network request is
made.

When no hubs are configured or passed, ``notify_hubs()`` returns an empty list
without opening an HTTP client. If you inject a custom ``httpx.Client`` into
``notify_hubs()`` for testing or integration, that trusted client controls its
own redirect behavior; the package-created client uses ``follow_redirects=False``.

Management Command
------------------

You can notify hubs from a deployment hook, cron job, or manual operation:

.. code-block:: bash

   python manage.py notify_websub https://example.com/feed/

Pass hubs explicitly with repeated ``--hub`` options:

.. code-block:: bash

   python manage.py notify_websub https://example.com/feed/ \
       --hub https://hub.example/ \
       --hub https://backup.example/websub

The command exits with a Django ``CommandError`` for invalid URLs or when no
hub is configured. Individual hub failures are printed but do not abort
notification of later hubs.

Subscriber Flow
---------------

django-indieweb can keep host-level subscriber state in
``WebSubSubscription`` rows. A subscription is keyed by its hub URL, topic URL,
and an unguessable callback token. The callback endpoint is:

.. code-block:: text

   /indieweb/websub/<callback-token>/

Use ``request_websub_subscription()`` when your application explicitly decides
to subscribe or unsubscribe from a topic:

.. code-block:: python

   from indieweb.models import WebSubSubscription
   from indieweb.websub import request_websub_subscription

   result = request_websub_subscription(
       "https://source.example/feed",
       "https://hub.example/sub",
       callback_base_url="https://example.com/indieweb/websub",
       lease_seconds=86400,
       secret="shared-delivery-secret",
   )

   if result.success:
       # The hub accepted the request. It still needs to verify the callback.
       assert result.subscription.state == WebSubSubscription.STATE_PENDING_SUBSCRIBE

The helper sends WebSub-compatible form fields to the hub:
``hub.mode``, ``hub.callback``, ``hub.topic``, and optional
``hub.lease_seconds``/``hub.secret``. A ``2xx`` hub response records the
request and leaves the row pending until callback verification completes.
Network failures and non-``2xx`` responses are captured in the returned result
and on the subscription row.

Calling ``request_websub_subscription()`` for an already-active subscription is
a renewal request. The row stays ``active`` while verification is pending so
current deliveries remain accepted until the existing lease expires. If the
hub rejects a renewal request or the request fails, the row remains active and
keeps its current lease metadata. A stored ``hub.secret`` remains in effect
until the hub verifies the renewal. If you pass a new ``secret`` value, it is
staged and only replaces the current delivery secret after successful
``subscribe`` verification; rejected or failed renewal requests keep the
previously stored secret. Omit ``secret`` on renewal when you want to keep the
current delivery secret and clear any earlier unverified staged secret. Pass
``secret=""`` when you want the verified renewal to drop a stored secret and
accept unsigned deliveries.

Set ``mode=WebSubSubscription.MODE_UNSUBSCRIBE`` to ask the hub to cancel an
existing subscription. Unknown subscriptions are rejected before any network
request is made.

Callback Verification
---------------------

The callback ``GET`` accepts WebSub verification requests only when the token,
``hub.mode``, and ``hub.topic`` match a pending subscription row. Accepted
verification requests echo ``hub.challenge`` with HTTP ``200``.

For ``subscribe`` verification, django-indieweb marks the row ``active``,
records ``hub.lease_seconds`` when supplied by the hub, and computes
``lease_expires_at``. For ``unsubscribe`` verification, it marks the row
``unsubscribed`` and clears active lease fields. Missing, mismatched, or
out-of-state verification requests are rejected and do not mutate the row.

Content Distribution
--------------------

The callback ``POST`` accepts deliveries for active subscriptions only. It
records latest-delivery metadata including content type, byte size, SHA-256
digest, status code, delivery time, and signature algorithm. It deliberately
does not parse feeds or persist delivered content; host applications own those
semantics.

Configure ``INDIEWEB_WEBSUB_DELIVERY_HOOK`` to receive accepted deliveries:

.. code-block:: python

   # myapp/websub.py
   def process_delivery(*, subscription_id, hub_url, topic_url, body, headers):
       enqueue_feed_processing.delay(subscription_id, body)

.. code-block:: python

   # settings.py
   INDIEWEB_WEBSUB_DELIVERY_HOOK = "myapp.websub.process_delivery"

The hook is called with keyword arguments ``subscription_id``, ``hub_url``,
``topic_url``, raw ``body`` bytes, and request ``headers``. Hook failures are
logged, recorded on the subscription row, and returned as HTTP ``500`` so the
hub can retry. When no hook is configured, accepted deliveries return
``204 No Content`` after metadata is recorded.

Signed Deliveries
-----------------

If a subscription was initiated with ``hub.secret``, the callback requires a
valid HMAC signature before accepting delivery. It supports
``X-Hub-Signature-256`` and ``X-Hub-Signature`` headers with
``sha1``, ``sha256``, ``sha384``, or ``sha512`` digest labels. Missing,
malformed, unsupported, or mismatched signatures return HTTP ``403`` and are
recorded without invoking the host hook.

Unsigned deliveries remain accepted for subscriptions without a stored secret.
Secrets longer than 200 characters are rejected before a subscription request
is sent to the hub.

Security and Compatibility Notes
--------------------------------

WebSub is server-to-server. Prefer HTTPS topic and hub URLs, and avoid leaking
private or draft topic URLs to public hubs. Subscriber callback URLs include an
unguessable token and should be served over HTTPS. django-indieweb performs no
WebSub network calls unless your application explicitly calls
``notify_hubs()``, runs ``notify_websub``, or calls
``request_websub_subscription()``.

``request_websub_subscription()`` validates that hub and topic values are
syntactically valid ``http`` or ``https`` URLs, but it does not apply a private
IP, internal hostname, or allowlist policy. Treat hub URLs as trusted operator
configuration or apply your own allowlist before passing user-influenced URLs
to the helper.

The subscriber callback is CSRF-exempt because hubs are server-to-server
senders. It is not included in django-indieweb's opt-in CORS mixin; browsers do
not need cross-origin access to this callback. The optional
``websub_callback`` rate-limit key can be configured with
``INDIEWEB_RATE_LIMITS``.

django-indieweb does not auto-discover feeds, auto-subscribe to arbitrary
topics, renew leases in the background, parse delivered feeds, create calendar
or post models, or run a WebSub hub. Existing publisher helper APIs and the
``notify_websub`` command remain backward-compatible.
