IndieAuth Implementation
========================

Django-IndieWeb provides a complete IndieAuth implementation that supports both authentication (logging into sites) and authorization (granting permissions to apps).

Overview
--------

IndieAuth is a federated login protocol that enables users to sign in to websites using their own domain name. Django-IndieWeb implements the core IndieAuth endpoints plus public server metadata:

1. **Authorization Endpoint** (``/indieweb/auth/``) - Handles user consent and generates auth codes
2. **Token Endpoint** (``/indieweb/token/``) - Exchanges auth codes for access tokens
3. **Token Introspection Endpoint** (``/indieweb/token/introspect/``) - Verifies issued bearer tokens
4. **Authentication** - Verifies auth codes for login-only flows
5. **Server Metadata** (``/indieweb/auth/metadata/``) - Public JSON discovery for authorization-server capabilities

Authorization Flow with Consent Screen
--------------------------------------

When a client application requests authorization with scopes (permissions), Django-IndieWeb displays a consent screen to the user.

The consent screen shows:

* The client application requesting access (client_id)
* The user's identity URL (me)
* The logged-in user's configured h-card profile URL, when available
* A warning if the submitted ``me`` differs from that configured profile URL
* Requested permissions/scopes (if any)
* Approve and Deny buttons

The bundled consent page is protected against framing with
``X-Frame-Options: DENY`` and ``Content-Security-Policy: frame-ancestors
'none'``. Its bundled styles are served from ``static/css/indieweb.css`` rather
than inline CSS.

Example consent screen::

    Authorization Request

    https://quill.p3k.io is requesting access to your site.

    Your identity URL: https://example.com
    Configured identity URL: https://example.com

    Requested permissions:
    • create
    • update
    • delete

    [Approve] [Deny]

Server Metadata and Discovery
-----------------------------

The reusable metadata endpoint is available at ``/indieweb/auth/metadata/``
when the bundled URLconf is included under ``/indieweb/``. It returns an
IndieAuth/OAuth authorization-server metadata JSON document with absolute URLs
built from the current request:

.. code-block:: json

   {
       "issuer": "https://example.com/indieweb/",
       "authorization_endpoint": "https://example.com/indieweb/auth/",
       "token_endpoint": "https://example.com/indieweb/token/",
       "introspection_endpoint": "https://example.com/indieweb/token/introspect/",
       "response_types_supported": ["code"],
       "grant_types_supported": ["authorization_code"],
       "code_challenge_methods_supported": ["plain", "S256"],
       "scopes_supported": ["create", "update", "delete", "undelete", "media"],
       "service_documentation": "https://django-indieweb.readthedocs.io/en/latest/indieauth.html"
   }

The endpoint is public: it does not require a logged-in Django user or a bearer
token. The advertised capabilities match django-indieweb's current built-in
behavior. The authorization-code grant and ``code`` response type are listed
because the token endpoint exchanges authorization codes. ``plain`` and
``S256`` are both listed by default because both PKCE challenge methods are
accepted today. If ``INDIEWEB_REQUIRE_PKCE_S256`` is enabled, metadata lists
only ``S256``. The scope list advertises the built-in Micropub
resource-server scopes;
the legacy ``post`` alias is still accepted for create requests but is not
advertised as a preferred scope. The extension ``draft`` scope is not
advertised because django-indieweb does not implement built-in draft-only
resource-server behavior. Reader-oriented extension scopes such as ``read``,
``follow``, ``mute``, ``block``, and ``channels`` are also not advertised:
django-indieweb does not implement Microsub or other built-in reader-side
resource-server behavior for them. ``service_documentation`` points to the
human-readable django-indieweb IndieAuth documentation.

django-indieweb does not assume it owns the host project's root URLconf. Host
projects that want OAuth-compatible discovery at
``/.well-known/oauth-authorization-server`` can route that root path to the
same view; see :doc:`configuration`. You should also advertise the metadata
URL from your profile page with ``rel="indieauth-metadata"``. The older
``rel="authorization_endpoint"`` and ``rel="token_endpoint"`` links remain
useful for legacy clients.

The metadata advertises ``introspection_endpoint`` because django-indieweb
ships the bundled token introspection endpoint described below. It still does
not advertise protocol token revocation, refresh tokens, or
user-info/profile claims because those capabilities are not implemented.

When built-in CORS is configured with ``INDIEWEB_CORS_ALLOWED_ORIGINS``, the
metadata endpoint participates as a public read-only ``GET`` endpoint. It is
not rate limited by django-indieweb's optional protocol rate limiter.

Production Client and Identity Hardening
----------------------------------------

By default, django-indieweb remains compatible with legacy IndieAuth clients:
structurally valid ``client_id`` URLs are accepted, PKCE is optional, and the
submitted ``me`` value is shown on the consent screen. Production deployments
can tighten those defaults with settings:

* ``INDIEWEB_ALLOWED_CLIENT_IDS`` restricts clients to an exact normalized
  allowlist.
* ``INDIEWEB_CLIENT_ID_VALIDATOR`` can enforce custom client policy. The
  callable receives normalized ``client_id`` values: lowercased scheme/host
  and IDNA host form, with path/query/port semantics preserved.
* ``INDIEWEB_REQUIRE_PKCE`` requires a valid ``code_challenge`` before an
  authorization code can be issued.
* ``INDIEWEB_REQUIRE_PKCE_S256`` requires PKCE and rejects ``plain``
  challenges.
* ``INDIEWEB_BIND_ME_TO_USER`` requires the requested ``me`` to match
  ``user.indieweb_profile.url``. If enabled and no profile URL is configured,
  authorization requests fail closed.

The original submitted ``client_id`` is still stored and returned. Normalized
values are used only for operator policy decisions.

Redirect URI Binding
--------------------

The IndieAuth authorization endpoint binds the submitted ``redirect_uri`` to
the submitted ``client_id`` so a trusted client identifier cannot be paired
with an attacker-controlled redirect target. The binding is enforced on both
``AuthView.get`` and ``AuthView._handle_consent`` (consent POST), and the
resolved redirect URI is shown on the bundled consent screen for user
verification.

The check has three layers, evaluated in this order:

1. **Default same-origin rule.** When neither the allowlist nor the validator
   hook applies, the ``redirect_uri`` *origin* (scheme, host, port after IDNA
   encoding and default-port collapsing) must equal the ``client_id`` origin.
   Host-only equality is not enough: ``http`` and ``https`` differ, and a
   non-default port must match exactly.
2. **Per-client allowlist** (``INDIEWEB_REDIRECT_URI_ALLOWLIST``). When the
   ``client_id`` appears as a key in the configured mapping, only that
   client's allowlist entries are considered and the default same-origin rule
   no longer applies for that client. Entries with a trailing ``/`` are
   *prefix* entries: any candidate whose origin matches and whose path starts
   with the entry's path passes; the trailing slash is the path boundary.
   Entries without a trailing slash are *exact* entries: origin, path, and
   query string must all match. Fragments on either side are rejected.
3. **Policy hook** (``INDIEWEB_REDIRECT_URI_VALIDATOR``). When set, the
   configured callable ``(client_id: str, redirect_uri: str) -> bool``
   short-circuits both the default rule and the allowlist. Import errors,
   non-callable targets, exceptions raised by the callable, and non-bool
   return values fail closed (the request is rejected).

Misconfigured allowlists (``client_id`` keyed but with non-list/tuple values
or non-string entries) fail closed for that client.

.. warning::
   This binding is enforced by default and is a backwards-incompatible change
   for deployments that previously relied on cross-origin
   ``client_id``/``redirect_uri`` pairs without configuring a custom validator.
   Such deployments must add the relevant entries to
   ``INDIEWEB_REDIRECT_URI_ALLOWLIST`` or set
   ``INDIEWEB_REDIRECT_URI_VALIDATOR`` before upgrading; otherwise the
   authorization endpoint returns ``400 invalid redirect_uri for client_id``.

Token Introspection
-------------------

The bundled token introspection endpoint is available at
``/indieweb/token/introspect/``. It accepts ``POST`` requests and returns
JSON. Every request must authenticate the caller with a strictly parsed
``Authorization: Bearer <caller-token>`` header. The bearer scheme is
case-insensitive, but the header must contain exactly the scheme and one token
value. The caller token must be active, unexpired, owned by an active Django
user, and still allowed by ``INDIEWEB_ALLOWED_CLIENT_IDS`` and
``INDIEWEB_CLIENT_ID_VALIDATOR`` policy; missing, malformed, unknown, expired,
inactive-owner, or disallowed caller credentials return
``401 authentication error`` with ``Cache-Control: no-store`` and
``WWW-Authenticate: Bearer``.

The form-encoded ``token`` field is the target token being checked. If the
field is omitted, django-indieweb introspects the caller token itself. By
default, a caller may introspect another active token only when both tokens
are owned by the same Django user **and** issued to the same ``client_id``
after scheme/host case and IDNA normalization (RFC 7662 §2.1, narrow
reading). Cross-owner and cross-client lookups return the stable inactive
response rather than active metadata or a distinguishing error.

Hosts that need a broader policy — for example, a single first-party
resource-server credential that introspects tokens for any ``client_id`` —
can configure ``INDIEWEB_TOKEN_INTROSPECTION_AUTHORIZER`` (see
:doc:`configuration`) with a callable
``(caller_token, target_token) -> bool``. The hook runs after the existing
caller authentication and target-token validity checks and fails closed on
import errors, exceptions, non-callable values, and non-bool return values.

Active responses include only the token metadata needed by resource servers:

.. code-block:: json

   {
       "active": true,
       "me": "https://example.com/",
       "client_id": "https://app.example/",
       "scope": "create update",
       "iat": 1762348800,
       "exp": 1762435200
   }

``iat`` and ``exp`` are Unix timestamps for the token row creation time and
expiration time. Tokens created before expiration tracking existed may omit
``exp`` if their ``expires_at`` value is ``NULL``.

Inactive responses are intentionally stable and non-specific:

.. code-block:: json

   {"active": false}

Unknown tokens, deleted/revoked token rows, expired tokens, tokens whose
Django owner is inactive, tokens whose ``client_id`` no longer satisfies
``INDIEWEB_ALLOWED_CLIENT_IDS`` and ``INDIEWEB_CLIENT_ID_VALIDATOR`` policy,
cross-owner target tokens, and cross-client target tokens (under the default
or a configured ``INDIEWEB_TOKEN_INTROSPECTION_AUTHORIZER``) all return the
same inactive shape to authenticated callers. Introspection does not create tokens, refresh
expiration, delete rows, or otherwise mutate token state. It does not return
full bearer token keys.

The endpoint is a token-verification surface only. It does not implement a
separate OAuth token revocation endpoint, refresh tokens, or user-info/profile
claims. The browser token-management UI remains the way authenticated site
users delete their own token rows.

Managing Access Tokens
----------------------

Authenticated site users can review and revoke their own issued IndieAuth/
Micropub access tokens at ``/indieweb/tokens/``. The page lists token metadata
such as client ID, identity URL, scope, creation/update timestamps, expiration,
and active/expired status. It does not display full bearer token keys.

Each token row includes a CSRF-protected revoke form. Revoking a token deletes
that ``Token`` row, so the bearer credential immediately stops authenticating
Micropub and other token-protected requests. Users only see and revoke tokens
owned by their own Django account; tokens for other users are not listed and
cannot be revoked through this UI.

When an existing token row is reissued through the IndieAuth token endpoint,
django-indieweb refreshes its expiration and rotates the bearer key returned
to the client. The previous bearer key stops authenticating immediately.
Raw bearer token values are returned only when the token endpoint issues or
reissues a token. At rest, ``Token.key`` stores an HMAC digest derived from the
raw bearer value; the migration that introduces this format hashes legacy
plaintext token rows. Token hashes are keyed with Django's ``SECRET_KEY``, so
changing ``SECRET_KEY`` invalidates existing bearer tokens.

Authentication vs Authorization
-------------------------------

Django-IndieWeb supports two different IndieAuth flows:

**Authentication Only (No Scopes)**
   Used when logging into websites with your domain. No consent screen is required since no permissions are granted::

      GET /indieweb/auth/?response_type=code&me=https://example.com&client_id=https://site.com&redirect_uri=...&state=...

**Authorization with Scopes**
   Used when granting permissions to apps (like Micropub clients). Shows consent screen::

      GET /indieweb/auth/?response_type=code&me=https://example.com&client_id=https://app.com&redirect_uri=...&state=...&scope=create+update

Common scopes include:

* ``create`` - Create new posts
* ``update`` - Edit existing posts
* ``delete`` - Delete posts
* ``media`` - Upload media files

Scope strings are normalized before display and before storage: whitespace is
collapsed, duplicate tokens are removed while preserving first-seen order, and
an empty or whitespace-only value is treated as no scope. Unknown scope names
are intentionally preserved. IndieAuth and Micropub scopes are
extension-defined, and clients may request values such as ``profile``,
``media``, or site-specific scopes. django-indieweb enforces ``media`` for
direct uploads to the Micropub media endpoint; other unknown scopes are stored
but have no built-in resource-server behavior unless your application adds it.
That includes ``draft``: clients may request it and django-indieweb will store
it on auth codes and tokens, but the built-in Micropub resource server does not
advertise it or let it replace ``create``/``post`` for creates or ``update``
for updates. Submitted ``post-status=draft`` values are forwarded to the
configured Micropub handler; the host application decides how to persist,
filter, expose, or restrict draft content.

The same opaque-extension rule applies to reader-side scope names. Clients may
request values such as ``read``, ``follow``, ``mute``, ``block``, or
``channels``, and django-indieweb will preserve them after normalization and
return them from token issuance and introspection. Those scopes do not
authorize any built-in django-indieweb resource-server behavior: the package
does not ship Microsub channels, feed fetching, following, muting, blocking,
reader timelines, or reader UI. Host applications that implement reader-side
protocols need their own endpoints, models, authorization policy, metadata or
discovery behavior where applicable, and documentation.

Wire Compatibility Policy
-------------------------

Current IndieAuth clients send ``response_type=code`` on the authorization
request and ``grant_type=authorization_code`` when redeeming the code.
django-indieweb accepts those values and rejects any other present value with
HTTP 400. For backwards compatibility with older deployments and clients, both
parameters remain optional: authorization requests that omit ``response_type``
and token requests that omit ``grant_type`` continue to work.

Successful authorization redirects include ``code``, ``state``, ``iss``, and
the legacy ``me`` parameter. The ``iss`` value is derived from the same issuer
policy as the bundled metadata endpoint. With the standard ``/indieweb/``
mount it is ``https://example.com/indieweb/``. Host projects that route
metadata at ``/.well-known/oauth-authorization-server`` should publish one
canonical metadata URL and ensure clients compare redirects against that
issuer. Denial redirects include ``error=access_denied`` and ``state`` only;
the IndieAuth spec warns clients not to assume error responses originated from
the intended authorization server.

The authorization endpoint's profile-code verification POST and the token
endpoint return JSON success bodies when the client explicitly prefers
``Accept: application/json``. Default requests and wildcard-only
``Accept: */*`` requests keep the legacy
``application/x-www-form-urlencoded`` success body. Access-token responses now
include ``token_type=Bearer`` in both formats, alongside ``access_token``,
``expires_in``, ``scope``, and ``me``.

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
* ``scope`` - Normalized space-separated list of requested scopes, or ``None``
  when no scope was requested
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
3. **Token Expiration and Revocation**: Access tokens expire after 24 hours by
   default; the Micropub endpoint rejects expired tokens with HTTP 401. Users
   can also revoke their own tokens at ``/indieweb/tokens/``; revocation
   deletes the token row and immediately invalidates the bearer credential.
4. **CSRF Protection**: Browser consent ``approve`` and ``deny`` POSTs require
   Django's CSRF token. The legacy authorization-code verification POST remains
   CSRF-exempt because it is a protocol request rather than a browser consent
   submission.
5. **User Authentication**: Users must be logged in to approve/deny requests;
   unauthenticated submissions are rejected before django-indieweb builds any
   redirect to the submitted ``redirect_uri``.
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
   allowed by setting ``INDIEWEB_ALLOWED_CLIENT_IDS`` or
   ``INDIEWEB_CLIENT_ID_VALIDATOR`` (see :doc:`configuration`); policy runs at
   every authorization/token path and on every Micropub request, so revoking a
   client takes effect immediately for previously-issued tokens. A
   misconfigured validator (the dotted path fails to import or the callable
   raises) fails closed at every call site. Stored ``client_id`` values are
   not re-validated *structurally* on use, matching the ``redirect_uri``
   rule; configured client policy, however, IS re-applied on use, so
   pre-existing tokens whose ``client_id`` no longer satisfies operator
   policy are rejected with HTTP 403 ``invalid_client`` on the Micropub
   endpoint.
8. **redirect_uri Validation**: Submitted ``redirect_uri`` values must be
   syntactically valid URLs using the ``http`` or ``https`` scheme. They must
   not contain a fragment delimiter (``#``) at all, even with no fragment
   content, and must not include userinfo (``user:pass@``). The authorization
   endpoint rejects malformed values with HTTP 400 *before* creating an
   authorization code; the token endpoint rejects malformed submissions with
   ``invalid_grant``. If the authorization code was issued with a
   ``redirect_uri``, token exchange requires a submitted ``redirect_uri`` and
   compares it with the stored value after normalizing scheme/host case, IDNA
   host form, default ports, percent-encoded triplet case, and empty root path
   versus ``/``. Non-default ports, non-root paths, and query strings remain
   significant. Omitted required values and mismatches return
   ``invalid_grant`` and consume the matched auth code. ``redirect_uri`` values
   that already contain a query (e.g. ``?next=/x``) are preserved when
   ``code`` and ``state`` are appended.
9. **Scope Issuance Semantics**: The authorization endpoint normalizes scope
   strings before showing them on the consent screen and before storing them on
   the ``Auth`` row. Normalization splits on whitespace, de-duplicates while
   preserving first-seen order, and joins with single spaces; whitespace-only
   values become no scope. Unknown scopes are accepted and preserved after
   normalization because IndieAuth/Micropub scopes are extension-defined. The
   token endpoint issues the exact normalized scope stored with the auth code.
   If a token exchange includes a ``scope`` parameter, that submitted value is
   normalized and must match the stored auth-code scope exactly. A mismatch
   returns HTTP 400 ``invalid_grant`` with content type
   ``application/x-www-form-urlencoded`` and does not create or reissue a
   token. Omitting ``scope`` on token exchange continues to issue the stored
   auth-code scope. An explicitly empty ``scope=`` parameter normalizes to no
   scope, so it only succeeds when the auth code was issued with no scope.

10. **Per-Operation Scope Enforcement**: The Micropub resource server enforces
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
    use case for ``q=source`` is "fetch a post to edit it"); and
    ``POST /indieweb/media/`` requires ``media``. Configuration queries such
    as ``GET ?q=config``, ``GET ?q=category``, ``GET ?q=channel``,
    ``GET ?q=media-endpoint``, ``GET ?q=post-types``, ``GET ?q=syndicate-to``,
    and ``GET`` with no ``q`` only require an authenticated token. Stored
    ``scope`` is split on whitespace and compared as an exact token, so
    ``createXYZ`` does not satisfy ``create`` and ``mediaXYZ`` does not
    satisfy ``media``. ``draft`` is treated as an opaque extension scope by
    this built-in resource server: a token with only ``draft`` cannot create
    or update, while ``create draft`` can create because ``create`` is present.
    Reader scopes such as ``read``, ``follow``, ``mute``, ``block``, and
    ``channels`` are treated the same way: they may be stored on tokens, but
    they are not built-in Micropub permissions and are not advertised by the
    bundled metadata endpoint.
    Scope failures return HTTP 403 with the plain-text body
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

      <link rel="indieauth-metadata" href="https://mysite.com/indieweb/auth/metadata/">
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
