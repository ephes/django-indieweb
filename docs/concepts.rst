IndieWeb Concepts
=================

This document explains the IndieWeb concepts and protocols implemented by django-indieweb.

What is IndieWeb?
-----------------

The IndieWeb is a people-focused alternative to the "corporate web". It's a community of
independent website owners who want to own their data and stay connected. Key principles include:

- **Own your data** - Your content lives on your domain
- **Syndicate elsewhere** - Cross-post to social networks
- **Interoperability** - Standards-based protocols for communication

IndieAuth Protocol
------------------

IndieAuth is a federated login protocol that uses your own domain name as your identity.
It's built on top of OAuth 2.0 but simplified for the IndieWeb use case.

How IndieAuth Works
~~~~~~~~~~~~~~~~~~~

.. mermaid::

   graph TD
       A[User owns domain.com] --> B[User wants to sign in to app.com]
       B --> C[App redirects to user's auth endpoint]
       C --> D[User authenticates on their own site]
       D --> E[Auth endpoint redirects back with code]
       E --> F[App exchanges code for verification]
       F --> G[User is logged in as domain.com]

Key Components
~~~~~~~~~~~~~~

1. **Identity (me)** - Your domain name (e.g., ``https://example.com``)
2. **Client ID** - The application requesting authentication
3. **Authorization Endpoint** - Where users approve access
4. **Token Endpoint** - Where codes are exchanged for tokens
5. **Redirect URI** - Where to return after authorization

IndieAuth vs OAuth
~~~~~~~~~~~~~~~~~~

While similar to OAuth, IndieAuth has key differences:

- Your identity is your domain, not an account on a service
- No client registration required
- Simpler flow focused on authentication and authorization
- Designed for individual website owners

Micropub Protocol
-----------------

Micropub is a protocol for creating posts on your website using third-party clients.

Core Concepts
~~~~~~~~~~~~~

.. mermaid::

   graph LR
       A[Micropub Client] --> B[Sends POST request]
       B --> C[With access token]
       C --> D[To Micropub endpoint]
       D --> E[Creates content]
       E --> F[Returns 201 Created]

Post Types
~~~~~~~~~~

Micropub supports various post types through the ``h`` parameter:

- ``h-entry`` - Standard blog posts, notes, articles
- ``h-event`` - Events with start/end times
- ``h-card`` - Profile/contact information

Common Properties
~~~~~~~~~~~~~~~~~

- ``content`` - The main post content
- ``name`` - Post title
- ``category`` - Tags/categories
- ``in-reply-to`` - URL being replied to
- ``location`` - Geographic coordinates
- ``photo`` - Image URLs, or uploaded photo files on multipart create requests

Implementation Architecture
---------------------------

django-indieweb implements these protocols with three main components:

.. mermaid::

   classDiagram
       class Auth {
           +key: str
           +owner: User
           +client_id: str
           +redirect_uri: str
           +scope: str
           +me: str
           +code_challenge: str
           +code_challenge_method: str
           +created: datetime
       }

       class Token {
           +key: str
           +owner: User
           +client_id: str
           +me: str
           +scope: str
           +expires_at: datetime
           +created: datetime
       }

       class AuthView {
           +get() : authorization code
           +post() : verify code
       }

       class TokenView {
           +post() : access token
       }

       class MicropubView {
           +get() : configuration
           +post() : create content
       }

       class MicropubMediaView {
           +post() : upload media
       }

       Auth --> AuthView : creates
       AuthView --> TokenView : provides code
       TokenView --> Token : creates
       Token --> MicropubView : authenticates
       Token --> MicropubMediaView : authenticates

Data Flow
~~~~~~~~~

1. **Authorization Phase**

   - User visits AuthView with client details
   - Django authenticates user (standard login)
   - Auth object created with temporary code
   - User redirected back to client with code

2. **Token Exchange**

   - Client POSTs code to TokenView
   - Code validated (exists, not expired, matches parameters)
   - Token object created with access key
   - Access token returned to client

3. **Micropub Operations**

   - Client sends a Micropub request to MicropubView with token
   - Token validated (exists, active user, scope matches the requested
     operation)
   - The configured ``MicropubContentHandler`` creates, retrieves, updates,
     deletes, or undeletes entries (the in-memory handler ships by default;
     see :doc:`micropub` for custom handlers)
   - Creates return ``201 Created`` with a ``Location`` header; successful
     update/delete/undelete actions return ``204 No Content`` unless an
     update or undelete relocates the entry and returns ``201 Created``

4. **Micropub Media Uploads**

   - Client discovers the media endpoint from ``GET /indieweb/micropub/?q=config``
   - Client sends ``multipart/form-data`` to ``/indieweb/media/`` with a
     bearer token that has ``media`` scope
   - The ``file`` part is stored through Django's configured storage backend
     using an unguessable name
   - The endpoint returns ``201 Created`` with a ``Location`` header that can
     be used as a later Micropub ``photo``, ``audio``, or ``video`` URL value

5. **Multipart Create Photo Uploads**

   - Client can also send ``multipart/form-data`` directly to
     ``/indieweb/micropub/`` for entry creation
   - ``photo`` file parts are validated and stored through the same media
     storage policy used by ``/indieweb/media/``
   - Stored media URLs are appended to the created entry's ``photo`` property
     alongside any URL-valued ``photo`` fields sent in the same request
   - Because this creates an entry, the request uses the create/post scope
     rule rather than the direct media endpoint's ``media`` scope

Security Model
--------------

Authorization Codes
~~~~~~~~~~~~~~~~~~~

- Single use - deleted after exchange
- Time limited - 60 seconds by default
- Bound to specific client_id and redirect_uri
- Random 32-character strings

Access Tokens
~~~~~~~~~~~~~

- Expire after ``INDIEWEB_TOKEN_EXPIRES_IN`` seconds (default 86400, i.e. 24 hours); reissuing the token via the IndieAuth flow refreshes the expiration
- Tokens issued before expiration tracking was added have ``expires_at=NULL`` and remain valid until they are reissued or deleted
- Bound to user, client, and scope
- Can be revoked by the owning user at ``/indieweb/tokens/`` or by deleting
  the ``Token`` object directly
- Should be transmitted over HTTPS only

Scopes
~~~~~~

Scopes limit what actions a token can perform. During authorization,
django-indieweb normalizes the requested scope string by splitting on
whitespace, removing duplicate tokens while preserving first-seen order, and
joining the result with single spaces. Unknown scope names are accepted and
preserved because IndieAuth/Micropub scopes are extension-defined.

The token endpoint issues the normalized scope stored with the auth code. If a
token exchange includes a ``scope`` parameter, the submitted value is
normalized and must exactly match the stored auth-code scope; clients cannot
broaden, narrow, or replace the approved scope at token issuance time. An
explicitly empty ``scope=`` parameter normalizes to no scope and is accepted
only for an auth code issued with no scope.

The Micropub resource server enforces scopes per operation; see :doc:`api` and
:doc:`indieauth` for the full mapping.

- ``create`` - Required for ``POST`` requests that create new posts (legacy
  alias ``post`` is also accepted)
- ``update`` - Required for ``POST action=update`` and ``GET ?q=source``.
- ``delete`` - Required for ``POST action=delete``
- ``undelete`` - Required for ``POST action=undelete``
- ``media`` - Required for direct uploads to the Micropub media endpoint

Best Practices
--------------

For Service Providers
~~~~~~~~~~~~~~~~~~~~~

1. Always use HTTPS in production
2. Validate all parameters strictly
3. Configure rate limiting for production traffic
4. Log authorization attempts
5. Tune token lifetimes for your risk profile

For Users
~~~~~~~~~

1. Only authorize apps you trust
2. Use unique passwords for your domain
3. Review authorized apps regularly
4. Revoke unused tokens

Limitations
-----------

Current implementation limitations are tracked in ``BACKLOG.md``. Built-in
rate limiting, built-in CORS support, Webmention vouch support, Salmentions,
publisher-side WebSub support, minimal WebSub subscriber callbacks, common
Micropub h-entry post-type advertisement, and Micropub event/RSVP property
forwarding are available. A bundled WebSub hub, automatic subscriber discovery,
background lease renewal, and host-owned event/RSVP storage semantics remain
outside django-indieweb.

Future Enhancements
-------------------

Potential improvements for full IndieWeb support are tracked in ``BACKLOG.md``:

1. **WebSub subscriber operations** - Add optional cleanup/renewal workflows, richer diagnostics, and host-owned worker examples around the minimal callback foundation
2. **Micropub post-type integrations** - Add examples for host applications that map event/RSVP properties into their own content, calendar, or response models

Resources
---------

- `IndieWeb.org <https://indieweb.org/>`_ - Main IndieWeb community site
- `IndieAuth Spec <https://indieauth.spec.indieweb.org/>`_ - Protocol specification
- `Micropub Spec <https://micropub.spec.indieweb.org/>`_ - Micropub specification
- `IndieAuth.com <https://indieauth.com/>`_ - Reference implementation
