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

Report bugs at https://github.com/ephes/django-indieweb/issues.

If you are reporting a bug, please include:

* Your operating system name and version.
* Any details about your local setup that might be helpful in troubleshooting.
* Detailed steps to reproduce the bug.

Fix Bugs
~~~~~~~~

Look through the GitHub issues for bugs. Anything tagged with "bug"
is open to whoever wants to implement it.

Implement Features
~~~~~~~~~~~~~~~~~~

Look through the GitHub issues for features. Anything tagged with "feature"
is open to whoever wants to implement it.

.. note::
   The Micropub endpoint is currently a stub implementation. A full implementation
   would be a valuable contribution!

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

    $ uv run pytest                    # Run tests
    $ uv run mypy                      # Type checking
    $ uv run ruff check .              # Linting
    $ uv run ruff format .             # Code formatting
    $ uv run pre-commit run --all-files  # All pre-commit checks

6. To test against multiple Python versions (3.10, 3.11, 3.12, 3.13), use tox::

    $ tox

7. Commit your changes and push your branch to GitHub::

    $ git add .
    $ git commit -m "Your detailed description of your changes."
    $ git push origin name-of-your-bugfix-or-feature

8. Submit a pull request through the GitHub website.

Pull Request Guidelines
-----------------------

Before you submit a pull request, check that it meets these guidelines:

1. The pull request should include tests using pytest style (not unittest.TestCase).
2. If the pull request adds functionality, the docs should be updated. Put
   your new functionality into a function with a docstring, and add the
   feature to the list in README.rst.
3. The pull request should work for Python 3.10, 3.11, 3.12, and 3.13. The
   GitHub Actions will run automatically to check this.
4. Add type annotations to new code. Run ``uv run mypy`` to check types.
5. Follow the existing code style. Run ``uv run ruff format .`` to format code.

Development Commands
--------------------

Here's a quick reference of development commands::

    # Install development environment
    uv sync

    # Run tests
    uv run pytest

    # Run specific test file
    uv run pytest tests/test_models.py

    # Run tests with coverage
    uv run pytest --cov=indieweb --cov-report=html

    # Type checking
    uv run mypy

    # Format code
    uv run ruff format .

    # Run linting
    uv run ruff check .

    # Fix linting issues
    uv run ruff check --fix .

    # Run all pre-commit hooks
    pre-commit run --all-files

    # Build documentation locally
    cd docs && uv run sphinx-build -b html . _build/html

    # Run tox for all Python versions
    tox

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

To run the Django development server with the example project::

    $ cd example_project
    $ python manage.py runserver

You can then test the endpoints at http://localhost:8000/indieweb/
