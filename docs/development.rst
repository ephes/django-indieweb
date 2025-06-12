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

To run tests with coverage::

    uv run pytest --cov=indieweb --cov-report=html
    open htmlcov/index.html

Running Tox
-----------

Tox is used to test against multiple Python versions (3.10, 3.11, 3.12, 3.13).

To run tests for all Python versions::

    tox

To run tests for a specific Python version::

    tox -e py313

To run pre-commit checks::

    tox -e pre-commit

Code Quality
------------

The project uses Ruff for linting and formatting.

Format code::

    uv run ruff format .

Run linting checks::

    uv run ruff check .

Fix linting issues automatically::

    uv run ruff check --fix .

Run all pre-commit hooks::

    pre-commit run --all-files

Building Documentation
----------------------

To build the documentation locally::

    cd docs
    make html
    open _build/html/index.html

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

   You can also set the token as an environment variable::

    export UV_PUBLISH_TOKEN=your_token
    uv publish

5. Create a git tag for the release::

    git tag -a v0.0.8 -m "Release version 0.0.8"
    git push origin v0.0.8

Development Commands Summary
----------------------------

.. code-block:: bash

    # Install development environment
    uv sync

    # Run tests
    uv run pytest

    # Run tests with coverage
    uv run pytest --cov=indieweb

    # Run tox for all Python versions
    tox

    # Format code
    uv run ruff format .

    # Run linting
    uv run ruff check .

    # Build package
    uv build

    # Publish to PyPI
    uv publish --token your_token
