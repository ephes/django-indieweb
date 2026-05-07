Micropub Implementation Guide
=============================

Overview
--------

django-indieweb provides a Micropub endpoint that can create, query, update,
delete, and undelete content in your Django application, plus a Micropub media
endpoint for direct media uploads. The content endpoint uses a pluggable
handler system that allows you to integrate Micropub with any Django content
model; the media endpoint stores uploads through Django's configured storage
backend and can delegate media listing, metadata, and deletion to optional
host-owned hooks.

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

5. Static-Site and Storage-Boundary Examples
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Static-site projects can use the same ``MicropubContentHandler`` interface.
django-indieweb only parses the Micropub request, checks the token and scope,
and calls your handler. Host code still owns persistence, path and URL
mapping, front matter format, static-site rendering, build/deploy commands,
repository credentials, commits, pushes, media indexing, and media deletion
policy.

The repository includes tested copy-and-adapt source in
``examples/static_site_micropub.py``. That directory is not installed as a
public Python package when django-indieweb is installed from PyPI, so copy the
parts you need into your Django project, for example
``myapp/static_site_examples.py``, and configure your copied handler from
there. The example mapper turns Micropub properties into Markdown files with
front matter. It uses ``mp-slug`` when present, falls back to
title/content-derived slugs, stores common fields such as title, date, tags,
post status, photos, channel and syndication requests in front matter, and
preserves the original Micropub properties for host code that wants to
reconstruct source responses later.

For a Jekyll- or Eleventy-style layout, configure the mapper with a posts
directory such as ``_posts`` and a date-prefixed filename. For Hugo-style
content, use a directory such as ``content/posts``. The example deliberately
does not run Jekyll, Hugo, Eleventy, Git, or deployment commands:

.. code:: python

   from pathlib import Path

   from myapp.static_site_examples import LocalFilesystemStaticSiteHandler

   class MyStaticSiteMicropubHandler(LocalFilesystemStaticSiteHandler):
       def __init__(self):
           super().__init__(
               content_root=Path("/srv/example-site"),
               public_base_url="https://example.com/",
           )

   # settings.py
   INDIEWEB_MICROPUB_HANDLER = "myapp.micropub.MyStaticSiteMicropubHandler"

``LocalFilesystemStaticSiteHandler`` writes only below the explicit
``content_root`` passed by host code. Its default mapping creates paths such as
``content/posts/2026-05-06-my-note.md`` and public URLs such as
``https://example.com/posts/2026/05/06/my-note/``. Adapt the mapper when your
site uses a different permalink policy. The filesystem example rejects an
already-existing target path so hosts must choose their own slug-collision
policy instead of silently overwriting a post.

If your publication workflow stores source files through Django storage, pass
an explicit storage instance instead of teaching django-indieweb a new storage
abstraction:

.. code:: python

   from django.core.files.storage import storages
   from myapp.static_site_examples import DjangoStorageStaticSiteHandler

   class MyStorageMicropubHandler(DjangoStorageStaticSiteHandler):
       def __init__(self):
           super().__init__(
               storage=storages["static_site_posts"],
               public_base_url="https://example.com/",
           )

For Git-backed workflows, keep credentials, commits, pushes, branches, review
policy, and deployment triggers in a host adapter. The example handler only
calls the adapter boundary:

.. code:: python

   from myapp.static_site_examples import GitBackedStaticSiteHandler

   class RepositoryPostStore:
       def save_file(self, *, path, content, message):
           # Host-owned: write a worktree file, open a pull request, call a
           # private GitHub/GitLab client, or enqueue review. No network call
           # is hidden inside django-indieweb.
           raise NotImplementedError

   class MyGitMicropubHandler(GitBackedStaticSiteHandler):
       def __init__(self):
           super().__init__(
               store=RepositoryPostStore(),
               public_base_url="https://example.com/",
           )

Static-site source queries and editing actions usually require more than a
file write. To support ``GET ?q=source`` by URL, ``GET ?q=source`` list mode,
``action=update``, ``action=delete``, or ``action=undelete``, keep a durable
host index that maps public URLs to source paths and ownership. Without that
index, return ``None`` for optional source-list/media-list hooks or raise an
explicit host error rather than guessing paths from arbitrary URLs.

The same boundary applies to media. Direct media uploads can store files
through Django storage, but source listing, metadata lookup, and deletion need
a host-owned media index. The example ``IndexedMediaHooksMixin`` delegates
``list_media()``, ``get_media()``, and ``delete_media()`` to such an index so
django-indieweb never infers storage paths from submitted URLs. Assign the
index on the concrete handler, for example in ``__init__``, before enabling
those hooks.

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
- ``mp-slug`` - Suggested slug for host code to interpret
- ``mp-channel`` - Requested host-defined channel UID(s)
- ``mp-photo-alt`` - Submitted text alternatives for photo values
- ``mp-syndicate-to`` - Requested host-defined syndication target UID(s)
- ``post-status`` - Submitted publication status such as ``draft`` or
  ``published``

For h-event-style form requests, django-indieweb forwards event properties
such as ``name``, ``summary``, ``description``, ``start``, ``end``,
``location``, ``category``, ``url``, and ``published`` unchanged as normalized
arrays. If a client also sends h-entry-style ``content`` for an event-like
post, that property is forwarded as ``content`` rather than remapped.

For RSVP posts, the form parser forwards ``rsvp``, ``in-reply-to``, ``name``,
``content``, ``category``, and ``published``. django-indieweb does not infer
attendance, event date, time-zone, calendar-feed, or persistence behavior.
Your configured handler owns those choices.

Command Properties and Draft Status
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

django-indieweb preserves common Micropub command-style properties on create
requests so your configured ``MicropubContentHandler.create_entry()`` can make
host-specific decisions. It does not execute those commands itself: it does
not generate slugs, choose or route channels, attach ``mp-photo-alt`` to stored
files, cross-post, enqueue syndication, or implement draft storage.

Form-encoded creates normalize submitted command values to property arrays.
Single values become one-item arrays:

.. code:: bash

   curl -X POST https://example.com/indieweb/micropub/ \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -d "h=entry" \
     -d "content=Draft note" \
     -d "mp-slug=draft-note" \
     -d "mp-channel=notes" \
     -d "mp-photo-alt=A text alternative" \
     -d "mp-syndicate-to=https://social.example/@user" \
     -d "post-status=draft"

The handler receives:

.. code:: json

   {
     "content": ["Draft note"],
     "mp-slug": ["draft-note"],
     "mp-channel": ["notes"],
     "mp-photo-alt": ["A text alternative"],
     "mp-syndicate-to": ["https://social.example/@user"],
     "post-status": ["draft"]
   }

For list-shaped command properties, clients can use array notation:

.. code:: bash

   curl -X POST https://example.com/indieweb/micropub/ \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -d "h=entry" \
     -d "mp-channel[]=notes" \
     -d "mp-channel[]=articles" \
     -d "mp-photo-alt[]=First image alt" \
     -d "mp-photo-alt[]=Second image alt" \
     -d "mp-syndicate-to[]=https://social.example/@user" \
     -d "mp-syndicate-to[]=https://news.example/list"

Only ``category`` keeps the historical comma-splitting behavior. Command
properties are not comma-split. Array notation is meaningful only for the
list-shaped command properties shown above: ``mp-channel``,
``mp-photo-alt``, and ``mp-syndicate-to``.

Microformats2 JSON creates pass the submitted ``properties`` object to the
handler unchanged, including command properties and ``post-status``, except
for server-managed properties described below:

.. code:: json

   {
     "type": ["h-entry"],
     "properties": {
       "content": ["Draft note"],
       "mp-slug": ["draft-note"],
       "mp-channel": ["notes"],
       "mp-photo-alt": ["A text alternative"],
       "mp-syndicate-to": ["https://social.example/@user"],
       "post-status": ["draft"]
     }
   }

The ``draft`` IndieAuth scope is treated as an extension scope by
django-indieweb. It may be requested, displayed, stored, and returned on
tokens, but it is not advertised in built-in server metadata and does not
replace the normal operation scopes. A create request with
``post-status=draft`` still requires ``create`` or the legacy ``post`` alias;
``action=update`` still requires ``update``. A token with ``create draft``
can create because ``create`` is present, while a token with only ``draft`` is
rejected by the built-in Micropub resource-server scope gate. Hosts that want
draft-only permissions should add their own policy around token issuance,
handler behavior, or a custom resource-server layer.

Server-Managed Properties
~~~~~~~~~~~~~~~~~~~~~~~~~

django-indieweb owns a small set of Micropub properties that clients cannot
set or edit through the bundled resource server. Create requests that submit
``uid`` or ``author`` are rejected with ``400 invalid_request`` before
``MicropubContentHandler.create_entry()`` is called. This applies to
Microformats2 JSON, simple JSON, and form-encoded creates, including array
notation such as ``uid[]``.

``action=update`` applies the same gate before
``MicropubContentHandler.update_entry()`` is called. ``replace`` and ``add``
reject maps containing ``uid`` or ``author``. ``delete`` rejects both the list
form, such as ``"delete": ["uid"]``, and the value-specific map form, such as
``"delete": {"author": [...]}``.

Command and extension properties remain allowed and handler-owned:
``mp-slug``, ``mp-channel``, ``mp-photo-alt``, ``mp-syndicate-to``, and
``post-status`` are preserved for host code rather than denied by this gate.

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

Media Source and Delete Hooks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

django-indieweb does not keep a bundled media index. Direct uploads are stored
through Django storage, but listing uploaded files, returning metadata for a
specific media URL, and deleting media remain host-owned operations. Host
projects can opt into those operations by implementing these optional
``MicropubContentHandler`` hooks:

- ``list_media(user, limit=None, offset=0, filter=None)``
- ``get_media(url, user)``
- ``delete_media(url, user)``

The default hooks are unsupported. When no hook is configured,
``GET /indieweb/media/?q=source`` and ``POST /indieweb/media/`` with
``action=delete`` return ``501 not_implemented`` after the token and ``media``
scope checks pass. django-indieweb never infers a storage path from a
submitted URL and never deletes from ``default_storage`` for this action
unless host code does so inside ``delete_media()``.

List media with ``q=source``:

.. code:: bash

   curl https://example.com/indieweb/media/?q=source \
     -H "Authorization: Bearer YOUR_TOKEN"

Successful list responses are JSON:

.. code:: json

   {
     "items": [
       {
         "properties": {
           "url": ["https://example.com/media/photo.jpg"],
           "name": ["photo.jpg"],
           "media-type": ["photo"]
         }
       }
     ],
     "paging": {"limit": null, "offset": 0, "total": 1}
   }

``limit`` and ``offset`` are optional non-negative integers; malformed values
return ``400 invalid_request``. ``filter`` is passed through to the host hook
as submitted. ``total`` is included only when the hook returns a known total.

Fetch metadata for one URL by adding ``url``:

.. code:: bash

   curl "https://example.com/indieweb/media/?q=source&url=https://example.com/media/photo.jpg" \
     -H "Authorization: Bearer YOUR_TOKEN"

The response is a single media object:

.. code:: json

   {
     "properties": {
       "url": ["https://example.com/media/photo.jpg"],
       "name": ["photo.jpg"],
       "media-type": ["photo"]
     }
   }

An empty, unknown, or rejected ``url`` returns ``400 invalid_request``.
Unexpected hook exceptions return ``500`` and are logged.

Delete host-owned media by submitting ``action=delete`` and ``url`` to the
media endpoint with a ``media``-scoped token:

.. code:: bash

   curl -X POST https://example.com/indieweb/media/ \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -d "action=delete" \
     -d "url=https://example.com/media/photo.jpg"

Successful deletes return ``204 No Content`` with an empty body. Missing,
empty, unknown, or hook-rejected URLs return ``400 invalid_request``.

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

Returns supported post types and features. The ``q`` array advertises the query
names django-indieweb actually implements today, so clients can discover
``q=category``, ``q=channel``, ``q=media-endpoint``, ``q=post-types``,
``q=source``, and ``q=syndicate-to`` without probing every
Micropub-extension query name. django-indieweb intentionally does not advertise
or implement unrelated extension query names such as ``q=contacts`` or a
standalone ``q=properties`` query.

Example response excerpt:

.. code:: json

   {
     "media-endpoint": "https://example.com/indieweb/media/",
     "syndicate-to": [],
     "categories": [],
     "channels": [],
     "post-types": [
       {"type": "note", "name": "Note", "properties": ["content"]},
       {"type": "article", "name": "Article", "properties": ["name", "content"]},
       {"type": "photo", "name": "Photo", "properties": ["photo", "content", "category"]},
       {"type": "audio", "name": "Audio", "properties": ["audio", "content", "category"]},
       {"type": "video", "name": "Video", "properties": ["video", "content", "category"]},
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
     ],
     "q": ["config", "source", "syndicate-to", "category", "channel", "media-endpoint", "post-types"]
   }

The built-in handler advertises common h-entry shapes and forwards normalized
properties to ``create_entry()``. RSVP is advertised as a distinct post type
because clients commonly expose RSVP as a creation mode, even though the
wire-format remains an ``h-entry`` with ``rsvp`` and ``in-reply-to``
properties. Audio and video are advertised for URL-valued ``audio`` and
``video`` properties that django-indieweb already normalizes and forwards to
the configured handler. django-indieweb does not infer storage semantics from
post-type names; your configured handler decides how to persist and render
bookmarks, likes, reposts, replies, articles, notes, photo posts, audio posts,
video posts, events, and RSVPs. Advertising audio and video post types does
not add transcoding, players, storage models, media processing, media-source
listing, or media-delete behavior.

**Media Endpoint:**

.. code:: bash

   curl https://example.com/indieweb/micropub/?q=media-endpoint \
     -H "Authorization: Bearer YOUR_TOKEN"

Returns the effective media endpoint under the ``media-endpoint`` JSON key:

.. code:: json

   {"media-endpoint": "https://example.com/indieweb/media/"}

The direct query uses the same value as ``q=config``. If your handler returns a
truthy ``media-endpoint`` value from ``get_config()``, django-indieweb preserves
it. Otherwise the view injects the bundled ``/indieweb/media/`` endpoint as an
absolute URL.

**Post Types:**

.. code:: bash

   curl https://example.com/indieweb/micropub/?q=post-types \
     -H "Authorization: Bearer YOUR_TOKEN"

Returns the configured handler's supported vocabulary under the ``post-types``
JSON key. The default in-memory handler returns the same post-type objects
shown in ``q=config``. Custom handlers remain authoritative: override
``MicropubContentHandler.get_config()`` to change the advertised post types,
names, or property lists. The default audio and video entries advertise only
normalized ``audio``/``video`` URLs plus optional ``content`` and ``category``;
host code still owns persistence, rendering, and any media-processing workflow.

Clients can request a specific post type with ``post-type``:

.. code:: bash

   curl "https://example.com/indieweb/micropub/?q=post-types&post-type=note" \
     -H "Authorization: Bearer YOUR_TOKEN"

The response remains a ``post-types`` list containing only matching type
objects, or an empty list if the submitted type is not advertised. ``q=post-types``
also supports ``filter``, ``limit``, and ``offset`` with the same policy as the
category and channel queries; ``post-type`` is applied first, then those list
parameters operate on the narrowed list. django-indieweb does not infer storage
semantics from this advertisement; the configured handler still decides how
submitted properties map to host models.

**Categories:**

.. code:: bash

   curl https://example.com/indieweb/micropub/?q=category \
     -H "Authorization: Bearer YOUR_TOKEN"

Returns the configured handler's ``categories`` list under the ``categories``
JSON key. The default in-memory handler advertises an empty list. Override
``MicropubContentHandler.get_config()`` in your handler to expose host-defined
categories:

.. code:: python

   def get_config(self, user):
       config = super().get_config(user)
       config["categories"] = ["indieweb", "micropub", "django"]
       return config

Example response:

.. code:: json

   {"categories": ["indieweb", "micropub", "django"]}

**Channels:**

.. code:: bash

   curl https://example.com/indieweb/micropub/?q=channel \
     -H "Authorization: Bearer YOUR_TOKEN"

Returns the configured handler's ``channels`` list under the ``channels`` JSON
key. The shape of each item is host-defined; clients commonly expect objects
with ``uid`` and ``name``:

.. code:: python

   def get_config(self, user):
       config = super().get_config(user)
       config["channels"] = [
           {"uid": "notes", "name": "Notes"},
           {"uid": "articles", "name": "Articles"},
       ]
       return config

Example response:

.. code:: json

   {
     "channels": [
       {"uid": "notes", "name": "Notes"},
       {"uid": "articles", "name": "Articles"}
     ]
   }

django-indieweb preserves submitted ``mp-channel`` command properties on
creates, but it does not interpret channel data, select defaults, or route
publication by channel. Those decisions remain host-handler concerns.

The list-valued config queries support the ``filter``, ``limit``, and ``offset``
parameters. ``filter`` is a free-form string; items are matched
case-insensitively as a substring against either the string item itself or a
stable JSON serialization of dict items (so common fields such as ``uid`` and
``name`` are searchable without per-handler configuration). ``limit`` and
``offset`` must be non-negative integers; the order of operations is filter →
offset → limit. Malformed ``limit`` or ``offset`` values (non-integers,
negative numbers, or floats) return ``400 invalid_request`` rather than being
silently coerced to zero. Missing ``categories`` or ``channels`` keys in a
custom handler config return an empty list under the response key rather than
raising.

**Syndication Targets:**

.. code:: bash

   curl https://example.com/indieweb/micropub/?q=syndicate-to \
     -H "Authorization: Bearer YOUR_TOKEN"

Returns the configured handler's ``syndicate-to`` list under the
``syndicate-to`` JSON key. The built-in handler returns an empty list because
django-indieweb does not include bundled syndicators.

.. code:: json

   {
     "syndicate-to": [
       {
         "uid": "https://social.example/@username",
         "name": "Example Social",
         "service": {
           "name": "Example Social",
           "url": "https://social.example/"
         },
         "checked": true
       }
     ]
   }

Custom handlers populate this list from
``MicropubContentHandler.get_config()``. Each target should include a stable
``uid`` clients can submit back and a human-readable ``name``. Hosts may add
``service`` metadata, such as service ``name``, ``url``, or ``photo`` values,
when clients should display platform details. Hosts that support a default
selection can add a boolean ``checked`` value; django-indieweb only advertises
that value and does not choose targets for the client.

.. code:: python

   def get_config(self, user):
       config = super().get_config(user)
       config["syndicate-to"] = [
           {
               "uid": "https://social.example/@username",
               "name": "Example Social",
               "service": {
                   "name": "Example Social",
                   "url": "https://social.example/",
               },
               "checked": True,
           },
           {
               "uid": "https://syndication.example/targets/newsletter",
               "name": "Newsletter",
           },
       ]
       return config

If a custom handler omits ``syndicate-to`` or returns a non-list value, the
direct query returns ``{"syndicate-to": []}`` rather than raising. The
aggregate ``q=config`` response preserves the handler's configured
``syndicate-to`` value unchanged.

**Source List:**

.. code:: bash

   curl "https://example.com/indieweb/micropub/?q=source&limit=10&offset=0&filter=django" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Accept: application/json"

When no ``url`` parameter is supplied, ``GET ?q=source`` uses the optional
``MicropubContentHandler.list_entries(user, limit=..., offset=..., filter=...)``
hook to return editable/source posts from your host application. Existing
custom handlers that do not implement this optional hook continue to load; list
mode returns ``501 not_implemented`` for them.

The response contains Microformats-style source items and paging metadata:

.. code:: json

   {
     "items": [
       {
         "type": ["h-entry"],
         "properties": {
           "content": ["Hello source list"],
           "url": ["https://example.com/posts/123/"]
         }
       }
     ],
     "paging": {
       "limit": 10,
       "offset": 0,
       "total": 1
     }
   }

The bundled in-memory handler supports list mode for development and tests. It
adds a ``url`` property to list items when the stored entry properties do not
already include one, so clients have a value they can submit to update/delete or
``q=source&url=...``. Custom handlers remain authoritative for content
enumeration, ordering, permissions, filtering, and whether ``total`` can be
reported accurately.

``limit`` and ``offset`` must be non-negative integers. If ``limit`` is omitted,
django-indieweb passes a default limit of ``20`` to avoid unbounded source-list
responses; omitted ``offset`` defaults to ``0``. ``filter`` is optional and is
passed to the handler as a free-form string. The in-memory handler matches it
case-insensitively as a substring against a stable JSON serialization of each
source item. Cursor-style ``after``/``before`` paging, bundled post storage or
search, media source/delete hooks, command properties, and syndication routing
remain out of scope for this slice.

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

Syndication is host-owned. django-indieweb can advertise targets through
``get_config()`` and pass Micropub request properties to your content handler,
but it does not cross-post, call webhooks, choose targets, store syndicator
credentials, or run syndicator plugins.

.. code:: python

   def get_config(self, user):
       config = super().get_config(user)

       config['syndicate-to'] = [
           {
               'uid': 'https://social.example/@username',
               'name': 'Example Social',
               'service': {
                   'name': 'Example Social',
                   'url': 'https://social.example/'
               },
               'checked': True
           },
           {
               'uid': 'https://syndication.example/targets/newsletter',
               'name': 'Newsletter'
           }
       ]

       return config

When a client submits syndication choices, consume those values inside your
handler after the host post is created. JSON and form-encoded Micropub creates
preserve an ``mp-syndicate-to`` array in ``properties`` so a host can enqueue
its own task or record pending syndication state:

.. code:: python

   class MyMicropubHandler(MicropubContentHandler):
       def create_entry(self, properties, user):
           post = create_post_from_micropub_properties(properties, user)
           targets = properties.get("mp-syndicate-to", [])

           for target_uid in targets:
               create_pending_syndication(post=post, target_uid=target_uid)

           return MicropubEntry(
               type=["h-entry"],
               properties=properties,
               url=post.get_absolute_url(),
           )

Error Handling
--------------

The Micropub endpoint returns the following HTTP status codes:

- ``201 Created`` - Success on entry create, and on update/undelete actions
  whose handler returns a relocated entry URL; a ``Location`` header points
  at the new or canonical URL. Delete cannot relocate.
- ``204 No Content`` - Success on update/delete/undelete actions when the
  entry's URL did not change (delete always returns this on success)
- ``400 Bad Request`` - Invalid request data: the configured handler raised
  on entry creation; a create request submitted server-managed ``uid`` or
  ``author`` properties; an action request had an unknown ``url`` (handler
  raised ``ValueError``), missing ``url``, malformed JSON, a non-object
  JSON body, or — for ``action=update`` — a non-JSON body, an empty update
  payload (no ``replace``/``add``/``delete``), a non-array operation value,
  an attempt to mutate server-managed ``uid`` or ``author`` properties, or an
  otherwise spec-non-conformant operation shape; a ``GET ?q=source``
  by-URL request had an empty ``url`` or a ``url`` unknown to the handler; a
  source-list request had malformed ``limit``/``offset`` or the handler raised
  ``ValueError``; a media endpoint ``q=source`` request had an empty or unknown
  ``url`` or malformed ``limit``/``offset``; a media endpoint ``action=delete``
  request had a missing, empty, unknown, or hook-rejected ``url``; or a media
  endpoint upload was not ``multipart/form-data`` or lacked the ``file`` part.
  Action, source-query, media-query, media-delete, and media-upload client
  failures use the plain-text body ``invalid_request``.
- ``401 Unauthorized`` - Missing, expired, or invalid access token, or the
  token's owner is inactive. The response body is ``authentication error`` and
  includes ``Cache-Control: no-store`` and ``WWW-Authenticate: Bearer``.
- ``413 Payload Too Large`` - Media endpoint or multipart create upload exceeded
  ``INDIEWEB_MEDIA_MAX_UPLOAD_BYTES``; body ``invalid_request``
- ``415 Unsupported Media Type`` - Media endpoint or multipart create upload
  content type was not listed in ``INDIEWEB_MEDIA_ALLOWED_TYPES``; body
  ``invalid_request``
- ``403 Forbidden`` - body ``authorization error`` when the token lacks the
  scope required for the requested operation; body ``invalid_client`` when
  the token's ``client_id`` is rejected by ``INDIEWEB_ALLOWED_CLIENT_IDS`` or
  the configured ``INDIEWEB_CLIENT_ID_VALIDATOR``
- ``501 Not Implemented`` - ``GET ?q=source`` without ``url`` reached a
  configured handler that does not support the optional ``list_entries()`` hook;
  or ``GET /indieweb/media/?q=source`` / media ``action=delete`` reached a
  handler that does not support the corresponding optional media hook; body
  ``not_implemented``
- ``500 Internal Server Error`` - The configured handler raised an unexpected
  exception (e.g. database failure) during ``update``/``delete``/``undelete``
  or ``GET ?q=source``, a configured media hook raised an unexpected exception,
  or the configured storage backend raised while saving a media endpoint or
  multipart create upload; the exception is logged via ``logger.exception`` so
  the stack trace stays in the server log rather than the response body

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
