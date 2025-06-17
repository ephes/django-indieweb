.. django-indieweb documentation master file

Welcome to django-indieweb's documentation!
============================================

**django-indieweb** provides IndieAuth and Micropub endpoints for Django applications.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   concepts
   tutorial
   api
   configuration
   development
   changelog
   modules

Features
--------

* IndieAuth authentication endpoint
* IndieAuth token endpoint
* Micropub endpoint for creating posts (stub implementation)
* Django integration

.. warning::
   The Micropub endpoint is currently a stub implementation. It accepts requests
   but does not actually create content. See the :doc:`tutorial` for how to extend it.

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

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
