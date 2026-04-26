# Done

Completed backlog items move here from `BACKLOG.md`. Keep entries concise, but include validation and documentation/changelog notes so future contributors can understand what changed.

## 2026-04-26

### Add Token Expiration Handling and Fix Auth-Code Timeout Calculation

- Added `Token.expires_at` (`DateTimeField(null=True, blank=True, db_index=True)`) plus migration `0010_token_expires_at` and a `Token.is_expired()` helper.
- Added the `INDIEWEB_TOKEN_EXPIRES_IN` setting (default 86400 seconds) and updated `TokenView.send_token()` to persist `expires_at` on create and reissue and to report the live remaining lifetime in `expires_in` instead of the previous hardcoded `10`.
- Updated `TokenAuthMixin.authenticated()` to reject tokens whose `expires_at` is in the past with HTTP 401. Legacy tokens with `expires_at=NULL` remain accepted for backwards compatibility until they are reissued.
- Replaced `(now - auth.created).seconds` with `total_seconds()` in `TokenView.post()` so auth codes older than one day are correctly rejected.
- Added regression tests covering: token response advertising the configured lifetime, persisted `expires_at`, reissue refresh, expired-token rejection on the Micropub endpoint, legacy null-expiry acceptance, and multi-day-old auth-code rejection.
- Documentation: updated `docs/api.rst`, `docs/configuration.rst`, and `docs/indieauth.rst` for the new setting and 24-hour default lifetime.
- Changelog: updated `docs/changelog.rst`.
- Validation: `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, and `git diff --check` all passed.

### Triage and Resolve Open Dependabot Alerts

- Raised the runtime Django dependency floor to `Django>=5.2.13,<6.0`.
- Raised direct development dependency floors for `pytest>=9.0.3` and `requests>=2.33.0`.
- Refreshed `uv.lock` so vulnerable locked packages resolve to patched versions: Django `5.2.13`, pytest `9.0.3`, requests `2.33.1`, urllib3 `2.6.3`, sqlparse `0.5.5`, Pygments `2.20.0`, filelock `3.29.0`, and virtualenv `21.2.4`.
- Updated `TokenView.send_token()` to query by `owner_id` for compatibility with newer `django-stubs` while keeping the public type generic for custom user models.
- Documentation: no usage docs changed; dependency/security status is recorded in the changelog.
- Changelog: updated `docs/changelog.rst`.
- Validation: `uv sync`, `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, and `git diff --check` passed.
- Dependabot verification: the GitHub API reports 0 open Dependabot alerts after GitHub rescanned the pushed `uv.lock`.

### Verify Micropub Create Flow End to End

- Confirmed Micropub create handles form-encoded and JSON bodies and returns `201 Created` with an absolute `Location` header.
- Coverage: `tests/test_micropub_create.py` and `tests/test_micropub_endpoint.py`.
- Implementation reference: `src/indieweb/views.py`, `src/indieweb/handlers.py`.
- Documentation: no changes needed; `docs/micropub.rst` already matches the current create behavior.
- Changelog: no entry needed; verification only, no behavior change.
- Validation: `uv run pytest tests/test_micropub_create.py tests/test_token_endpoint.py tests/test_auth_endpoint.py` and `uv run pytest tests/test_h_card.py tests/test_h_card_extra_classes.py tests/test_h_card_integration.py tests/test_h_card_templatetags.py --cov=indieweb.h_card --cov-report=term-missing` passed during the backlog audit.

### Add Backlog Page to Documentation Navigation

- Added `docs/backlog.rst` as a dedicated documentation page for the Markdown backlog workflow.
- Added the Backlog page to the Sphinx sidebar navigation.
- Documentation: updated `docs/index.rst` and `docs/development.rst`.
- Changelog: updated `docs/changelog.rst`.
- Validation: `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv run pytest`, and `git diff --check` all passed.

### Switch Hook Runner to prek and Fix pyupgrade on Python 3.14

- Upgraded hook revisions, including `pyupgrade` from `v3.21.0` to `v3.21.2`, which fixes the observed Python 3.14 crash.
- Replaced the development dependency `pre-commit` with `prek`.
- Updated tox, contributor docs, agent instructions, and README references to use `prek`.
- Added `specs/2026-04-26_pyupgrade_issue.md` with the investigation notes and reproduction commands.
- Documentation: updated `README.rst`, `CONTRIBUTING.rst`, `docs/development.rst`, `AGENTS.md`, and `CLAUDE.md`.
- Changelog: updated `docs/changelog.rst`.
- Validation: `uv run prek run --all-files`, `uv run tox -e hooks`, `uv run tox -e pre-commit`, `uvx --python 3.14 prek run pyupgrade --all-files`, `uv run ruff check .`, `uv run mypy`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run pytest`, `uv build`, and `git diff --check` all passed.

### Replace Beads with Markdown Backlog Workflow

- Removed Beads and Beadsflow as the project work-tracking system.
- Added `BACKLOG.md` for planned work and `DONE.md` for completed work.
- Linked the backlog from the project documentation.
- Updated agent instructions to use the Markdown workflow and to keep docs/changelog entries aligned with completed work.
- Documentation: updated `docs/development.rst` and `docs/index.rst`.
- Changelog: updated `docs/changelog.rst`.
- Validation: `uv run ruff check .`, `uv run mypy`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run pytest`, `uv build`, `git diff --check`, and `uv run --python 3.13 pre-commit run --all-files` all passed.
