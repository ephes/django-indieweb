============
Contributing
============

Contributions are welcome, and they are greatly appreciated! Every
little bit helps, and credit will always be given.

You can contribute in many ways:

Types of Contributions
----------------------

Report Bugs
~~~~~~~~~~~

Report bugs at https://github.com/ephes/django-indieweb/issues. Planned work is
tracked in ``BACKLOG.md`` in the repository root.

If you are reporting a bug, please include:

* Your operating system name and version.
* Any details about your local setup that might be helpful in troubleshooting.
* Detailed steps to reproduce the bug.

Fix Bugs
~~~~~~~~

Look through ``BACKLOG.md`` for planned bugfix work. If you fix an unlisted
bug, add enough context to the pull request for the fix to be reviewed and
record any remaining follow-up work in ``BACKLOG.md``.

Implement Features
~~~~~~~~~~~~~~~~~~

Look through ``BACKLOG.md`` for planned feature work. Keep the item current
while you work and move completed items to ``DONE.md`` with validation,
documentation, and changelog notes.
Micropub ships with an in-memory handler; contributions adding richer handlers,
multipart create-upload handling, or additional post types are welcome.

Write Documentation
~~~~~~~~~~~~~~~~~~~

django-indieweb could always use more documentation, whether as part of the
official django-indieweb docs, in docstrings, or even on the web in blog posts,
articles, and such.

Submit Feedback
~~~~~~~~~~~~~~~

The best way to send feedback is to file an issue at https://github.com/ephes/django-indieweb/issues.

If you are proposing a feature:

* Explain in detail how it would work.
* Keep the scope as narrow as possible, to make it easier to implement.
* Remember that this is a volunteer-driven project, and that contributions
  are welcome :)

Get Started!
------------

Ready to contribute? Here's how to set up ``django-indieweb`` for local development.

1. Fork the ``django-indieweb`` repo on GitHub.

2. Clone your fork locally::

    $ git clone git@github.com:your_name_here/django-indieweb.git

3. Install your local copy using uv. This is how you set up your fork for local development::

    $ cd django-indieweb/
    $ uv sync

   This will create a virtual environment and install all dependencies including development tools.

4. Create a branch for local development::

    $ git checkout -b name-of-your-bugfix-or-feature

   Now you can make your changes locally.

5. When you're done making changes, check that your changes pass the tests and quality checks::

    $ uv run pytest                    # Run tests with coverage gate
    $ uv run mypy                      # Type checking
    $ uv run ruff check .              # Linting
    $ uv run ruff format .             # Code formatting
    $ uv run prek run --all-files      # All configured hooks
    $ uv run sphinx-build -W -b html docs docs/_build/html

6. To test against the supported Python and Django version matrix, use tox::

    $ tox

7. To run the suite once with Django migrations enabled, use the dedicated tox environment::

    $ tox -e py313-django52-migrations

8. Commit your changes and push your branch to GitHub::

    $ git add .
    $ git commit -m "Your detailed description of your changes."
    $ git push origin name-of-your-bugfix-or-feature

9. Submit a pull request through the GitHub website.

Pull Request Guidelines
-----------------------

Before you submit a pull request, check that it meets these guidelines:

1. The pull request should include tests using pytest style (not unittest.TestCase).
2. If the pull request adds functionality, the docs should be updated. Put
   your new functionality into a function with a docstring, and add the
   feature to the list in README.rst.
3. The pull request should work for Django 5.2 LTS on Python 3.10, 3.11, 3.12,
   3.13, and 3.14, and Django 6.0 on Python 3.12, 3.13, and 3.14. Run ``tox``
   locally for the supported matrix when you have the matching Python
   interpreters installed.
4. Add type annotations to new code. Run ``uv run mypy`` to check types.
5. Follow the existing code style. Run ``uv run ruff format .`` to format code.

GitHub Actions reruns the supported Python/Django tox matrix, mypy, Ruff lint
and formatting checks, configured prek hooks, and Sphinx with warnings treated
as errors for pull requests and pushes to ``develop``.

Development Commands
--------------------

Here's a quick reference of development commands::

    # Install development environment
    uv sync

    # Run tests with coverage gate
    uv run pytest

    # Run specific test file
    uv run pytest tests/test_models.py

    # Generate an HTML coverage report
    uv run pytest --cov-report=html

    # Type checking
    uv run mypy

    # Format code
    uv run ruff format .

    # Run linting
    uv run ruff check .

    # Fix linting issues
    uv run ruff check --fix .

    # Run all configured hooks
    uv run prek run --all-files

    # Build and preview documentation locally
    just docs

    # Validate documentation without opening a browser
    uv run sphinx-build -W -b html docs docs/_build/html

    # Run tox for the supported Python/Django matrix
    tox

    # Run tests with Django migrations enabled
    tox -e py313-django52-migrations

Tips
----

Code Style
~~~~~~~~~~

* We use Ruff for both linting and formatting (replacing Black, isort, and flake8)
* Line length is 119 characters
* Use type annotations for function parameters and return values
* Write docstrings for all classes and public functions

Testing
~~~~~~~

* Write tests using pytest style (functions with fixtures, not TestCase classes)
* Use ``@pytest.mark.django_db`` for tests that need database access
* Do not mix ``pytest.mark.parametrize`` into existing ``django.test.TestCase`` classes
* Convert legacy ``TestCase`` files in focused maintenance slices, not during unrelated feature work
* The default ``uv run pytest`` command measures package coverage and enforces the ``pyproject.toml`` coverage gate
* Aim for high test coverage but focus on testing behavior, not implementation
* Test files go in the ``tests/`` directory

Type Annotations
~~~~~~~~~~~~~~~~

* Add type annotations to all new code
* Use ``from __future__ import annotations`` for better forward compatibility
* Run ``uv run mypy`` to check for type errors
* Use ``TYPE_CHECKING`` for imports only needed for type checking

Documentation
~~~~~~~~~~~~~

* Update documentation for any new features
* Use reStructuredText (.rst) format for documentation
* Include code examples where appropriate
* Add docstrings to all public functions and classes

Database Migrations
~~~~~~~~~~~~~~~~~~~

If you change models::

    $ python manage.py makemigrations
    $ python manage.py migrate

Make sure to commit any migration files created.

Debugging
~~~~~~~~~

To run the Django development server with the example project script
(local smoke-testing only — see the warning at the top of the file)::

    $ python example_project.py runserver

The script refuses to start without ``DJANGO_SECRET_KEY`` unless
``ALLOW_UNSAFE_DEV_SECRET=1`` is set, never auto-creates a superuser
(use ``python example_project.py createsuperuser`` to make one), and
binds to ``localhost``/``127.0.0.1`` by default.

You can then test the endpoints at http://localhost:8000/indieweb/
