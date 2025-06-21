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

Security Considerations
-----------------------

1. **HTTPS Required**: Always use HTTPS in production for all IndieAuth endpoints
2. **Auth Code Timeout**: Auth codes expire after 60 seconds by default
3. **CSRF Protection**: The consent form includes Django's CSRF token
4. **User Authentication**: Users must be logged in to approve/deny requests

Configuration
-------------

Configure IndieAuth behavior in your Django settings::

    # Auth code expiration time in seconds (default: 60)
    INDIEAUTH_CODE_TIMEOUT = 60

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
