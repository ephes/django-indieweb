API Reference
=============

This document describes the IndieWeb endpoints provided by django-indieweb.

.. note::
   The Micropub endpoint is now fully implemented with a pluggable content handler
   system. See the :doc:`micropub` documentation for implementation details.

Endpoints Overview
------------------

django-indieweb provides three main endpoints:

- ``/indieweb/auth/`` - IndieAuth authorization endpoint
- ``/indieweb/token/`` - Token endpoint for exchanging auth codes
- ``/indieweb/micropub/`` - Micropub endpoint for creating content

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
- ``application/json`` - JSON formatted data

**Common Parameters:**

- ``h`` - The entry type (e.g., "entry")
- ``content`` - The post content
- ``name`` - The post title/name
- ``category`` - Categories (comma-separated in form data, array in JSON)
- ``in-reply-to`` - URL this post is replying to
- ``location`` - Geographic location in geo URI format
- ``photo`` - Photo URL(s)
- ``published`` - Publication date

**Form-Encoded Example:**

.. code-block:: http

    POST /indieweb/micropub/ HTTP/1.1
    Host: yoursite.com
    Authorization: Bearer xyz789
    Content-Type: application/x-www-form-urlencoded

    h=entry&content=Hello+World&category=test,indieweb

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
  ``update``. ``GET ?q=config``, ``GET ?q=syndicate-to``, and ``GET`` with
  no ``q`` only require an authenticated token. Stored ``scope`` is split on
  whitespace and matched as an exact token, so ``createXYZ`` does not satisfy
  ``create``.
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
- ``post`` - Legacy alias for ``create``.

``GET ?q=config``, ``GET ?q=syndicate-to``, and ``GET`` with no ``q`` only
require an authenticated token; no specific scope is enforced.

Multiple scopes can be requested by separating with spaces: ``scope=create update``

Rate Limiting
-------------

Currently, no rate limiting is implemented.

CORS Support
------------

CORS headers are not automatically added. Configure your Django middleware if needed.


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
