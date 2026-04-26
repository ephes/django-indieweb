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
       Client->>TokenEndpoint: POST with code, client_id, redirect_uri, code_verifier
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

- ``scope`` - Space-separated list of scopes (e.g., "create update")
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
- ``scope`` - The requested scope; falls back to the value stored with the auth code
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

Query Endpoints
~~~~~~~~~~~~~~~

The Micropub endpoint supports several query parameters:

**Configuration Query:**

.. code-block:: http

    GET /indieweb/micropub/?q=config HTTP/1.1
    Authorization: Bearer xyz789

Returns supported post types and features.

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

**401 Unauthorized**

- Missing or invalid access token
- Expired access token
- User account associated with the token is inactive

**403 Forbidden**

- Token lacks required scope (``authorization error``)
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

Scopes
------

The following scopes are supported:

- ``create`` - Create new posts
- ``update`` - Update existing posts (not implemented)
- ``delete`` - Delete posts (not implemented)
- ``post`` - Alias for create

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
