Configuration
=============

This document describes how to configure django-indieweb in your Django project.

Metadata Discovery URLs
-----------------------

Include the reusable app URLconf wherever your host project wants the bundled
endpoints to live. The common mount path is ``/indieweb/``:

.. code-block:: python

   # urls.py
   from django.urls import include, path

   urlpatterns = [
       path("indieweb/", include("indieweb.urls")),
   ]

With that configuration, the IndieAuth metadata endpoint is available at
``/indieweb/auth/metadata/``. Because django-indieweb is a reusable app, it
does not add root-level well-known routes by default. Host projects that want
OAuth-compatible discovery can publish the same reusable metadata view at
``/.well-known/oauth-authorization-server`` from the project URLconf:

.. code-block:: python

   # urls.py
   from django.urls import include, path
   from indieweb.views import IndieAuthMetadataView

   urlpatterns = [
       path("indieweb/", include("indieweb.urls")),
       path(
           ".well-known/oauth-authorization-server",
           IndieAuthMetadataView.as_view(),
           name="oauth-authorization-server",
       ),
   ]

The metadata view builds absolute authorization, token, and token
introspection endpoint URLs from the request and the active URL namespace
where possible. If you route the view directly at the well-known path, keep
the bundled URLconf included with its default ``indieweb`` namespace so the
view can reverse ``indieweb:auth``, ``indieweb:token``, and
``indieweb:token-introspection``.

Advertise metadata discovery from your profile page with a Link header or HTML
``link`` element:

.. code-block:: html

   <link rel="indieauth-metadata" href="https://example.com/indieweb/auth/metadata/">

If you also route the well-known path, the value can be
``https://example.com/.well-known/oauth-authorization-server`` instead. The
older ``authorization_endpoint`` and ``token_endpoint`` link relations can
remain in place for legacy IndieAuth clients.

Choose one metadata URL as your canonical discovery URL in profile links and
client documentation. The bundled mounted endpoint and the host-level
well-known route both describe the same django-indieweb endpoints, but their
``issuer`` values differ by design: the mounted endpoint uses the app mount
prefix, while the well-known route uses the site root as required for root
well-known publication. Successful bundled authorization redirects now include
``iss`` using the mounted endpoint issuer, such as
``https://example.com/indieweb/``. If you publish a host-level well-known
metadata URL as canonical, keep client-facing discovery and issuer validation
guidance aligned with that canonical URL.

The built-in metadata advertises only django-indieweb's bundled
resource-server scopes: ``create``, ``update``, ``delete``, ``undelete``, and
``media``. It intentionally does not advertise reader-oriented scopes such as
``read``, ``follow``, ``mute``, ``block``, or ``channels`` because the package
does not include Microsub or other reader-side resource-server behavior.

Django Settings
---------------

INDIWEB_AUTH_CODE_TIMEOUT
~~~~~~~~~~~~~~~~~~~~~~~~~

Controls how long authorization codes remain valid before they must be exchanged for tokens.

**Default:** ``60`` (seconds)

**Example:**

.. code-block:: python

   # settings.py
   INDIWEB_AUTH_CODE_TIMEOUT = 120  # 2 minutes

.. note::
   Authorization codes are single-use. Once exchanged for a token, they cannot be reused.

INDIEWEB_TOKEN_EXPIRES_IN
~~~~~~~~~~~~~~~~~~~~~~~~~

Controls how long newly issued or reissued access tokens remain valid.

**Default:** ``86400`` (seconds — 24 hours)

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_TOKEN_EXPIRES_IN = 3600  # 1 hour

The token endpoint reports the remaining lifetime in the ``expires_in`` field of
its response, and the Micropub endpoint rejects expired tokens with HTTP 401.
Authenticated users can revoke their own tokens manually at
``/indieweb/tokens/``; revocation deletes the ``Token`` row and immediately
invalidates the bearer credential.

.. note::
   Tokens created before this field existed have ``expires_at`` set to ``NULL``
   and continue to be accepted indefinitely until they are reissued. Operators
   that want to retire those tokens should delete them or trigger a reissue
   through the IndieAuth flow.

INDIEWEB_CLIENT_ID_VALIDATOR
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional dotted path to a callable ``(client_id: str) -> bool`` that gates which
``client_id`` values are allowed by the IndieAuth and Micropub endpoints.

**Default:** ``None`` (every structurally-valid ``client_id`` is permitted)

When set, the configured callable is invoked **on top of** structural validation
(an ``http``/``https`` URL with no userinfo and no fragment) at four
authorization/token paths — the authorization GET, the consent approval POST,
the code-verification POST, and the token endpoint POST — and again on the
resource-server path inside ``TokenAuthMixin``. The latter is intentional:
operator policy may evolve and revoke a previously-allowed ``client_id``, in
which case existing tokens for that client must stop working immediately.

**Example:**

.. code-block:: python

   # myapp/indieauth.py
   _ALLOWLIST = {"https://quill.p3k.io/", "https://micropublish.net/"}

   def is_allowed_client(client_id: str) -> bool:
       return client_id in _ALLOWLIST

.. code-block:: python

   # settings.py
   INDIEWEB_CLIENT_ID_VALIDATOR = "myapp.indieauth.is_allowed_client"

.. note::
   If the configured dotted path fails to import, or the callable raises, the
   request is rejected (fail-closed). Misconfiguration cannot silently weaken
   access control. The exact response shape depends on the call site: the
   authorization endpoint and the code-verification POST return HTTP 400 with
   a plain-text ``invalid_client`` body; the token endpoint returns HTTP 400
   with body ``invalid_request`` and content type
   ``application/x-www-form-urlencoded`` (matching the existing missing-
   ``code`` case); and the Micropub resource-server path returns HTTP 403
   with body ``invalid_client``.

.. note::
   Stored ``client_id`` values are not re-validated *structurally* on use,
   matching the ``redirect_uri`` rule. The configured validator callable
   IS re-applied on use, so revoking a previously-allowed client takes
   effect immediately for existing tokens. A token issued before
   ``client_id`` access control existed (or by an out-of-band script) keeps
   working as long as it satisfies the configured validator (or the
   validator is unset).

INDIEWEB_RATE_LIMITS
~~~~~~~~~~~~~~~~~~~~

Optional per-endpoint request limits for django-indieweb's public protocol
endpoints. The setting uses Django's configured cache backend for counters and
does not add any model, migration, or runtime dependency.

**Default:** ``None`` (rate limiting disabled)

Set this to ``None`` or an empty dictionary to disable built-in rate limiting.
Each configured endpoint key accepts a mapping with:

- ``limit`` - Maximum number of requests allowed during the window.
- ``window`` - Window length in seconds.

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_RATE_LIMITS = {
       "auth": {"limit": 30, "window": 300},
       "token": {"limit": 10, "window": 300},
       "token_introspection": {"limit": 60, "window": 300},
       "micropub": {"limit": 120, "window": 60},
       "media": {"limit": 30, "window": 300},
       "websub_callback": {"limit": 120, "window": 60},
       "webmention": {"limit": 60, "window": 300},
       "webmention_status": {"limit": 120, "window": 60},
   }

Supported endpoint keys:

- ``auth`` - ``/indieweb/auth/``
- ``token`` - ``/indieweb/token/``
- ``token_introspection`` - ``/indieweb/token/introspect/``
- ``micropub`` - ``/indieweb/micropub/``
- ``media`` - ``/indieweb/media/``
- ``websub_callback`` - ``/indieweb/websub/<token>/``
- ``webmention`` - ``/indieweb/webmention/``
- ``webmention_status`` - ``/indieweb/webmention/<pk>/``

Counters are isolated by endpoint key, HTTP method, and client identity, so
``GET`` and ``POST`` requests to the same endpoint use independent counters.
Set each endpoint limit as a per-method budget. The client identity is
``request.META["REMOTE_ADDR"]`` by default, and the value is hashed before it
is used in cache keys. django-indieweb does not read or trust
``X-Forwarded-For`` directly. If your site runs behind a reverse proxy, load
balancer, CDN, or platform router, configure that trusted infrastructure so
Django receives the correct client address in ``REMOTE_ADDR`` before enabling
IP-based limits.

Cache backend choice affects the strength of the limit. Django's default
``LocMemCache`` is local to one process, so multi-worker deployments can allow
roughly ``limit`` requests per worker during each window. Use a shared cache
backend such as Redis or Memcached when you need deployment-wide counters.
``DummyCache`` does not persist counters and effectively disables built-in
rate limiting.

When a limit is exceeded, the endpoint returns HTTP ``429`` with a plain-text
``rate limit exceeded`` body. A ``Retry-After`` header is included when the
cache-backed window reset time is available. Requests under the limit continue
through the existing view code unchanged, including authentication,
authorization, Micropub handler calls, media storage, Webmention processing,
and async Webmention enqueueing.

Malformed endpoint entries, non-mapping values, or non-positive ``limit`` /
``window`` values are ignored and logged, leaving that endpoint unlimited.
This keeps the optional hardening setting from breaking existing deployments
because of a typo, but production operators should monitor logs after changing
rate-limit configuration.

The browser token-management pages at ``/indieweb/tokens/`` and
``/indieweb/tokens/<pk>/revoke/`` are not covered by this setting because they
are authenticated Django UI views rather than public IndieWeb protocol
endpoints.

INDIEWEB_MICROPUB_HANDLER
~~~~~~~~~~~~~~~~~~~~~~~~~

Optional dotted path to a ``MicropubContentHandler`` subclass that owns
Micropub persistence for your host project.

**Default:** ``None`` (use the bundled in-memory development handler)

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_MICROPUB_HANDLER = "myapp.micropub.BlogPostMicropubHandler"

The handler is loaded and instantiated for Micropub content operations. It is
the extension point for creating, retrieving, listing, updating, deleting, and
undeleting entries, and for optional media source/delete hooks. See
:doc:`micropub` for model-backed examples and for tested static-site examples
that map Micropub properties to host-owned file paths, public URLs, front
matter, local filesystem writes, Django storage writes, and Git-backed adapter
boundaries.

django-indieweb does not add a content-store plugin system, static-site
generator preset system, repository credential setting, commit/push workflow,
build command, deployment hook, media database, or media deletion policy for
this setting. Host code remains responsible for those concerns.

INDIEWEB_MEDIA_MAX_UPLOAD_BYTES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Maximum file size accepted by the Micropub media endpoint at
``/indieweb/media/`` and by ``photo`` file parts on multipart create requests
sent to ``/indieweb/micropub/``.

**Default:** ``10485760`` (10 MiB)

Requests whose uploaded ``file`` or ``photo`` part is larger than this value
are rejected with HTTP 413 and body ``invalid_request`` before storage is
called.
django-indieweb enforces this limit after Django has finished parsing the
multipart body, which means oversized uploads can still consume temporary disk
and bandwidth before the view rejects them. For denial-of-service protection,
also configure a complementary limit at the web server, reverse proxy, CDN, or
Django deployment layer, for example nginx ``client_max_body_size``.

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_MEDIA_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MiB

Set this to ``None`` to disable django-indieweb's media upload size check. If
you do that, enforce an upload limit outside these views so authenticated
clients cannot fill local or remote storage.

INDIEWEB_MEDIA_ALLOWED_TYPES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Iterable of MIME content types accepted by the Micropub media endpoint and by
``photo`` file parts on multipart create requests.

**Default:** common image, audio, and video types:

.. code-block:: python

   (
       "image/jpeg",
       "image/png",
       "image/gif",
       "image/webp",
       "image/heic",
       "image/heif",
       "audio/mpeg",
       "audio/mp4",
       "audio/ogg",
       "audio/wav",
       "audio/webm",
       "video/mp4",
       "video/quicktime",
       "video/ogg",
       "video/webm",
   )

Uploads whose ``file`` or ``photo`` part reports a content type outside the
allowlist are rejected with HTTP 415 and body ``invalid_request`` before
storage is called.
The value is based on the upload's submitted content type; if your deployment
needs stronger guarantees, inspect files after upload or use storage/server
policies that prevent active content from executing on your primary domain.

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_MEDIA_ALLOWED_TYPES = ("image/jpeg", "image/png", "image/webp")

Set this to ``None`` to disable django-indieweb's content-type check. If you
allow broad uploads, serve media from a separate origin or with defensive
headers such as ``Content-Disposition: attachment`` for risky types.

Media Source and Delete Hooks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No additional setting is required for Micropub media source or delete support.
Those optional operations are exposed through the configured
``INDIEWEB_MICROPUB_HANDLER``:

- ``list_media(user, limit=None, offset=0, filter=None)``
- ``get_media(url, user)``
- ``delete_media(url, user)``

When a handler does not implement a hook, ``/indieweb/media/`` returns
``501 not_implemented`` for that operation after token authentication and the
``media`` scope check. Host code owns any media index, metadata fields,
ownership checks, storage deletion, and audit trail. django-indieweb does not
add a media model, migration, management UI, image transform pipeline, or a
non-Django storage abstraction for these hooks.

INDIEWEB_WEBSUB_HUBS
~~~~~~~~~~~~~~~~~~~~

Hub URLs used by the WebSub publisher helpers when a caller does not pass hubs
explicitly.

**Default:** ``()`` (no hubs configured)

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_WEBSUB_HUBS = (
       "https://hub.example/",
       "https://backup.example/websub",
   )

The values must be non-empty ``http`` or ``https`` URLs. Discovery helpers such
as ``websub_link_header()`` and the ``websub_link_tags`` template tag require at
least one hub so they cannot silently render an invalid WebSub publisher
advertisement. ``notify_hubs()`` with no configured hubs returns an empty
result list; the ``notify_websub`` management command treats that as a
configuration error.

INDIEWEB_WEBSUB_TIMEOUT
~~~~~~~~~~~~~~~~~~~~~~~

Per-request timeout, in seconds, used by ``notify_hubs()`` and the
``notify_websub`` management command when no explicit timeout is passed. The
same timeout is used by ``request_websub_subscription()`` when it sends
subscriber subscribe/unsubscribe requests to a hub.

**Default:** ``10.0``

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_WEBSUB_TIMEOUT = 3.0

The timeout must be a positive number. Hub notification failures, including
timeouts and connection errors, are captured in per-hub result objects instead
of being raised. Malformed topic URLs and malformed hub URLs raise
``ValueError`` before any network request is made. Invalid timeout values raise
``ValueError`` only when at least one hub would be notified; the empty-hubs
path short-circuits before timeout validation.

INDIEWEB_WEBSUB_CALLBACK_BASE_URL
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Absolute URL prefix used by ``request_websub_subscription()`` to construct
tokenized subscriber callback URLs.

**Default:** unset

**Example:**

.. code-block:: python

   INDIEWEB_WEBSUB_CALLBACK_BASE_URL = "https://example.com/indieweb/websub"

The generated callback URL appends the subscription's unguessable token as one
path component, for example
``https://example.com/indieweb/websub/<token>/``. Set this to the public HTTPS
URL where hubs can reach django-indieweb's ``websub-callback`` route. The value
is required only for subscriber request helpers; publisher helpers do not read
it.

INDIEWEB_WEBSUB_DELIVERY_MAX_BYTES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Maximum raw body size accepted by the WebSub subscriber callback ``POST``.

**Default:** ``1048576`` (1 MiB)

Requests above this limit return HTTP ``413`` and update the subscription's
latest-delivery diagnostics without invoking the host delivery hook. Set this
to ``None`` to disable django-indieweb's built-in size check only when your
server, proxy, or worker queue enforces an equivalent limit.
Malformed values are ignored and logged; the callback falls back to the
default 1 MiB limit instead of failing every delivery.

INDIEWEB_WEBSUB_DELIVERY_ALLOWED_TYPES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional iterable of content types accepted by the WebSub subscriber callback.

**Default:** ``None`` (no content-type allowlist)

When configured, the callback compares the base ``Content-Type`` value without
parameters. Requests outside the allowlist return HTTP ``415`` and do not
invoke the host delivery hook.
Malformed allowlist values are ignored and logged, leaving the callback with no
content-type allowlist.

**Example:**

.. code-block:: python

   INDIEWEB_WEBSUB_DELIVERY_ALLOWED_TYPES = (
       "application/atom+xml",
       "application/rss+xml",
       "application/json",
   )

INDIEWEB_WEBSUB_DELIVERY_HOOK
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional dotted path to a callable that receives accepted WebSub deliveries.

**Default:** ``None`` (record metadata only)

The callable is invoked with keyword arguments:

.. code-block:: python

   def process_delivery(*, subscription_id, hub_url, topic_url, body, headers):
       ...

``body`` is the raw request body as bytes. ``headers`` is a dictionary copy of
the request headers. The callback view validates the token, active
subscription state, size/content-type limits, and any stored ``hub.secret``
signature before loading or calling this hook. Hook import failures,
non-callables, and raised exceptions are logged, recorded on the subscription
row, and returned as HTTP ``500`` so the hub can retry.

``hub.secret`` values stored on ``WebSubSubscription`` are limited to 200
characters. Renewal requests preserve the existing stored secret when
``request_websub_subscription()`` is called with ``secret=None`` and clear any
earlier unverified staged secret. When a renewal request provides a new secret,
that value is staged and only becomes the active delivery secret after the hub
verifies the renewal; failed renewal requests keep the previous secret. Passing
``secret=""`` stages removal of the stored secret, so a verified renewal can
switch the subscription back to unsigned deliveries.

See :doc:`websub` and ``examples/websub_workflows.py`` for tested
copy-and-adapt delivery hook examples that enqueue a compact payload for a
host-owned worker. The examples keep feed parsing, entry persistence, queue
choice, retry behavior, and delivery body storage policy outside
django-indieweb.

WebSub Subscriber Models and Commands
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``WebSubSubscription`` stores host-level subscriber state for a hub/topic pair,
including tokenized callback identity, pending verification mode, lease
metadata, staged ``hub.secret`` values, latest request diagnostics, latest
denial diagnostics, and latest delivery diagnostics.

``WebSubDeliveryAttempt`` stores metadata-only delivery history linked to a
subscription. It records received time, content type, byte size, SHA-256
digest, signature algorithm, HTTP status code, and bounded error text. It does
not store raw hub delivery bodies or parsed feed content. The table is
append-only from the callback path, so high-volume subscribers should choose a
retention policy that matches their operational needs. Operators can delete
old attempts from Django admin or from a host-owned maintenance command, for
example:

.. code-block:: python

   from datetime import timedelta

   from django.utils import timezone
   from indieweb.models import WebSubDeliveryAttempt

   cutoff = timezone.now() - timedelta(days=90)
   WebSubDeliveryAttempt.objects.filter(received_at__lt=cutoff).delete()

The tested ``prune_websub_delivery_attempts()`` example in
``examples/websub_workflows.py`` wraps the same policy with a returned count
for operator logs. Retention days remain host configuration, not a
django-indieweb setting.

Use the read-only ``websub_subscriptions`` management command to inspect
active subscriptions whose leases have expired or expire within a configured
window:

.. code-block:: bash

   python manage.py websub_subscriptions --renewal-window-hours 24

The command makes no hub network calls. Operators that want to renew a listed
subscription should explicitly call ``request_websub_subscription()`` from
their application workflow or a separate, host-owned management task.
Set ``--renewal-window-hours 0`` when you only want expired subscriptions.
The tested ``renew_websub_candidates()`` example shows how to combine
``get_websub_renewal_candidates()`` with explicit
``request_websub_subscription()`` calls from a host-owned cron, Celery beat,
Django management command, or manual operator workflow.

INDIEWEB_WEBMENTION_ENQUEUE
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional dotted path to a callable ``(webmention_id: int) -> None`` that queues
receive-side Webmention processing for a persisted ``Webmention`` row.

**Default:** ``None`` (incoming Webmentions are processed synchronously)

When unset, ``POST /indieweb/webmention/`` keeps the backwards-compatible
synchronous behavior: it validates the submitted ``source`` and ``target``,
processes the Webmention in the request path, and returns ``201 Created`` with
a ``Location`` header for the status endpoint.

When set, the receive endpoint validates the request and target domain, creates
or reuses the ``Webmention`` row for the submitted ``source``/``target`` pair,
calls the configured enqueue hook with that row's primary key, and returns
``202 Accepted`` with a ``Location`` header for
``/indieweb/webmention/<pk>/``. Source fetching, target-link verification,
microformats2 parsing, spam checks, final status transitions, and
``webmention_received`` signal emission happen later when a worker processes
the queued row.

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_WEBMENTION_ENQUEUE = "myapp.webmentions.enqueue_webmention"

.. code-block:: python

   # myapp/webmentions.py
   from myapp.tasks import process_webmention_task

   def enqueue_webmention(webmention_id: int) -> None:
       process_webmention_task.delay(webmention_id)

.. code-block:: python

   # myapp/tasks.py
   from indieweb.processors import process_queued_webmention

   def process_webmention_task(webmention_id: int) -> None:
       process_queued_webmention(webmention_id)

The configured enqueue callable should schedule work only. It should not call
``process_queued_webmention()`` inline from the receive request unless your
deployment intentionally wants synchronous behavior under a custom hook.

.. note::
   If the configured path cannot be imported, resolves to a non-callable, or
   raises while enqueueing, the receive endpoint returns HTTP 500 and does not
   fall back to inline processing. Invalid receive requests still return HTTP
   400 before the hook is loaded or called. Import and non-callable failures
   happen before a row is persisted; if the callable itself raises, the
   ``Webmention`` row has already been created or reused and remains
   ``pending`` until a queue retry path or manual cleanup reconciles it.

INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional iterable of domains that django-indieweb may trust as Webmention
Vouch voucher sites when no custom Vouch trust policy is configured.

**Default:** ``None`` (submitted Vouch URLs are stored but not verified)

When this setting is ``None`` or empty, incoming Webmentions may include the optional
``vouch`` form parameter, and django-indieweb validates and stores that URL,
but Vouch does not affect whether the processor marks the Webmention
``verified`` unless ``INDIEWEB_WEBMENTION_VOUCH_REQUIRED`` is enabled.

When set to an iterable of domain names, the processor verifies submitted
Vouch URLs. A voucher URL must be on the configured Django ``Site`` domain or
one of these domains. The voucher is fetched with the same bounded redirect
policy used for Webmention source fetches, the final URL must remain on a
trusted domain, the response must be HTTP ``200`` with ``text/html`` content,
and the voucher page must contain an HTTP(S) HTML ``href`` to the submitted
source URL's domain. If any Vouch check fails, the Webmention is marked
``failed``.

**Example:**

.. code-block:: python

   INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS = ("trusted.example", "events.example")

Domain matching is exact after lowercasing and treating a leading ``www.`` as
equivalent to the bare hostname. Subdomains are not implicitly trusted.

If ``INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY`` is configured, that callable
owns the submitted and final voucher URL trust decisions. In that case,
``INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS`` is ignored by django-indieweb's
built-in trust check, though your policy callable may read the setting itself.

INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional dotted path to a callable that decides whether django-indieweb should
trust a submitted Webmention Vouch URL.

**Default:** ``None`` (use ``INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS`` as
the default/simple trust policy)

When set, the processor imports the callable and invokes it during Vouch
verification with keyword arguments:

.. code-block:: python

   def trust_vouch(
       *,
       webmention: Webmention,
       source_url: str,
       target_url: str,
       vouch_url: str,
       final_vouch_url: str | None = None,
   ) -> bool:
       ...

The callable is evaluated twice for a submitted voucher:

1. Before fetching the voucher, with ``final_vouch_url=None``. Returning
   ``False`` rejects the voucher without a network request.
2. After fetching and following allowed redirects, with ``final_vouch_url`` set
   to the final voucher URL. Returning ``False`` rejects the voucher even if
   the submitted URL was trusted.

Both calls must return a truthy value. The policy controls only whether the
submitted and final voucher URLs are trusted. The processor still requires the
voucher response to be HTTP ``200`` with ``text/html`` content and to contain
an HTTP(S) HTML ``href`` to the submitted source URL's domain.

**Example:**

.. code-block:: python

   # myapp/webmentions.py
   from urllib.parse import urlparse

   TRUSTED_VOUCH_HOSTS = {"trusted.example", "events.example"}

   def trust_vouch(
       *,
       webmention,
       source_url: str,
       target_url: str,
       vouch_url: str,
       final_vouch_url: str | None = None,
   ) -> bool:
       candidate = final_vouch_url or vouch_url
       return urlparse(candidate).hostname in TRUSTED_VOUCH_HOSTS

.. code-block:: python

   # settings.py
   INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY = "myapp.webmentions.trust_vouch"

If the configured path cannot be imported, resolves to a non-callable, or the
callable raises, Vouch verification fails closed and the Webmention is marked
``failed`` by the processor. When receiving asynchronously, the request path
does not import or call the trust policy; workers evaluate it when they run
``WebmentionProcessor``.

INDIEWEB_WEBMENTION_VOUCH_REQUIRED
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Require incoming Webmentions to have a verifiable Vouch URL.

**Default:** ``False``

When ``False``, ordinary Webmentions without ``vouch`` continue to verify
normally. When ``True``, the processor marks a Webmention ``failed`` if it has
no stored ``vouch`` or if the configured Vouch verification does not succeed.
This requirement is enforced in ``WebmentionProcessor`` and queued worker
paths, not in the receive request path.

When ``INDIEWEB_WEBMENTION_VOUCH_REQUIRED`` is ``True`` and
neither ``INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY`` nor
``INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS`` is configured, Vouch
verification fails closed for submitted vouchers. Configure a trust policy or
at least one trusted voucher domain before enabling required mode in
production.

Salmention Configuration
~~~~~~~~~~~~~~~~~~~~~~~~

There is no Salmention-specific setting in django-indieweb today.
django-indieweb persists verified Webmention source snapshots and stable nested
child response rows as a foundation for receive-side Salmention support, but
the bundled ``show_webmentions`` template tag renders verified children inline
under verified parent replies. Outbound sender support records ordinary
``WebmentionSender.send_webmentions()`` delivery attempts to the outbound
target-history table by default and exposes
``WebmentionSender.resend_salmentions()`` for application-triggered union-of-
current-and-historical resends. The ``send_webmentions`` management command
also exposes this workflow with ``--salmention-resend`` for operator-triggered
resends and ``--dry-run --salmention-resend`` previews. The documented design
uses package-managed history plus an explicit host-application or
operator-triggered resend workflow, not a setting toggle.
See :doc:`webmention` for the support-status details, target-history design,
and current ordinary Webmention reprocessing behavior.

URL Configuration
-----------------

Basic URL Setup
~~~~~~~~~~~~~~~

The standard way to include django-indieweb URLs:

.. code-block:: python

   # urls.py
   from django.urls import path, include

   urlpatterns = [
       path('indieweb/', include('indieweb.urls', namespace='indieweb')),
   ]

This creates the following endpoints:

- ``/indieweb/auth/`` - Authorization endpoint
- ``/indieweb/auth/metadata/`` - IndieAuth authorization-server metadata endpoint
- ``/indieweb/token/`` - Token endpoint
- ``/indieweb/token/introspect/`` - Token introspection endpoint
- ``/indieweb/tokens/`` - Browser UI for viewing and revoking the logged-in user's tokens
- ``/indieweb/tokens/<pk>/revoke/`` - CSRF-protected POST action for revoking one owned token
- ``/indieweb/micropub/`` - Micropub endpoint
- ``/indieweb/media/`` - Micropub media endpoint for uploads and optional
  host-owned media source/delete hooks
- ``/indieweb/websub/<token>/`` - WebSub subscriber callback endpoint
- ``/indieweb/webmention/`` - Webmention receive endpoint
- ``/indieweb/webmention/<pk>/`` - Webmention status endpoint

The bundled URLconf does not create a Microsub endpoint, reader feed endpoint,
reader timeline, following/muting/blocking endpoint, or reader UI. There is no
Microsub setting in django-indieweb; host projects that add reader-side
protocols own those URLs, storage models, authorization policy, discovery or
metadata behavior, and documentation.

Custom URL Paths
~~~~~~~~~~~~~~~~

You can customize the URL paths:

.. code-block:: python

   # urls.py
   from indieweb import views

   urlpatterns = [
       path('auth/', views.AuthView.as_view(), name='auth'),
       path('auth/metadata/', views.IndieAuthMetadataView.as_view(), name='auth-metadata'),
       path('token/', views.TokenView.as_view(), name='token'),
       path('token/introspect/', views.TokenIntrospectionView.as_view(), name='token-introspection'),
       path('tokens/', views.TokenManagementView.as_view(), name='tokens'),
       path('tokens/<int:pk>/revoke/', views.TokenRevokeView.as_view(), name='token-revoke'),
       path('api/micropub/', views.MicropubView.as_view(), name='micropub'),
       path('api/media/', views.MicropubMediaView.as_view(), name='media'),
       path('websub/<str:token>/', views.WebSubCallbackView.as_view(), name='websub-callback'),
       path('webmention/', views.WebmentionEndpoint.as_view(), name='webmention'),
       path('webmention/<int:pk>/', views.WebmentionStatusView.as_view(), name='webmention-status'),
   ]

Middleware Configuration
------------------------

CSRF Exemption
~~~~~~~~~~~~~~

The IndieWeb protocol views are automatically exempt from CSRF protection.
This is necessary for token and Micropub endpoints to accept POST requests
from external clients, and for the WebSub subscriber callback to accept
server-to-server hub deliveries.

If you need CSRF protection, you'll need to implement your own views:

.. code-block:: python

   from django.views.decorators.csrf import csrf_protect
   from indieweb.views import TokenView as BaseTokenView

   @method_decorator(csrf_protect, name='dispatch')
   class TokenView(BaseTokenView):
       pass

Authentication Backend
~~~~~~~~~~~~~~~~~~~~~~

django-indieweb uses Django's standard authentication system. Ensure you have
authentication middleware enabled:

.. code-block:: python

   MIDDLEWARE = [
       ...
       'django.contrib.sessions.middleware.SessionMiddleware',
       'django.contrib.auth.middleware.AuthenticationMiddleware',
       ...
   ]

Database Configuration
----------------------

Models
~~~~~~

django-indieweb currently creates eight models:

1. **Auth** - Stores authorization codes temporarily
2. **Token** - Stores access tokens
3. **Webmention** - Stores incoming webmention source/target pairs, parsed
   content, status, and spam-check results
4. **WebmentionSourceSnapshot** - Stores the latest verified fetched source
   snapshot related to a submitted Webmention for receive-side Salmention
   comparison
5. **WebmentionNestedResponse** - Stores stable nested ``h-entry`` responses
   discovered inside verified parent Webmention sources for receive-side
   Salmention rendering
6. **WebmentionOutboundTarget** - Stores outbound Webmention target-history
   rows keyed by the exact HTTP(S) ``source_url`` and ``target_url`` strings,
   with endpoint diagnostics, first/latest send timestamps, latest result
   fields, latest Vouch URL, and diagnostic current-content last-seen tracking
7. **WebSubSubscription** - Stores host-level subscriber state for a hub/topic
   pair, including an unguessable callback token, pending verification mode,
   lease metadata, optional delivery secret, latest request diagnostics, and
   latest delivery metadata
8. **Profile** - Stores user h-card data

``Auth``, ``Token``, and ``Profile`` use ``settings.AUTH_USER_MODEL`` for their
user relationships. ``WebmentionSourceSnapshot`` is tied one-to-one to a parent
``Webmention`` and cascades when that parent is deleted.
``WebmentionNestedResponse`` is tied many-to-one to a parent ``Webmention``,
is unique per parent and stable nested identity, and also cascades when the
parent is deleted.

``WebmentionOutboundTarget`` is separate from incoming ``Webmention`` rows and
uses no foreign key to them. Rows are unique by the exact source URL and target
URL strings stored for outbound delivery history. Ordinary sender calls now
record and refresh these rows by default for delivered current external targets,
and ``WebmentionSender.resend_salmentions()`` uses rows for exactly the same
``source_url`` together with current source links. The management-command
``--salmention-resend`` flag wraps the same sender workflow without adding a
new setting or schema requirement.

``WebSubSubscription`` rows are host-level, not user-owned. django-indieweb
does not infer which Django user should own external feed subscriptions; host
applications decide when to call the subscription helper and how to process
accepted deliveries.

Migrations
~~~~~~~~~~

After installation, run migrations:

.. code-block:: bash

   python manage.py migrate indieweb

Custom User Model
~~~~~~~~~~~~~~~~~

If using a custom user model, ensure it's configured before running migrations:

.. code-block:: python

   # settings.py
   AUTH_USER_MODEL = 'myapp.User'

Security Configuration
----------------------

HTTPS Requirement
~~~~~~~~~~~~~~~~~

For production, always use HTTPS:

.. code-block:: python

   # settings.py
   SECURE_SSL_REDIRECT = True
   SESSION_COOKIE_SECURE = True
   CSRF_COOKIE_SECURE = True

Login URL
~~~~~~~~~

Configure where users are redirected for authentication:

.. code-block:: python

   # settings.py
   LOGIN_URL = '/accounts/login/'
   LOGIN_REDIRECT_URL = '/'

Allowed Hosts
~~~~~~~~~~~~~

Ensure your domain is in ``ALLOWED_HOSTS``:

.. code-block:: python

   # settings.py
   ALLOWED_HOSTS = ['yourdomain.com', 'www.yourdomain.com']

Extending Functionality
-----------------------

Token Metadata
~~~~~~~~~~~~~~

The built-in ``Token`` model already includes ``created``, ``modified``,
``client_id``, ``me``, ``scope``, and ``expires_at`` fields. To track
application-specific token metadata without shadowing built-in fields, store it
in a separate model related to ``Token``:

.. code-block:: python

   # myapp/models.py
   from django.db import models
   from indieweb.models import Token

   class TokenMetadata(models.Model):
       token = models.OneToOneField(Token, on_delete=models.CASCADE, related_name='metadata')
       last_used = models.DateTimeField(null=True)

Custom Views
~~~~~~~~~~~~

Extend views to add application-specific behavior:

.. code-block:: python

   # myapp/views.py
   from indieweb.views import TokenView as BaseTokenView

   class TokenView(BaseTokenView):
       def post(self, request, *args, **kwargs):
           # Add deployment-specific auditing, metrics, or policy checks here.
           return super().post(request, *args, **kwargs)

Logging Configuration
---------------------

Enable logging to debug issues:

.. code-block:: python

   # settings.py
   LOGGING = {
       'version': 1,
       'disable_existing_loggers': False,
       'handlers': {
           'file': {
               'level': 'DEBUG',
               'class': 'logging.FileHandler',
               'filename': 'indieweb.log',
           },
       },
       'loggers': {
           'indieweb': {
               'handlers': ['file'],
               'level': 'DEBUG',
               'propagate': True,
           },
       },
   }

CORS Configuration
------------------

django-indieweb can add CORS headers to its public protocol endpoints without
adding middleware or a third-party dependency. Built-in CORS support is
disabled by default and applies only to:

- ``/indieweb/auth/``
- ``/indieweb/auth/metadata/``
- ``/indieweb/token/``
- ``/indieweb/token/introspect/``
- ``/indieweb/micropub/``
- ``/indieweb/media/``
- ``/indieweb/webmention/``
- ``/indieweb/webmention/<pk>/``

The browser token-management pages at ``/indieweb/tokens/`` and
``/indieweb/tokens/<pk>/revoke/`` are intentionally excluded because they are
authenticated Django UI views with CSRF-protected browser actions.

INDIEWEB_CORS_ALLOWED_ORIGINS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Allowed browser origins for django-indieweb's public protocol endpoint CORS
handling.

**Default:** ``None`` (CORS disabled)

Set this to ``None`` or an empty iterable to disable built-in CORS support.
Set it to an iterable of exact origins to allow only those origins, or to the
string ``"*"`` to explicitly allow every origin.

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_CORS_ALLOWED_ORIGINS = (
       "https://app.example.com",
       "https://client.example.com",
   )

Actual endpoint responses with an allowed ``Origin`` receive
``Access-Control-Allow-Origin`` without changing the existing status code,
body, content type, authentication behavior, scope checks, rate limiting, or
protocol processing. Responses that echo a specific request origin also
receive ``Vary: Origin``. Disallowed origins receive no CORS headers.

For allow-all deployments:

.. code-block:: python

   INDIEWEB_CORS_ALLOWED_ORIGINS = "*"

When allow-all is used without credentials, responses send
``Access-Control-Allow-Origin: *`` and do not vary by origin. When allow-all is
combined with ``INDIEWEB_CORS_ALLOW_CREDENTIALS = True``, django-indieweb
echoes the request origin and sends ``Vary: Origin`` because browsers reject
``Access-Control-Allow-Origin: *`` on credentialed CORS responses.

INDIEWEB_CORS_ALLOW_CREDENTIALS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Whether to add ``Access-Control-Allow-Credentials: true`` on allowed CORS
responses.

**Default:** ``False``

Enable this only when browser clients need credentialed CORS semantics. Bearer
token authentication remains unchanged; CORS does not authorize requests and
does not replace endpoint authentication, authorization, or scope checks.

INDIEWEB_CORS_ALLOWED_HEADERS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Headers advertised on successful preflight responses.

**Default:** ``("Authorization", "Content-Type", "Accept")``

**Example:**

.. code-block:: python

   INDIEWEB_CORS_ALLOWED_HEADERS = (
       "Authorization",
       "Content-Type",
       "Accept",
       "Accept-Language",
   )

INDIEWEB_CORS_MAX_AGE
~~~~~~~~~~~~~~~~~~~~~

Value for ``Access-Control-Max-Age`` on successful preflight responses.

**Default:** ``86400``

Set this to ``None`` to omit ``Access-Control-Max-Age``.

Preflight Behavior
~~~~~~~~~~~~~~~~~~

Configured preflight ``OPTIONS`` requests require an allowed ``Origin`` and an
``Access-Control-Request-Method`` that matches the target endpoint. Successful
preflights return ``204 No Content`` with ``Access-Control-Allow-Origin``,
``Access-Control-Allow-Methods``, ``Access-Control-Allow-Headers``, and
``Access-Control-Max-Age`` when configured.

Preflights short-circuit before rate limiting, token authentication, Micropub
handler calls, media storage, Webmention processing, and async Webmention
enqueue hooks. The IndieAuth metadata endpoint is public/read-only and is
included for metadata discovery, but it is not covered by
``INDIEWEB_RATE_LIMITS``. WebSub subscriber callbacks are server-to-server hub
endpoints and are excluded from built-in CORS handling. Disallowed origins do
not receive permissive preflight headers. Malformed CORS settings are ignored
and logged so optional CORS hardening does not crash existing endpoints;
production operators should monitor logs after changing CORS configuration.

If you need site-wide CORS behavior for views outside django-indieweb's public
protocol endpoints, configure deployment-level middleware separately.

Testing Configuration
---------------------

For testing, you might want to disable certain security features:

.. code-block:: python

   # test_settings.py
   from .settings import *

   # Disable HTTPS redirect for tests
   SECURE_SSL_REDIRECT = False

   # Use a faster password hasher
   PASSWORD_HASHERS = [
       'django.contrib.auth.hashers.MD5PasswordHasher',
   ]

   # Shorter auth code timeout for faster tests
   INDIWEB_AUTH_CODE_TIMEOUT = 5

Performance Optimization
------------------------

Database Indexes
~~~~~~~~~~~~~~~~

The Token model already has an index on the ``key`` field. For better performance
with many tokens, consider adding indexes on commonly queried fields:

.. code-block:: python

   # In a migration
   migrations.AddIndex(
       model_name='token',
       index=models.Index(fields=['owner', 'client_id']),
   )

Caching
~~~~~~~

Cache token lookups for better performance:

.. code-block:: python

   # myapp/views.py
   from django.core.cache import cache
   from indieweb.models import Token

   def get_token(key):
       cache_key = f'token_{key}'
       token = cache.get(cache_key)

       if token is None:
           try:
               token = Token.objects.select_related('owner').get(key=key)
               cache.set(cache_key, token, 300)  # Cache for 5 minutes
           except Token.DoesNotExist:
               return None

       return token
