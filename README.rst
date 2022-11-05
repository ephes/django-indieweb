=============================
django-indieweb
=============================

.. image:: https://badge.fury.io/py/django-indieweb.png
    :target: https://badge.fury.io/py/django-indieweb

.. image:: https://travis-ci.org/ephes/django-indieweb.png?branch=master
    :target: https://travis-ci.org/ephes/django-indieweb

includes indieauth and a micropub endpoint

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
