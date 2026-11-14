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

Standalone sanitizer security and content-preservation contracts use a fixed
synthetic HTML corpus, parsed as HTML5 fragments. Run them directly with::

    uv run pytest tests/test_sanitizers.py --no-cov

Parse Worker Protocol and Watchdog Tests
----------------------------------------

The settings-free parse child accepts one JSON object per invocation. The
internal ``source`` request requires exactly ``operation="source"``, ``html``,
``base_url`` and ``target_url``; ``vouch`` requires exactly
``operation="vouch"``, ``html`` and ``source_url``. Every document/URL field
must be a string (empty strings are allowed); missing, extra or non-string
fields and unsupported operations fail before analysis. Invalid request
errors report only the exception type, without echoing request data.

Run the focused protocol and RSS watchdog contracts with::

    uv run pytest tests/test_parse_worker_protocol.py tests/test_memory_watchdog.py --no-cov

The protocol suite fakes resource-limit setup and exercises ``main`` with
synthetic JSON. The watchdog suite drives the actual loop with fake RSS,
thread startup, sleep and exit boundaries, including below/equal/above-limit
samples. It never starts a real watchdog thread, sleeps, exhausts memory,
changes OS limits or exits the test process. The existing isolation suite
continues to exercise real child processes.

Running Tox
-----------

Tox is used to test the supported Python and Django version matrix:

- Django 5.2 LTS on Python 3.11, 3.12, 3.13, and 3.14
- Django 6.0 on Python 3.12, 3.13, and 3.14
- Django 6.1 on Python 3.12, 3.13, and 3.14

The runtime dependency is pinned to Django ``>=5.2.13,<6.2`` so supported
stable Django series are explicit. Django 4.2 is no longer included because its
extended support has ended.

To run tests for the full supported matrix::

    tox

The full matrix requires the corresponding Python interpreters to be available
locally. The default tox run also includes the required ``storage-sqlite`` lane
and the existing migrations lane. Run all checks locally before integration.

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

State-transition regressions also run in CI against a disposable PostgreSQL 17
service on branch pushes and pull requests. The service contains only synthetic
rows. To run the same tests against your disposable local PostgreSQL instance::

    DJANGO_SETTINGS_MODULE=tests.settings_postgres uv run pytest --migrations --no-cov tests/test_outbound_state.py

The test settings use database ``indieweb_synthetic``, user/password ``synthetic``
and localhost port 5432 (override ``INDIEWEB_TEST_POSTGRES_PORT`` if needed).
Never point these settings at a database containing real data.

For overlapping SQLite connections use a disposable file-backed test database
(shared-cache in-memory tables do not wait for concurrent locks)::

    DJANGO_INDIEWEB_TEST_SQLITE_PATH=/tmp/indieweb-synthetic.sqlite3 uv run pytest --migrations --no-cov tests/test_outbound_state.py

Nested-response batches and routed WebSub diagnostics also run with migrations
on the synthetic PostgreSQL CI service, including an isolated second database::

    DJANGO_SETTINGS_MODULE=tests.settings_postgres uv run pytest --migrations --no-cov tests/test_nested_response_queries.py tests/test_delivery_diagnostic_atomicity.py

Webmention count and display regressions run on both SQLite and the disposable
PostgreSQL service. Count tests temporarily apply case/accent/space-insensitive
collations to real columns and restore them after each test (PostgreSQL requires
ICU support, provided by the CI image)::

    DJANGO_SETTINGS_MODULE=tests.settings_postgres uv run pytest --migrations --no-cov tests/test_webmention_count_collations.py tests/test_webmention_display_queries.py

Authorization contention tests
------------------------------

``tests/test_auth_contention.py`` complements deterministic stale-code rejection checks
with committed requests on independent connections. It covers token/token and
auth/token redemption of a scoped code, plus consent/exchange in both write
orders. Events pause a completed DELETE until the competing request reaches its
DELETE call; they do not assert scheduler-level lock-wait overlap. Every worker
result or exception is collected and connections are closed. PostgreSQL statement/lock timeouts and
bounded event waits prevent a deadlock from hanging the suite. Expiry cases
hold an independent writer across the consumption DELETE, then advance a
controlled clock to ages 59, 60 and 61 seconds before releasing it. Both
redemption endpoints must reject the expired code without changing an existing
token. Owner cases commit disablement after lookup on a separate connection.
``tests/test_auth_owner_eligibility.py`` also exercises stale related-object
caches and deletion; ``tests/test_auth_lifetime_settings.py`` checks strict
configuration admission and system checks. Routed issuance rollback and
replica-read fixtures live in ``tests/test_token_issuance_atomicity.py``.

Use a fresh temporary directory for file-backed SQLite::

    storage_dir=$(mktemp -d)
    DJANGO_INDIEWEB_TEST_SQLITE_PATH="$storage_dir/test.sqlite3" uv run pytest --migrations --no-cov tests/test_auth_contention.py

Run the same cases against a disposable synthetic PostgreSQL database::

    DJANGO_SETTINGS_MODULE=tests.settings_postgres uv run pytest --migrations --no-cov tests/test_auth_contention.py

The normal in-memory SQLite suite skips these cases because shared-cache
locking cannot reproduce the supported file-backed behavior. The regression
oracles reject a removed consume gate (two successful redemptions) and an owner
row lock before consent DELETE (PostgreSQL consent/exchange deadlock).

Required local storage lanes
----------------------------

The fast default pytest run uses in-memory SQLite and skips six real contention
cases plus two receive recovery journeys that require connection reopen. A local validation is complete only after the migration and storage
lanes also pass::

    uv run tox -e py313-django52-migrations,storage-sqlite
    INDIEWEB_TEST_POSTGRES_PORT=5432 uv run tox -e storage-postgres

``storage-sqlite`` owns a database under tox's temporary directory and recreates
it with ``--create-db`` on every run. Both storage lanes enable real migrations
and set ``DJANGO_INDIEWEB_REQUIRE_STORAGE_TESTS=1``: selecting an in-memory SQLite
database is a failure, never a successful skip. The PostgreSQL lane is opt-in
and uses only the disposable synthetic instance described above. No workflow
or hosted matrix jobs are added; these are required local checks.

Both lanes run authorization contention, outgoing-history concurrent writers,
fresh/reissued token persistence rollback, and receive persistence recovery
(``tests/test_receive_persistence_recovery.py``). Receive recovery injects real
constraint failures after snapshot/child writes, reopens the connection and
retries, checking exact rollback and eventual reconciliation. The rollback tests inject a
failure after a real token INSERT/UPDATE and after code deletion; code, bearer
hash, expiry and modification time must roll back together. A healthy retry
then succeeds once. Moving issuance outside the atomic block fails both tests.
A broken migration must fail the migration-enabled lane during database setup.

WebSub admission and display snapshots
--------------------------------------

The required ``storage-sqlite`` and ``storage-postgres`` lanes also run
``tests/test_websub_delivery_admission.py`` and
``tests/test_webmention_display_snapshot.py`` with real migrations. Delivery tests
commit secret rotation or unsubscribe confirmation on a second connection after
the first lookup, prove the current-authority reload, and hold signature
validation while a competing writer attempts to change authority. Host dispatch
must observe a committed acceptance, including with ``ATOMIC_REQUESTS`` enabled.
Lease tests cover immediately before, exactly at and after expiry, plus denied
and confirmed renewals and legacy unknown expiry.

The display oracle commits moderation on a second connection after the first
SELECT starts. It permits only a complete old or new parent/child/direct-source
generation, with one query for both filtered and unfiltered renders and for 1 or
20 children. File SQLite uses WAL in this test to allow that concurrent commit;
PostgreSQL uses its statement snapshot. Both use invented URLs and credentials.
Run these lanes against a disposable local database only; no hosted CI is needed.
