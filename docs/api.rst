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

       Client->>AuthEndpoint: GET with client_id, redirect_uri, state, me
       AuthEndpoint->>User: Redirect to login if not authenticated
       User->>AuthEndpoint: Login
       AuthEndpoint->>Client: Redirect with auth code
       Client->>TokenEndpoint: POST with code, client_id, redirect_uri
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
- ``redirect_uri`` - Must match the original auth request
- ``me`` - The user's profile URL
- ``scope`` - The requested scope

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

    access_token=xyz789&scope=create&me=https://user.example.com&expires_in=10

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

**401 Unauthorized**

- Missing or invalid authentication token
- Expired authorization code
- Invalid authorization code

**403 Forbidden**

- Token lacks required scope
- User account is inactive

**404 Not Found**

- Missing required parameters

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
