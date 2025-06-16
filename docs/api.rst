API Reference
=============

This document describes the IndieWeb endpoints provided by django-indieweb.

.. warning::
   The Micropub endpoint is currently not fully implemented. It accepts requests
   but does not actually create content. This is a limitation of the current version.

Endpoints Overview
------------------

django-indieweb provides three main endpoints:

- ``/indieweb/auth/`` - IndieAuth authorization endpoint
- ``/indieweb/token/`` - Token endpoint for exchanging auth codes
- ``/indieweb/micropub/`` - Micropub endpoint for creating content (stub implementation)

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

.. warning::
   This endpoint is currently a stub implementation. It accepts requests but
   does not actually create content in the database.

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

Creates a new post (currently only returns success without creating content).

**Common Parameters:**

- ``h`` - The entry type (e.g., "entry")
- ``content`` - The post content
- ``category`` - Comma-separated categories
- ``in-reply-to`` - URL this post is replying to
- ``location`` - Geographic location in geo URI format

**Example Request:**

.. code-block:: http

    POST /indieweb/micropub/ HTTP/1.1
    Host: yoursite.com
    Authorization: Bearer xyz789
    Content-Type: application/x-www-form-urlencoded

    h=entry&content=Hello+World&category=test,indieweb

**Location Format:**

- Simple: ``geo:37.786971,-122.399677``
- With uncertainty: ``geo:37.786971,-122.399677;u=35``

**Response:**

.. code-block:: http

    HTTP/1.1 201 Created
    Content-Type: text/plain

    created

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
