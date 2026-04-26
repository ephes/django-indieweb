IndieAuth Implementation
========================

Django-IndieWeb provides a complete IndieAuth implementation that supports both authentication (logging into sites) and authorization (granting permissions to apps).

Overview
--------

IndieAuth is a federated login protocol that enables users to sign in to websites using their own domain name. Django-IndieWeb implements all three IndieAuth endpoints:

1. **Authorization Endpoint** (``/indieweb/auth/``) - Handles user consent and generates auth codes
2. **Token Endpoint** (``/indieweb/token/``) - Exchanges auth codes for access tokens
3. **Authentication** - Verifies auth codes for login-only flows

Authorization Flow with Consent Screen
--------------------------------------

When a client application requests authorization with scopes (permissions), Django-IndieWeb displays a consent screen to the user.

The consent screen shows:

* The client application requesting access (client_id)
* The user's identity URL (me)
* Requested permissions/scopes (if any)
* Approve and Deny buttons

Example consent screen::

    Authorization Request

    https://quill.p3k.io is requesting access to your site.

    Your identity URL: https://example.com

    Requested permissions:
    • create
    • update
    • delete

    [Approve] [Deny]

Authentication vs Authorization
-------------------------------

Django-IndieWeb supports two different IndieAuth flows:

**Authentication Only (No Scopes)**
   Used when logging into websites with your domain. No consent screen is required since no permissions are granted::

      GET /indieweb/auth/?me=https://example.com&client_id=https://site.com&redirect_uri=...&state=...

**Authorization with Scopes**
   Used when granting permissions to apps (like Micropub clients). Shows consent screen::

      GET /indieweb/auth/?me=https://example.com&client_id=https://app.com&redirect_uri=...&state=...&scope=create+update

Common scopes include:

* ``create`` - Create new posts
* ``update`` - Edit existing posts
* ``delete`` - Delete posts
* ``media`` - Upload media files

Customizing the Consent Screen
------------------------------

The consent screen template can be customized by overriding ``indieweb/consent.html`` in your project:

1. Create the directory structure in your templates folder::

      templates/
      └── indieweb/
          └── consent.html

2. Copy the default template as a starting point::

      {% extends "base.html" %}

      {% block content %}
      <div class="authorization-request">
          <h1>Authorization Request</h1>

          <p><strong>{{ client_id }}</strong> is requesting access to your site.</p>

          {% if scope_list %}
          <p>Requested permissions:</p>
          <ul>
              {% for permission in scope_list %}
              <li>{{ permission }}</li>
              {% endfor %}
          </ul>
          {% endif %}

          <form method="post">
              {% csrf_token %}
              <input type="hidden" name="client_id" value="{{ client_id }}">
              <input type="hidden" name="redirect_uri" value="{{ redirect_uri }}">
              <input type="hidden" name="state" value="{{ state }}">
              <input type="hidden" name="me" value="{{ me }}">
              {% if scope %}
              <input type="hidden" name="scope" value="{{ scope }}">
              {% endif %}
              {% if code_challenge %}
              <input type="hidden" name="code_challenge" value="{{ code_challenge }}">
              <input type="hidden" name="code_challenge_method" value="{{ code_challenge_method }}">
              {% endif %}

              <button type="submit" name="action" value="approve">Approve</button>
              <button type="submit" name="action" value="deny">Deny</button>
          </form>
      </div>
      {% endblock %}

Available template context variables:

* ``client_id`` - The application requesting access
* ``redirect_uri`` - Where to redirect after authorization
* ``state`` - State parameter for CSRF protection
* ``me`` - The user's identity URL
* ``scope`` - Space-separated list of requested scopes
* ``scope_list`` - Python list of individual scopes
* ``code_challenge`` - PKCE challenge from the authorization request, or
  ``None`` when no PKCE was sent. Custom templates that omit this hidden
  input will silently drop PKCE and will not interoperate with PKCE clients.
* ``code_challenge_method`` - PKCE method (``S256`` or ``plain``) paired with
  ``code_challenge``

Security Considerations
-----------------------

1. **HTTPS Required**: Always use HTTPS in production for all IndieAuth endpoints
2. **Auth Code Timeout**: Auth codes expire after 60 seconds by default
3. **Token Expiration**: Access tokens expire after 24 hours by default; the
   Micropub endpoint rejects expired tokens with HTTP 401
4. **CSRF Protection**: The consent form includes Django's CSRF token
5. **User Authentication**: Users must be logged in to approve/deny requests
6. **PKCE (RFC 7636)**: The authorization endpoint accepts an optional
   ``code_challenge`` (43-128 characters from the unreserved set
   ``[A-Za-z0-9._~-]``) and ``code_challenge_method`` (``S256`` or
   ``plain``; defaults to ``plain`` when ``code_challenge`` is sent without a
   method, per RFC 7636 §4.3). Malformed challenges and unsupported methods
   are rejected with HTTP 400 *before* any authorization code is issued.
   When an auth code was issued with a ``code_challenge``, the token
   endpoint requires a matching ``code_verifier`` and rejects any mismatch,
   any missing verifier, any verifier submitted without a stored challenge,
   and any verifier outside the RFC length and character set with
   ``invalid_grant``. The S256 verification computes
   ``BASE64URL-WITHOUT-PADDING(SHA256(verifier))`` and compares it to the
   stored challenge in constant time. Auth codes issued before this change
   (no ``code_challenge`` stored) continue to be redeemable without a
   ``code_verifier``, preserving backwards compatibility for legacy clients.
7. **client_id Validation**: Submitted ``client_id`` values must be
   syntactically valid URLs using the ``http`` or ``https`` scheme. They must
   not contain a fragment delimiter (``#``) at all, even with no fragment
   content, and must not include userinfo (``user:pass@``). The authorization
   endpoint (GET, consent POST, and code-verification POST) rejects
   malformed values with HTTP 400 *before* creating an authorization code:
   plain-text body ``invalid client_id`` for structural failures and
   ``invalid_client`` for validator failures. The token endpoint rejects
   malformed submissions with HTTP 400 ``invalid_request`` and content type
   ``application/x-www-form-urlencoded`` (matching the existing missing-
   ``code`` case). Operators can additionally restrict which clients are
   allowed by setting ``INDIEWEB_CLIENT_ID_VALIDATOR`` (see
   :doc:`configuration`); the configured callable runs at every
   authorization/token path and on every Micropub request, so revoking a
   client takes effect immediately for previously-issued tokens. A
   misconfigured validator (the dotted path fails to import or the callable
   raises) fails closed at every call site. Stored ``client_id`` values are
   not re-validated *structurally* on use, matching the ``redirect_uri``
   rule; the configured validator, however, IS re-applied on use, so
   pre-existing tokens whose ``client_id`` no longer satisfies operator
   policy are rejected with HTTP 403 ``invalid_client`` on the Micropub
   endpoint.
8. **redirect_uri Validation**: Submitted ``redirect_uri`` values must be
   syntactically valid URLs using the ``http`` or ``https`` scheme. They must
   not contain a fragment delimiter (``#``) at all, even with no fragment
   content, and must not include userinfo (``user:pass@``). The authorization
   endpoint rejects malformed values with HTTP 400 *before* creating an
   authorization code; the token endpoint rejects malformed submissions with
   ``invalid_grant``. When comparing the value submitted at the token
   endpoint with the value stored alongside the authorization code, the
   scheme and host are compared case-insensitively while the path and query
   are compared verbatim. ``redirect_uri`` values that already contain a
   query (e.g. ``?next=/x``) are preserved when ``code`` and ``state`` are
   appended.
9. **Per-Operation Scope Enforcement**: The Micropub resource server enforces
   scopes per operation rather than treating ``create`` as a master scope.
   The W3C Micropub Recommendation (`§5 Scope
   <https://www.w3.org/TR/micropub/#scope>`_) allows servers to define their
   own granular scopes; the names below are the project's chosen policy and
   follow the conventional names that reference clients (Quill, Indigenous,
   Micropublish) request. ``POST`` entry create requires ``create`` (the
   legacy alias ``post`` is still accepted); ``POST action=update`` requires
   ``update``; ``POST action=delete`` requires ``delete``;
   ``POST action=undelete`` requires ``undelete``; ``GET ?q=source`` requires
   ``update`` (the spec does not define a separate read scope and the typical
   use case for ``q=source`` is "fetch a post to edit it").
   ``GET ?q=config``, ``GET ?q=syndicate-to``, and ``GET`` with no ``q`` only
   require an authenticated token. Stored ``scope`` is split on whitespace
   and compared as an exact token, so ``createXYZ`` does not satisfy
   ``create``. Scope failures return HTTP 403 with the plain-text body
   ``authorization error``. The ``update``, ``delete``, and ``undelete``
   actions and the ``GET ?q=source`` query dispatch into the configured
   ``MicropubContentHandler`` after the scope check succeeds.

Configuration
-------------

Configure IndieAuth behavior in your Django settings::

    # Auth code expiration time in seconds (default: 60)
    INDIWEB_AUTH_CODE_TIMEOUT = 60

    # Access token lifetime in seconds (default: 86400, i.e. 24 hours)
    INDIEWEB_TOKEN_EXPIRES_IN = 86400

    # Login URL for redirecting unauthenticated users
    LOGIN_URL = "/accounts/login/"

Testing IndieAuth
-----------------

Test your IndieAuth implementation using:

1. **Web-based testers**:

   * https://indieauth.com/
   * https://indielogin.com/

2. **Micropub clients** (for authorization):

   * Quill (https://quill.p3k.io/)
   * Indigenous for iOS/Android
   * Micropublish (https://micropublish.net/)

3. **Unit tests**::

       def test_consent_screen_displays(client, user):
           client.login(username=user.username, password="password")

           response = client.get("/indieweb/auth/", {
               "me": "https://example.com",
               "client_id": "https://app.example.com",
               "redirect_uri": "https://app.example.com/callback",
               "state": "12345",
               "scope": "create"
           })

           assert response.status_code == 200
           assert "Authorization Request" in response.content.decode()

Example: Using IndieAuth with a Micropub Client
------------------------------------------------

1. Configure your site's homepage to advertise the endpoints:

   .. code-block:: html

      <link rel="authorization_endpoint" href="https://mysite.com/indieweb/auth/">
      <link rel="token_endpoint" href="https://mysite.com/indieweb/token/">
      <link rel="micropub" href="https://mysite.com/indieweb/micropub/">

2. When a Micropub client tries to authenticate:

   a. It discovers your endpoints from your homepage
   b. Redirects you to the authorization endpoint
   c. You see the consent screen and approve/deny
   d. The client receives an auth code
   e. The client exchanges the code for an access token
   f. The client can now create posts using the token

Troubleshooting
---------------

**"Missing parameter" errors**
   Ensure all required parameters are provided: ``me``, ``client_id``, ``redirect_uri``, ``state``

**Consent screen not showing**
   Check that you're logged in and all parameters are valid

**Auth code expired**
   Auth codes are only valid for 60 seconds. The client must exchange them quickly.

**No scopes shown on consent screen**
   This is normal for authentication-only flows. Scopes are only shown when the client requests permissions.
