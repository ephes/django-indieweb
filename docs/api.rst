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

Endpoints Overview
------------------

django-indieweb provides these endpoints and browser views:

- ``/indieweb/auth/`` - IndieAuth authorization endpoint
- ``/indieweb/token/`` - Token endpoint for exchanging auth codes
- ``/indieweb/tokens/`` - Browser UI for authenticated users to view and revoke their own tokens
- ``/indieweb/micropub/`` - Micropub endpoint for creating, querying, updating, and deleting content
- ``/indieweb/media/`` - Micropub media endpoint for direct media uploads
- ``/indieweb/websub/<token>/`` - WebSub subscriber callback for one subscription token
- ``/indieweb/webmention/`` - Webmention endpoint for receiving webmentions
- ``/indieweb/webmention/<pk>/`` - Webmention status endpoint

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
``X-Hub-Signature-256`` or ``X-Hub-Signature`` HMAC header. Invalid signatures
return HTTP ``403`` and do not call the host hook.

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

**Optional Parameters:**

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
- If user is authenticated: Redirects to ``redirect_uri`` with auth code

**Example Response:**

.. code-block:: http

    HTTP/1.1 302 Found
    Location: https://app.example.com/callback?code=abc123&state=1234567890&me=https://user.example.com

POST Request
~~~~~~~~~~~~

Verifies an authorization code (used for code verification).

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

Returns the ``me`` parameter associated with the auth code.

**Example Response:**

.. code-block:: http

    HTTP/1.1 200 OK
    Content-Type: application/x-www-form-urlencoded

    me=https://user.example.com

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

- ``redirect_uri`` - If sent, it must be a syntactically valid ``http``/``https`` URL with no fragment delimiter (``#``) and no userinfo (``user:pass@``), and must match the value used in the original auth request after normalizing scheme and host case (path and query are compared verbatim); malformed values and mismatches are rejected with ``invalid_grant``
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

Returns an access token.

**Example Response:**

.. code-block:: http

    HTTP/1.1 201 Created
    Content-Type: application/x-www-form-urlencoded

    access_token=xyz789&scope=create&me=https://user.example.com&expires_in=86400

The ``expires_in`` value is the remaining token lifetime in seconds. The
default lifetime is 24 hours and can be tuned with the
``INDIEWEB_TOKEN_EXPIRES_IN`` setting (see :doc:`configuration`). Reissuing a
token via the IndieAuth flow refreshes its expiration. Tokens whose
``expires_at`` has passed are rejected with HTTP 401 by the Micropub endpoint.

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

    authentication error

Micropub Endpoint
-----------------

**URL:** ``/indieweb/micropub/``

The Micropub endpoint supports creating, updating, and deleting content through
a pluggable handler system. See :doc:`micropub` for detailed implementation guide.

Authentication
~~~~~~~~~~~~~~

All Micropub requests require a valid access token provided either:

1. In the ``Authorization`` header: ``Authorization: Bearer <token>``
2. In the POST body: ``Authorization=Bearer <token>``

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
            "category": ["test", "indieweb"]
        }
    }

**Response:**

.. code-block:: http

    HTTP/1.1 201 Created
    Location: https://yoursite.com/posts/123/

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
  arrays), or ``delete`` is neither a list of strings nor a map of property
  names to arrays
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

Returns supported post types and features.

The default in-memory handler advertises these post types:

- ``note`` - ``content``
- ``article`` - ``name``, ``content``
- ``photo`` - ``photo``, optional ``content`` and ``category``
- ``reply`` - ``in-reply-to``, ``content``
- ``bookmark`` - ``bookmark-of``, ``name``, ``content``
- ``like`` - ``like-of``
- ``repost`` - ``repost-of``
- ``event`` - ``name``, ``summary``, ``description``, ``start``, ``end``,
  ``location``, ``category``, ``url``, ``published``
- ``rsvp`` - ``rsvp``, ``in-reply-to``, ``name``, ``content``

**Source Query:**

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
``properties[]=NAME``. When a filter is present, the response contains only
the requested properties that exist on the entry, and omits ``type`` to match
the Micropub source-query examples:

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

``GET ?q=source`` returns ``400 invalid_request`` when ``url`` is missing or
unknown to the handler, and ``500 Internal Server Error`` when the handler
raises an unexpected exception. Scope failures still return ``403`` with
body ``authorization error`` before source-query dispatch.

**Syndication Targets Query:**

.. code-block:: http

    GET /indieweb/micropub/?q=syndicate-to HTTP/1.1
    Authorization: Bearer xyz789

Returns available syndication targets.

Micropub Media Endpoint
-----------------------

**URL:** ``/indieweb/media/``

The Micropub media endpoint accepts direct file uploads for clients that
discover ``media-endpoint`` through ``GET /indieweb/micropub/?q=config``.
It uses the same bearer-token authentication path as the Micropub endpoint,
including token expiration, inactive-owner rejection, and the configured
``INDIEWEB_CLIENT_ID_VALIDATOR`` resource-server policy.

Uploads require the exact ``media`` scope. This follows the convention used by
Quill and similar Micropub clients, while keeping django-indieweb's scope model
explicit. The scope check is separate from ``create``/``post`` so a token that
can create entries cannot upload files unless the user approved media access.

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

**Error Response:**

- ``400 Bad Request`` body ``invalid_request`` when the request is not
  ``multipart/form-data`` or does not include a ``file`` part
- ``401 Unauthorized`` body ``authentication error`` for missing, invalid, or
  expired tokens, or inactive token owners
- ``413 Payload Too Large`` body ``invalid_request`` when the uploaded file
  exceeds ``INDIEWEB_MEDIA_MAX_UPLOAD_BYTES``
- ``415 Unsupported Media Type`` body ``invalid_request`` when the uploaded
  file's content type is not in ``INDIEWEB_MEDIA_ALLOWED_TYPES``
- ``403 Forbidden`` body ``authorization error`` when the token lacks the
  ``media`` scope
- ``403 Forbidden`` body ``invalid_client`` when the stored token's
  ``client_id`` is rejected by ``INDIEWEB_CLIENT_ID_VALIDATOR``
- ``500 Internal Server Error`` if the configured Django storage backend raises
  unexpectedly while saving the upload

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
    Location: https://yoursite.com/indieweb/webmention/123/

**Queued Response:**

When ``INDIEWEB_WEBMENTION_ENQUEUE`` is configured, the endpoint creates or
reuses the ``Webmention`` row, calls the configured enqueue hook with that row's
primary key, and returns ``202 Accepted`` with a status ``Location``:

.. code-block:: http

    HTTP/1.1 202 Accepted
    Location: https://yoursite.com/indieweb/webmention/123/

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

**URL:** ``/indieweb/webmention/<pk>/``

Returns the stored status for a received Webmention:

.. code-block:: http

    HTTP/1.1 200 OK
    Content-Type: application/json

    {"source": "https://source.example/post", "target": "https://yoursite.com/post", "status": "pending", "vouch": "https://trusted.example/vouch"}

The response includes ``vouch`` when the Webmention has stored Vouch metadata,
``verified_at`` when the Webmention has been verified, and
``vouch_verified_at`` when configured Vouch verification has succeeded. Missing
IDs return ``404``.

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
- ``redirect_uri`` sent on token exchange does not match the value stored with the auth code (after lowercasing scheme and host)
- ``code_verifier`` is missing on token exchange when the auth code was issued with a ``code_challenge``
- ``code_verifier`` does not match the stored ``code_challenge`` under the stored ``code_challenge_method`` (``S256`` or ``plain``)
- ``code_verifier`` is submitted on token exchange but no ``code_challenge`` was stored with the auth code
- ``code_verifier`` is malformed (length outside 43-128 or characters outside the unreserved set ``[A-Za-z0-9._~-]``)

**400 Bad Request — ``invalid_request``**

- Missing required ``code`` or ``client_id`` on token exchange
- ``client_id`` on token exchange is malformed (invalid URL, contains a ``#``
  delimiter, includes userinfo, or uses a disallowed scheme)
- ``client_id`` on token exchange is rejected by the configured
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
- Micropub ``GET ?q=source`` with a missing ``url`` parameter or a ``url``
  unknown to the configured handler. Missing requested ``properties[]`` names
  are omitted from successful filtered responses instead of causing an error.
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

**403 Forbidden**

- Token lacks the scope required for the requested Micropub operation
  (``authorization error``). Per-operation requirements: ``POST`` entry create
  requires ``create`` (or the legacy alias ``post``); ``POST action=update``
  requires ``update``; ``POST action=delete`` requires ``delete``;
  ``POST action=undelete`` requires ``undelete``; ``GET ?q=source`` requires
  ``update``; ``POST /indieweb/media/`` requires ``media``; and multipart
  create uploads sent to ``POST /indieweb/micropub/`` remain create requests,
  requiring ``create`` or ``post`` rather than ``media``. ``GET ?q=config``,
  ``GET ?q=syndicate-to``, and ``GET`` with no ``q`` only require an
  authenticated token. Stored ``scope`` is split on whitespace and matched as
  an exact token, so ``createXYZ`` does not satisfy ``create`` and
  ``mediaXYZ`` does not satisfy ``media``.
- The stored token's ``client_id`` is rejected by the configured
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
  ``INDIEWEB_CLIENT_ID_VALIDATOR`` callable, or that callable cannot be
  imported (fail-closed)

**400 Bad Request — ``invalid_request`` (authorization endpoint)**

- ``code_challenge`` on the authorization endpoint is malformed (length
  outside 43-128 or characters outside the unreserved set ``[A-Za-z0-9._~-]``)
- ``code_challenge_method`` is not one of ``S256`` or ``plain``

**404 Not Found**

- Missing required parameters on the authorization endpoint

**500 Internal Server Error**

- A configured Micropub handler raised an exception other than
  ``ValueError`` while servicing ``POST action=update``/``delete``/``undelete``,
  or raised any exception while servicing ``GET ?q=source``. The exception is
  logged via ``logger.exception`` so the stack trace stays in the server log
  rather than the response body.
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

``GET ?q=config``, ``GET ?q=syndicate-to``, and ``GET`` with no ``q`` only
require an authenticated token; no specific scope is enforced.

Multiple scopes can be requested by separating with spaces: ``scope=create update``

Rate Limiting
-------------

django-indieweb can rate-limit its public protocol endpoints with Django's
cache framework. Rate limiting is disabled by default; set
``INDIEWEB_RATE_LIMITS`` to opt in. See :doc:`configuration` for the setting
shape and deployment notes.

Endpoint keys:

- ``auth`` - ``GET`` and ``POST`` requests to ``/indieweb/auth/``
- ``token`` - ``POST`` requests to ``/indieweb/token/``
- ``micropub`` - ``GET`` and ``POST`` requests to ``/indieweb/micropub/``
- ``media`` - ``POST`` requests to ``/indieweb/media/``
- ``websub_callback`` - ``GET`` and ``POST`` requests to
  ``/indieweb/websub/<token>/``
- ``webmention`` - ``GET`` and ``POST`` requests to ``/indieweb/webmention/``
- ``webmention_status`` - ``GET`` requests to
  ``/indieweb/webmention/<pk>/``

Counters are scoped by endpoint key, HTTP method, and the client identity from
``REMOTE_ADDR``. ``GET`` and ``POST`` requests to the same endpoint use
independent counters, so set each endpoint limit as a per-method budget.
django-indieweb does not trust ``X-Forwarded-For`` directly. Deployments
behind a proxy should configure trusted upstream middleware or infrastructure
so Django receives the intended client address in ``REMOTE_ADDR``.

When a configured limit is exceeded, the endpoint returns:

.. code-block:: http

    HTTP/1.1 429 Too Many Requests
    Content-Type: text/plain
    Retry-After: 60

    rate limit exceeded

``Retry-After`` is included when the cache-backed window reset time is
available. Requests below the limit keep the same response bodies, status
codes, authentication behavior, scope checks, and processing flow as before.
The browser token-management pages are not covered by these protocol endpoint
rate-limit keys.

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
  ``INDIEWEB_CORS_ALLOW_CREDENTIALS`` is enabled
- ``Vary: Origin`` whenever the response echoes a specific request origin

Configured preflight ``OPTIONS`` requests short-circuit before rate limiting,
token authentication, Micropub handler work, media storage, Webmention
processing, and async enqueue hooks. WebSub subscriber callbacks are excluded
from built-in CORS because they are server-to-server hub callbacks. A valid preflight needs an allowed
``Origin`` plus an ``Access-Control-Request-Method`` that is supported by the
target endpoint. Successful preflights return:

.. code-block:: http

    HTTP/1.1 204 No Content
    Access-Control-Allow-Origin: https://app.example.com
    Access-Control-Allow-Methods: POST
    Access-Control-Allow-Headers: Authorization, Content-Type, Accept
    Access-Control-Max-Age: 86400
    Vary: Origin

Endpoint method coverage:

- ``auth`` - ``GET`` and ``POST`` requests to ``/indieweb/auth/``
- ``token`` - ``POST`` requests to ``/indieweb/token/``
- ``micropub`` - ``GET`` and ``POST`` requests to ``/indieweb/micropub/``
- ``media`` - ``POST`` requests to ``/indieweb/media/``
- ``webmention`` - ``GET`` and ``POST`` requests to ``/indieweb/webmention/``
- ``webmention_status`` - ``GET`` requests to
  ``/indieweb/webmention/<pk>/``

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
