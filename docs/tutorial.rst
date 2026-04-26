Tutorial
========

This tutorial will guide you through integrating django-indieweb into your Django project
to add IndieAuth authentication, Micropub content creation, and Webmention support.

.. note::
   Micropub ships with an in-memory handler for quick testing; configure ``INDIEWEB_MICROPUB_HANDLER``
   to store content in your own models.

Prerequisites
-------------

- Django project up and running
- Python 3.10 or higher
- Basic understanding of OAuth-like flows

Installation
------------

1. Install the package:

   .. code-block:: bash

      pip install django-indieweb

2. Add ``indieweb`` to your ``INSTALLED_APPS``:

   .. code-block:: python

      INSTALLED_APPS = [
          ...
          'indieweb',
      ]

3. Include the URLs in your project's ``urls.py``:

   .. code-block:: python

      from django.urls import path, include

      urlpatterns = [
          ...
          path('indieweb/', include('indieweb.urls', namespace='indieweb')),
      ]

4. Run migrations:

   .. code-block:: bash

      python manage.py migrate

Basic Setup
-----------

After installation, you'll have these endpoints available:

- ``/indieweb/auth/`` - IndieAuth authorization (consent)
- ``/indieweb/token/`` - Token exchange
- ``/indieweb/micropub/`` - Micropub content creation (uses configured handler)
- ``/indieweb/webmention/`` - Webmention receive endpoint (Link rel="webmention" is advertised)
- ``/indieweb/webmention/<pk>/`` - Webmention status lookup

Implementing IndieAuth Login
----------------------------

Here's how to implement IndieAuth login in your application:

Client-Side Implementation
~~~~~~~~~~~~~~~~~~~~~~~~~~

1. **Create a login form:**

   .. code-block:: html

      <form id="indieauth-form">
          <input type="url" name="me" placeholder="https://yoursite.com" required>
          <button type="submit">Sign in with IndieAuth</button>
      </form>

2. **Handle the login flow:**

   .. code-block:: javascript

      document.getElementById('indieauth-form').addEventListener('submit', (e) => {
          e.preventDefault();

          const me = e.target.me.value;
          const client_id = window.location.origin;
          const redirect_uri = window.location.origin + '/auth/callback';
          const state = Math.random().toString(36).substring(2, 15);
          const scope = 'create';

          // Store state for verification
          sessionStorage.setItem('indieauth_state', state);

          // Redirect to authorization endpoint
          const authUrl = new URL('/indieweb/auth/', window.location.origin);
          authUrl.searchParams.append('me', me);
          authUrl.searchParams.append('client_id', client_id);
          authUrl.searchParams.append('redirect_uri', redirect_uri);
          authUrl.searchParams.append('state', state);
          authUrl.searchParams.append('scope', scope);

          window.location.href = authUrl.toString();
      });

3. **Handle the callback:**

   .. code-block:: javascript

      // On your callback page
      const urlParams = new URLSearchParams(window.location.search);
      const code = urlParams.get('code');
      const state = urlParams.get('state');
      const me = urlParams.get('me');

      // Verify state
      if (state !== sessionStorage.getItem('indieauth_state')) {
          alert('Invalid state parameter');
          return;
      }

      // Exchange code for token
      fetch('/indieweb/token/', {
          method: 'POST',
          headers: {
              'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: new URLSearchParams({
              code: code,
              client_id: window.location.origin,
              redirect_uri: window.location.origin + '/auth/callback',
              me: me,
              scope: 'create'
          })
      })
      .then(response => response.text())
      .then(data => {
          const params = new URLSearchParams(data);
          const access_token = params.get('access_token');

          // Store the token securely
          localStorage.setItem('micropub_token', access_token);
          localStorage.setItem('micropub_me', params.get('me'));
      });

Using the Micropub Endpoint
---------------------------

Once you have an access token, you can make requests to the Micropub endpoint:

Verifying Token
~~~~~~~~~~~~~~~

.. code-block:: javascript

   fetch('/indieweb/micropub/', {
       method: 'GET',
       headers: {
           'Authorization': 'Bearer ' + localStorage.getItem('micropub_token')
       }
   })
   .then(response => response.text())
   .then(data => {
       console.log('Token valid for:', new URLSearchParams(data).get('me'));
   });

Creating a Post
~~~~~~~~~~~~~~~

.. code-block:: javascript

   fetch('/indieweb/micropub/', {
       method: 'POST',
       headers: {
           'Authorization': 'Bearer ' + localStorage.getItem('micropub_token'),
           'Content-Type': 'application/x-www-form-urlencoded'
       },
       body: new URLSearchParams({
           h: 'entry',
           content: 'Hello from Micropub!',
           category: 'test,micropub'
       })
   })
   .then(response => {
       if (response.status === 201) {
           console.log('Post created! Location:', response.headers.get('Location'));
       }
   });

Extending the Micropub Endpoint
-------------------------------

To persist content, configure your own handler:

.. code-block:: python

   # settings.py
   INDIEWEB_MICROPUB_HANDLER = "myapp.micropub_handler.BlogPostMicropubHandler"

See :doc:`micropub` for a full handler example (create, retrieve, update, delete stubs). The default
in-memory handler implements source queries, update, delete, and undelete in process memory only — entries
do not persist across restarts. Configure your own handler for durable storage.

.. code-block:: python

   # myapp/micropub_handler.py
   from indieweb.handlers import MicropubContentHandler, MicropubEntry
   from myapp.models import BlogPost

   class BlogPostMicropubHandler(MicropubContentHandler):
       def create_entry(self, properties, user):
           post = BlogPost.objects.create(
               author=user,
               content=properties.get("content", [""])[0],
           )
           return MicropubEntry(url=post.get_absolute_url(), properties=properties)

       def update_entry(self, url, updates, user):
           raise NotImplementedError("Update not yet implemented")

       def delete_entry(self, url, user):
           raise NotImplementedError("Delete not yet implemented")

       def undelete_entry(self, url, user):
           raise NotImplementedError("Undelete not supported")

       def get_entry(self, url, user):
           return None

Then include the bundled URLconf:

.. code-block:: python

   # urls.py
   from django.urls import include, path

   urlpatterns = [
       path("indieweb/", include("indieweb.urls")),
       # ... other patterns
   ]

Server-Side Token Validation
----------------------------

For server-side applications, you might want to validate tokens:

.. code-block:: python

   from indieweb.models import Token

   def validate_token(request):
       auth_header = request.META.get('HTTP_AUTHORIZATION', '')
       if auth_header.startswith('Bearer '):
           key = auth_header.split()[1]
           try:
               token = Token.objects.get(key=key)
               if not token.owner.is_active:
                   return None
               if token.is_expired():
                   return None
               return token
           except Token.DoesNotExist:
               pass
       return None

Security Considerations
-----------------------

1. **Always verify the state parameter** to prevent CSRF attacks
2. **Use HTTPS in production** for all endpoints
3. **Store tokens securely** - consider using session storage instead of localStorage
4. **Tune token lifetime** via the ``INDIEWEB_TOKEN_EXPIRES_IN`` setting (default 86400 seconds); see :doc:`configuration`
5. **Validate redirect_uri** matches registered client applications

Debugging Tips
--------------

1. Check Django logs for authentication failures
2. Verify all required parameters are present
3. Ensure user is logged in before authorization
4. Check that authorization codes are used within 60 seconds
5. Verify scope requirements match token permissions

Common Issues
-------------

**"Missing parameter" error**
   Ensure all required parameters are included in the request

**401 Unauthorized on token endpoint**
   - Authorization code may have expired (60 second timeout)
   - Code may have already been used
   - Parameters don't match original auth request

**403 Forbidden on micropub endpoint**
   Token doesn't have the scope required for the requested operation. Create
   requires ``create`` or the legacy alias ``post``; source and update require
   ``update``; delete requires ``delete``; undelete requires ``undelete``.

**Redirect loops**
   Check that login redirect URLs are properly configured in Django settings


Adding User Profiles with H-Cards
---------------------------------

H-cards allow you to add rich profile information for your users:

1. Create a profile for a user:

   .. code-block:: python

      from django.contrib.auth import get_user_model
      from indieweb.models import Profile

      User = get_user_model()
      user = User.objects.get(username="alice")

      Profile.objects.create(
          user=user,
          name="Alice Johnson",
          photo_url="https://example.com/alice.jpg",
          url="https://example.com/alice",
          h_card={
              "name": ["Alice Johnson"],
              "photo": ["https://example.com/alice.jpg"],
              "url": ["https://example.com/alice"],
              "email": ["alice@example.com"],
              "note": ["Web developer and blogger"]
          }
      )

2. Display the h-card on your homepage:

   .. code-block:: django

      {# templates/home.html #}
      {% load indieweb_tags %}

      <\!DOCTYPE html>
      <html>
      <head>
          <title>{{ user.username }} - Homepage</title>
          {% webmention_endpoint_link %}
      </head>
      <body>
          <header>
              {% h_card user %}
          </header>

          <main>
              <\!-- Your content here -->
          </main>
      </body>
      </html>

3. The h-card will render with proper microformats2 markup, making your profile
   machine-readable for other IndieWeb tools and services.

See :doc:`h-card` for more details on h-card properties and customization.
