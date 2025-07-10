Micropub Implementation Guide
=============================

Overview
--------

django-indieweb now provides a fully functional Micropub endpoint that
can create content in your Django application. The implementation uses a
pluggable content handler system that allows you to integrate Micropub
with any Django content model.

Quick Start
-----------

1. Basic Setup
~~~~~~~~~~~~~~

The Micropub endpoint is available at ``/indieweb/micropub/`` by
default. It requires authentication via IndieAuth tokens with the “post”
scope.

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

Common h-entry properties are supported: - ``content`` - The main
content - ``name`` - Title/name of the entry - ``category`` -
Tags/categories (comma-separated or array) - ``location`` - Geographic
location (geo URI format) - ``in-reply-to`` - URL this post is replying
to - ``photo`` - Photo URL(s) - ``published`` - Publication date

Query Endpoints
~~~~~~~~~~~~~~~

**Configuration:**

.. code:: bash

   curl https://example.com/indieweb/micropub/?q=config \
     -H "Authorization: Bearer YOUR_TOKEN"

Returns supported post types and features.

**Syndication Targets:**

.. code:: bash

   curl https://example.com/indieweb/micropub/?q=syndicate-to \
     -H "Authorization: Bearer YOUR_TOKEN"

Testing Your Implementation
---------------------------

1. **Get an access token** via IndieAuth with “post” scope
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
       elif properties.get('in-reply-to'):
           post_type = 'reply'

       # Create appropriate model based on type
       if post_type == 'article':
           return self._create_article(properties, user)
       elif post_type == 'photo':
           return self._create_photo_post(properties, user)
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

The Micropub endpoint returns appropriate HTTP status codes: -
``201 Created`` - Success, with Location header - ``400 Bad Request`` -
Invalid request data - ``401 Unauthorized`` - Missing or invalid token -
``403 Forbidden`` - Token lacks required scope - ``501 Not Implemented``
- For unimplemented features

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

- Implement update and delete operations
- Add media endpoint support for file uploads
- Implement WebSub for real-time updates
- Add support for more post types (events, RSVPs, etc.)
