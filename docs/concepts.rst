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
- ``photo`` - Image URLs

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
           +created: datetime
       }

       class Token {
           +key: str
           +owner: User
           +client_id: str
           +me: str
           +scope: str
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

       Auth --> AuthView : creates
       AuthView --> TokenView : provides code
       TokenView --> Token : creates
       Token --> MicropubView : authenticates

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

3. **Content Creation**

   - Client sends POST to MicropubView with token
   - Token validated (exists, active user, correct scope)
   - Content would be created (not implemented)
   - Success response returned

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

- Long-lived (no built-in expiration)
- Bound to user, client, and scope
- Can be revoked by deleting Token object
- Should be transmitted over HTTPS only

Scopes
~~~~~~

Scopes limit what actions a token can perform:

- ``create`` - Create new posts
- ``update`` - Modify existing posts (not implemented)
- ``delete`` - Remove posts (not implemented)
- ``read`` - Access private posts (not implemented)

Best Practices
--------------

For Service Providers
~~~~~~~~~~~~~~~~~~~~~

1. Always use HTTPS in production
2. Validate all parameters strictly
3. Implement rate limiting
4. Log authorization attempts
5. Consider token expiration

For Users
~~~~~~~~~

1. Only authorize apps you trust
2. Use unique passwords for your domain
3. Review authorized apps regularly
4. Revoke unused tokens

Limitations
-----------

Current implementation limitations:

1. **Micropub is not functional** - Only returns success without creating content
2. **No token expiration** - Tokens are valid indefinitely
3. **No token revocation UI** - Must delete via Django admin
4. **No scope enforcement** - Only checks for "post" in scope
5. **No media endpoint** - Can't upload images
6. **No update/delete** - Only create operations

Future Enhancements
-------------------

Potential improvements for full IndieWeb support:

1. **Functional Micropub** - Actually create content
2. **Media Endpoint** - Handle file uploads
3. **Micropub Extensions** - Update, delete, undelete
4. **Token Management** - UI for viewing/revoking tokens
5. **WebSub** - Real-time updates
6. **Webmention** - Receive mentions from other sites

Resources
---------

- `IndieWeb.org <https://indieweb.org/>`_ - Main IndieWeb community site
- `IndieAuth Spec <https://indieauth.spec.indieweb.org/>`_ - Protocol specification
- `Micropub Spec <https://micropub.spec.indieweb.org/>`_ - Micropub specification
- `IndieAuth.com <https://indieauth.com/>`_ - Reference implementation
