Development
===========

This section covers development workflows for django-indieweb.

Setting Up Development Environment
----------------------------------

Clone the repository and install dependencies using uv::

    git clone https://github.com/ephes/django-indieweb.git
    cd django-indieweb
    uv sync

This will create a virtual environment and install all dependencies including development tools.

Running Tests
-------------

Run the test suite using pytest::

    uv run pytest

The default pytest command measures coverage for the ``indieweb`` package and
enforces the configured coverage gate in ``pyproject.toml``.

New tests should use pytest function style with fixtures and plain ``assert``.
Use ``@pytest.mark.django_db`` or the ``db`` fixture for tests that need
database access. A few older ``django.test.TestCase`` files remain; do not mix
pytest parametrization into those classes. Convert them in focused maintenance
slices rather than during unrelated feature work.

To generate an HTML coverage report::

    uv run pytest --cov-report=html
    open htmlcov/index.html

Running Tox
-----------

Tox is used to test against multiple Python versions (3.10, 3.11, 3.12, 3.13).

To run tests for all Python versions::

    tox

To run tests for a specific Python version::

    tox -e py313

To run configured hooks::

    tox -e hooks

Continuous Integration
----------------------

GitHub Actions runs the tox matrix, mypy, Ruff lint and formatting checks,
configured prek hooks, and Sphinx with warnings treated as errors for pull
requests and pushes to ``develop``.

Code Quality
------------

The project uses Ruff for linting and formatting.

Format code::

    uv run ruff format .

Run linting checks::

    uv run ruff check .

Fix linting issues automatically::

    uv run ruff check --fix .

Run all configured hooks::

    uv run prek run --all-files

Type Checking
-------------

The project uses mypy for static type checking. Type annotations have been added to improve code quality and catch potential bugs early.

Run type checking::

    uv run mypy

To run mypy with more verbose output::

    uv run mypy --show-error-codes

To check a specific file::

    uv run mypy src/indieweb/views.py

The mypy configuration is defined in ``pyproject.toml`` and includes:

- Strict optional checking
- Disallowing untyped function definitions
- Django plugin for better Django support
- Type stubs for external libraries (django-stubs, types-requests)

Building Documentation
----------------------

To build and preview the documentation locally::

    just docs

For validation without opening a browser, run Sphinx directly with warnings
treated as errors::

    uv run sphinx-build -W -b html docs docs/_build/html

Project Backlog
---------------

Planned and completed work are described in :doc:`backlog`.

Building and Publishing Releases
--------------------------------

1. Update the version number in:

   - ``pyproject.toml``
   - ``src/indieweb/__init__.py``
   - ``docs/conf.py``

2. Update the changelog in ``docs/changelog.rst``

3. Build the package::

    uv build

   This will create distribution files in the ``dist/`` directory.

4. Upload to PyPI::

    uv publish --token your_token

   Replace ``your_token`` with your PyPI API token.

5. Create a git tag for the release::

    git tag -a v0.0.8 -m "Release version 0.0.8"
    git push origin v0.0.8

Development Commands Summary
----------------------------

.. code-block:: bash

    # Install development environment
    uv sync

    # Run tests with coverage and the configured coverage gate
    uv run pytest

    # Generate an HTML coverage report
    uv run pytest --cov-report=html

    # Run type checking
    uv run mypy

    # Run tox for all Python versions
    tox

    # Format code
    uv run ruff format .

    # Run linting
    uv run ruff check .

    # Run configured hooks
    uv run prek run --all-files

    # Build documentation
    uv run sphinx-build -W -b html docs docs/_build/html

    # Build package
    uv build

    # Publish to PyPI
    uv publish --token your_token
