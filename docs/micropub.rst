Micropub Implementation Guide
=============================

Overview
--------

django-indieweb provides a Micropub endpoint that can create, query, update,
delete, and undelete content in your Django application, plus a Micropub media
endpoint for direct media uploads. The content endpoint uses a pluggable
handler system that allows you to integrate Micropub with any Django content
model; the media endpoint stores uploads through Django's configured storage
backend.

Quick Start
-----------

1. Basic Setup
~~~~~~~~~~~~~~

The Micropub endpoint is available at ``/indieweb/micropub/`` by
default. It requires authentication via IndieAuth tokens. Scopes are
enforced per operation: ``POST`` entry create requires ``create`` (the
legacy alias ``post`` is still accepted), ``POST action=update`` requires
``update``, ``POST action=delete`` requires ``delete``,
``POST action=undelete`` requires ``undelete``, and ``GET ?q=source``
requires ``update``. The media endpoint is available at ``/indieweb/media/``
and requires ``media``. See :doc:`api` for the full mapping.

2. Using the Default In-Memory Handler
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For testing and development, django-indieweb includes an in-memory
content handler that stores posts in memory:

.. code:: python

   # This is the default if no handler is configured
   # Posts are stored in memory and lost on restart

3. Creating a Custom Content Handler
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To integrate Micropub with your Django models, create a custom content
handler:

.. code:: python

   # myapp/micropub_handler.py
   from indieweb.handlers import MicropubContentHandler, MicropubEntry
   from myapp.models import BlogPost

   class BlogPostMicropubHandler(MicropubContentHandler):
       def create_entry(self, properties, user):
           # Extract properties
           content = properties.get('content', [''])[0]
           name = properties.get('name', [''])[0]
           categories = properties.get('category', [])

           # Create your model instance
           post = BlogPost.objects.create(
               author=user,
               title=name or 'Untitled',
               content=content,
               status='published'
           )

           # Add categories/tags
           for category in categories:
               post.tags.add(category)

           # Return MicropubEntry with the URL
           return MicropubEntry(
               url=post.get_absolute_url(),
               properties=properties
           )

       def get_entry(self, url, user):
           # Parse URL to get post
           try:
               post = BlogPost.objects.get(
                   slug=url.split('/')[-2],  # Adjust based on your URL structure
                   author=user
               )
               return MicropubEntry(
                   url=post.get_absolute_url(),
                   properties={
                       'name': [post.title],
                       'content': [post.content],
                       'published': [post.created.isoformat()],
                   }
               )
           except BlogPost.DoesNotExist:
               return None

       def update_entry(self, url, updates, user):
           # Implement update logic
           post = self._get_post_from_url(url, user)

           if 'replace' in updates:
               for key, values in updates['replace'].items():
                   if key == 'content':
                       post.content = values[0]
                   elif key == 'name':
                       post.title = values[0]

           post.save()
           return self.get_entry(url, user)

       def delete_entry(self, url, user):
           post = self._get_post_from_url(url, user)
           post.delete()

       def undelete_entry(self, url, user):
           # Implement if you support soft deletes
           raise NotImplementedError("Undelete not supported")

4. Configure Your Handler
~~~~~~~~~~~~~~~~~~~~~~~~~

In your Django settings:

.. code:: python

   # settings.py
   INDIEWEB_MICROPUB_HANDLER = 'myapp.micropub_handler.BlogPostMicropubHandler'

Supported Features
------------------

Content Types
~~~~~~~~~~~~~

The Micropub endpoint supports both form-encoded and JSON requests:

**Form-encoded:**

.. code:: bash

   curl -X POST https://example.com/indieweb/micropub/ \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -d "h=entry" \
     -d "content=Hello World!" \
     -d "category=indieweb,micropub"

**JSON:**

.. code:: bash

   curl -X POST https://example.com/indieweb/micropub/ \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "type": ["h-entry"],
       "properties": {
         "content": ["Hello JSON!"],
         "category": ["indieweb", "json"]
       }
     }'

Supported Properties
~~~~~~~~~~~~~~~~~~~~

Common h-entry properties are supported:

- ``content`` - The main content
- ``name`` - Title/name of the entry
- ``category`` - Tags/categories (comma-separated or array)
- ``location`` - Geographic location (geo URI format)
- ``in-reply-to`` - URL this post is replying to
- ``bookmark-of`` - URL this post bookmarks
- ``like-of`` - URL this post likes
- ``repost-of`` - URL this post reposts
- ``rsvp`` - RSVP value for RSVP posts
- ``photo`` - Photo URL(s), or uploaded photo files on multipart create requests
- ``audio`` - Audio URL(s)
- ``video`` - Video URL(s)
- ``published`` - Publication date
- ``summary`` - Event summary
- ``description`` - Event description
- ``start`` - Event start value
- ``end`` - Event end value
- ``url`` - Event URL

For h-event-style form requests, django-indieweb forwards event properties
such as ``name``, ``summary``, ``description``, ``start``, ``end``,
``location``, ``category``, ``url``, and ``published`` unchanged as normalized
arrays. If a client also sends h-entry-style ``content`` for an event-like
post, that property is forwarded as ``content`` rather than remapped.

For RSVP posts, the form parser forwards ``rsvp``, ``in-reply-to``, ``name``,
``content``, ``category``, and ``published``. django-indieweb does not infer
attendance, event date, time-zone, calendar-feed, or persistence behavior.
Your configured handler owns those choices.

Media Endpoint
~~~~~~~~~~~~~~

``GET /indieweb/micropub/?q=config`` advertises the media endpoint as an
absolute ``media-endpoint`` URL. Custom ``MicropubContentHandler.get_config()``
overrides do not need to add this value themselves; the Micropub view injects
the configured endpoint URL into the response.

Upload media directly to ``/indieweb/media/`` with a token that has the
``media`` scope. The request must be ``multipart/form-data`` with one part
named ``file``:

.. code:: bash

   curl -X POST https://example.com/indieweb/media/ \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -F "file=@sunset.jpg;type=image/jpeg"

Successful uploads are stored through Django's configured storage backend
using an unguessable key under ``indieweb/media/``. The endpoint returns
``201 Created`` with an absolute ``Location`` header and an empty body:

.. code:: http

   HTTP/1.1 201 Created
   Location: https://example.com/media/indieweb/media/ff176c461dd111e6b6ba3e1d05defe78.jpg

Use that URL as a later Micropub property value, for example:

.. code:: bash

   curl -X POST https://example.com/indieweb/micropub/ \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "type": ["h-entry"],
       "properties": {
         "content": ["A photo post"],
         "photo": ["https://example.com/media/indieweb/media/ff176c461dd111e6b6ba3e1d05defe78.jpg"]
       }
     }'

Multipart create requests sent directly to ``/indieweb/micropub/`` can also
include ``photo`` file parts. These are create requests, so they require
``create`` (or the legacy ``post`` alias), not ``media``. Each uploaded photo
is validated and stored with the same policy as the direct media endpoint, and
the resulting absolute media URL is appended to the entry's ``photo`` property
before ``MicropubContentHandler.create_entry()`` is called. Existing URL-valued
``photo`` form fields are preserved, so clients can send both referenced and
uploaded photos in one create request:

.. code:: bash

   curl -X POST https://example.com/indieweb/micropub/ \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -F "h=entry" \
     -F "content=A photo post" \
     -F "photo=https://photos.example.org/existing.jpg" \
     -F "photo=@sunset.jpg;type=image/jpeg"

The handler receives properties shaped like:

.. code:: json

   {
     "content": ["A photo post"],
     "photo": [
       "https://photos.example.org/existing.jpg",
       "https://example.com/media/indieweb/media/ff176c461dd111e6b6ba3e1d05defe78.jpg"
     ]
   }

The media endpoint and multipart create uploads share two safety settings:

- ``INDIEWEB_MEDIA_MAX_UPLOAD_BYTES`` defaults to 10 MiB. Larger uploads
  return ``413 invalid_request`` before storage is called.
- ``INDIEWEB_MEDIA_ALLOWED_TYPES`` defaults to common image, audio, and video
  MIME types. Other content types return ``415 invalid_request`` before
  storage is called.

Set either value to ``None`` to disable that built-in check, but only when your
web server, CDN, storage backend, or application enforces equivalent limits.
If you allow broad content types such as HTML or SVG, serve uploaded media
from a separate origin or with defensive headers such as
``Content-Disposition: attachment``.

Update, Delete, Undelete
~~~~~~~~~~~~~~~~~~~~~~~~

The endpoint also supports the Micropub update, delete, and undelete actions.
Updates are JSON-only (per Micropub §3.7); delete and undelete accept either
form-encoded or JSON bodies. Update bodies must contain at least one of
``replace``, ``add``, or ``delete``, and the values inside each operation
must be arrays (per Micropub §3.4) — empty bodies and scalar operation
values are rejected with ``400 invalid_request``.

Update and undelete return ``204 No Content`` on success, or ``201 Created``
with a ``Location`` header when the configured handler relocates the entry.
Delete always returns ``204 No Content`` (the handler interface does not
return an entry on delete, so a relocation response is not possible). All
three return ``400 invalid_request`` when the entry is unknown to the
handler or ``url`` is missing, and ``500`` when the handler raises an
unexpected exception.

**Update (replace, JSON):**

.. code:: bash

   curl -X POST https://example.com/indieweb/micropub/ \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "action": "update",
       "url": "https://example.com/posts/123/",
       "replace": {"content": ["Updated content"]}
     }'

**Update (add and delete combined, JSON):**

.. code:: bash

   curl -X POST https://example.com/indieweb/micropub/ \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "action": "update",
       "url": "https://example.com/posts/123/",
       "add": {"category": ["new-tag"]},
       "delete": ["draft"]
     }'

**Delete (form-encoded):**

.. code:: bash

   curl -X POST https://example.com/indieweb/micropub/ \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -d "action=delete" \
     -d "url=https://example.com/posts/123/"

**Undelete (form-encoded):**

.. code:: bash

   curl -X POST https://example.com/indieweb/micropub/ \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -d "action=undelete" \
     -d "url=https://example.com/posts/123/"

Query Endpoints
~~~~~~~~~~~~~~~

**Configuration:**

.. code:: bash

   curl https://example.com/indieweb/micropub/?q=config \
     -H "Authorization: Bearer YOUR_TOKEN"

Returns supported post types and features.

Example response excerpt:

.. code:: json

   {
     "media-endpoint": "https://example.com/indieweb/media/",
     "syndicate-to": [],
     "post-types": [
       {"type": "note", "name": "Note", "properties": ["content"]},
       {"type": "article", "name": "Article", "properties": ["name", "content"]},
       {"type": "photo", "name": "Photo", "properties": ["photo", "content", "category"]},
       {"type": "reply", "name": "Reply", "properties": ["in-reply-to", "content"]},
       {"type": "bookmark", "name": "Bookmark", "properties": ["bookmark-of", "name", "content"]},
       {"type": "like", "name": "Like", "properties": ["like-of"]},
       {"type": "repost", "name": "Repost", "properties": ["repost-of"]},
       {
         "type": "event",
         "name": "Event",
         "properties": ["name", "summary", "description", "start", "end", "location", "category", "url", "published"]
       },
       {"type": "rsvp", "name": "RSVP", "properties": ["rsvp", "in-reply-to", "name", "content"]}
     ]
   }

The built-in handler advertises common h-entry shapes and forwards normalized
properties to ``create_entry()``. RSVP is advertised as a distinct post type
because clients commonly expose RSVP as a creation mode, even though the
wire-format remains an ``h-entry`` with ``rsvp`` and ``in-reply-to``
properties. django-indieweb does not infer storage semantics from post-type
names; your configured handler decides how to persist bookmarks, likes,
reposts, replies, articles, notes, photo posts, events, and RSVPs.

**Syndication Targets:**

.. code:: bash

   curl https://example.com/indieweb/micropub/?q=syndicate-to \
     -H "Authorization: Bearer YOUR_TOKEN"

**Source Content:**

.. code:: bash

   curl "https://example.com/indieweb/micropub/?q=source&url=https://example.com/posts/123/" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Accept: application/json"

Returns ``{"type": ["h-entry"], "properties": {...}}`` for the entry returned
by your configured handler's ``get_entry(url, user)`` method.

**Filtered Source Content:**

.. code:: bash

   curl "https://example.com/indieweb/micropub/?q=source&url=https://example.com/posts/123/&properties[]=content&properties[]=name" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Accept: application/json"

Returns only the requested existing properties as ``{"properties": {...}}``.
Missing requested property names are omitted.

Testing Your Implementation
---------------------------

1. **Get an access token** via IndieAuth with the ``create`` scope (or the
   legacy alias ``post``); use ``update``/``delete``/``undelete`` for those
   actions, ``update`` for ``GET ?q=source``, and ``media`` for direct media
   uploads
2. **Create a test post:**

.. code:: bash

   curl -X POST http://localhost:8000/indieweb/micropub/ \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -d "h=entry" \
     -d "content=Test post from Micropub!"

3. **Check the response:**

- Status: 201 Created
- Location header contains the URL of the created post

Advanced Integration
--------------------

Handling Different Post Types
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

   def create_entry(self, properties, user):
       # Determine post type
       post_type = 'note'  # default

       if properties.get('name'):
           post_type = 'article'
       elif properties.get('photo'):
           post_type = 'photo'
       elif properties.get('start'):
           post_type = 'event'
       elif properties.get('rsvp'):
           post_type = 'rsvp'
       elif properties.get('in-reply-to'):
           post_type = 'reply'

       # Create appropriate model based on type
       if post_type == 'article':
           return self._create_article(properties, user)
       elif post_type == 'photo':
           return self._create_photo_post(properties, user)
       elif post_type == 'event':
           return self._create_event(properties, user)
       elif post_type == 'rsvp':
           return self._create_rsvp(properties, user)
       else:
           return self._create_note(properties, user)

Adding Syndication Support
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

   def get_config(self, user):
       config = super().get_config(user)

       # Add syndication targets
       config['syndicate-to'] = [
           {
               'uid': 'https://twitter.com/username',
               'name': 'Twitter'
           },
           {
               'uid': 'https://mastodon.social/@username',
               'name': 'Mastodon'
           }
       ]

       return config

Error Handling
--------------

The Micropub endpoint returns the following HTTP status codes:

- ``201 Created`` - Success on entry create, and on update/undelete actions
  whose handler returns a relocated entry URL; a ``Location`` header points
  at the new or canonical URL. Delete cannot relocate.
- ``204 No Content`` - Success on update/delete/undelete actions when the
  entry's URL did not change (delete always returns this on success)
- ``400 Bad Request`` - Invalid request data: the configured handler raised
  on entry creation; an action request had an unknown ``url`` (handler
  raised ``ValueError``), missing ``url``, malformed JSON, a non-object
  JSON body, or — for ``action=update`` — a non-JSON body, an empty update
  payload (no ``replace``/``add``/``delete``), a non-array operation value,
  or an otherwise spec-non-conformant operation shape; a ``GET ?q=source``
  request had a missing ``url`` or a ``url`` unknown to the handler; or a
  media endpoint upload was not ``multipart/form-data`` or lacked the ``file``
  part. Action, source-query, and media-upload client failures use the
  plain-text body ``invalid_request``.
- ``401 Unauthorized`` - Missing, expired, or invalid access token, or the
  token's owner is inactive
- ``413 Payload Too Large`` - Media endpoint or multipart create upload exceeded
  ``INDIEWEB_MEDIA_MAX_UPLOAD_BYTES``; body ``invalid_request``
- ``415 Unsupported Media Type`` - Media endpoint or multipart create upload
  content type was not listed in ``INDIEWEB_MEDIA_ALLOWED_TYPES``; body
  ``invalid_request``
- ``403 Forbidden`` - body ``authorization error`` when the token lacks the
  scope required for the requested operation; body ``invalid_client`` when
  the token's ``client_id`` is rejected by the configured
  ``INDIEWEB_CLIENT_ID_VALIDATOR``
- ``500 Internal Server Error`` - The configured handler raised an unexpected
  exception (e.g. database failure) during ``update``/``delete``/``undelete``
  or ``GET ?q=source``, or the configured storage backend raised while saving
  a media endpoint or multipart create upload; the exception is logged via
  ``logger.exception`` so the stack trace stays in the server log rather than
  the response body

See :doc:`api` for the full per-operation scope mapping and the complete
error-response listing across all IndieWeb endpoints.

Security Considerations
-----------------------

1. **Always validate user permissions** in your handler
2. **Sanitize content** before storing
3. **Validate URLs** for properties like photo and in-reply-to
4. **Rate limiting** is recommended for production use

Example: Integration with django-cast
-------------------------------------

.. code:: python

   # cast_micropub.py
   from indieweb.handlers import MicropubContentHandler, MicropubEntry
   from cast.models import Post

   class CastMicropubHandler(MicropubContentHandler):
       def create_entry(self, properties, user):
           from cast.models import Blog

           # Get user's blog
           blog = Blog.objects.get(user=user)

           # Create post
           post = Post.objects.create(
               blog=blog,
               author=user,
               title=properties.get('name', [''])[0],
               content=properties.get('content', [''])[0],
               visible=True,
               published=True
           )

           # Handle categories
           categories = properties.get('category', [])
           for cat_name in categories:
               category, _ = Category.objects.get_or_create(
                   blog=blog,
                   name=cat_name
               )
               post.categories.add(category)

           return MicropubEntry(
               url=post.get_absolute_url(),
               properties=properties
           )

Then in settings:

.. code:: python

   INDIEWEB_MICROPUB_HANDLER = 'myproject.cast_micropub.CastMicropubHandler'

Next Steps
----------

- Use the existing :doc:`websub` publisher helpers to advertise feeds and notify hubs after host-owned topic changes
- Use the WebSub subscriber callback support if your host application explicitly subscribes to external topics and has a worker/hook policy for delivered content
