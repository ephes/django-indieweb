===============
django-indieweb
===============

.. image:: https://img.shields.io/readthedocs/django-indieweb?style=for-the-badge
   :target: https://django-indieweb.readthedocs.io/en/latest/

.. image:: https://img.shields.io/pypi/v/django-indieweb.svg?style=for-the-badge
   :target: https://pypi.org/project/django-indieweb/

.. image:: https://img.shields.io/badge/prek-enabled-brightgreen?style=for-the-badge
   :target: https://github.com/j178/prek
   :alt: prek

A Django application that provides IndieAuth, Micropub, Webmention, and WebSub support for IndieWeb integration

Documentation
-------------

The full documentation is at https://django-indieweb.readthedocs.io/.

Features
--------

* IndieAuth authentication endpoint
* IndieAuth token endpoint
* Micropub endpoint with content creation, source query, update, delete, undelete, and media upload support
* Webmention sending and receiving
* WebSub publisher helpers for topic discovery links and hub notifications
* Minimal WebSub subscriber callback support with lease tracking and delivery hooks
* Pluggable content handler system for Micropub
* Pluggable interfaces for Webmention URL resolution and spam checking
* Support for both form-encoded and JSON Micropub requests
* Microformats2 parsing for rich webmention content
* Micropub query endpoints (config with media-endpoint discovery, syndicate-to, source)
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
   * ``/indieweb/media/`` - Micropub media endpoint
   * ``/indieweb/webmention/`` - Webmention endpoint

5. To use Micropub for content creation and editing, create a custom content handler::

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

Adapter Responsibilities
~~~~~~~~~~~~~~~~~~~~~~~~

Micropub handlers are host-owned authorization boundaries. After
django-indieweb authenticates the bearer token and checks the requested scope,
your ``MicropubContentHandler`` must verify that the authenticated ``user`` is
allowed to create, update, delete, undelete, read source content, list content
or media, and manage media for the submitted URL or storage object. The bundled
``InMemoryMicropubHandler`` is an unsafe development/testing example only; it
keeps entries in process memory and performs no ownership checks.

Development
-----------

Setting up development environment::

    git clone https://github.com/ephes/django-indieweb.git
    cd django-indieweb
    uv sync

Handy Just commands (install `just` first) ::

    just install      # sync dependencies via uv
    just test         # run the pytest suite
    just typecheck    # run mypy
    just test-one path/to/test.py::TestCase::test_method

Running Tests
~~~~~~~~~~~~~

Run the test suite with coverage and the configured coverage gate::

    uv run pytest

Generate an HTML coverage report::

    uv run pytest --cov-report=html
    open htmlcov/index.html

Run tests for the supported Python/Django matrix using tox::

    tox

The supported tox matrix covers Django 5.2 LTS on Python 3.10 through 3.14 and
Django 6.0 on Python 3.12 through 3.14.

Contributing
------------

Contributions are welcome! Please feel free to submit a Pull Request.

License
-------

BSD License
