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
- ``/indieweb/micropub/`` - Micropub endpoint

Custom URL Paths
~~~~~~~~~~~~~~~~

You can customize the URL paths:

.. code-block:: python

   # urls.py
   from indieweb.views import AuthView, TokenView, MicropubView

   urlpatterns = [
       path('auth/', AuthView.as_view(), name='indieauth'),
       path('token/', TokenView.as_view(), name='token'),
       path('api/micropub/', MicropubView.as_view(), name='micropub'),
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

django-indieweb creates two models:

1. **Auth** - Stores authorization codes temporarily
2. **Token** - Stores access tokens

Both models use ``settings.AUTH_USER_MODEL`` for the user relationship.

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

Custom Token Model
~~~~~~~~~~~~~~~~~~

To add fields to the Token model:

.. code-block:: python

   # myapp/models.py
   from indieweb.models import Token

   class ExtendedToken(Token):
       expires_at = models.DateTimeField(null=True)
       last_used = models.DateTimeField(null=True)

       class Meta:
           db_table = 'indieweb_token'  # Use same table

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
