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

Bundled Browser UI Assets
-------------------------

The bundled IndieAuth consent page and token-management page load their
package stylesheet from ``static/css/indieweb.css``. Ensure your deployment's
normal static-file collection/serving setup includes django-indieweb's package
static files if you use those default templates.

The consent page sends ``X-Frame-Options: DENY`` and
``Content-Security-Policy: frame-ancestors 'none'``. Host projects that
override ``indieweb/consent.html`` should keep consent approve/deny forms as
ordinary CSRF-protected browser POSTs and should not rely on inline styles for
frame protection.

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
(an ``http``/``https`` URL with no userinfo and no fragment) at the
authorization/token paths — the authorization GET, the consent approval POST,
the consent denial POST, the code-verification POST, and the token endpoint
POST — and again on the resource-server path inside ``TokenAuthMixin``. The
latter is intentional:
operator policy may evolve and revoke a previously-allowed ``client_id``, in
which case existing tokens for that client must stop working immediately.
Before the callable is invoked, django-indieweb normalizes the policy input by
lowercasing the URL scheme and host, converting Unicode hostnames to IDNA ASCII
form, and preserving path, parameters, query string, fragment, and port
semantics. The submitted value is still displayed, stored on ``Auth``/``Token``
rows, and returned in protocol responses unchanged.

**Example:**

.. code-block:: python

   # myapp/indieauth.py
   _ALLOWLIST = {"https://quill.p3k.io/", "https://micropublish.net/"}

   def is_allowed_client(client_id: str) -> bool:
       return client_id in _ALLOWLIST

.. code-block:: python

   # settings.py
   INDIEWEB_CLIENT_ID_VALIDATOR = "myapp.indieauth.is_allowed_client"

INDIEWEB_ALLOWED_CLIENT_IDS
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional exact allowlist for production deployments that do not need a custom
``INDIEWEB_CLIENT_ID_VALIDATOR`` callable.

**Default:** ``None`` (no built-in allowlist restriction)

When set to a string or iterable of strings, every submitted or stored
``client_id`` must match one normalized allowlist entry. Entries use the same
comparison form as ``INDIEWEB_CLIENT_ID_VALIDATOR``: scheme/host case and IDNA
host forms are normalized, while path, parameters, query string, and ports
remain significant. Invalid allowlist entries fail closed and reject clients
until the setting is fixed.

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_ALLOWED_CLIENT_IDS = (
       "https://quill.p3k.io/",
       "https://micropublish.net/",
   )

``INDIEWEB_ALLOWED_CLIENT_IDS`` and ``INDIEWEB_CLIENT_ID_VALIDATOR`` can be
combined. In that case the client must pass the allowlist first and the custom
validator second.

INDIEWEB_REQUIRE_PKCE
~~~~~~~~~~~~~~~~~~~~~

Require authorization requests and consent approvals to include valid PKCE
parameters before an authorization code can be issued.

**Default:** ``False`` (legacy clients without PKCE remain accepted)

When enabled, omitted ``code_challenge`` values are rejected with HTTP 400
``invalid_request`` on both authorization GET and consent approval POST.
Both ``plain`` and ``S256`` remain accepted unless
``INDIEWEB_REQUIRE_PKCE_S256`` is also enabled. Token exchange behavior is
unchanged: when a challenge was stored with the authorization code, a matching
``code_verifier`` is required.

INDIEWEB_REQUIRE_PKCE_S256
~~~~~~~~~~~~~~~~~~~~~~~~~~

Require PKCE and allow only the ``S256`` challenge method for newly issued
authorization codes.

**Default:** ``False``

When enabled, omitted PKCE and ``plain`` challenges are rejected with HTTP 400
``invalid_request`` before an authorization code is issued. The public
IndieAuth metadata response advertises only ``["S256"]`` in
``code_challenge_methods_supported`` while this policy is active.

INDIEWEB_BIND_ME_TO_USER
~~~~~~~~~~~~~~~~~~~~~~~~

Bind the requested IndieAuth ``me`` URL to the logged-in Django user's
configured h-card profile URL.

**Default:** ``False``

When disabled, the bundled consent screen still shows the logged-in user's
configured profile URL from ``user.indieweb_profile.url`` when one exists, and
warns when the submitted ``me`` differs. When enabled, authorization GET and
consent POST requests fail closed with HTTP 400 ``invalid me`` if the user has
no configured profile URL or if the submitted ``me`` does not match it. Matching
uses the same URL comparison policy as redirect URI binding: scheme/host case,
IDNA host form, default ports, percent-encoded triplet case, and root
empty-path/``/`` equivalence are normalized while non-default ports, non-root
paths, and query strings remain significant.

.. note::
   If ``INDIEWEB_ALLOWED_CLIENT_IDS`` is invalid, the configured validator
   dotted path fails to import, or the validator callable raises, client policy
   rejects the request (fail-closed). Misconfiguration cannot silently weaken
   access control. The exact response shape depends on the call site: the
   authorization endpoint and the code-verification POST return HTTP 400 with
   a plain-text ``invalid_client`` body; the token endpoint returns HTTP 400
   with body ``invalid_request`` and content type
   ``application/x-www-form-urlencoded`` (matching the existing missing-
   ``code`` case); and the Micropub resource-server path returns HTTP 403
   with body ``invalid_client``.

.. note::
   Stored ``client_id`` values are not re-validated *structurally* on use,
   matching the ``redirect_uri`` rule. Configured client policy IS re-applied
   on use, so revoking a previously-allowed client takes effect immediately
   for existing tokens. A token issued before ``client_id`` access control
   existed (or by an out-of-band script) keeps working as long as it satisfies
   configured client policy, or no client policy is configured.

INDIEWEB_REDIRECT_URI_ALLOWLIST
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional per-client redirect URI allowlist. When a ``client_id`` appears as a
key in the mapping, the listed redirect URIs replace the default same-origin
``client_id``/``redirect_uri`` binding for that client.

**Default:** ``None`` (built-in same-origin binding applies to every client)

The mapping value is a list (or tuple) of allowlist entries. Each entry is a
URL string compared against the submitted ``redirect_uri`` after origin
normalization (scheme, IDNA-encoded host, default-port collapsing). Entries
with a trailing ``/`` are *prefix* entries — the candidate must share the
entry's origin and its path must start with the entry's path. Entries without
a trailing slash are *exact* entries — origin, path, and query string must all
match. Fragments on either side are rejected. Invalid mapping values
(non-list/tuple, non-string entries) fail closed for that client.

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_REDIRECT_URI_ALLOWLIST = {
       "https://client.example/": [
           "https://callback.example/oauth/cb",       # exact entry
           "https://callback.example/oauth/",         # prefix entry
       ],
   }

INDIEWEB_REDIRECT_URI_VALIDATOR
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional dotted path to a callable
``(client_id: str, redirect_uri: str) -> bool`` that decides whether a
``redirect_uri`` is bound to its ``client_id``.

**Default:** ``None`` (built-in same-origin rule applies, optionally overridden
per-client by ``INDIEWEB_REDIRECT_URI_ALLOWLIST``)

When set, the validator short-circuits both the default same-origin rule and
``INDIEWEB_REDIRECT_URI_ALLOWLIST``. The callable receives the originally
submitted strings (no normalization). Import errors, non-callable values,
exceptions raised inside the callable, and non-bool return values fail closed
so a misconfigured policy cannot silently weaken access control.

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_REDIRECT_URI_VALIDATOR = "myapp.indieauth.is_allowed_redirect"

.. warning::
   The redirect URI binding is enforced by default. Deployments that
   previously relied on cross-origin ``client_id``/``redirect_uri`` pairs
   without configuring a custom validator must add the necessary entries to
   ``INDIEWEB_REDIRECT_URI_ALLOWLIST`` or set
   ``INDIEWEB_REDIRECT_URI_VALIDATOR`` before upgrading; otherwise the
   authorization endpoint returns HTTP 400 ``invalid redirect_uri for
   client_id``.

INDIEWEB_TOKEN_INTROSPECTION_AUTHORIZER
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional dotted path to a callable
``(caller_token, target_token) -> bool`` that gates which target tokens an
authenticated introspection caller may see.

**Default:** ``None`` (built-in same-``client_id`` rule applies)

Without a configured authorizer the token introspection endpoint at
``/indieweb/token/introspect/`` enforces RFC 7662 §2.1 narrowly: a caller may
only introspect tokens issued to its own ``client_id``, after the same scheme,
host, and IDNA host normalization that other ``client_id`` policy hooks use.
Cross-client and cross-owner lookups return ``{"active": false}`` without
disclosing scope, ``me``, or expiry.

When set, the configured callable is invoked **after** the existing
authentication, owner, and target-token validity checks. It receives the
``Token`` instances for the caller and the proposed target. Only returning
the literal ``True`` allows the active introspection response; any other
return value (including ``False``, ``None``, truthy non-bool values such as
``"allow"`` or ``1``, and falsy non-bool values such as ``0`` or ``""``)
returns ``{"active": false}``. Import failures, callable exceptions, and
non-callable values also fail closed.

**Example:**

.. code-block:: python

   # myapp/indieauth.py
   _RESOURCE_SERVER_CLIENT_IDS = {"https://resource-server.example.org/"}

   def introspection_authorizer(caller_token, target_token) -> bool:
       """Allow a single first-party resource server to introspect every token."""
       return caller_token.client_id in _RESOURCE_SERVER_CLIENT_IDS

.. code-block:: python

   # settings.py
   INDIEWEB_TOKEN_INTROSPECTION_AUTHORIZER = "myapp.indieauth.introspection_authorizer"

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

The following is a hardened production starting point. Tune it for your
traffic patterns, trusted clients, queue capacity, and upstream deployment
limits:

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
- ``webmention_status`` - ``/indieweb/webmention/<status-token>/``

Counters are isolated by endpoint key, HTTP method, and client identity, so
``GET`` and ``POST`` requests to the same endpoint use independent counters.
Set each endpoint limit as a per-method budget. The client identity is
``request.META["REMOTE_ADDR"]`` by default, and the value is HMAC-digested with
Django's ``SECRET_KEY`` before it is used in cache keys. django-indieweb does
not read or trust ``X-Forwarded-For`` directly. If your site runs behind a
reverse proxy, load balancer, CDN, or platform router, configure that trusted
infrastructure so Django receives the correct client address in
``REMOTE_ADDR`` before enabling IP-based limits.

Cache backend choice affects the strength of the limit. Django's default
``LocMemCache`` is local to one process, so multi-worker deployments can allow
roughly ``limit`` requests per worker during each window. Use a shared cache
backend such as Redis or Memcached when you need deployment-wide counters.
``DummyCache`` does not persist counters and effectively disables built-in
rate limiting. The built-in limiter uses Django's portable cache primitives,
so its ``add``/``incr`` sequence is best-effort rather than a hard atomic
primitive on every backend. For adversarial environments that need strict
single-counter semantics, put a purpose-built limiter in front of Django, such
as a reverse proxy rule or a Redis Lua-script-based limiter.

When a limit is exceeded, the endpoint returns HTTP ``429`` with a plain-text
``rate limit exceeded`` body. A ``Retry-After`` header is included using the
cache-backed window reset time, or the configured ``window`` when the reset
marker has been evicted. Requests under the limit continue through the existing
view code unchanged, including authentication, authorization, Micropub handler
calls, media storage, Webmention processing, and async Webmention enqueueing.

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

Handlers are also the host-owned authorization boundary for content and media
ownership. After django-indieweb authenticates the bearer token and checks the
requested scope, the configured handler must verify that the authenticated
``user`` may create, update, delete, undelete, read source content, list
content or media, and delete media for the submitted URL or storage object. The
bundled ``InMemoryMicropubHandler`` is an unsafe development/testing example
only and performs no ownership checks.

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

INDIEWEB_MEDIA_MAX_UPLOAD_COUNT
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Maximum number of uploaded files accepted in one Micropub media request. This
applies to direct ``file`` uploads sent to ``/indieweb/media/`` and to
multipart ``photo`` file parts sent to ``/indieweb/micropub/`` create
requests.

**Default:** ``10``

Requests with more uploaded files than this limit are rejected with HTTP 413
and body ``invalid_request`` before storage is called. Direct media endpoint
uploads still accept exactly one ``file`` part; the count setting prevents
clients from smuggling extra file parts into the same multipart request.

Set this to ``None`` to disable django-indieweb's upload-count check. Keep a
deployment-level multipart part limit in place when disabling it.

INDIEWEB_MEDIA_MAX_UPLOAD_TOTAL_BYTES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Maximum aggregate byte size accepted across all uploaded files in one
Micropub media request. This complements
``INDIEWEB_MEDIA_MAX_UPLOAD_BYTES``, which applies to each individual file.

**Default:** ``52428800`` (50 MiB)

Requests whose uploaded files exceed this aggregate limit are rejected with
HTTP 413 and body ``invalid_request`` before storage is called. Uploads whose
size is unknown are rejected instead of being counted as zero bytes.

Set this to ``None`` to disable django-indieweb's aggregate upload-size check.
If you do that, enforce total body limits with Django, your ASGI/WSGI server,
reverse proxy, CDN, or storage backend.

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

Uploads are sniffed with the maintained ``filetype`` library before storage.
django-indieweb compares the sniffed media type, the submitted part
``Content-Type``, and the submitted filename suffix. Unknown formats,
declared/sniffed mismatches, and suffix mismatches are rejected with HTTP 415
and body ``invalid_request`` before storage is called. Stored object names are
unguessable keys under ``indieweb/media/`` and use a suffix derived from the
validated media type, not from the client filename.

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_MEDIA_ALLOWED_TYPES = ("image/jpeg", "image/png", "image/webp")

Set this to ``None`` to disable only django-indieweb's configured allowlist.
It does not make filenames or client headers trusted: uploads must still be a
known sniffed format and must still match their declared content type and
filename suffix. If you broaden accepted media types, serve uploads from a
separate origin where possible and add defensive response headers such as
``X-Content-Type-Options: nosniff`` and ``Content-Disposition: attachment``
for non-image or otherwise risky media.

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

INDIEWEB_MICROPUB_URL_POLICY
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional dotted path to a callable that gates submitted URLs for the Micropub
entry source query (``GET /indieweb/micropub/?q=source&url=...``), the media
source-by-URL query (``GET /indieweb/media/?q=source&url=...``), and the media
delete action (``POST /indieweb/media/`` with ``action=delete``). The callable
runs *before* the URL is forwarded to the configured handler.

**Default:** ``None`` (no view-level URL gate; submitted URLs are passed
unchanged to the handler, preserving the historical compatibility default)

The callable signature is::

   def policy(url: str, kind: Literal["entry", "media"], request: HttpRequest) -> bool: ...

Return ``True`` to permit the request; any other value (``False``, a non-bool
truthy value, ``None``) results in ``400 invalid_request`` and the handler is
not invoked. Exceptions raised by the callable, import failures, and
non-callable resolutions fail closed: the request returns ``500`` and the
underlying error is logged via ``logger.exception`` / ``logger.error``.

The hook intentionally avoids a hard same-host rule because media may live on
storage or CDN hosts that are distinct from the resource server. Hosts with
stricter requirements should encode them in their callable (e.g. allow only
URLs whose scheme is ``https`` and whose host is in an operator-controlled
allowlist of public origin and storage hosts).

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_MICROPUB_URL_POLICY = "your_project.micropub_policy.allow_only_owned_urls"

The callable is the host-owned authorization boundary for cross-origin or
storage-external URL submissions; it complements (not replaces) the
ownership checks the configured ``INDIEWEB_MICROPUB_HANDLER`` performs.

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

Hub URLs are outbound server-to-server targets. ``notify_hubs()`` and
``request_websub_subscription()`` reject loopback, private, link-local,
multicast, reserved, metadata-service, and other non-global IP destinations
after DNS resolution and after every redirect. Keep
``INDIEWEB_WEBSUB_HUBS`` operator-controlled; do not template hub URLs from
request data or user-editable content.

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
Malformed values, including an empty environment variable that resolves to
``""``, are ignored and logged; the callback falls back to the default 1 MiB
limit rather than disabling the cap.
The callback rejects an oversized ``Content-Length`` before reading the body
when the header is present. Also configure a tight Django
``DATA_UPLOAD_MAX_MEMORY_SIZE`` and matching reverse-proxy request-body limit
so oversized or malformed requests are stopped before they reach application
workers.

INDIEWEB_WEBSUB_HUB_RESPONSE_MAX_BYTES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Maximum decoded response size accepted from a WebSub hub for outbound
subscribe and publish requests.

**Default:** ``262144`` (256 KiB)

WebSub hub responses are typically small acknowledgements; the cap protects
django-indieweb against hostile or misconfigured hubs that return large or
compressed-bomb payloads. Hub responses above this limit are surfaced as
request failures rather than buffered into memory:
``request_websub_subscription()`` records the failure on the subscription's
``last_request_error`` diagnostics, and ``notify_hubs()`` returns it on the
``WebSubNotificationResult.error`` field for the hub.

Set this to ``None`` to disable the cap when your deployment already enforces
an equivalent limit. Malformed values, including an empty environment variable
that resolves to ``""``, are ignored and logged; outbound requests fall back
to the 256 KiB default instead of disabling the cap or failing every hub
call.

INDIEWEB_MICROPUB_SERVER_MANAGED_PROPERTIES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional iterable of additional Micropub property names that the resource
server manages and that clients must not submit.

**Default:** ``()`` (only the spec-mandated ``uid`` and ``author`` are denied)

Configured names extend the built-in deny-list (``uid``, ``author``); they
never replace it. The check applies consistently to create and update
(``replace`` / ``add`` / ``delete``) operations across both form-encoded and
JSON Micropub requests. Use this when the host adapter keys on internal
property names such as ``_owner``, ``_status``, or other reserved fields and
needs to reject client-supplied values for those properties before the
handler runs.

**Example:**

.. code-block:: python

   INDIEWEB_MICROPUB_SERVER_MANAGED_PROPERTIES = ("_owner", "_status")

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
For production, keep this hook short and hand accepted deliveries to a
host-owned queue or job table; feed parsing and persistence should not run
inline in the callback request.

``hub.secret`` values stored on ``WebSubSubscription`` are encrypted at rest
with key material derived from Django's ``SECRET_KEY``. Raw secrets are still
needed briefly at runtime to validate hub HMAC signatures. To rotate
``SECRET_KEY`` without re-subscribing every feed, add the previous value to
``SECRET_KEY_FALLBACKS``: decryption tries the primary key first and then each
fallback in declaration order, while new encryption always uses the primary
key. Every save of a ``WebSubSubscription`` row passively re-encrypts a
fallback-bound ciphertext under the primary, so existing subscriptions migrate
to the new key on the next save — including renewals that omit ``secret`` and
lease/state bookkeeping saves that pass an ``update_fields`` list. Operators
can therefore remove the old value from ``SECRET_KEY_FALLBACKS`` once every
active subscription has been saved at least once under the new primary.
Secrets passed to
``request_websub_subscription()`` must be non-empty, at least 20 bytes when
UTF-8 encoded, and at most 200 bytes when UTF-8 encoded. Renewal requests
preserve the existing stored secret when
``request_websub_subscription()`` is called with ``secret=None`` and clear any
earlier unverified staged secret. When a renewal request provides a new secret,
that value is staged and only becomes the active delivery secret after the hub
verifies the renewal; failed renewal requests keep the previous secret.
If the encryption key material is no longer available during migration
rollback, the reverse migration leaves encrypted values in place and logs a
warning before the schema narrows the storage columns.

For production, subscribe with a strong ``hub.secret`` for every topic. Set
``INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES = True`` if unsigned deliveries
should be rejected even for legacy rows without stored secrets.
``X-Hub-Signature-256`` is preferred over legacy ``X-Hub-Signature`` when both
headers are present. ``sha1`` signatures are rejected by default; set
``INDIEWEB_WEBSUB_ALLOW_SHA1_SIGNATURES = True`` only for a hub that cannot
send SHA-256 signatures.

Accepted delivery bodies are replay-checked for 300 seconds by default against
every retained accepted SHA-256 digest on the subscription, so a captured
payload A cannot be replayed after a different legitimate payload B has been
accepted. Set ``INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS`` to a
non-negative integer, or to ``None`` or ``0`` to disable this in-process
replay window. The history is bounded by
``INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX`` (default 64) so a hub that
accepts many distinct payloads inside the window cannot grow the cache without
bound. When the cap is reached, the oldest accepted digest is evicted: a
sufficiently old replay against a high-volume subscription may slip past the
check. The default of 64 suits most subscriptions; a high-volume topic that
receives more than 64 distinct delivery bodies inside the replay window can
evict older accepted digests before the window closes, leaving room for an
attacker who captured one of those bodies to replay it. Tune the cap to match
your hubs' burst rate, or set this to ``0`` to opt into "unbounded by count"
semantics — pruning is then purely time-based by the replay window. Signed
deployments that want every accepted body retained for the full window
should set the cap to ``0``. Set this to ``None`` to disable history pruning
entirely (equivalent to ``0`` for the count-eviction path; both leave
window-based pruning in place). Malformed values, including an empty
environment variable that resolves to ``""``, are ignored and logged; the
helper falls back to the default cap rather than disabling it. Entries older
than the replay window are pruned on every accepted delivery regardless of
the history cap.
Subscribe verification clamps confirmed lease durations to the configured
``INDIEWEB_WEBSUB_MIN_LEASE_SECONDS`` and
``INDIEWEB_WEBSUB_MAX_LEASE_SECONDS`` bounds. Defaults are 300 seconds and 30
days. Both bounds are themselves clamped to a sane range of 60 seconds to 90
days: out-of-range configuration is logged and pulled to the nearest in-range
value so a misconfigured ``min=1`` cannot accept one-second leases and a
misconfigured ``max=10**12`` cannot accept multi-thousand-year leases. If the
configured pair would invert after parsing, the helper falls back to the
defaults.

See :doc:`websub` and ``examples/websub_workflows.py`` for tested
copy-and-adapt delivery hook examples that enqueue a compact payload for a
host-owned worker. The examples keep feed parsing, entry persistence, queue
choice, retry behavior, and delivery body storage policy outside
django-indieweb.

INDIEWEB_WEBSUB_DELIVERY_ENQUEUE
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional dotted path to a callable that hands accepted WebSub deliveries to a
host-owned queue instead of running ``INDIEWEB_WEBSUB_DELIVERY_HOOK`` inline in
the callback request thread.

**Default:** ``None`` (deliveries run synchronously through
``INDIEWEB_WEBSUB_DELIVERY_HOOK`` if configured)

The callable receives the same keyword arguments as
``INDIEWEB_WEBSUB_DELIVERY_HOOK`` so a host can reuse one handler implementation
for either delivery mode:

.. code-block:: python

   def enqueue_delivery(*, subscription_id, hub_url, topic_url, body, headers):
       ...

When set, the callback view validates the token, active subscription state,
size and content-type limits, signature, and replay guard before invoking the
enqueue callable. On a successful enqueue the view returns HTTP ``204`` and
records the delivery as accepted; ``INDIEWEB_WEBSUB_DELIVERY_HOOK`` is
**not** called inline. The host's queue worker is responsible for running the
delivery hook (or any equivalent processing) later. Import failures,
non-callables, and exceptions raised by the enqueue callable are logged,
recorded on the subscription row with ``delivery enqueue failed``, and returned
as HTTP ``500`` so the hub retries.

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_WEBSUB_DELIVERY_ENQUEUE = "myapp.websub.enqueue_delivery"

.. code-block:: python

   # myapp/websub.py
   from myapp.tasks import process_websub_delivery_task

   def enqueue_delivery(*, subscription_id, hub_url, topic_url, body, headers):
       process_websub_delivery_task.delay(
           subscription_id=subscription_id,
           hub_url=hub_url,
           topic_url=topic_url,
           body=body,
           headers=headers,
       )

Production deployments should prefer queued processing. Synchronous deliveries
still run under bounded size and content-type limits, but feed parsing and
persistence should not run inline in the callback request.

.. note::
   ``INDIEWEB_WEBSUB_DELIVERY_ENQUEUE`` and ``INDIEWEB_WEBSUB_DELIVERY_HOOK``
   are mutually exclusive at request time: when both are set, the callback
   view enqueues the delivery and skips the inline hook. The queued worker is
   expected to call the host's delivery handler itself.

WebSub Subscriber Models and Commands
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``WebSubSubscription`` stores host-level subscriber state for a hub/topic pair,
including tokenized callback identity, pending verification mode, lease
metadata, encrypted staged ``hub.secret`` values, latest request diagnostics, latest
denial diagnostics, and latest delivery diagnostics.

``WebSubDeliveryAttempt`` stores metadata-only delivery history linked to a
subscription. It records received time, content type, byte size, SHA-256
digest, signature algorithm, HTTP status code, and bounded error text. It does
not store raw hub delivery bodies or parsed feed content. The table is
append-only from the callback path and Django admin does not allow deleting
attempt rows, so high-volume subscribers should choose an explicit host-owned
retention policy that matches their operational needs, for example:

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
``/indieweb/webmention/<status-token>/``. Source fetching, target-link verification,
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

Production deployments should prefer queued processing. Synchronous receiving
uses bounded fetches and parser work limits, but it still performs network
fetching and parsing in the request path. Pair the queue with deployment-level
request limits and an ``INDIEWEB_RATE_LIMITS`` entry for the ``webmention``
endpoint.

.. note::
   If the configured path cannot be imported, resolves to a non-callable, or
   raises while enqueueing, the receive endpoint returns HTTP 500 and does not
   fall back to inline processing. Invalid receive requests still return HTTP
   400 before the hook is loaded or called. Import and non-callable failures
   happen before a row is persisted; if the callable itself raises, the
   ``Webmention`` row has already been created or reused and remains
   ``pending`` until a queue retry path or manual cleanup reconciles it.

INDIEWEB_WEBMENTION_FETCH_MAX_BYTES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Maximum decoded response size accepted for receive-side Webmention source and
Vouch fetches.

**Default:** ``1048576`` (1 MiB)

Responses are streamed and counted while decoded chunks are read. Responses
over this limit mark the Webmention ``failed`` and are not stored as source
snapshots. Set this to ``None`` only when an upstream proxy, queue, or worker
boundary enforces an equivalent limit.

INDIEWEB_WEBMENTION_RESPONSE_MAX_BYTES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Maximum decoded response size accepted from a remote Webmention endpoint
during outbound delivery (``WebmentionSender.send_webmention``).

**Default:** ``1048576`` (1 MiB)

Responses are streamed and counted while decoded chunks are read. A hostile
endpoint that returns more than the configured limit causes the delivery to
be reported as a failure (``success=False``, ``status_code=None``,
``error="response too large: ..."``) instead of buffering the unbounded body.
Set this to ``None`` only when an upstream proxy, queue, or worker boundary
enforces an equivalent limit; malformed values fall back to the default cap.

INDIEWEB_WEBMENTION_NESTED_RESPONSE_MAX_DEPTH
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Maximum nested ``h-entry``/``h-card`` child depth inspected when extracting
Webmention/Salmention response candidates and when running the fallback
``h-entry``/``h-card``/page-level-author traversals on a parsed source
document. The microformats walks are iterative and bail out once the depth
cap is reached, so a maliciously deep ``children`` chain cannot exhaust the
Python recursion limit.

**Default:** ``8``

INDIEWEB_WEBMENTION_NESTED_RESPONSE_MAX_CANDIDATES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Maximum nested response candidates persisted for one verified source page.

**Default:** ``100``

INDIEWEB_WEBMENTION_SEARCH_MAX_ITEMS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Maximum parsed microformats items scanned while looking for the ``h-entry``
that mentions the submitted target, and while running the fallback
``h-entry``/``h-card``/page-level-author traversals on the same document.
The walks return whatever they have found so far when the budget is exhausted
rather than scanning unbounded.

**Default:** ``1000``

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

INDIEWEB_WEBMENTION_STATUS_PUBLIC
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Restrict the Webmention status endpoint response to a minimal public-safe
shape.

**Default:** ``False``

Status URLs at ``/indieweb/webmention/<status-token>/`` use opaque,
high-entropy ``status_token`` values, but a leaked status URL still reveals
the stored ``source`` URL, ``target`` URL, current ``status``, and
``verified_at`` timestamp to anyone who holds the token. The default
behavior treats this as token-holder diagnostics and is unchanged.

When set to ``True``, ``WebmentionStatusView`` returns only ``status`` and,
when set, ``verified_at``. The ``source`` and ``target`` URLs are omitted,
and no Vouch fields are exposed (they are also omitted in the default
response). This avoids leaking private or draft post URLs through a
forwarded ``Location`` header or a sender's logs.

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_WEBMENTION_STATUS_PUBLIC = True

.. note::
   Senders that follow the ``202 Accepted`` ``Location`` header to poll the
   status endpoint can still observe ``status`` (and ``verified_at`` once
   verified). They do not need ``source``/``target`` echoed back, since they
   already know which URL pair they submitted.

Salmention Configuration
~~~~~~~~~~~~~~~~~~~~~~~~

django-indieweb persists verified Webmention source snapshots and stable nested
child response rows as a foundation for receive-side Salmention support, and
the bundled ``show_webmentions`` template tag renders verified children inline
under verified parent replies. Outbound sender support records ordinary
``WebmentionSender.send_webmentions()`` delivery attempts to the outbound
target-history table by default and exposes
``WebmentionSender.resend_salmentions()`` for application-triggered union-of-
current-and-historical resends. The ``send_webmentions`` management command
also exposes this workflow with ``--salmention-resend`` for operator-triggered
resends and ``--dry-run --salmention-resend`` previews.

Resends remain explicit: receiving a Webmention never automatically triggers a
Salmention resend. Host applications or operators call the sender API or
management command after the source permalink has actually changed.

``INDIEWEB_SALMENTION_RESEND_COOLDOWN_SECONDS`` controls the cooldown for
historical-only targets after recent resend attempts, including no-endpoint
outcomes.

**Default:** ``86400`` (24 hours)

``INDIEWEB_SALMENTION_SUCCESS_CUTOFF_SECONDS`` controls when successful
historical-only targets are skipped so removed links are not re-pinged
forever. The cutoff is measured from ``last_seen_in_source_at`` when available,
with send/attempt/create timestamps used as fallbacks for older rows. Set this
to ``None`` to disable the successful-target cutoff.

**Default:** ``2592000`` (30 days)

``INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES`` controls when a
historical-only target row is deleted after repeated failures. Failures include
failed deliveries and no-endpoint outcomes. Successful deliveries reset the
counter. Current targets are still attempted even if their historical state
would otherwise be skipped or dropped.

**Default:** ``5``

**Example:**

.. code-block:: python

   INDIEWEB_SALMENTION_RESEND_COOLDOWN_SECONDS = 6 * 60 * 60
   INDIEWEB_SALMENTION_SUCCESS_CUTOFF_SECONDS = 14 * 24 * 60 * 60
   INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES = 3

See :doc:`webmention` for the support-status details, target-history design,
and current ordinary Webmention reprocessing behavior.

Webmention.io Host Integrations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

There is no Webmention.io setting in django-indieweb. Host projects that use
Webmention.io own their API token, endpoint advertisement, client code,
import/display layer, caching, moderation, sanitization, and scheduling outside
this package. Do not configure ``WEBMENTION_IO_TOKEN`` or a similar value as a
django-indieweb core setting.

The built-in Webmention URLs remain ``/indieweb/webmention/`` and
``/indieweb/webmention/<status-token>/``. A host may choose to advertise Webmention.io's
external endpoint on selected pages instead of django-indieweb's endpoint, or
may fetch Webmention.io JF2 from host code and display/import it alongside
built-in ``Webmention`` rows. See :doc:`webmention` for mapping and HTML
sanitization guidance.

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
- ``/indieweb/webmention/<status-token>/`` - Webmention status endpoint

The bundled URLconf does not create a Microsub endpoint, reader feed endpoint,
reader timeline, following/muting/blocking endpoint, reader UI, or
Webmention.io endpoint/dashboard. There is no Microsub setting or Webmention.io
token setting in django-indieweb; host projects that add reader-side protocols
or Webmention.io integrations own those URLs, storage models, authorization
policy, discovery or metadata behavior, credentials, sanitization, and
documentation.

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
       path('webmention/<str:status_token>/', views.WebmentionStatusView.as_view(), name='webmention-status'),
   ]

Middleware Configuration
------------------------

CSRF Exemption
~~~~~~~~~~~~~~

Most IndieWeb protocol views are automatically exempt from CSRF protection.
This is necessary for token and Micropub endpoints to accept POST requests
from external clients, and for the WebSub subscriber callback to accept
server-to-server hub deliveries. The browser consent approve/deny POST branch
of ``AuthView`` is the exception: it enforces Django CSRF protection because it
is a logged-in browser state-changing flow. The legacy authorization-code
verification POST to the same endpoint remains CSRF-exempt.

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

django-indieweb currently creates nine models:

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
   lease metadata, encrypted delivery secrets, latest request diagnostics,
   latest delivery metadata, and accepted-delivery replay metadata
8. **WebSubDeliveryAttempt** - Stores metadata-only WebSub delivery-attempt
   audit rows linked to a ``WebSubSubscription``
9. **Profile** - Stores user h-card data

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

Injected HTTP Clients
~~~~~~~~~~~~~~~~~~~~~

Several django-indieweb APIs (``WebmentionProcessor``,
``process_queued_webmention``, ``WebmentionSender.discover_endpoint``,
``WebmentionSender.send_webmention``, ``WebmentionSender.fetch_content``,
``notify_hubs``, ``request_websub_subscription``) accept an optional
``client`` keyword that takes an ``httpx.Client`` instance. When a caller
provides one, django-indieweb trusts the transport: DNS-based SSRF blocking
and IP pinning are not applied to that client's requests. Production
deployments should leave ``client`` unset so the package-managed client and
SSRF safety checks apply. Treat the injection point as a test/integration
escape hatch and review the source docstrings in
``src/indieweb/processors.py``, ``src/indieweb/senders.py``, and
``src/indieweb/websub.py`` before using it. See the prominent warnings in
:doc:`webmention` and :doc:`websub` for details.

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
- ``/indieweb/webmention/<status-token>/``

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
receive ``Vary: Origin``. Disallowed origins receive no permissive CORS
headers, and origin-dependent responses include ``Vary: Origin`` so shared
caches do not reuse an origin-specific decision for another browser origin.

For allow-all deployments:

.. code-block:: python

   INDIEWEB_CORS_ALLOWED_ORIGINS = "*"

When allow-all is used without credentials, responses send
``Access-Control-Allow-Origin: *`` and do not vary by origin. When allow-all is
combined with ``INDIEWEB_CORS_ALLOW_CREDENTIALS = True``, django-indieweb
logs a warning, ignores the credential setting, and keeps the non-credential
wildcard behavior. It never emits ``Access-Control-Allow-Credentials: true``
with wildcard origins.

INDIEWEB_CORS_ALLOW_CREDENTIALS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Whether to add ``Access-Control-Allow-Credentials: true`` on allowed CORS
responses.

**Default:** ``False``

Enable this only when browser clients need credentialed CORS semantics. Bearer
token authentication remains unchanged; CORS does not authorize requests and
does not replace endpoint authentication, authorization, or scope checks.
This setting is unsupported with ``INDIEWEB_CORS_ALLOWED_ORIGINS = "*"`` and
is ignored for that combination.

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
If another middleware or view has already set ``Access-Control-Allow-Origin``
on a response, django-indieweb does not overwrite it. It preserves the
downstream CORS decision and adds ``Vary: Origin`` only when the existing value
is origin-specific rather than ``*``.

.. _production-hardening:

Production hardening
--------------------

The bundled defaults favour protocol compatibility (e.g., PKCE is optional,
the ``me`` parameter is not bound to the logged-in user, rate limits are
disabled). For an internet-facing IndieAuth/Micropub deployment, copy the
settings block below into your ``settings.py`` and customise for your
domain:

.. code-block:: python

   # Hardened defaults for public IndieAuth/Micropub endpoints.
   INDIEWEB_REQUIRE_PKCE = True
   INDIEWEB_REQUIRE_PKCE_S256 = True
   INDIEWEB_BIND_ME_TO_USER = True
   INDIEWEB_ALLOWED_CLIENT_IDS = [
       "https://your-trusted-app.example/",
   ]
   INDIEWEB_REDIRECT_URI_ALLOWLIST = {
       "https://your-trusted-app.example/": [
           "https://your-trusted-app.example/oauth/callback",
       ],
   }
   INDIEWEB_RATE_LIMITS = {
       "auth":                {"limit": 10,  "window": 60},
       "token":               {"limit": 20,  "window": 60},
       "token_introspection": {"limit": 60,  "window": 60},
       "micropub":            {"limit": 60,  "window": 60},
       "media":               {"limit": 30,  "window": 60},
       "webmention":          {"limit": 60,  "window": 60},
       "webmention_status":   {"limit": 30,  "window": 60},
       "websub_callback":     {"limit": 120, "window": 60},
   }
   INDIEWEB_MICROPUB_URL_POLICY = "your_project.micropub_policy.allow_only_owned_urls"
   INDIEWEB_WEBMENTION_STATUS_PUBLIC = True
   INDIEWEB_LOG_REDACTION = "redact"

Notes:

* Compatibility defaults remain non-strict for protocol interop. Override
  them in production with the block above (or your equivalent) so PKCE is
  required, the ``me`` parameter is bound to the authenticated user, and
  only known client identifiers can drive the authorization endpoint.
* ``INDIEWEB_ALLOWED_CLIENT_IDS`` is a coarse allowlist; if you need more
  flexible policy (per-environment lists, host suffix matching, etc.) use
  ``INDIEWEB_CLIENT_ID_VALIDATOR`` instead.
* ``INDIEWEB_RATE_LIMITS`` numbers above are conservative starting points;
  tune from operational data. The keys correspond to the bundled
  ``auth``, ``token``, ``token_introspection``, ``micropub``, ``media``,
  ``webmention``, ``webmention_status``, and ``websub_callback`` endpoints.
* See :doc:`indieauth` for ``INDIEWEB_REDIRECT_URI_ALLOWLIST`` semantics
  (exact entries vs trailing-``/`` prefix entries) and for the
  ``INDIEWEB_REDIRECT_URI_VALIDATOR`` policy hook.
* ``INDIEWEB_MICROPUB_URL_POLICY`` is a host-owned dotted path that gates
  submitted URLs on the entry source query and media source/delete actions
  before they reach the configured handler. Replace the placeholder above
  with a callable that returns ``True`` only for URLs your deployment
  considers safe (e.g. owned post URLs, plus your storage and CDN hosts).
  Returning anything else yields ``400 invalid_request``; raises and import
  failures fail closed with ``500``.
* ``INDIEWEB_WEBMENTION_STATUS_PUBLIC = True`` restricts the Webmention
  status endpoint response to ``status`` and (when set) ``verified_at``,
  omitting the stored ``source`` and ``target`` URLs. The default response
  shape is intended as token-holder diagnostics; enable the public-safe mode
  for deployments where a leaked status URL must not reveal the URL pair.
* ``INDIEWEB_LOG_REDACTION = "redact"`` opts INFO/WARNING log lines that
  reference IndieAuth/Micropub/Webmention/WebSub URLs and the OAuth ``state``
  parameter into a stable HMAC-SHA256 digest (truncated to 12 hex chars,
  keyed with ``SECRET_KEY``) instead of emitting the raw values. See
  :ref:`log-redaction` for details on which call sites are covered and how
  to correlate digests across log lines.

.. _log-redaction:

INDIEWEB_LOG_REDACTION
^^^^^^^^^^^^^^^^^^^^^^

Default: ``"passthrough"``.

Controls whether INFO/WARNING log lines emitted by the views, processors,
and WebSub modules render IndieAuth/Micropub URLs, the OAuth ``state``
parameter, the verified ``me`` URL, webmention/WebSub source/target URLs,
Webmention outcome URLs (410 Gone, fetch failures, vouch verification
failures, spam, success, size-limit warnings), and bearer-token /
authorization-code prefixes verbatim or as a stable HMAC-SHA256 digest.

* ``"passthrough"`` (default): URL/state/me values appear verbatim, and
  bearer tokens are rendered in the existing ``{value[:8]}...``
  diagnostic form (``redact_token`` truncates even in passthrough so the
  full credential is never written to logs). Backwards-compatible with
  existing log pipelines.
* ``"redact"``: URL/state/me/token values are replaced by a 12-character
  hex digest derived from ``SECRET_KEY``. The digest is one-way and
  stable per input, so log consumers can correlate events for the same
  value without seeing the underlying secret or URL.
  ``redact_url_origin`` (used for the ``me`` parameter) digests scheme+host
  so multiple paths under the same origin collapse to a shared digest.
  ``redact_token`` (used by ``TokenAuthMixin`` and
  ``TokenIntrospectionView`` for token-not-found / expired-token /
  duplicate-token failure logs) digests the full token so even the
  leading bytes never appear in redacted logs.

ERROR-level logs are not redacted, so operators retain full URLs for
incident response. Rotate ``SECRET_KEY`` to invalidate previously-emitted
digests; values are scoped to the current key.

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
