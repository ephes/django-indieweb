.. django-indieweb documentation master file

Welcome to django-indieweb's documentation!
============================================

**django-indieweb** provides IndieAuth, Micropub, Webmention, and h-card support for Django applications.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   concepts
   tutorial
   indieauth
   micropub
   webmention
   h-card
   api
   configuration
   development
   backlog
   changelog
   modules

Features
--------

* **IndieAuth authentication endpoint** - For logging into IndieWeb sites
* **IndieAuth authorization endpoint with consent screen** - For granting permissions to apps
* **IndieAuth token endpoint** - For exchanging auth codes for access tokens
* **Micropub endpoint with content creation, source query, update, delete, and undelete support**
* **Webmention support** - Send and receive cross-site conversations
* **H-card profiles** - Store and display user profiles with microformats2
* Pluggable content handler system for Micropub integration
* Pluggable interfaces for Webmention URL resolution and spam checking
* Support for both form-encoded and JSON Micropub requests
* Microformats2 parsing for rich webmention content and h-cards
* Micropub query endpoints (config, syndicate-to, source)
* Django integration

.. note::
   The Micropub endpoint now includes content creation, source query, update,
   delete, and undelete actions through a pluggable handler architecture. See
   :doc:`micropub` for implementation details.

Project Planning
----------------

Planned work is tracked in the project backlog. See :doc:`backlog`.

Installation
------------

Install django-indieweb using pip::

    pip install django-indieweb

Or with uv::

    uv pip install django-indieweb

Quick Start
-----------

1. Add "indieweb" to your INSTALLED_APPS setting::

    INSTALLED_APPS = [
        ...
        'indieweb',
    ]

2. Include the indieweb URLconf in your project urls.py::

    path('indieweb/', include('indieweb.urls')),

3. Run migrations::

    python manage.py migrate

4. Visit the IndieWeb endpoints at:

   * ``/indieweb/auth/`` - Authentication endpoint
   * ``/indieweb/token/`` - Token endpoint
   * ``/indieweb/micropub/`` - Micropub endpoint
   * ``/indieweb/webmention/`` - Webmention endpoint

5. To enable content creation and editing via Micropub, create a content handler::

    from indieweb.handlers import MicropubContentHandler, MicropubEntry

    class MyContentHandler(MicropubContentHandler):
        def create_entry(self, properties, user):
            # Your content creation logic here
            pass

   See :doc:`micropub` for detailed implementation examples.

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
