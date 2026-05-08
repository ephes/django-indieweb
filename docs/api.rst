API Reference
=============

This document describes the IndieWeb endpoints provided by django-indieweb.

.. note::
   The Micropub endpoint supports content creation, source query, update,
   delete, and undelete through a pluggable content handler system. See the
   :doc:`micropub` documentation for implementation details.

.. note::
   WebSub support includes publisher helpers plus a tokenized subscriber
   callback endpoint for host-owned subscriptions. It does not include a hub
   service. See :doc:`websub`.

.. seealso::

   For a copyable production-hardening settings snippet covering PKCE,
   ``me`` binding, client/redirect URI allowlists, and per-endpoint rate
   limits across the IndieAuth, Micropub, Webmention, and WebSub callback
   endpoints below, see :ref:`Production hardening <production-hardening>`
   in the configuration guide.

Endpoints Overview
------------------

django-indieweb provides these endpoints and browser views:

- ``/indieweb/auth/`` - IndieAuth authorization endpoint
- ``/indieweb/auth/metadata/`` - Public IndieAuth authorization-server metadata endpoint
- ``/indieweb/token/`` - Token endpoint for exchanging auth codes
- ``/indieweb/token/introspect/`` - Token introspection endpoint for verifying bearer tokens
- ``/indieweb/tokens/`` - Browser UI for authenticated users to view and revoke their own tokens
- ``/indieweb/micropub/`` - Micropub endpoint for creating, querying, updating, and deleting content
- ``/indieweb/media/`` - Micropub media endpoint for direct uploads and optional host-owned media source/delete hooks
- ``/indieweb/websub/<token>/`` - WebSub subscriber callback for one subscription token
- ``/indieweb/webmention/`` - Webmention endpoint for receiving webmentions
- ``/indieweb/webmention/<status-token>/`` - Webmention status endpoint

There is no bundled Microsub endpoint, reader feed endpoint, reader timeline,
following/muting/blocking endpoint, or reader UI. Host applications that need
reader-side protocols must provide that resource-server behavior themselves.
There is also no bundled Webmention.io endpoint, API client, token setting,
import command, dashboard, or display API. Host applications that use
Webmention.io own that external integration; the endpoint contracts below
describe only django-indieweb's built-in Webmention receiver and status views.

WebSub Publisher Helpers
------------------------

django-indieweb exposes publisher helpers in ``indieweb.websub`` for
host-owned feeds and topic pages.

Discovery
~~~~~~~~~

``build_websub_links(topic_url, hubs=None)`` returns one ``rel="hub"`` link per
hub and exactly one ``rel="self"`` link for the topic URL. When ``hubs`` is
omitted, hub URLs are read from ``INDIEWEB_WEBSUB_HUBS``.

``websub_link_header(topic_url, hubs=None)`` returns a combined HTTP ``Link``
header value, and ``add_websub_link_header(response, topic_url, hubs=None)``
adds or appends that header to a Django response.

For HTML templates, load ``websub_tags`` and render:

.. code-block:: django

    {% load websub_tags %}
    {% websub_link_tags "https://example.com/feed/" %}

Notification
~~~~~~~~~~~~

``notify_hubs(topic_url, hubs=None, timeout=None)`` sends a form-encoded POST
to each hub with ``hub.mode=publish`` and ``hub.url=<topic_url>``. It returns a
list of result objects containing the hub URL, topic URL, success flag, status
code when available, and error text for failed attempts.

``notify_hubs()`` and ``request_websub_subscription()`` both accept an optional
``client`` keyword that takes an ``httpx.Client``. When provided, the project
trusts the transport: DNS-based SSRF blocking and IP pinning are not applied
to that client's requests. Production callers should leave ``client`` unset so
the package-managed transport is used. See the explicit injected-client
warnings in :doc:`websub` and :doc:`webmention` and the source docstrings in
``src/indieweb/websub.py``, ``src/indieweb/senders.py``, and
``src/indieweb/processors.py`` for the full transport-trust contract.

The ``notify_websub`` management command wraps the same helper:

.. code-block:: bash

    python manage.py notify_websub https://example.com/feed/

Use repeated ``--hub`` options to override ``INDIEWEB_WEBSUB_HUBS`` for one
command invocation.

WebSub Subscriber Callback
--------------------------

**URL:** ``/indieweb/websub/<token>/``

The subscriber callback is a server-to-server endpoint for rows in
``WebSubSubscription``. The ``<token>`` path component is generated per
subscription and is intentionally unguessable.

Subscription Request Helper
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``request_websub_subscription(topic_url, hub_url, ...)`` explicitly asks a hub
to subscribe or unsubscribe a callback. It sends the WebSub form fields
``hub.mode``, ``hub.callback``, ``hub.topic``, and optional
``hub.lease_seconds``/``hub.secret``. A successful hub response leaves the row
pending until callback verification succeeds.

Verification GET
~~~~~~~~~~~~~~~~

The callback accepts verification ``GET`` requests with:

- ``hub.mode`` - ``subscribe``, ``unsubscribe``, or ``denied``
- ``hub.topic`` - the exact topic URL stored on the subscription
- ``hub.challenge`` - echoed verbatim for accepted verification requests
- ``hub.lease_seconds`` - optional lease duration on subscribe verification
- ``hub.reason`` - optional denial diagnostic when ``hub.mode=denied``

Accepted ``subscribe`` verification marks the subscription active and records
lease metadata. Accepted ``unsubscribe`` verification marks it unsubscribed.
Accepted ``denied`` callbacks record bounded denial diagnostics, clear pending
state, return HTTP ``204``, and either mark pending subscribes denied or
keep the current active subscription in place when a renewal or unsubscribe
request is denied.
Missing, mismatched, or out-of-state verification requests return a client
error and do not mutate the row.

Delivery POST
~~~~~~~~~~~~~

The callback accepts content distribution ``POST`` requests for active
subscriptions. It records delivery metadata and then calls the optional
``INDIEWEB_WEBSUB_DELIVERY_HOOK``. Successful accepted deliveries return
``204 No Content``. The package does not parse feeds or persist delivered
content. Metadata for each recorded attempt is also available in
``WebSubDeliveryAttempt`` rows linked to the subscription.

If the subscription has a stored ``hub.secret``, delivery must include a valid
SHA-256-or-stronger HMAC header. ``X-Hub-Signature-256`` is preferred over
legacy ``X-Hub-Signature`` when both are present, and ``sha1`` signatures are
disabled unless ``INDIEWEB_WEBSUB_ALLOW_SHA1_SIGNATURES`` is enabled. Invalid
signatures return HTTP ``403`` and do not call the host hook. Duplicate bodies
matching the latest accepted delivery are rejected within the configured replay
window.

IndieAuth Server Metadata
-------------------------

**URL:** ``/indieweb/auth/metadata/``

Returns public IndieAuth/OAuth authorization-server metadata as JSON. The view
does not require a logged-in user, an authorization code, or a bearer token.
It is intended for clients that discover the server through
``rel="indieauth-metadata"`` or through a host-project route such as
``/.well-known/oauth-authorization-server``.

**Example Request:**

.. code-block:: http

    GET /indieweb/auth/metadata/ HTTP/1.1
    Host: yoursite.com

**Example Response:**

.. code-block:: http

    HTTP/1.1 200 OK
    Content-Type: application/json

    {
        "issuer": "https://yoursite.com/indieweb/",
        "authorization_endpoint": "https://yoursite.com/indieweb/auth/",
        "token_endpoint": "https://yoursite.com/indieweb/token/",
        "introspection_endpoint": "https://yoursite.com/indieweb/token/introspect/",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["plain", "S256"],
        "scopes_supported": ["create", "update", "delete", "undelete", "media"],
        "service_documentation": "https://django-indieweb.readthedocs.io/en/latest/indieauth.html"
    }

Response fields:

- ``issuer`` - Absolute issuer URL built from the request. For the bundled
  mounted endpoint this is the common mount prefix, such as
  ``https://yoursite.com/indieweb/``. For a host-level well-known route to the
  same view this is the site root, such as ``https://yoursite.com/``.
- ``authorization_endpoint`` - Absolute URL for ``/indieweb/auth/`` or the
  equivalent namespaced mount path.
- ``token_endpoint`` - Absolute URL for ``/indieweb/token/`` or the equivalent
  namespaced mount path.
- ``introspection_endpoint`` - Absolute URL for
  ``/indieweb/token/introspect/`` or the equivalent namespaced mount path.
- ``response_types_supported`` - ``["code"]``.
- ``grant_types_supported`` - ``["authorization_code"]``, matching the token
  endpoint's authorization-code exchange behavior.
- ``code_challenge_methods_supported`` - ``["plain", "S256"]`` by default,
  matching the PKCE methods accepted by the authorization and token endpoints.
  When ``INDIEWEB_REQUIRE_PKCE_S256`` is enabled, this is ``["S256"]``.
- ``scopes_supported`` - Built-in Micropub resource-server scopes advertised by
  django-indieweb: ``create``, ``update``, ``delete``, ``undelete``, and
  ``media``. Unknown extension scopes can still be requested and stored, and
  the legacy ``post`` alias is still accepted for create requests, but those
  values are not advertised as built-in capabilities. The extension ``draft``
  scope is also not advertised; django-indieweb stores it like any other
  unknown scope and leaves draft-only permission policy to host code.
  Reader-oriented extension scopes such as ``read``, ``follow``, ``mute``,
  ``block``, and ``channels`` are likewise not advertised because
  django-indieweb does not implement Microsub or other built-in reader-side
  resource-server behavior.
- ``service_documentation`` - Human-facing documentation URL for
  django-indieweb's IndieAuth behavior.

When built-in CORS is enabled, this public read-only endpoint supports
configured ``GET`` preflight and actual response headers. It is not covered by
``INDIEWEB_RATE_LIMITS``.

The response intentionally omits ``revocation_endpoint`` and
``userinfo_endpoint`` because django-indieweb does not implement those
protocol endpoints. The browser token management UI at ``/indieweb/tokens/``
is not a protocol revocation endpoint.

IndieAuth Flow
--------------

.. mermaid::

   sequenceDiagram
       participant Client
       participant User
       participant AuthEndpoint as /indieweb/auth/
       participant TokenEndpoint as /indieweb/token/

       Client->>AuthEndpoint: GET with client_id, redirect_uri, state, me, code_challenge
       AuthEndpoint->>User: Redirect to login if not authenticated
       User->>AuthEndpoint: Login
       AuthEndpoint->>Client: Redirect with auth code
       Client->>TokenEndpoint: POST with code, client_id, redirect_uri, scope, code_verifier
       TokenEndpoint->>Client: Return access token
       Client->>Client: Store access token for future requests

Authorization Endpoint
----------------------

**URL:** ``/indieweb/auth/``

This endpoint handles the IndieAuth authorization flow.

GET Request
~~~~~~~~~~~

Initiates the authorization flow.

**Required Parameters:**

- ``client_id`` - The client application's URL
- ``redirect_uri`` - Where to redirect after authorization
- ``state`` - Random string to prevent CSRF attacks
- ``me`` - The user's profile URL

``client_id`` must be an absolute ``http``/``https`` URL with no userinfo and
no fragment delimiter. Operator policy checks through
``INDIEWEB_ALLOWED_CLIENT_IDS`` or ``INDIEWEB_CLIENT_ID_VALIDATOR`` receive a
normalized comparison value with lowercased scheme/host and IDNA host form;
the original submitted value is still shown, stored, and returned.

**Optional Parameters:**

- ``response_type`` - Current IndieAuth clients send ``code``. django-indieweb
  accepts ``response_type=code`` and rejects any other present value with HTTP
  400 ``invalid response_type``. Omitted ``response_type`` remains accepted for
  legacy clients.
- ``scope`` - Space-separated list of scopes (e.g., "create update"). The
  value is normalized before display/storage by splitting on whitespace,
  removing duplicate tokens while preserving first-seen order, and joining
  with single spaces. Unknown scope names are accepted and preserved.
- ``code_challenge`` - PKCE code challenge (RFC 7636). 43-128 characters from
  the unreserved set ``[A-Za-z0-9._~-]``. When sent, the value is stored
  alongside the auth code and the matching ``code_verifier`` is required at
  the token endpoint.
- ``code_challenge_method`` - PKCE challenge method. Must be ``S256`` or
  ``plain``; defaults to ``plain`` if ``code_challenge`` is sent without a
  method (RFC 7636 §4.3). Other values are rejected with HTTP 400.

**Example Request:**

.. code-block:: http

    GET /indieweb/auth/?client_id=https://app.example.com&redirect_uri=https://app.example.com/callback&state=1234567890&me=https://user.example.com&scope=create HTTP/1.1
    Host: yoursite.com

**Response:**

- If user is not authenticated: Redirects to Django login
- If user is authenticated: Returns the consent screen with
  ``X-Frame-Options: DENY`` and ``Content-Security-Policy: frame-ancestors
  'none'`` to prevent framing. When the logged-in user has a configured
  h-card profile URL, the consent screen also shows that local identity URL
  and warns if it differs from the submitted ``me`` value.
- If user is authenticated and approves: Redirects to ``redirect_uri`` with
  ``code``, ``state``, ``iss``, and the legacy ``me`` parameter
- If user denies: Redirects to ``redirect_uri`` with ``error=access_denied``
  and ``state``. Denial redirects do not include ``iss`` because clients must
  not assume error responses originated from the intended authorization server.
  Consent approve/deny submissions require a valid Django CSRF token and a
  logged-in user before any client redirect is built.

**Example Response:**

.. code-block:: http

    HTTP/1.1 302 Found
    Location: https://app.example.com/callback?code=abc123&state=1234567890&me=https://user.example.com&iss=https%3A%2F%2Fyoursite.com%2Findieweb%2F

POST Request
~~~~~~~~~~~~

Verifies an authorization code (used for code verification). This legacy
protocol POST remains CSRF-exempt; browser consent approve/deny POSTs to the
same endpoint are CSRF-protected.

**Required Parameters:**

- ``code`` - The authorization code
- ``client_id`` - The client application's URL

**Example Request:**

.. code-block:: http

    POST /indieweb/auth/ HTTP/1.1
    Host: yoursite.com
    Content-Type: application/x-www-form-urlencoded

    code=abc123&client_id=https://app.example.com

**Response:**

Returns the ``me`` parameter associated with the auth code. When the client
explicitly prefers ``Accept: application/json``, the success response is JSON.
Default requests and wildcard-only ``Accept: */*`` requests keep the legacy
form-encoded body.

**Example Response:**

.. code-block:: http

    HTTP/1.1 200 OK
    Content-Type: application/x-www-form-urlencoded

    me=https://user.example.com

.. code-block:: http

    HTTP/1.1 200 OK
    Content-Type: application/json

    {"me": "https://user.example.com"}

Token Endpoint
--------------

**URL:** ``/indieweb/token/``

Exchanges authorization codes for access tokens.

POST Request
~~~~~~~~~~~~

**Required Parameters:**

- ``code`` - The authorization code from the auth endpoint
- ``client_id`` - The client application's URL

**Optional Parameters:**

- ``grant_type`` - Current IndieAuth clients send ``authorization_code``.
  django-indieweb accepts ``grant_type=authorization_code`` and rejects any
  other present value with HTTP 400 ``invalid_request``. Omitted
  ``grant_type`` remains accepted for legacy clients.
- ``redirect_uri`` - Required when the original authorization request stored a
  ``redirect_uri``. When sent, it must be a syntactically valid
  ``http``/``https`` URL with no fragment delimiter (``#``) and no userinfo
  (``user:pass@``), and must match the value used in the original auth request
  after normalization. Normalization lowercases scheme/host, IDNA-encodes host
  names, collapses default ports (``:80`` for HTTP and ``:443`` for HTTPS),
  lowercases percent-encoded triplets, and treats an empty root path as
  equivalent to ``/``. Non-default ports, non-root paths, and query strings
  remain significant. Malformed, omitted-required, and mismatched values are
  rejected with ``invalid_grant``.
- ``me`` - The user's profile URL; falls back to the value stored with the auth code
- ``scope`` - Optional scope confirmation. If omitted, the token is issued
  with the normalized scope stored with the auth code. If sent, the submitted
  value is normalized and must exactly match the stored auth-code scope;
  mismatches are rejected with ``invalid_grant`` and no token is created or
  reissued. The token endpoint cannot broaden, narrow, or replace the scope
  approved during authorization. An explicitly empty ``scope=`` parameter
  normalizes to no scope, so it only succeeds for an auth code that was issued
  with no scope.
- ``code_verifier`` - PKCE code verifier (RFC 7636), required when the auth
  code was issued with a ``code_challenge``. 43-128 characters from the
  unreserved set ``[A-Za-z0-9._~-]``. The server recomputes the challenge from
  the verifier (``S256`` SHA-256 + base64url-without-padding, or ``plain``
  string equality) and compares in constant time. Mismatches, missing
  verifiers when a challenge was stored, and verifiers submitted when no
  challenge was stored are all rejected with ``invalid_grant``.

**Example Request:**

.. code-block:: http

    POST /indieweb/token/ HTTP/1.1
    Host: yoursite.com
    Content-Type: application/x-www-form-urlencoded

    code=abc123&client_id=https://app.example.com&redirect_uri=https://app.example.com/callback&me=https://user.example.com&scope=create

**Response:**

Returns an access token. When the client explicitly prefers
``Accept: application/json``, the success response is JSON. Default requests
and wildcard-only ``Accept: */*`` requests keep the legacy form-encoded body.
Both formats include ``token_type=Bearer``.

**Example Response:**

.. code-block:: http

    HTTP/1.1 201 Created
    Content-Type: application/x-www-form-urlencoded

    access_token=xyz789&token_type=Bearer&expires_in=86400&scope=create&me=https://user.example.com

.. code-block:: http

    HTTP/1.1 201 Created
    Content-Type: application/json

    {
        "access_token": "xyz789",
        "token_type": "Bearer",
        "expires_in": 86400,
        "scope": "create",
        "me": "https://user.example.com"
    }

The ``expires_in`` value is the remaining token lifetime in seconds. The
default lifetime is 24 hours and can be tuned with the
``INDIEWEB_TOKEN_EXPIRES_IN`` setting (see :doc:`configuration`). Reissuing a
token via the IndieAuth flow refreshes its expiration and rotates the returned
bearer key for the existing token row. The previous bearer key stops
authenticating immediately. Tokens whose ``expires_at`` has passed are
rejected with HTTP 401 by the Micropub endpoint. Raw bearer token values are
returned only in the token endpoint response; ``Token.key`` stores an HMAC
digest derived from the raw value, and legacy plaintext token rows are hashed
by the migration that introduces this storage format. Token hashes are keyed
with Django's ``SECRET_KEY``, so changing ``SECRET_KEY`` invalidates existing
bearer tokens.

Token Introspection Endpoint
----------------------------

**URL:** ``/indieweb/token/introspect/``

Verifies django-indieweb bearer tokens for resource servers and clients that
need token metadata. The endpoint is CSRF-exempt, returns JSON for all
successful requests, and is advertised from the IndieAuth metadata response as
``introspection_endpoint``.

Introspection requires caller authentication. Send a strict
``Authorization: Bearer <caller-token>`` header with every request. The caller
token must be an active django-indieweb ``Token`` row, its Django owner must be
active, it must not be expired, and its ``client_id`` must still satisfy
``INDIEWEB_ALLOWED_CLIENT_IDS`` and ``INDIEWEB_CLIENT_ID_VALIDATOR`` policy.
Malformed, missing, unknown, expired, inactive-owner, or disallowed caller
credentials return ``401 Unauthorized`` with ``Cache-Control: no-store`` and
``WWW-Authenticate: Bearer``.

The form ``token`` field is the target token being checked. If ``token`` is
omitted, django-indieweb checks the caller bearer token itself, allowing a
token to introspect itself. A caller token may introspect another token only
when both tokens are owned by the same Django user. Authenticated callers that
submit an unknown token, an inactive target token, or a token owned by a
different user receive the same inactive JSON response.

POST Request
~~~~~~~~~~~~

**Request Fields:**

- ``Authorization: Bearer <caller-token>`` - Required caller credential. The
  bearer scheme is case-insensitive, but the header must contain exactly the
  scheme and one token value.
- ``token`` - Optional access token value to verify, normally sent as
  ``application/x-www-form-urlencoded``. If omitted, django-indieweb
  introspects the caller bearer token itself.

**Example Request:**

.. code-block:: http

    POST /indieweb/token/introspect/ HTTP/1.1
    Host: yoursite.com
    Authorization: Bearer caller-token
    Content-Type: application/x-www-form-urlencoded
    Accept: application/json

    token=xyz789

**Active Response:**

.. code-block:: http

    HTTP/1.1 200 OK
    Content-Type: application/json

    {
        "active": true,
        "me": "https://user.example.com/",
        "client_id": "https://app.example.com/",
        "scope": "create update",
        "iat": 1762348800,
        "exp": 1762435200
    }

``iat`` and ``exp`` are whole-second Unix timestamps. ``iat`` is the token row
creation time. ``exp`` is the token expiration time and is omitted only for
legacy non-expiring rows where ``Token.expires_at`` is ``NULL``.

**Inactive Response:**

.. code-block:: http

    HTTP/1.1 200 OK
    Content-Type: application/json

    {"active": false}

Unknown token values, deleted token rows, expired tokens, tokens whose owner
is inactive, and tokens whose ``client_id`` no longer satisfies
``INDIEWEB_ALLOWED_CLIENT_IDS`` and ``INDIEWEB_CLIENT_ID_VALIDATOR`` policy all
return the same inactive response to authenticated callers. Authenticated
callers checking a token owned by a different Django user also receive this
inactive response. The endpoint does not disclose which inactive condition
applied. It does not create tokens, refresh expiration, delete token rows, or
expose the full bearer token value in the response.

**Unauthorized Response:**

.. code-block:: http

    HTTP/1.1 401 Unauthorized
    Cache-Control: no-store
    WWW-Authenticate: Bearer

    authentication error

This endpoint is only token introspection. django-indieweb does not implement
refresh tokens, a separate OAuth/IndieAuth token revocation endpoint, or
user-info/profile claims in this response.

Token Management UI
-------------------

**URL:** ``/indieweb/tokens/``

This browser-facing page lets authenticated Django users review their own
issued IndieAuth/Micropub access tokens and revoke tokens they no longer want
to keep active. It is not an OAuth/IndieAuth token revocation protocol
endpoint and does not change the ``/indieweb/token/`` wire protocol.

The list shows token metadata including ``client_id``, ``me``, ``scope``,
``created``, ``modified``, ``expires_at``, and active/expired status. Full
bearer token keys are not displayed.

Each token can be revoked with a CSRF-protected ``POST`` to
``/indieweb/tokens/<pk>/revoke/``. Revocation deletes the matching ``Token``
row, so the bearer token immediately stops authenticating Micropub requests.
Users can only list and revoke tokens owned by their own account. Missing or
foreign token IDs return ``404`` from the revoke view.

**Error Response:**

.. code-block:: http

    HTTP/1.1 401 Unauthorized
    Content-Type: text/plain
    Cache-Control: no-store
    WWW-Authenticate: Bearer

    authentication error

Micropub Endpoint
-----------------

**URL:** ``/indieweb/micropub/``

The Micropub endpoint supports creating, updating, and deleting content through
a pluggable handler system. See :doc:`micropub` for detailed implementation guide.

Authentication
~~~~~~~~~~~~~~

All Micropub requests require a valid access token in the ``Authorization``
header: ``Authorization: Bearer <token>``. The bearer scheme is
case-insensitive, but the header must contain exactly the scheme and one token
value. Tokens are not accepted from query strings or from a POST-body
``Authorization`` field.

GET Request
~~~~~~~~~~~

Returns the authenticated user's profile URL.

**Example Request:**

.. code-block:: http

    GET /indieweb/micropub/ HTTP/1.1
    Host: yoursite.com
    Authorization: Bearer xyz789

**Response:**

.. code-block:: http

    HTTP/1.1 200 OK
    Content-Type: application/x-www-form-urlencoded

    me=https://user.example.com

POST Request
~~~~~~~~~~~~

Creates a new post using the configured content handler.

**Supported Content Types:**

- ``application/x-www-form-urlencoded`` - Form-encoded data
- ``multipart/form-data`` - Form data plus ``photo`` file uploads
- ``application/json`` - JSON formatted data

**Common Parameters:**

- ``h`` - The entry type (e.g., "entry")
- ``content`` - The post content
- ``name`` - The post title/name
- ``category`` - Categories (comma-separated in form data, array in JSON)
- ``in-reply-to`` - URL this post is replying to
- ``bookmark-of`` - URL this post bookmarks
- ``like-of`` - URL this post likes
- ``repost-of`` - URL this post reposts
- ``rsvp`` - RSVP value such as ``yes``, ``no``, ``maybe``, or ``interested``
- ``location`` - Geographic location in geo URI format
- ``summary`` - Event summary for h-event-style creates
- ``description`` - Event description for h-event-style creates
- ``start`` - Event start value forwarded unchanged to the handler
- ``end`` - Event end value forwarded unchanged to the handler
- ``url`` - Event URL forwarded unchanged to the handler
- ``photo`` - Photo URL(s), or uploaded photo files on multipart create requests
- ``audio`` - Audio URL(s)
- ``video`` - Video URL(s)
- ``published`` - Publication date
- ``mp-slug`` - Suggested slug preserved for the configured handler
- ``mp-channel`` - Requested host-defined channel UID(s), including
  ``mp-channel[]`` array notation in form data
- ``mp-photo-alt`` - Submitted photo text alternative(s), including
  ``mp-photo-alt[]`` array notation in form data
- ``mp-syndicate-to`` - Requested host-defined syndication target UID(s),
  including ``mp-syndicate-to[]`` array notation in form data
- ``post-status`` - Submitted publication status such as ``draft`` or
  ``published``, preserved for the configured handler

**Form-Encoded Example:**

.. code-block:: http

    POST /indieweb/micropub/ HTTP/1.1
    Host: yoursite.com
    Authorization: Bearer xyz789
    Content-Type: application/x-www-form-urlencoded

    h=entry&content=Hello+World&category=test,indieweb

**Multipart Create with Photo Upload Example:**

.. code-block:: http

    POST /indieweb/micropub/ HTTP/1.1
    Host: yoursite.com
    Authorization: Bearer xyz789
    Content-Type: multipart/form-data; boundary=...

    --...
    Content-Disposition: form-data; name="h"

    entry
    --...
    Content-Disposition: form-data; name="content"

    Photo post
    --...
    Content-Disposition: form-data; name="photo"

    https://photos.example.org/existing.jpg
    --...
    Content-Disposition: form-data; name="photo"; filename="sunset.jpg"
    Content-Type: image/jpeg

    ... binary data ...
    --...--

Uploaded ``photo`` files are stored through Django's configured storage
backend using the same name generation, ``INDIEWEB_MEDIA_MAX_UPLOAD_BYTES``
limit, ``INDIEWEB_MEDIA_ALLOWED_TYPES`` allowlist, and absolute URL building
as the direct media endpoint. The created entry receives the resulting
absolute media URL(s) as ``photo`` property values. URL-valued ``photo`` form
fields are preserved and precede uploaded media URLs.

This is still a create operation: it requires ``create`` (or the legacy
``post`` alias), not ``media``. The separate ``/indieweb/media/`` endpoint
continues to require the exact ``media`` scope.

**JSON Example:**

.. code-block:: http

    POST /indieweb/micropub/ HTTP/1.1
    Host: yoursite.com
    Authorization: Bearer xyz789
    Content-Type: application/json

    {
        "type": ["h-entry"],
        "properties": {
            "content": ["Hello World"],
            "category": ["test", "indieweb"],
            "mp-syndicate-to": ["https://social.example/@user"],
            "post-status": ["draft"]
        }
    }

Form-encoded creates normalize forwarded properties to arrays. Single
``mp-slug``, ``mp-channel``, ``mp-photo-alt``, ``mp-syndicate-to``, and
``post-status`` form values become one-item arrays in the handler properties.
``mp-channel[]``, ``mp-photo-alt[]``, and ``mp-syndicate-to[]`` preserve all
submitted values as arrays. Only ``category`` is comma-split; command
properties are not comma-split.

Microformats2 JSON create requests pass the submitted ``properties`` object to
``MicropubContentHandler.create_entry()`` unchanged, including command
properties and ``post-status``, except that server-managed properties are
rejected before the handler is called.

These values are preserved, not executed. django-indieweb does not generate
slugs from ``mp-slug``, choose or route publication by ``mp-channel``, attach
``mp-photo-alt`` to stored files or media metadata, cross-post or enqueue
syndication from ``mp-syndicate-to``, or implement draft storage from
``post-status``. Host code owns those behaviors.

Server-managed properties
~~~~~~~~~~~~~~~~~~~~~~~~~

django-indieweb rejects client-submitted ``uid`` and ``author`` properties on
Micropub creates and updates because those values are server-owned in bundled
resource-server behavior. Rejected create requests return ``400 invalid_request``
before ``MicropubContentHandler.create_entry()`` is called. Rejected
``action=update`` requests return ``400 invalid_request`` before
``MicropubContentHandler.update_entry()`` is called when ``replace``, ``add``,
or either ``delete`` shape names one of these properties.

Command and extension properties such as ``mp-slug``, ``mp-channel``,
``mp-photo-alt``, ``mp-syndicate-to``, and ``post-status`` remain handler-owned
and are not part of this deny-list.

**Response:**

.. code-block:: http

    HTTP/1.1 201 Created
    Location: https://yoursite.com/posts/123/

- ``201 Created`` with a ``Location`` header on success
- ``400 Bad Request`` body ``invalid_request`` when the configured
  ``MicropubContentHandler.create_entry()`` raises ``ValueError``; the
  rejection is logged at warning level and the exception message is not
  echoed in the response body
- ``500 Internal Server Error`` with an empty body when
  ``MicropubContentHandler.create_entry()`` raises any other exception. The
  full exception is logged via ``logger.exception``; handler stack traces and
  internal error messages are never returned to the client

Update Action
~~~~~~~~~~~~~

Update an existing post via ``action=update``. Per the Micropub specification
(§3.7), update requests must be JSON. The body carries any of the
``replace``, ``add``, and ``delete`` keys; their semantics match the spec.

**Request Body Keys:**

- ``action`` - Must be ``"update"``
- ``url`` - The URL of the entry to update (required)
- ``replace`` *(optional)* - Object whose keys are property names and values
  are arrays of replacement values. The named properties are overwritten.
- ``add`` *(optional)* - Object whose keys are property names and values are
  arrays of values to append to those properties.
- ``delete`` *(optional)* - Either a list of property names to delete entirely,
  or an object whose keys are property names and values are arrays of specific
  values to remove from each property.

**Example Request — replace:**

.. code-block:: http

    POST /indieweb/micropub/ HTTP/1.1
    Host: yoursite.com
    Authorization: Bearer xyz789
    Content-Type: application/json

    {
        "action": "update",
        "url": "https://yoursite.com/posts/123/",
        "replace": {"content": ["Updated content"]}
    }

**Example Request — add and delete combined:**

.. code-block:: http

    POST /indieweb/micropub/ HTTP/1.1
    Host: yoursite.com
    Authorization: Bearer xyz789
    Content-Type: application/json

    {
        "action": "update",
        "url": "https://yoursite.com/posts/123/",
        "add": {"category": ["new-tag"]},
        "delete": ["draft"]
    }

**Response:**

- ``204 No Content`` when the update succeeds and the entry's URL is unchanged
- ``201 Created`` with a ``Location`` header when the configured handler
  returns an entry whose URL differs from the submitted URL (§3.7)
- ``400 Bad Request`` body ``invalid_request`` when the entry is unknown to
  the handler, ``url`` is missing, the body is not JSON or not a JSON object,
  the body contains none of ``replace``/``add``/``delete`` (§3.4 requires at
  least one), values inside ``replace``/``add`` are not arrays (§3.4 requires
  arrays), ``replace``/``add``/``delete`` attempts to mutate a server-managed
  property such as ``uid`` or ``author``, or ``delete`` is neither a list of
  strings nor a map of property names to arrays
- ``500 Internal Server Error`` when the configured handler raises an
  exception other than ``ValueError`` (logged via ``logger.exception``)

Form-encoded update requests are rejected with ``400 invalid_request``;
update bodies must be JSON.

Delete Action
~~~~~~~~~~~~~

Delete an existing post via ``action=delete``. Both form-encoded and JSON
bodies are accepted; both require ``url``.

**Form-Encoded Example:**

.. code-block:: http

    POST /indieweb/micropub/ HTTP/1.1
    Host: yoursite.com
    Authorization: Bearer xyz789
    Content-Type: application/x-www-form-urlencoded

    action=delete&url=https://yoursite.com/posts/123/

**JSON Example:**

.. code-block:: http

    POST /indieweb/micropub/ HTTP/1.1
    Host: yoursite.com
    Authorization: Bearer xyz789
    Content-Type: application/json

    {"action": "delete", "url": "https://yoursite.com/posts/123/"}

**Response:**

- ``204 No Content`` on success (delete cannot relocate)
- ``400 Bad Request`` body ``invalid_request`` when the entry is unknown to
  the handler or ``url`` is missing
- ``500 Internal Server Error`` when the configured handler raises an
  exception other than ``ValueError``

Undelete Action
~~~~~~~~~~~~~~~

Restore a previously-deleted post via ``action=undelete``. Both form-encoded
and JSON bodies are accepted; both require ``url``.

**Form-Encoded Example:**

.. code-block:: http

    POST /indieweb/micropub/ HTTP/1.1
    Host: yoursite.com
    Authorization: Bearer xyz789
    Content-Type: application/x-www-form-urlencoded

    action=undelete&url=https://yoursite.com/posts/123/

**Response:**

- ``204 No Content`` when the undelete succeeds and the entry's URL is unchanged
- ``201 Created`` with a ``Location`` header when the configured handler
  returns an entry whose URL differs from the submitted URL (§3.10)
- ``400 Bad Request`` body ``invalid_request`` when the URL is not in the
  handler's deleted set or ``url`` is missing
- ``500 Internal Server Error`` when the configured handler raises an
  exception other than ``ValueError``

Query Endpoints
~~~~~~~~~~~~~~~

The Micropub endpoint supports several query parameters:

**Configuration Query:**

.. code-block:: http

    GET /indieweb/micropub/?q=config HTTP/1.1
    Authorization: Bearer xyz789

Returns supported post types and features. The response also includes a ``q``
array advertising the query names django-indieweb implements
(``config``, ``source``, ``syndicate-to``, ``category``, ``channel``,
``media-endpoint``, ``post-types``), plus default empty ``syndicate-to``,
``categories``, and ``channels`` arrays from the bundled handler.

The default in-memory handler advertises these post types:

- ``note`` - ``content``
- ``article`` - ``name``, ``content``
- ``photo`` - ``photo``, optional ``content`` and ``category``
- ``audio`` - ``audio``, optional ``content`` and ``category``
- ``video`` - ``video``, optional ``content`` and ``category``
- ``reply`` - ``in-reply-to``, ``content``
- ``bookmark`` - ``bookmark-of``, ``name``, ``content``
- ``like`` - ``like-of``
- ``repost`` - ``repost-of``
- ``event`` - ``name``, ``summary``, ``description``, ``start``, ``end``,
  ``location``, ``category``, ``url``, ``published``
- ``rsvp`` - ``rsvp``, ``in-reply-to``, ``name``, ``content``

``media-endpoint`` and ``post-types`` can also be queried directly. The direct
subqueries use the same effective handler configuration as ``q=config``;
custom handler values remain authoritative, and django-indieweb injects the
bundled media endpoint only when the handler omits a truthy ``media-endpoint``.
The built-in audio and video post types only advertise URL-valued properties
that are normalized and forwarded to the configured handler. Host code owns
persistence, rendering, transcoding, media players, storage models, and media
processing.

**Media Endpoint Query:**

.. code-block:: http

    GET /indieweb/micropub/?q=media-endpoint HTTP/1.1
    Authorization: Bearer xyz789

Returns JSON shaped like:

.. code-block:: json

    {"media-endpoint": "https://yoursite.com/indieweb/media/"}

**Post Types Query:**

.. code-block:: http

    GET /indieweb/micropub/?q=post-types HTTP/1.1
    Authorization: Bearer xyz789

Returns the handler's supported vocabulary as ``{"post-types": [...]}``.
Clients can add ``post-type=<type>`` to return only matching advertised types;
unknown values return an empty list. ``q=post-types`` also accepts optional
``filter``, ``limit``, and ``offset`` parameters. ``filter`` is matched
case-insensitively against a stable JSON serialization of each post-type item;
``post-type`` is applied first, then ``filter``/``offset``/``limit`` operate on
the narrowed list. ``limit`` and ``offset`` must be non-negative integers, and
malformed values return ``400 invalid_request``.

django-indieweb intentionally does not implement unrelated extension query
names such as ``q=contacts`` or a standalone ``q=properties`` query. Unsupported
or unknown query names continue to fall back to the legacy token verification
response with the authenticated token's ``me`` URL.

**Source Query:**

.. code-block:: http

    GET /indieweb/micropub/?q=source&limit=20&offset=0&filter=django HTTP/1.1
    Authorization: Bearer xyz789
    Accept: application/json

When no ``url`` parameter is supplied, returns a list of editable/source posts
through the optional
``MicropubContentHandler.list_entries(user, limit=..., offset=..., filter=...)``
hook. Existing custom handlers are not required to implement this hook; if the
hook returns ``None`` (the default implementation), django-indieweb returns
``501 Not Implemented`` with body ``not_implemented``.

List-mode responses contain ``items`` and ``paging``:

.. code-block:: json

    {
        "items": [
            {
                "type": ["h-entry"],
                "properties": {
                    "content": ["Hello World"],
                    "url": ["https://yoursite.com/posts/123/"]
                }
            }
        ],
        "paging": {
            "limit": 20,
            "offset": 0,
            "total": 1
        }
    }

Each item uses the same Microformats-style ``type``/``properties`` shape as a
full source-by-URL response. List mode adds a ``url`` property when the handler's
entry properties do not already include one, using the ``MicropubEntry.url``
value, so clients have a URL for later source/update/delete requests. ``total``
is included only when the handler reports an accurate filtered total.

``limit`` and ``offset`` must be non-negative integers. If omitted, ``limit``
defaults to ``20`` and ``offset`` defaults to ``0``. Malformed values return
``400 invalid_request``. ``filter`` is optional and passed to the handler as a
free-form string; the bundled in-memory handler applies it as a
case-insensitive substring match against a stable JSON serialization of each
source item. Host handlers remain authoritative for content enumeration,
ordering, permissions, filtering, and pagination. Cursor-style ``after`` and
``before`` paging are not implemented yet.

.. code-block:: http

    GET /indieweb/micropub/?q=source&url=https://yoursite.com/posts/123/ HTTP/1.1
    Authorization: Bearer xyz789
    Accept: application/json

Returns the source content for an existing entry. The configured
``MicropubContentHandler.get_entry(url, user)`` method receives the submitted
``url`` unchanged and returns a ``MicropubEntry``. A full source response
includes both the Microformats type and all entry properties:

.. code-block:: json

    {
        "type": ["h-entry"],
        "properties": {
            "content": ["Hello World"],
            "category": ["test", "indieweb"]
        }
    }

Clients can request a subset of properties using the array form
``properties[]=NAME``. When properties are requested, the response contains
only the requested properties that exist on the entry, and omits ``type`` to
match the Micropub source-query examples:

.. code-block:: http

    GET /indieweb/micropub/?q=source&url=https://yoursite.com/posts/123/&properties[]=content&properties[]=name HTTP/1.1
    Authorization: Bearer xyz789
    Accept: application/json

.. code-block:: json

    {
        "properties": {
            "content": ["Hello World"],
            "name": ["Post title"]
        }
    }

``GET ?q=source`` returns ``400 invalid_request`` when a submitted ``url`` is
empty or unknown to the handler in source-by-URL mode, when list-mode ``limit``
or ``offset`` is malformed, or when the handler rejects a list query with
``ValueError``. It returns ``501 not_implemented`` when list mode is unsupported
by the configured handler, and ``500 Internal Server Error`` when the handler
raises an unexpected exception. Scope failures still return ``403`` with body
``authorization error`` before source-query dispatch.

**Category Query:**

.. code-block:: http

    GET /indieweb/micropub/?q=category HTTP/1.1
    Authorization: Bearer xyz789

Returns the handler's ``categories`` configuration list under the
``categories`` JSON key. The bundled in-memory handler advertises an empty
list; custom handlers populate it by overriding
``MicropubContentHandler.get_config()``.

The response is JSON shaped like:

.. code-block:: json

    {"categories": ["indieweb", "micropub"]}

**Channel Query:**

.. code-block:: http

    GET /indieweb/micropub/?q=channel HTTP/1.1
    Authorization: Bearer xyz789

Returns the handler's ``channels`` configuration list under the ``channels``
JSON key. Channel item shape is host-defined; clients commonly expect
``{"uid": ..., "name": ...}`` objects:

.. code-block:: json

    {
        "channels": [
            {"uid": "notes", "name": "Notes"},
            {"uid": "articles", "name": "Articles"}
        ]
    }

Channel data exposed here is informational. django-indieweb preserves submitted
``mp-channel`` values on create requests, but it does not select defaults or
route publication by channel. Channel-aware publication remains a
host-handler concern. This Micropub ``q=channel`` configuration query and the
``mp-channel`` command property are publishing-side features; they are not
Microsub channels and do not imply reader timeline, feed, or subscription
support.

``q=category``, ``q=channel``, and ``q=post-types`` accept optional
``filter``, ``limit``, and ``offset`` parameters. ``filter`` is matched
case-insensitively as a
substring against string items, or against a stable JSON serialization of
dict items (so common fields such as ``uid`` and ``name`` are searchable
without per-handler configuration). ``limit`` and ``offset`` must be
non-negative integers; the order of operations is filter → offset → limit.
Malformed ``limit`` or ``offset`` values (non-integers, negative numbers, or
floats) return ``400 invalid_request``. Missing ``categories`` or ``channels``
keys in a custom handler config return an empty list under the response key
instead of raising; missing or non-list ``post-types`` returns an empty
``post-types`` list.

These configuration queries are token-required only and do not require a
per-operation scope, matching the existing ``q=config`` and ``q=syndicate-to``
behavior.

**Syndication Targets Query:**

.. code-block:: http

    GET /indieweb/micropub/?q=syndicate-to HTTP/1.1
    Authorization: Bearer xyz789

Returns the configured handler's syndication target list as
``{"syndicate-to": [...]}``. The bundled in-memory handler returns
``{"syndicate-to": []}``; custom handlers populate the list by overriding
``MicropubContentHandler.get_config()``.

Target objects should include a stable ``uid`` value clients can submit back
and a human-readable ``name``. Hosts may include optional ``service`` metadata
when clients should display platform details, and may include a boolean
``checked`` value when a target should be selected by default:

.. code-block:: json

    {
        "syndicate-to": [
            {
                "uid": "https://social.example/@username",
                "name": "Example Social",
                "service": {
                    "name": "Example Social",
                    "url": "https://social.example/"
                },
                "checked": true
            }
        ]
    }

The direct query uses the same copied effective handler configuration as
``q=config``. If a handler omits ``syndicate-to`` or returns a non-list value,
the direct query returns an empty list instead of raising. ``q=config``
preserves a custom handler's ``syndicate-to`` value unchanged.

This query is token-required only and does not require ``create``, ``update``,
``delete``, ``undelete``, or ``media`` scope. Syndication execution remains
host-owned: django-indieweb does not cross-post, call webhooks, choose targets,
store syndicator credentials, or run syndicator plugins.

Micropub Scope Policy
~~~~~~~~~~~~~~~~~~~~~

django-indieweb enforces built-in Micropub scopes by operation:

- entry create requires ``create`` or the legacy ``post`` alias
- ``action=update`` and ``GET ?q=source`` require ``update``
- ``action=delete`` requires ``delete``
- ``action=undelete`` requires ``undelete``
- direct media uploads to ``/indieweb/media/`` require ``media``
- configuration queries such as ``q=config``, ``q=category``, ``q=channel``,
  ``q=media-endpoint``, ``q=post-types``, and ``q=syndicate-to`` are
  token-required only and have no operation-scope gate

The extension ``draft`` scope may be requested and stored as an opaque
IndieAuth scope string, but django-indieweb does not advertise it as a
built-in resource-server scope and does not treat it as a substitute for
``create`` or ``update``. A create request with ``post-status=draft`` still
requires ``create`` or ``post``; an update request still requires ``update``.
A token scoped ``create draft`` can create because ``create`` is present, not
because ``draft`` has built-in behavior. Hosts that want draft-only
permissions need to implement that policy in host token handling, handlers, or
a custom resource-server layer.

Reader-oriented scopes such as ``read``, ``follow``, ``mute``, ``block``,
``channels``, and similar extension strings follow the same storage rule:
django-indieweb accepts and preserves them as opaque IndieAuth scopes, and
token issuance/introspection can return them. They do not satisfy any built-in
Micropub or media endpoint permission, and no bundled Microsub/resource-server
behavior is attached to them. Host applications that implement reader
protocols own their reader endpoints, channel/follow/mute/block models, feed
fetching, authorization policy, metadata/discovery behavior, and API contracts.

Micropub Media Endpoint
-----------------------

**URL:** ``/indieweb/media/``

The Micropub media endpoint accepts direct file uploads for clients that
discover ``media-endpoint`` through ``GET /indieweb/micropub/?q=config``.
It uses the same bearer-token authentication path as the Micropub endpoint,
including token expiration, inactive-owner rejection, and the configured
``INDIEWEB_ALLOWED_CLIENT_IDS`` / ``INDIEWEB_CLIENT_ID_VALIDATOR``
resource-server policy.

Uploads, source queries, and media delete actions require the exact ``media``
scope. This follows the convention used by Quill and similar Micropub clients,
while keeping django-indieweb's scope model explicit. The scope check is
separate from ``create``/``post`` so a token that can create entries cannot use
the media endpoint unless the user approved media access.

POST Request
~~~~~~~~~~~~

Send a ``multipart/form-data`` request with one part named ``file``:

.. code-block:: http

    POST /indieweb/media/ HTTP/1.1
    Host: yoursite.com
    Authorization: Bearer xyz789
    Content-Type: multipart/form-data; boundary=...

    --...
    Content-Disposition: form-data; name="file"; filename="sunset.jpg"
    Content-Type: image/jpeg

    ... binary data ...
    --...--

The uploaded file is stored through Django's configured storage backend using
an unguessable name under ``indieweb/media/``. The suggested client filename is
not used as the storage basename; only the final suffix is preserved.
Uploads larger than ``INDIEWEB_MEDIA_MAX_UPLOAD_BYTES`` (default 10 MiB) are
rejected before storage. Upload content types must be listed in
``INDIEWEB_MEDIA_ALLOWED_TYPES`` (default: common image, audio, and video
types).

**Response:**

.. code-block:: http

    HTTP/1.1 201 Created
    Location: https://yoursite.com/media/indieweb/media/ff176c461dd111e6b6ba3e1d05defe78.jpg

The response body is empty. Clients can use the ``Location`` URL as a
``photo``, ``audio``, or ``video`` property value in a later Micropub create or
update request.

GET Source Query
~~~~~~~~~~~~~~~~

``GET /indieweb/media/?q=source`` delegates to optional host-owned media hooks
on the configured ``MicropubContentHandler``. django-indieweb does not maintain
a media index or infer storage ownership from URLs.

When the host implements ``list_media(user, limit=..., offset=..., filter=...)``,
the endpoint returns a list response:

.. code-block:: http

    GET /indieweb/media/?q=source&limit=10&offset=0 HTTP/1.1
    Host: yoursite.com
    Authorization: Bearer xyz789

.. code-block:: json

    {
        "items": [
            {
                "properties": {
                    "url": ["https://yoursite.com/media/photo.jpg"],
                    "name": ["photo.jpg"],
                    "media-type": ["photo"]
                }
            }
        ],
        "paging": {"limit": 10, "offset": 0, "total": 1}
    }

``limit`` and ``offset`` must be non-negative integers when present.
``filter`` is passed to the hook as a string or ``None``. ``total`` appears
only when the hook returns a known total.

When the host implements ``get_media(url, user)``, submit ``url`` to retrieve
one media item's metadata:

.. code-block:: http

    GET /indieweb/media/?q=source&url=https://yoursite.com/media/photo.jpg HTTP/1.1
    Host: yoursite.com
    Authorization: Bearer xyz789

.. code-block:: json

    {
        "properties": {
            "url": ["https://yoursite.com/media/photo.jpg"],
            "name": ["photo.jpg"],
            "media-type": ["photo"]
        }
    }

If the hook omits a ``url`` property, django-indieweb adds one from the
``MicropubMediaItem.url`` value.

POST Delete Action
~~~~~~~~~~~~~~~~~~

``POST /indieweb/media/`` with ``action=delete`` delegates to the optional
``delete_media(url, user)`` hook. Form-encoded bodies are supported; JSON
objects with ``action`` and ``url`` are also accepted.

.. code-block:: http

    POST /indieweb/media/ HTTP/1.1
    Host: yoursite.com
    Authorization: Bearer xyz789
    Content-Type: application/x-www-form-urlencoded

    action=delete&url=https://yoursite.com/media/photo.jpg

Successful host deletes return:

.. code-block:: http

    HTTP/1.1 204 No Content

The response body is empty. Missing, empty, unknown, or rejected URLs return
``400 invalid_request``. When no media delete hook is configured, the endpoint
returns ``501 not_implemented``. django-indieweb never deletes
``default_storage`` files by guessing from arbitrary submitted URLs.

**Error Response:**

- ``400 Bad Request`` body ``invalid_request`` when the request is not
  ``multipart/form-data`` or does not include a ``file`` part; when
  ``q=source`` has an empty or unknown ``url`` or malformed ``limit``/``offset``;
  when ``action=delete`` has a missing, empty, unknown, or rejected ``url``;
  or when a media hook raises ``ValueError``
- ``401 Unauthorized`` body ``authentication error`` for missing, invalid, or
  expired tokens, or inactive token owners. The response includes
  ``Cache-Control: no-store`` and ``WWW-Authenticate: Bearer``.
- ``413 Payload Too Large`` body ``invalid_request`` when the uploaded file
  exceeds ``INDIEWEB_MEDIA_MAX_UPLOAD_BYTES``
- ``415 Unsupported Media Type`` body ``invalid_request`` when the uploaded
  file's content type is not in ``INDIEWEB_MEDIA_ALLOWED_TYPES``
- ``403 Forbidden`` body ``authorization error`` when the token lacks the
  ``media`` scope
- ``403 Forbidden`` body ``invalid_client`` when the stored token's
  ``client_id`` is rejected by ``INDIEWEB_ALLOWED_CLIENT_IDS`` or
  ``INDIEWEB_CLIENT_ID_VALIDATOR``
- ``501 Not Implemented`` body ``not_implemented`` when the requested source
  or delete hook is not configured on the handler
- ``500 Internal Server Error`` if the configured Django storage backend raises
  unexpectedly while saving the upload, or when a configured media hook raises
  an unexpected exception

Webmention Endpoint
-------------------

**URL:** ``/indieweb/webmention/``

The Webmention endpoint receives notifications that another page links to a
page on the configured Django ``Site`` domain. Requests must be
``application/x-www-form-urlencoded`` or another form submission that populates
``request.POST``; JSON bodies are not supported by this endpoint.

POST Request
~~~~~~~~~~~~

**Required Parameters:**

- ``source`` - Absolute URL of the page that links to your content
- ``target`` - Absolute URL on your configured ``Site`` domain

**Optional Parameters:**

- ``vouch`` - Absolute ``http`` or ``https`` URL of a voucher page. When
  present, the endpoint validates and stores it as Webmention Vouch metadata.
  Receiver-side Vouch verification, if configured, happens later in
  ``WebmentionProcessor`` or the queued worker path.

The endpoint rejects missing parameters, malformed URLs, and targets whose
network location does not exactly match the current ``Site.domain`` before
processing or enqueueing.

**Synchronous Response:**

When ``INDIEWEB_WEBMENTION_ENQUEUE`` is unset, the endpoint processes the
Webmention in the request path and returns ``201 Created`` with a ``Location``
header pointing to the status endpoint:

.. code-block:: http

    HTTP/1.1 201 Created
    Location: https://yoursite.com/indieweb/webmention/WbH8aUEs3WkT2V6vYcU6r2kNfT4mP9bQd7xR5sLaJz0p/

**Queued Response:**

When ``INDIEWEB_WEBMENTION_ENQUEUE`` is configured, the endpoint creates or
reuses the ``Webmention`` row, calls the configured enqueue hook with that row's
primary key, and returns ``202 Accepted`` with a status ``Location``:

.. code-block:: http

    HTTP/1.1 202 Accepted
    Location: https://yoursite.com/indieweb/webmention/WbH8aUEs3WkT2V6vYcU6r2kNfT4mP9bQd7xR5sLaJz0p/

In queued mode, the request path does not fetch or verify the source URL.
It also does not fetch or verify a submitted ``vouch`` URL. Workers should call
``indieweb.processors.process_queued_webmention(pk)`` to run the existing
processor and update the row status.

**Error Response:**

- ``400 Bad Request`` when ``source`` or ``target`` is missing, ``source`` or
  ``target`` is not a valid URL, submitted ``vouch`` is not a valid ``http`` or
  ``https`` URL, or ``target`` is outside the configured ``Site`` domain
- ``500 Internal Server Error`` in queued mode when the configured
  ``INDIEWEB_WEBMENTION_ENQUEUE`` path cannot be imported, is not callable, or
  raises while enqueueing

Webmention Status Endpoint
~~~~~~~~~~~~~~~~~~~~~~~~~~

**URL:** ``/indieweb/webmention/<status-token>/``

Returns public status details for a received Webmention. Status URLs use an
opaque token stored on the ``Webmention`` row rather than the row's sequential
primary key:

.. code-block:: http

    HTTP/1.1 200 OK
    Content-Type: application/json

    {"source": "https://source.example/post", "target": "https://yoursite.com/post", "status": "pending"}

The response includes ``verified_at`` when the Webmention has been verified.
It does not expose stored Vouch URLs or Vouch verification timestamps. Missing
or guessed status tokens return ``404``.

The default response shape above is intended as token-holder diagnostics: a
sender that received the ``202 Accepted`` ``Location`` (or a holder of the
opaque token) can confirm which ``source``/``target`` pair the row records and
its current ``status``. For deployments where a leaked status URL must not
echo the stored URL pair, set
``INDIEWEB_WEBMENTION_STATUS_PUBLIC = True`` (see
:doc:`configuration`). In public-safe mode the body is restricted to
``status`` and, when set, ``verified_at``; ``source`` and ``target`` are
omitted.

Error Responses
---------------

All endpoints may return these error responses:

**400 Bad Request — ``invalid_grant``**

- Expired authorization code
- Invalid authorization code
- ``scope`` sent on token exchange does not normalize to the scope stored with
  the auth code, including attempts to add a scope to a no-scope auth code
  or attempts to submit an explicitly empty ``scope=`` for a scoped auth code
- ``redirect_uri`` sent on token exchange is malformed (invalid URL, contains a ``#`` delimiter, includes userinfo, or uses a disallowed scheme)
- ``redirect_uri`` is omitted on token exchange when the matched auth code was
  issued with one
- ``redirect_uri`` sent on token exchange does not match the value stored with
  the auth code after normalization of scheme/host case, IDNA host form,
  default ports, percent-encoded triplet case, and root empty-path/``/``
  equivalence
- ``code_verifier`` is missing on token exchange when the auth code was issued with a ``code_challenge``
- ``code_verifier`` does not match the stored ``code_challenge`` under the stored ``code_challenge_method`` (``S256`` or ``plain``)
- ``code_verifier`` is submitted on token exchange but no ``code_challenge`` was stored with the auth code
- ``code_verifier`` is malformed (length outside 43-128 or characters outside the unreserved set ``[A-Za-z0-9._~-]``)

**400 Bad Request — ``invalid_request``**

- Missing required ``code`` or ``client_id`` on token exchange
- ``grant_type`` sent on token exchange is present but is not
  ``authorization_code``
- ``client_id`` on token exchange is malformed (invalid URL, contains a ``#``
  delimiter, includes userinfo, or uses a disallowed scheme)
- ``client_id`` on token exchange is rejected by the configured
  ``INDIEWEB_ALLOWED_CLIENT_IDS`` setting or
  ``INDIEWEB_CLIENT_ID_VALIDATOR`` callable, or that callable cannot be
  imported (fail-closed)
- Micropub ``POST`` with ``Content-Type: application/json`` whose body
  cannot be parsed as JSON or does not parse to a JSON object (rejected
  before scope/action dispatch so a malformed update body cannot fall
  through to the create path)
- Micropub ``POST action=update``/``delete``/``undelete`` against an unknown
  ``url``, missing ``url``, or — for ``action=update`` — a non-JSON request
  body, an empty update payload (none of ``replace``/``add``/``delete``),
  a non-array operation value (``replace``/``add`` values must be arrays per
  §3.4), or a ``delete`` value that is neither a list of property names nor
  a map of property names to arrays. The Micropub specification's response
  listings for these actions are limited; this project chose
  ``400 invalid_request`` for all three so client errors look consistent
  with the IndieAuth/token-endpoint behavior, rather than guessing
  handler-specific permission semantics with a ``404`` or ``403``.
- Micropub ``GET ?q=source&url=...`` with an empty ``url`` or a ``url`` unknown
  to the configured handler. Missing requested ``properties[]`` names are
  omitted from successful filtered responses instead of causing an error.
- Micropub ``GET ?q=source`` without ``url`` when ``limit`` or ``offset`` is
  malformed (non-integer, negative, or float), or when the configured handler's
  ``list_entries()`` hook rejects the query by raising ``ValueError``.
- Micropub ``GET ?q=category``, ``GET ?q=channel``, or ``GET ?q=post-types``
  with a malformed ``limit`` or ``offset`` parameter (non-integer, negative,
  or float). A missing ``categories``/``channels``/``post-types`` key in the
  configured handler's config returns an empty list rather than an error, and
  an unrecognized ``filter`` or ``post-type`` value simply returns no matches.
- Micropub ``GET ?q=syndicate-to`` returns an empty list rather than an error
  when the configured handler omits ``syndicate-to`` or returns a non-list
  value.
- Micropub media endpoint ``GET ?q=source&url=...`` with an empty ``url`` or a
  URL unknown to the configured ``get_media()`` hook.
- Micropub media endpoint ``GET ?q=source`` without ``url`` when ``limit`` or
  ``offset`` is malformed, or when the configured ``list_media()`` hook rejects
  the query by raising ``ValueError``.
- Micropub media endpoint ``POST action=delete`` with a missing, empty,
  unknown, or hook-rejected ``url``.
- Micropub media endpoint upload requests that are not ``multipart/form-data``
  or do not include a ``file`` part.

**413 Payload Too Large — ``invalid_request``**

- Micropub media endpoint upload whose ``file`` part exceeds
  ``INDIEWEB_MEDIA_MAX_UPLOAD_BYTES``.
- Micropub multipart create upload whose ``photo`` part exceeds
  ``INDIEWEB_MEDIA_MAX_UPLOAD_BYTES``.

**415 Unsupported Media Type — ``invalid_request``**

- Micropub media endpoint upload whose ``file`` content type is not listed in
  ``INDIEWEB_MEDIA_ALLOWED_TYPES``.
- Micropub multipart create upload whose ``photo`` content type is not listed
  in ``INDIEWEB_MEDIA_ALLOWED_TYPES``.

**401 Unauthorized**

- Missing or invalid access token
- Expired access token
- User account associated with the token is inactive
- Missing, malformed, unknown, expired, inactive-owner, or disallowed caller
  bearer credential on token introspection

Token-protected resource views return the plain-text body
``authentication error`` and include ``Cache-Control: no-store`` and
``WWW-Authenticate: Bearer`` on these 401 responses. Token introspection
caller authentication failures use the same body and headers.

**403 Forbidden**

- Token lacks the scope required for the requested Micropub operation
  (``authorization error``). Per-operation requirements: ``POST`` entry create
  requires ``create`` (or the legacy alias ``post``); ``POST action=update``
  requires ``update``; ``POST action=delete`` requires ``delete``;
  ``POST action=undelete`` requires ``undelete``; ``GET ?q=source`` requires
  ``update``; ``POST /indieweb/media/`` requires ``media``; ``GET
  /indieweb/media/?q=source`` and media ``POST action=delete`` also require
  ``media``; and multipart create uploads sent to ``POST /indieweb/micropub/``
  remain create requests, requiring ``create`` or ``post`` rather than
  ``media``. ``GET ?q=config``,
  ``GET ?q=syndicate-to``, ``GET ?q=category``, ``GET ?q=channel``,
  ``GET ?q=media-endpoint``, ``GET ?q=post-types``, and ``GET`` with no ``q``
  only require an authenticated token. Stored ``scope`` is split on whitespace
  and matched as an exact token, so ``createXYZ`` does not satisfy ``create``
  and ``mediaXYZ`` does not satisfy ``media``.
- The stored token's ``client_id`` is rejected by the configured
  ``INDIEWEB_ALLOWED_CLIENT_IDS`` setting or
  ``INDIEWEB_CLIENT_ID_VALIDATOR`` callable, or that callable cannot be
  imported (``invalid_client``)

**400 Bad Request — invalid redirect_uri**

- ``redirect_uri`` on the authorization endpoint is malformed (invalid URL,
  contains a ``#`` delimiter, includes userinfo, or uses a disallowed scheme)

**400 Bad Request — invalid client_id**

- ``client_id`` on the authorization endpoint is malformed (invalid URL,
  contains a ``#`` delimiter, includes userinfo, or uses a disallowed scheme)

**400 Bad Request — ``invalid_client`` (authorization endpoint)**

- ``client_id`` on the authorization endpoint is rejected by the configured
  ``INDIEWEB_ALLOWED_CLIENT_IDS`` setting or
  ``INDIEWEB_CLIENT_ID_VALIDATOR`` callable, or that callable cannot be
  imported (fail-closed)

**400 Bad Request — ``invalid_request`` (authorization endpoint)**

- ``code_challenge`` on the authorization endpoint is malformed (length
  outside 43-128 or characters outside the unreserved set ``[A-Za-z0-9._~-]``)
- ``code_challenge_method`` is not one of ``S256`` or ``plain``
- ``code_challenge`` is omitted while ``INDIEWEB_REQUIRE_PKCE`` or
  ``INDIEWEB_REQUIRE_PKCE_S256`` is enabled
- ``code_challenge_method=plain`` is used while
  ``INDIEWEB_REQUIRE_PKCE_S256`` is enabled

**400 Bad Request — invalid me**

- ``me`` does not match the logged-in user's configured h-card profile URL
  while ``INDIEWEB_BIND_ME_TO_USER`` is enabled, or no profile URL is
  configured in that mode

**404 Not Found**

- Missing required parameters on the authorization endpoint

**501 Not Implemented — ``not_implemented``**

- Micropub ``GET ?q=source`` without ``url`` when the configured handler does
  not support the optional ``MicropubContentHandler.list_entries()`` hook.
- Micropub media endpoint ``GET ?q=source`` or ``POST action=delete`` when the
  configured handler does not support the corresponding optional media hook.

**500 Internal Server Error**

- A configured Micropub handler raised an exception other than
  ``ValueError`` while servicing ``POST action=update``/``delete``/``undelete``,
  or raised any unexpected exception while servicing ``GET ?q=source`` by URL
  or list mode. The exception is logged via ``logger.exception`` so the stack
  trace stays in the server log rather than the response body.
- A configured media hook raised an unexpected exception while servicing
  ``GET /indieweb/media/?q=source`` or media ``POST action=delete``.
- The configured Django storage backend raised unexpectedly while saving a
  Micropub media endpoint upload or multipart create ``photo`` upload.

Scopes
------

The Micropub endpoint enforces scopes per operation. Stored ``scope`` values
are split on whitespace and compared as exact tokens, so ``createXYZ`` does
not satisfy ``create``.

The authorization endpoint normalizes requested scope strings before showing
them on the consent screen and before storing them on ``Auth``. Normalization
splits on whitespace, de-duplicates while preserving first-seen order, and
joins tokens with single spaces; empty or whitespace-only values become no
scope. Unknown scopes are preserved rather than rejected because
IndieAuth/Micropub scopes are extension-defined.

The token endpoint issues the stored auth-code scope. If a token exchange
includes ``scope``, the submitted value is normalized and must match the stored
auth-code scope exactly. A mismatch returns ``400 invalid_grant`` with content
type ``application/x-www-form-urlencoded`` and does not create or reissue a
token. An explicitly empty ``scope=`` parameter normalizes to no scope and is
accepted only when the auth code was issued with no scope.

When an auth code was issued with a ``redirect_uri``, token exchange also
requires a submitted ``redirect_uri``. Omitted required values and mismatches
return ``400 invalid_grant`` with content type
``application/x-www-form-urlencoded`` and consume the matched auth code.
Comparison normalizes scheme/host case, IDNA host form, default ports,
percent-encoded triplet case, and empty root path versus ``/``. Non-default
ports, non-root paths, and query strings remain significant.

- ``create`` - Required for ``POST`` requests that create new posts. The
  legacy alias ``post`` is also accepted.
- ``update`` - Required for ``POST action=update`` and for ``GET ?q=source``
  (which is typically used to fetch a post for editing).
- ``delete`` - Required for ``POST action=delete``.
- ``undelete`` - Required for ``POST action=undelete``.
- ``media`` - Required for ``POST /indieweb/media/`` direct uploads. Multipart
  create uploads sent to ``POST /indieweb/micropub/`` are covered by the
  create/post scope because they create an entry.
- ``post`` - Legacy alias for ``create``.

``GET ?q=config``, ``GET ?q=syndicate-to``, ``GET ?q=category``,
``GET ?q=channel``, ``GET ?q=media-endpoint``, ``GET ?q=post-types``, and
``GET`` with no ``q`` only require an authenticated token; no specific scope is
enforced.

Multiple scopes can be requested by separating with spaces: ``scope=create update``

Reader-oriented extension scopes such as ``read``, ``follow``, ``mute``,
``block``, and ``channels`` may also be requested and stored, but
django-indieweb treats them as opaque strings. They are not advertised in the
built-in IndieAuth metadata and do not grant built-in Microsub, reader feed,
channel, following, muting, blocking, timeline, or reader UI behavior.

Rate Limiting
-------------

django-indieweb can rate-limit its public protocol endpoints with Django's
cache framework. Rate limiting is disabled by default; set
``INDIEWEB_RATE_LIMITS`` to opt in. See :doc:`configuration` for the setting
shape and deployment notes.

Endpoint keys:

- ``auth`` - ``GET`` and ``POST`` requests to ``/indieweb/auth/``
- ``token`` - ``POST`` requests to ``/indieweb/token/``
- ``token_introspection`` - ``POST`` requests to
  ``/indieweb/token/introspect/``
- ``micropub`` - ``GET`` and ``POST`` requests to ``/indieweb/micropub/``
- ``media`` - ``POST`` requests to ``/indieweb/media/``
- ``websub_callback`` - ``GET`` and ``POST`` requests to
  ``/indieweb/websub/<token>/``
- ``webmention`` - ``GET`` and ``POST`` requests to ``/indieweb/webmention/``
- ``webmention_status`` - ``GET`` requests to
  ``/indieweb/webmention/<status-token>/``

Counters are scoped by endpoint key, HTTP method, and the client identity from
``REMOTE_ADDR``. ``GET`` and ``POST`` requests to the same endpoint use
independent counters, so set each endpoint limit as a per-method budget.
The client identity is HMAC-digested with Django's ``SECRET_KEY`` before it is
used in cache keys. django-indieweb does not trust ``X-Forwarded-For``
directly. Deployments behind a proxy should configure trusted upstream
middleware or infrastructure so Django receives the intended client address in
``REMOTE_ADDR``.

When a configured limit is exceeded, the endpoint returns:

.. code-block:: http

    HTTP/1.1 429 Too Many Requests
    Content-Type: text/plain
    Retry-After: 60

    rate limit exceeded

``Retry-After`` uses the cache-backed window reset time, or the configured
window when the reset marker has been evicted. The built-in limiter uses
Django's portable cache primitives and is best-effort rather than a hard atomic
limit on every backend; use a deployment-level limiter when strict adversarial
rate limiting is required. Requests below the limit keep the same response
bodies, status codes, authentication behavior, scope checks, and processing
flow as before. The browser token-management pages are not covered by these
protocol endpoint rate-limit keys.

CORS Support
------------

django-indieweb includes opt-in, endpoint-scoped CORS support for its public
IndieWeb protocol endpoints. CORS is disabled by default; set
``INDIEWEB_CORS_ALLOWED_ORIGINS`` to a tuple/list of allowed origins, or to
``"*"`` for an explicit allow-all policy. See :doc:`configuration` for the
full setting shape.

When CORS is configured and a request includes an allowed ``Origin`` header,
actual endpoint responses keep their existing status, body, content type,
authentication behavior, scope checks, rate limiting, and processing flow, and
add:

- ``Access-Control-Allow-Origin`` with the matching origin, or ``*`` for
  allow-all without credentials
- ``Access-Control-Allow-Credentials: true`` when
  ``INDIEWEB_CORS_ALLOW_CREDENTIALS`` is enabled for an explicit origin
  allowlist
- ``Vary: Origin`` whenever the response echoes a specific request origin

The combination ``INDIEWEB_CORS_ALLOWED_ORIGINS = "*"`` and
``INDIEWEB_CORS_ALLOW_CREDENTIALS = True`` is unsupported. django-indieweb logs
a warning, keeps ``Access-Control-Allow-Origin: *``, and does not emit
``Access-Control-Allow-Credentials: true``.

Configured preflight ``OPTIONS`` requests short-circuit before rate limiting,
token authentication, Micropub handler work, media storage, Webmention
processing, and async enqueue hooks. WebSub subscriber callbacks are excluded
from built-in CORS because they are server-to-server hub callbacks. A valid
preflight needs an allowed ``Origin`` plus an
``Access-Control-Request-Method`` that is supported by the target endpoint.
Disallowed-origin responses and preflight rejections include ``Vary: Origin``
for explicit allowlists and do not receive permissive CORS headers. Existing
``Access-Control-Allow-Origin`` headers set by downstream middleware are not
overwritten.
Successful preflights return:

.. code-block:: http

    HTTP/1.1 204 No Content
    Access-Control-Allow-Origin: https://app.example.com
    Access-Control-Allow-Methods: POST
    Access-Control-Allow-Headers: Authorization, Content-Type, Accept
    Access-Control-Max-Age: 86400
    Vary: Origin

Endpoint method coverage:

- ``auth`` - ``GET`` and ``POST`` requests to ``/indieweb/auth/``
- ``auth-metadata`` - ``GET`` requests to ``/indieweb/auth/metadata/``
- ``token`` - ``POST`` requests to ``/indieweb/token/``
- ``token_introspection`` - ``POST`` requests to
  ``/indieweb/token/introspect/``
- ``micropub`` - ``GET`` and ``POST`` requests to ``/indieweb/micropub/``
- ``media`` - ``POST`` requests to ``/indieweb/media/``
- ``webmention`` - ``GET`` and ``POST`` requests to ``/indieweb/webmention/``
- ``webmention_status`` - ``GET`` requests to
  ``/indieweb/webmention/<status-token>/``

Disallowed origins receive no permissive CORS headers. The browser
token-management pages at ``/indieweb/tokens/`` and
``/indieweb/tokens/<pk>/revoke/`` are excluded because they are authenticated
Django UI views with CSRF-protected browser actions, not public protocol
endpoints.


H-Card Support
--------------

While h-cards are not accessed via HTTP endpoints, django-indieweb provides models and template tags for managing user profile data.

Models
~~~~~~

**Profile Model**

Store h-card data for users:

.. code-block:: python

    from indieweb.models import Profile

    profile = Profile.objects.create(
        user=user,
        name="Display Name",
        h_card={
            "name": ["Display Name"],
            "url": ["https://example.com"],
            "photo": ["https://example.com/photo.jpg"]
        }
    )

Template Tags
~~~~~~~~~~~~~

**h_card Tag**

Render h-card microformats in templates:

.. code-block:: django

    {% load indieweb_tags %}
    {% h_card user %}

Utilities
~~~~~~~~~

**Parsing Functions**

.. code-block:: python

    from indieweb.h_card import parse_h_card, validate_h_card

    # Parse h-card from HTML
    h_card_data = parse_h_card(html_string)

    # Validate h-card structure
    is_valid = validate_h_card(h_card_data)

See :doc:`h-card` for detailed documentation.
