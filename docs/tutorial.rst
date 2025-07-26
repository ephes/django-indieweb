Tutorial
========

This tutorial will guide you through integrating django-indieweb into your Django project
to add IndieAuth authentication and Micropub support.

.. note::
   The Micropub endpoint is currently a stub implementation that accepts requests
   but doesn't create actual content. You'll need to extend it for your use case.

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

After installation, you'll have three endpoints available:

- ``/indieweb/auth/`` - For IndieAuth authorization
- ``/indieweb/token/`` - For token exchange
- ``/indieweb/micropub/`` - For content creation (needs implementation)

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

.. warning::
   This endpoint currently returns success but doesn't create actual content.
   You'll need to extend the ``MicropubView`` to implement content creation.

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
           console.log('Post created!');
       }
   });

Extending the Micropub Endpoint
-------------------------------

To make the Micropub endpoint functional, you'll need to extend it:

.. code-block:: python

   # myapp/views.py
   from indieweb.views import MicropubView as BaseMicropubView
   from myapp.models import BlogPost

   class MicropubView(BaseMicropubView):
       def post(self, request, *args, **kwargs):
           # Call parent to handle authentication
           self.request = request

           # Create actual content
           post = BlogPost.objects.create(
               author=self.token.owner,
               content=self.content or '',
               categories=','.join(self.categories)
           )

           # Return created status with location header
           response = HttpResponse('created', status=201)
           response['Location'] = post.get_absolute_url()
           return response

Then update your URLs to use your extended view:

.. code-block:: python

   # urls.py
   from myapp.views import MicropubView

   urlpatterns = [
       path('micropub/', MicropubView.as_view(), name='micropub'),
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
               if token.owner.is_active:
                   return token
           except Token.DoesNotExist:
               pass
       return None

Security Considerations
-----------------------

1. **Always verify the state parameter** to prevent CSRF attacks
2. **Use HTTPS in production** for all endpoints
3. **Store tokens securely** - consider using session storage instead of localStorage
4. **Implement token expiration** if needed (not built-in)
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
   Token doesn't have required scope (needs "post" or "create")

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
