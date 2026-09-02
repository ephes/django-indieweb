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
enforces the configured coverage gate in ``pyproject.toml``. It uses
``--no-migrations`` for fast iteration.

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

Tox is used to test the supported Python and Django version matrix:

- Django 5.2 LTS on Python 3.10, 3.11, 3.12, 3.13, and 3.14
- Django 6.0 on Python 3.12, 3.13, and 3.14
- Django 6.1 on Python 3.12, 3.13, and 3.14

The runtime dependency is pinned to Django ``>=5.2.13,<6.2`` so supported
stable Django series are explicit. Django 4.2 is no longer included because its
extended support has ended.

To run tests for the full supported matrix::

    tox

The full matrix requires the corresponding Python interpreters to be available
locally. GitHub Actions provides them in CI.

To run tests for a specific Python/Django combination::

    tox -e py313-django60

To run the suite once with Django migrations enabled::

    tox -e py313-django52-migrations

To run configured hooks::

    tox -e hooks

Continuous Integration
----------------------

GitHub Actions runs every tox Python/Django matrix environment, mypy, Ruff lint
and formatting checks, configured prek hooks, and Sphinx with warnings treated
as errors for pull requests and pushes to ``develop``.

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

Line Counts
-----------

To print repository line-count summaries by language, area, and directory::

    just loc

During the ``slopscope`` pre-release phase, the ``just loc`` recipe installs
``slopscope`` from PyPI with ``uv run --prerelease allow`` and explicit
``rich`` support. Override ``SLOPSCOPE_SPEC`` with a local path when developing
``slopscope`` from a sibling checkout. ``slopscope`` uses ``cloc`` when it is
available and otherwise falls back to its Python physical-line counter.

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

Read the Docs installs both ``docs/requirements.txt`` and the project itself
from ``.readthedocs.yml``. Installing the project keeps the hosted build's
runtime dependencies aligned with ``pyproject.toml`` when documentation setup
imports the Django application.

Project Backlog
---------------

Planned and completed work are described in :doc:`backlog`.

Building and Publishing Releases
--------------------------------

1. Update the version number in:

   - ``pyproject.toml``
   - ``src/indieweb/__init__.py``
   - ``docs/conf.py``

2. Update the changelog in ``docs/changelog.rst``:

   - Move the prior ``Unreleased`` entries under a new
     ``X.Y.Z (YYYY-MM-DD)`` heading.
   - Leave a fresh ``Unreleased`` section above the new release entry.
   - Add a note when the published package version skips over a
     repository-local version that was never published to PyPI.

3. Run the release validation gates::

    uv run pytest
    uv run mypy
    uv run prek run --all-files
    uv run sphinx-build -W -b html docs docs/_build/html
    tox -p auto

4. Clean old package artifacts and build the package::

    just clean-build
    uv build

   This will create distribution files in the ``dist/`` directory.

5. Validate the built wheel and source distribution metadata::

    uvx twine check dist/django_indieweb-*.whl dist/django_indieweb-*.tar.gz

6. Generate a CycloneDX SBOM from the locked runtime dependency graph::

    just sbom

   ``uv.lock`` is tracked for reproducible release dependency review, and the
   SBOM is written to ``dist/django-indieweb-sbom.cdx.json``.

7. Upload to PyPI::

    uv publish --token your_token

   Replace ``your_token`` with your PyPI API token.

8. Create a git tag for the release. Current tags use plain version numbers::

    git tag -a 0.6.0 -m "Release version 0.6.0"
    git push origin 0.6.0

9. Create the GitHub release and attach the validated artifacts::

    gh release create 0.6.0 \
      dist/django_indieweb-0.6.0-py3-none-any.whl \
      dist/django_indieweb-0.6.0.tar.gz \
      dist/django-indieweb-sbom.cdx.json \
      --title "0.6.0" --generate-notes

Publishing packages, pushing refs, and creating GitHub releases require
explicit, in-conversation maintainer approval for the exact action and target.
Agents may perform those operations once approved; otherwise they stop after
validation and artifact generation and report the remaining commands.

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

    # Run tox for the supported Python/Django matrix
    tox

    # Run tests with Django migrations enabled
    tox -e py313-django52-migrations

    # Format code
    uv run ruff format .

    # Run linting
    uv run ruff check .

    # Run configured hooks
    uv run prek run --all-files

    # Count repository lines by language, area, and directory
    just loc

    # Build documentation
    uv run sphinx-build -W -b html docs docs/_build/html

    # Build package
    uv build

    # Generate release SBOM
    just sbom

    # Publish to PyPI
    uv publish --token your_token
