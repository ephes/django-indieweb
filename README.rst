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

A Django application that includes IndieAuth and a Micropub endpoint

Documentation
-------------

The full documentation is at https://django-indieweb.readthedocs.org.

Quickstart
----------

Install django-indieweb::

    pip install django-indieweb

Then use it in a project::

    import indieweb

Features
--------

* TODO

Running Tests
--------------

Does the code actually work?

::

    source <YOURVIRTUALENV>/bin/activate
    (myenv) $ pip install flit
    (myenv) $ flit install -s
    (myenv) $ pytest

Show coverage:

::

    $ coverage run -m pytest tests && coverage html && open htmlcov/index.html
