===============
django-indieweb
===============

.. image:: https://img.shields.io/readthedocs/django-indieweb?style=for-the-badge
   :target: https://django-indieweb.readthedocs.io/en/latest/

.. image:: https://img.shields.io/pypi/v/django-indieweb.svg?style=for-the-badge
   :target: https://pypi.org/project/django-indieweb/

.. image:: https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white&style=for-the-badge
   :target: https://github.com/pre-commit/pre-commit
   :alt: pre-commit

A Django application that provides IndieAuth, Micropub, and Webmention endpoints for IndieWeb integration

Documentation
-------------

The full documentation is at https://django-indieweb.readthedocs.io/.

Features
--------

* IndieAuth authentication endpoint
* IndieAuth token endpoint
* Micropub endpoint with full content creation support
* Webmention sending and receiving
* Pluggable content handler system for Micropub
* Pluggable interfaces for Webmention URL resolution and spam checking
* Support for both form-encoded and JSON Micropub requests
* Microformats2 parsing for rich webmention content
* Micropub query endpoints (config, syndicate-to)
* Django integration

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

5. To use Micropub for content creation, create a custom content handler::

    from indieweb.handlers import MicropubContentHandler, MicropubEntry

    class MyContentHandler(MicropubContentHandler):
        def create_entry(self, properties, user):
            # Create your content here
            post = MyBlogPost.objects.create(
                author=user,
                content=properties.get('content', [''])[0]
            )
            return MicropubEntry(
                url=post.get_absolute_url(),
                properties=properties
            )
        # ... implement other methods

   Then configure it in settings::

    INDIEWEB_MICROPUB_HANDLER = 'myapp.handlers.MyContentHandler'

Development
-----------

Setting up development environment::

    git clone https://github.com/ephes/django-indieweb.git
    cd django-indieweb
    uv sync

Running Tests
~~~~~~~~~~~~~

Run the test suite::

    uv run pytest

Run tests with coverage::

    uv run pytest --cov=indieweb --cov-report=html
    open htmlcov/index.html

Run tests for all Python versions using tox::

    tox

Contributing
------------

Contributions are welcome! Please feel free to submit a Pull Request.

License
-------

BSD License
