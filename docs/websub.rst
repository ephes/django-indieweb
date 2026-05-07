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

Hub responses are bounded to ``INDIEWEB_WEBSUB_HUB_RESPONSE_MAX_BYTES``
(default 256 KiB). Both ``notify_hubs()`` and ``request_websub_subscription()``
stream the response and surface oversized replies as a request failure rather
than buffering the payload: ``notify_hubs()`` returns the failure on the
``WebSubNotificationResult.error`` field for the hub, while
``request_websub_subscription()`` additionally persists it on the
subscription's ``last_request_error`` diagnostics.

Set the value to ``None`` to disable the cap when your deployment already
enforces an equivalent limit. Malformed values, including an empty
environment variable that resolves to ``""``, are ignored with a warning and
the helper falls back to the 256 KiB default.

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

Subscriber Lease Inspection
---------------------------

Subscriber lease maintenance is explicit and operator-driven. django-indieweb
does not run background renewal jobs and does not contact hubs unless your
application calls ``request_websub_subscription()`` itself.

Use ``websub_subscriptions`` to list active subscriptions whose confirmed
lease has expired or expires within a configurable renewal window:

.. code-block:: bash

   python manage.py websub_subscriptions
   python manage.py websub_subscriptions --renewal-window-hours 6

The command prints metadata only: subscription id, topic URL, hub URL, status,
and ``lease_expires_at``. It does not send renewal or unsubscribe requests.
Applications that want to renew a listed subscription should make an explicit
call to ``request_websub_subscription()`` from their own operator workflow.
Use ``--renewal-window-hours 0`` to list expired subscriptions only.

The same lease-inspection behavior is available through
``get_websub_expired_subscriptions()``, ``get_websub_renewal_candidates()``,
and ``summarize_websub_leases()`` in ``indieweb.websub``. Renewal candidates
include already-expired active subscriptions, so callers do not need to union
the candidate set with ``get_websub_expired_subscriptions()``.

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
       secret="shared-delivery-secret-32-bytes",
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
current delivery secret and clear any earlier unverified staged secret.
Secrets must be non-empty, at least 20 bytes when UTF-8 encoded, and at most
200 bytes when UTF-8 encoded. Stored active and pending secrets are encrypted
at rest.

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
``lease_expires_at``. Confirmed lease durations are clamped to
``INDIEWEB_WEBSUB_MIN_LEASE_SECONDS`` and
``INDIEWEB_WEBSUB_MAX_LEASE_SECONDS`` (defaults: 300 seconds and 30 days).
For ``unsubscribe`` verification, it marks the row ``unsubscribed`` and clears
active lease fields. Missing, mismatched, or out-of-state verification
requests are rejected and do not mutate the row.

The callback also accepts WebSub denial callbacks with ``hub.mode=denied``
and a matching ``hub.topic``. ``hub.challenge`` is not required for denial.
The optional ``hub.reason`` value is stored in bounded denial diagnostics on
``WebSubSubscription`` and the callback returns ``204 No Content``. A denied
initial subscribe request moves the row to ``denied`` and clears pending
lease/secret staging. A denied renewal for an already-active subscription
keeps the row ``active``, preserves the current lease and secret, and clears
only the staged renewal state. A denied pending unsubscribe request restores
the row to ``active`` and clears only the pending unsubscribe state,
preserving the current lease metadata so deliveries can continue. Denials
without a matching pending request return a client error and do not mutate the
row.

Content Distribution
--------------------

The callback ``POST`` accepts deliveries for active subscriptions only. It
records latest-delivery metadata including content type, byte size, SHA-256
digest, status code, delivery time, signature algorithm, the latest accepted
delivery digest, and a bounded list of recently accepted SHA-256 digests used
for replay checks. Each recorded delivery attempt also creates a
``WebSubDeliveryAttempt`` row with the same bounded metadata for operator
diagnostics. Duplicate bodies matching any retained accepted digest within the
replay window are rejected with HTTP ``409`` for 300 seconds by default, so a
captured payload A is rejected even after a different legitimate payload B
has been accepted in between. Set
``INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS`` to tune or disable the
window and ``INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX`` to bound the
history (default 64 entries; the oldest digest is evicted once the cap is
reached). Entries older than the replay window are pruned on every accepted
delivery. django-indieweb deliberately does not parse feeds or persist
delivered content; host applications own those semantics.

Subscribe with a strong ``hub.secret`` whenever possible. Deliveries for rows
with a stored secret must include a valid SHA-256-or-stronger HMAC signature.
``X-Hub-Signature-256`` is preferred over legacy ``X-Hub-Signature`` when both
are present. Legacy ``sha1`` signatures are rejected by default; enable
``INDIEWEB_WEBSUB_ALLOW_SHA1_SIGNATURES`` only for hubs that cannot send
SHA-256. Set ``INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES`` to reject unsigned
deliveries for rows that still have no stored secret.

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

Host-Owned Delivery Workflows
-----------------------------

The delivery hook is intended to hand work to your application quickly. Keep
feed parsing, entry persistence, retry policy, and queue configuration in host
code so the WebSub callback path remains small and hub retries stay meaningful.

The tested examples in ``examples/websub_workflows.py`` are copy-and-adapt
host code. They show a hook shaped for ``INDIEWEB_WEBSUB_DELIVERY_HOOK`` that
builds a compact queue payload:

.. code-block:: python

   # myapp/websub_workflows.py
   from examples.websub_workflows import queue_websub_delivery
   from myapp.tasks import websub_delivery_queue

   def process_delivery(*, subscription_id, hub_url, topic_url, body, headers):
       queue_websub_delivery(
           subscription_id=subscription_id,
           hub_url=hub_url,
           topic_url=topic_url,
           body=body,
           headers=headers,
           queue=websub_delivery_queue,
       )

.. code-block:: python

   # settings.py
   INDIEWEB_WEBSUB_DELIVERY_HOOK = "myapp.websub_workflows.process_delivery"

The queue adapter only needs an ``enqueue_websub_delivery(payload)`` method.
That method can call Celery, RQ, a database-backed job table, or another
host-owned worker system. django-indieweb does not import those packages,
create queues, start workers, or retry deliveries itself.

Worker code can later load the subscription metadata and delegate the raw feed
body to your parser and persistence layer:

.. code-block:: python

   from examples.websub_workflows import process_queued_websub_delivery
   from myapp.feeds import feed_delivery_processor

   def process_websub_delivery_task(payload):
       result = process_queued_websub_delivery(
           payload,
           processor=feed_delivery_processor,
       )
       if not result.processed:
           logger.info("Skipped WebSub delivery: %s", result.error)

The processor owns feed parsing and storage. It might use ``feedparser``,
``xml.etree.ElementTree``, a Microformats parser, or a custom reader pipeline,
but those choices stay in the host application. django-indieweb records bounded
delivery metadata and passes raw bytes to the hook; it does not store delivery
bodies or parsed feed entries.

Explicit Lease Renewal
----------------------

Lease renewal is also host-owned. The examples include
``renew_websub_candidates()`` as a pattern for a management command, cron job,
Celery beat task, or manual operator action:

.. code-block:: python

   from datetime import timedelta

   from examples.websub_workflows import renew_websub_candidates

   attempts = renew_websub_candidates(
       callback_base_url="https://example.com/indieweb/websub",
       within=timedelta(hours=24),
       lease_seconds=86400,
       secret_for_subscription=lambda subscription: None,
   )
   for attempt in attempts:
       if not attempt.success:
           logger.warning("WebSub renewal failed: %s", attempt)

The helper selects rows with ``get_websub_renewal_candidates()`` and calls
``request_websub_subscription()`` for each candidate. That means it sends hub
network requests only when your host job explicitly invokes it. The optional
``secret_for_subscription`` callable is where your application can keep,
rotate, or remove delivery secrets according to operator policy.

Delivery Attempt Retention
--------------------------

``WebSubDeliveryAttempt`` rows are metadata-only diagnostics, but busy
subscribers should still prune them according to a host retention policy. The
example ``prune_websub_delivery_attempts()`` deletes attempts older than a
configured number of days and returns a count suitable for operator logs:

.. code-block:: python

   from examples.websub_workflows import prune_websub_delivery_attempts

   result = prune_websub_delivery_attempts(retention_days=90)
   logger.info("Pruned %s WebSub delivery attempts", result.deleted_count)

Choose the retention window in your application. django-indieweb does not add
a global retention setting, scheduler, or management command that deletes rows
automatically.

Signed Deliveries
-----------------

If a subscription was initiated with ``hub.secret``, the callback requires a
valid HMAC signature before accepting delivery. It supports
``X-Hub-Signature-256`` and ``X-Hub-Signature`` headers with SHA-256 or
stronger digest labels by default. ``sha1`` is accepted only when
``INDIEWEB_WEBSUB_ALLOW_SHA1_SIGNATURES`` is enabled. When multiple supported
signatures are present, the strongest supplied algorithm must validate.
Missing, malformed, unsupported, or mismatched signatures return HTTP ``403``
and are recorded without invoking the host hook.

Unsigned deliveries remain accepted for subscriptions without a stored secret.
Set ``INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES`` to reject them.
Empty secrets, secrets shorter than 20 bytes, and secrets longer than 200
bytes when UTF-8 encoded are rejected before a subscription request is sent to
the hub.

Security and Compatibility Notes
--------------------------------

WebSub is server-to-server. Prefer HTTPS topic and hub URLs, and avoid leaking
private or draft topic URLs to public hubs. Subscriber callback URLs include an
unguessable token and should be served over HTTPS. django-indieweb performs no
WebSub network calls unless your application explicitly calls
``notify_hubs()``, runs ``notify_websub``, or calls
``request_websub_subscription()``.

``request_websub_subscription()`` and ``notify_hubs()`` validate that hub and
topic values are syntactically valid ``http`` or ``https`` URLs. Hub network
requests use the shared outbound HTTP safety checks: loopback, private,
link-local, multicast, reserved, metadata-service, and other non-global IP
destinations are rejected after DNS resolution and again after each redirect.
Treat hub URLs as trusted operator configuration and do not build them from
request data or user-editable templates.

The subscriber callback is CSRF-exempt because hubs are server-to-server
senders. It is not included in django-indieweb's opt-in CORS mixin; browsers do
not need cross-origin access to this callback. The optional
``websub_callback`` rate-limit key can be configured with
``INDIEWEB_RATE_LIMITS``.

The callback checks an oversized ``Content-Length`` before reading the request
body when that header is present, then applies
``INDIEWEB_WEBSUB_DELIVERY_MAX_BYTES`` to the body that is actually read.
Production deployments should also set a tight Django
``DATA_UPLOAD_MAX_MEMORY_SIZE`` and matching proxy/CDN body-size limit. Keep
``INDIEWEB_WEBSUB_DELIVERY_HOOK`` small and enqueue accepted deliveries for
host-owned workers when feed parsing or persistence is non-trivial.

Raw ``hub.secret`` values are encrypted at rest with key material derived from
Django's ``SECRET_KEY``. Rotating ``SECRET_KEY`` requires re-subscribing with
fresh WebSub secrets so future deliveries can still be validated. Rolling the
migration back after rotating ``SECRET_KEY`` may leave encrypted values in
place; the reverse migration logs a warning when it cannot decrypt a stored
secret.

django-indieweb does not auto-discover feeds, auto-subscribe to arbitrary
topics, renew leases in the background, parse delivered feeds, create calendar
or post models, or run a WebSub hub. Existing publisher helper APIs and the
``notify_websub`` command remain backward-compatible.
