Configuration
=============

This document describes how to configure django-indieweb in your Django project.

Django Settings
---------------

INDIWEB_AUTH_CODE_TIMEOUT
~~~~~~~~~~~~~~~~~~~~~~~~~

Controls how long authorization codes remain valid before they must be exchanged for tokens.

**Default:** ``60`` (seconds)

**Example:**

.. code-block:: python

   # settings.py
   INDIWEB_AUTH_CODE_TIMEOUT = 120  # 2 minutes

.. note::
   Authorization codes are single-use. Once exchanged for a token, they cannot be reused.

INDIEWEB_TOKEN_EXPIRES_IN
~~~~~~~~~~~~~~~~~~~~~~~~~

Controls how long newly issued or reissued access tokens remain valid.

**Default:** ``86400`` (seconds — 24 hours)

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_TOKEN_EXPIRES_IN = 3600  # 1 hour

The token endpoint reports the remaining lifetime in the ``expires_in`` field of
its response, and the Micropub endpoint rejects expired tokens with HTTP 401.
Authenticated users can revoke their own tokens manually at
``/indieweb/tokens/``; revocation deletes the ``Token`` row and immediately
invalidates the bearer credential.

.. note::
   Tokens created before this field existed have ``expires_at`` set to ``NULL``
   and continue to be accepted indefinitely until they are reissued. Operators
   that want to retire those tokens should delete them or trigger a reissue
   through the IndieAuth flow.

INDIEWEB_CLIENT_ID_VALIDATOR
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional dotted path to a callable ``(client_id: str) -> bool`` that gates which
``client_id`` values are allowed by the IndieAuth and Micropub endpoints.

**Default:** ``None`` (every structurally-valid ``client_id`` is permitted)

When set, the configured callable is invoked **on top of** structural validation
(an ``http``/``https`` URL with no userinfo and no fragment) at four
authorization/token paths — the authorization GET, the consent approval POST,
the code-verification POST, and the token endpoint POST — and again on the
resource-server path inside ``TokenAuthMixin``. The latter is intentional:
operator policy may evolve and revoke a previously-allowed ``client_id``, in
which case existing tokens for that client must stop working immediately.

**Example:**

.. code-block:: python

   # myapp/indieauth.py
   _ALLOWLIST = {"https://quill.p3k.io/", "https://micropublish.net/"}

   def is_allowed_client(client_id: str) -> bool:
       return client_id in _ALLOWLIST

.. code-block:: python

   # settings.py
   INDIEWEB_CLIENT_ID_VALIDATOR = "myapp.indieauth.is_allowed_client"

.. note::
   If the configured dotted path fails to import, or the callable raises, the
   request is rejected (fail-closed). Misconfiguration cannot silently weaken
   access control. The exact response shape depends on the call site: the
   authorization endpoint and the code-verification POST return HTTP 400 with
   a plain-text ``invalid_client`` body; the token endpoint returns HTTP 400
   with body ``invalid_request`` and content type
   ``application/x-www-form-urlencoded`` (matching the existing missing-
   ``code`` case); and the Micropub resource-server path returns HTTP 403
   with body ``invalid_client``.

.. note::
   Stored ``client_id`` values are not re-validated *structurally* on use,
   matching the ``redirect_uri`` rule. The configured validator callable
   IS re-applied on use, so revoking a previously-allowed client takes
   effect immediately for existing tokens. A token issued before
   ``client_id`` access control existed (or by an out-of-band script) keeps
   working as long as it satisfies the configured validator (or the
   validator is unset).

URL Configuration
-----------------

Basic URL Setup
~~~~~~~~~~~~~~~

The standard way to include django-indieweb URLs:

.. code-block:: python

   # urls.py
   from django.urls import path, include

   urlpatterns = [
       path('indieweb/', include('indieweb.urls', namespace='indieweb')),
   ]

This creates the following endpoints:

- ``/indieweb/auth/`` - Authorization endpoint
- ``/indieweb/token/`` - Token endpoint
- ``/indieweb/tokens/`` - Browser UI for viewing and revoking the logged-in user's tokens
- ``/indieweb/tokens/<pk>/revoke/`` - CSRF-protected POST action for revoking one owned token
- ``/indieweb/micropub/`` - Micropub endpoint
- ``/indieweb/webmention/`` - Webmention receive endpoint
- ``/indieweb/webmention/<pk>/`` - Webmention status endpoint

Custom URL Paths
~~~~~~~~~~~~~~~~

You can customize the URL paths:

.. code-block:: python

   # urls.py
   from indieweb import views

   urlpatterns = [
       path('auth/', views.AuthView.as_view(), name='indieauth'),
       path('token/', views.TokenView.as_view(), name='token'),
       path('tokens/', views.TokenManagementView.as_view(), name='tokens'),
       path('tokens/<int:pk>/revoke/', views.TokenRevokeView.as_view(), name='token-revoke'),
       path('api/micropub/', views.MicropubView.as_view(), name='micropub'),
       path('webmention/', views.WebmentionEndpoint.as_view(), name='webmention'),
       path('webmention/<int:pk>/', views.WebmentionStatusView.as_view(), name='webmention-status'),
   ]

Middleware Configuration
------------------------

CSRF Exemption
~~~~~~~~~~~~~~

The IndieWeb views are automatically exempt from CSRF protection. This is necessary
for the token and micropub endpoints to accept POST requests from external clients.

If you need CSRF protection, you'll need to implement your own views:

.. code-block:: python

   from django.views.decorators.csrf import csrf_protect
   from indieweb.views import TokenView as BaseTokenView

   @method_decorator(csrf_protect, name='dispatch')
   class TokenView(BaseTokenView):
       pass

Authentication Backend
~~~~~~~~~~~~~~~~~~~~~~

django-indieweb uses Django's standard authentication system. Ensure you have
authentication middleware enabled:

.. code-block:: python

   MIDDLEWARE = [
       ...
       'django.contrib.sessions.middleware.SessionMiddleware',
       'django.contrib.auth.middleware.AuthenticationMiddleware',
       ...
   ]

Database Configuration
----------------------

Models
~~~~~~

django-indieweb creates four models:

1. **Auth** - Stores authorization codes temporarily
2. **Token** - Stores access tokens
3. **Webmention** - Stores incoming webmention source/target pairs, parsed
   content, status, and spam-check results
4. **Profile** - Stores user h-card data

``Auth``, ``Token``, and ``Profile`` use ``settings.AUTH_USER_MODEL`` for
their user relationships.

Migrations
~~~~~~~~~~

After installation, run migrations:

.. code-block:: bash

   python manage.py migrate indieweb

Custom User Model
~~~~~~~~~~~~~~~~~

If using a custom user model, ensure it's configured before running migrations:

.. code-block:: python

   # settings.py
   AUTH_USER_MODEL = 'myapp.User'

Security Configuration
----------------------

HTTPS Requirement
~~~~~~~~~~~~~~~~~

For production, always use HTTPS:

.. code-block:: python

   # settings.py
   SECURE_SSL_REDIRECT = True
   SESSION_COOKIE_SECURE = True
   CSRF_COOKIE_SECURE = True

Login URL
~~~~~~~~~

Configure where users are redirected for authentication:

.. code-block:: python

   # settings.py
   LOGIN_URL = '/accounts/login/'
   LOGIN_REDIRECT_URL = '/'

Allowed Hosts
~~~~~~~~~~~~~

Ensure your domain is in ``ALLOWED_HOSTS``:

.. code-block:: python

   # settings.py
   ALLOWED_HOSTS = ['yourdomain.com', 'www.yourdomain.com']

Extending Functionality
-----------------------

Token Metadata
~~~~~~~~~~~~~~

The built-in ``Token`` model already includes ``created``, ``modified``,
``client_id``, ``me``, ``scope``, and ``expires_at`` fields. To track
application-specific token metadata without shadowing built-in fields, store it
in a separate model related to ``Token``:

.. code-block:: python

   # myapp/models.py
   from django.db import models
   from indieweb.models import Token

   class TokenMetadata(models.Model):
       token = models.OneToOneField(Token, on_delete=models.CASCADE, related_name='metadata')
       last_used = models.DateTimeField(null=True)

Custom Views
~~~~~~~~~~~~

Extend views to add functionality:

.. code-block:: python

   # myapp/views.py
   from indieweb.views import TokenView as BaseTokenView
   from django.core.cache import cache

   class TokenView(BaseTokenView):
       def post(self, request, *args, **kwargs):
           # Add rate limiting
           ip = request.META.get('REMOTE_ADDR')
           cache_key = f'token_attempt_{ip}'
           attempts = cache.get(cache_key, 0)

           if attempts > 5:
               return HttpResponse('Too many attempts', status=429)

           cache.set(cache_key, attempts + 1, 300)  # 5 minutes

           return super().post(request, *args, **kwargs)

Logging Configuration
---------------------

Enable logging to debug issues:

.. code-block:: python

   # settings.py
   LOGGING = {
       'version': 1,
       'disable_existing_loggers': False,
       'handlers': {
           'file': {
               'level': 'DEBUG',
               'class': 'logging.FileHandler',
               'filename': 'indieweb.log',
           },
       },
       'loggers': {
           'indieweb': {
               'handlers': ['file'],
               'level': 'DEBUG',
               'propagate': True,
           },
       },
   }

CORS Configuration
------------------

For cross-origin requests, install and configure django-cors-headers:

.. code-block:: bash

   pip install django-cors-headers

.. code-block:: python

   # settings.py
   INSTALLED_APPS = [
       ...
       'corsheaders',
   ]

   MIDDLEWARE = [
       ...
       'corsheaders.middleware.CorsMiddleware',
       'django.middleware.common.CommonMiddleware',
       ...
   ]

   # Allow specific origins
   CORS_ALLOWED_ORIGINS = [
       "https://app.example.com",
       "https://client.example.com",
   ]

   # Or allow all origins (not recommended for production)
   CORS_ALLOW_ALL_ORIGINS = True

Testing Configuration
---------------------

For testing, you might want to disable certain security features:

.. code-block:: python

   # test_settings.py
   from .settings import *

   # Disable HTTPS redirect for tests
   SECURE_SSL_REDIRECT = False

   # Use a faster password hasher
   PASSWORD_HASHERS = [
       'django.contrib.auth.hashers.MD5PasswordHasher',
   ]

   # Shorter auth code timeout for faster tests
   INDIWEB_AUTH_CODE_TIMEOUT = 5

Performance Optimization
------------------------

Database Indexes
~~~~~~~~~~~~~~~~

The Token model already has an index on the ``key`` field. For better performance
with many tokens, consider adding indexes on commonly queried fields:

.. code-block:: python

   # In a migration
   migrations.AddIndex(
       model_name='token',
       index=models.Index(fields=['owner', 'client_id']),
   )

Caching
~~~~~~~

Cache token lookups for better performance:

.. code-block:: python

   # myapp/views.py
   from django.core.cache import cache
   from indieweb.models import Token

   def get_token(key):
       cache_key = f'token_{key}'
       token = cache.get(cache_key)

       if token is None:
           try:
               token = Token.objects.select_related('owner').get(key=key)
               cache.set(cache_key, token, 300)  # Cache for 5 minutes
           except Token.DoesNotExist:
               return None

       return token
