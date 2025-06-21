.. django-indieweb documentation master file

Welcome to django-indieweb's documentation!
============================================

**django-indieweb** provides IndieAuth and Micropub endpoints for Django applications.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   concepts
   tutorial
   micropub
   api
   configuration
   development
   changelog
   modules

Features
--------

* IndieAuth authentication endpoint
* IndieAuth token endpoint
* **Micropub endpoint with full content creation support**
* Pluggable content handler system for Micropub integration
* Support for both form-encoded and JSON Micropub requests
* Micropub query endpoints (config, syndicate-to)
* Django integration

.. note::
   The Micropub endpoint now includes a complete content creation system with a
   pluggable handler architecture. See :doc:`micropub` for implementation details.

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

4. Visit the IndieAuth endpoints at:

   * ``/indieweb/auth/`` - Authentication endpoint
   * ``/indieweb/token/`` - Token endpoint
   * ``/indieweb/micropub/`` - Micropub endpoint

5. To enable content creation via Micropub, create a content handler::

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
