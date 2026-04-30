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

INDIEWEB_MEDIA_MAX_UPLOAD_BYTES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Maximum file size accepted by the Micropub media endpoint at
``/indieweb/media/`` and by ``photo`` file parts on multipart create requests
sent to ``/indieweb/micropub/``.

**Default:** ``10485760`` (10 MiB)

Requests whose uploaded ``file`` or ``photo`` part is larger than this value
are rejected with HTTP 413 and body ``invalid_request`` before storage is
called.
django-indieweb enforces this limit after Django has finished parsing the
multipart body, which means oversized uploads can still consume temporary disk
and bandwidth before the view rejects them. For denial-of-service protection,
also configure a complementary limit at the web server, reverse proxy, CDN, or
Django deployment layer, for example nginx ``client_max_body_size``.

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_MEDIA_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MiB

Set this to ``None`` to disable django-indieweb's media upload size check. If
you do that, enforce an upload limit outside these views so authenticated
clients cannot fill local or remote storage.

INDIEWEB_MEDIA_ALLOWED_TYPES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Iterable of MIME content types accepted by the Micropub media endpoint and by
``photo`` file parts on multipart create requests.

**Default:** common image, audio, and video types:

.. code-block:: python

   (
       "image/jpeg",
       "image/png",
       "image/gif",
       "image/webp",
       "image/heic",
       "image/heif",
       "audio/mpeg",
       "audio/mp4",
       "audio/ogg",
       "audio/wav",
       "audio/webm",
       "video/mp4",
       "video/quicktime",
       "video/ogg",
       "video/webm",
   )

Uploads whose ``file`` or ``photo`` part reports a content type outside the
allowlist are rejected with HTTP 415 and body ``invalid_request`` before
storage is called.
The value is based on the upload's submitted content type; if your deployment
needs stronger guarantees, inspect files after upload or use storage/server
policies that prevent active content from executing on your primary domain.

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_MEDIA_ALLOWED_TYPES = ("image/jpeg", "image/png", "image/webp")

Set this to ``None`` to disable django-indieweb's content-type check. If you
allow broad uploads, serve media from a separate origin or with defensive
headers such as ``Content-Disposition: attachment`` for risky types.

INDIEWEB_WEBMENTION_ENQUEUE
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional dotted path to a callable ``(webmention_id: int) -> None`` that queues
receive-side Webmention processing for a persisted ``Webmention`` row.

**Default:** ``None`` (incoming Webmentions are processed synchronously)

When unset, ``POST /indieweb/webmention/`` keeps the backwards-compatible
synchronous behavior: it validates the submitted ``source`` and ``target``,
processes the Webmention in the request path, and returns ``201 Created`` with
a ``Location`` header for the status endpoint.

When set, the receive endpoint validates the request and target domain, creates
or reuses the ``Webmention`` row for the submitted ``source``/``target`` pair,
calls the configured enqueue hook with that row's primary key, and returns
``202 Accepted`` with a ``Location`` header for
``/indieweb/webmention/<pk>/``. Source fetching, target-link verification,
microformats2 parsing, spam checks, final status transitions, and
``webmention_received`` signal emission happen later when a worker processes
the queued row.

**Example:**

.. code-block:: python

   # settings.py
   INDIEWEB_WEBMENTION_ENQUEUE = "myapp.webmentions.enqueue_webmention"

.. code-block:: python

   # myapp/webmentions.py
   from myapp.tasks import process_webmention_task

   def enqueue_webmention(webmention_id: int) -> None:
       process_webmention_task.delay(webmention_id)

.. code-block:: python

   # myapp/tasks.py
   from indieweb.processors import process_queued_webmention

   def process_webmention_task(webmention_id: int) -> None:
       process_queued_webmention(webmention_id)

The configured enqueue callable should schedule work only. It should not call
``process_queued_webmention()`` inline from the receive request unless your
deployment intentionally wants synchronous behavior under a custom hook.

.. note::
   If the configured path cannot be imported, resolves to a non-callable, or
   raises while enqueueing, the receive endpoint returns HTTP 500 and does not
   fall back to inline processing. Invalid receive requests still return HTTP
   400 before the hook is loaded or called. Import and non-callable failures
   happen before a row is persisted; if the callable itself raises, the
   ``Webmention`` row has already been created or reused and remains
   ``pending`` until a queue retry path or manual cleanup reconciles it.

INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional iterable of domains that django-indieweb may trust as Webmention
Vouch voucher sites when no custom Vouch trust policy is configured.

**Default:** ``None`` (submitted Vouch URLs are stored but not verified)

When this setting is ``None`` or empty, incoming Webmentions may include the optional
``vouch`` form parameter, and django-indieweb validates and stores that URL,
but Vouch does not affect whether the processor marks the Webmention
``verified`` unless ``INDIEWEB_WEBMENTION_VOUCH_REQUIRED`` is enabled.

When set to an iterable of domain names, the processor verifies submitted
Vouch URLs. A voucher URL must be on the configured Django ``Site`` domain or
one of these domains. The voucher is fetched with the same bounded redirect
policy used for Webmention source fetches, the final URL must remain on a
trusted domain, the response must be HTTP ``200`` with ``text/html`` content,
and the voucher page must contain an HTTP(S) HTML ``href`` to the submitted
source URL's domain. If any Vouch check fails, the Webmention is marked
``failed``.

**Example:**

.. code-block:: python

   INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS = ("trusted.example", "events.example")

Domain matching is exact after lowercasing and treating a leading ``www.`` as
equivalent to the bare hostname. Subdomains are not implicitly trusted.

If ``INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY`` is configured, that callable
owns the submitted and final voucher URL trust decisions. In that case,
``INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS`` is ignored by django-indieweb's
built-in trust check, though your policy callable may read the setting itself.

INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optional dotted path to a callable that decides whether django-indieweb should
trust a submitted Webmention Vouch URL.

**Default:** ``None`` (use ``INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS`` as
the default/simple trust policy)

When set, the processor imports the callable and invokes it during Vouch
verification with keyword arguments:

.. code-block:: python

   def trust_vouch(
       *,
       webmention: Webmention,
       source_url: str,
       target_url: str,
       vouch_url: str,
       final_vouch_url: str | None = None,
   ) -> bool:
       ...

The callable is evaluated twice for a submitted voucher:

1. Before fetching the voucher, with ``final_vouch_url=None``. Returning
   ``False`` rejects the voucher without a network request.
2. After fetching and following allowed redirects, with ``final_vouch_url`` set
   to the final voucher URL. Returning ``False`` rejects the voucher even if
   the submitted URL was trusted.

Both calls must return a truthy value. The policy controls only whether the
submitted and final voucher URLs are trusted. The processor still requires the
voucher response to be HTTP ``200`` with ``text/html`` content and to contain
an HTTP(S) HTML ``href`` to the submitted source URL's domain.

**Example:**

.. code-block:: python

   # myapp/webmentions.py
   from urllib.parse import urlparse

   TRUSTED_VOUCH_HOSTS = {"trusted.example", "events.example"}

   def trust_vouch(
       *,
       webmention,
       source_url: str,
       target_url: str,
       vouch_url: str,
       final_vouch_url: str | None = None,
   ) -> bool:
       candidate = final_vouch_url or vouch_url
       return urlparse(candidate).hostname in TRUSTED_VOUCH_HOSTS

.. code-block:: python

   # settings.py
   INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY = "myapp.webmentions.trust_vouch"

If the configured path cannot be imported, resolves to a non-callable, or the
callable raises, Vouch verification fails closed and the Webmention is marked
``failed`` by the processor. When receiving asynchronously, the request path
does not import or call the trust policy; workers evaluate it when they run
``WebmentionProcessor``.

INDIEWEB_WEBMENTION_VOUCH_REQUIRED
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Require incoming Webmentions to have a verifiable Vouch URL.

**Default:** ``False``

When ``False``, ordinary Webmentions without ``vouch`` continue to verify
normally. When ``True``, the processor marks a Webmention ``failed`` if it has
no stored ``vouch`` or if the configured Vouch verification does not succeed.
This requirement is enforced in ``WebmentionProcessor`` and queued worker
paths, not in the receive request path.

When ``INDIEWEB_WEBMENTION_VOUCH_REQUIRED`` is ``True`` and
neither ``INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY`` nor
``INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS`` is configured, Vouch
verification fails closed for submitted vouchers. Configure a trust policy or
at least one trusted voucher domain before enabling required mode in
production.

Salmention Configuration
~~~~~~~~~~~~~~~~~~~~~~~~

There is no Salmention-specific setting in django-indieweb today.
django-indieweb persists verified Webmention source snapshots and stable nested
child response rows as a foundation for receive-side Salmention support, but
nested rendering is still deferred. Sending Salmentions also still needs
outbound target tracking for each original post. See :doc:`webmention` for the
support-status details and current ordinary Webmention reprocessing behavior.

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
- ``/indieweb/media/`` - Micropub media endpoint
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
       path('api/media/', views.MicropubMediaView.as_view(), name='media'),
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

django-indieweb creates six models:

1. **Auth** - Stores authorization codes temporarily
2. **Token** - Stores access tokens
3. **Webmention** - Stores incoming webmention source/target pairs, parsed
   content, status, and spam-check results
4. **WebmentionSourceSnapshot** - Stores the latest verified fetched source
   snapshot related to a submitted Webmention for future Salmention comparison
5. **WebmentionNestedResponse** - Stores stable nested ``h-entry`` responses
   discovered inside verified parent Webmention sources for future Salmention
   rendering
6. **Profile** - Stores user h-card data

``Auth``, ``Token``, and ``Profile`` use ``settings.AUTH_USER_MODEL`` for their
user relationships. ``WebmentionSourceSnapshot`` is tied one-to-one to a parent
``Webmention`` and cascades when that parent is deleted.
``WebmentionNestedResponse`` is tied many-to-one to a parent ``Webmention``,
is unique per parent and stable nested identity, and also cascades when the
parent is deleted.

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
