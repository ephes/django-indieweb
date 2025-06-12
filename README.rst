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

A Django application that provides IndieAuth and Micropub endpoints for IndieWeb integration

Documentation
-------------

The full documentation is at https://django-indieweb.readthedocs.io/.

Features
--------

* IndieAuth authentication endpoint
* IndieAuth token endpoint
* Micropub endpoint for creating posts
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

4. Visit the IndieAuth endpoints at:

   * ``/indieweb/auth/`` - Authentication endpoint
   * ``/indieweb/token/`` - Token endpoint
   * ``/indieweb/micropub/`` - Micropub endpoint

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
