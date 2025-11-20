# Repository Guidelines

## Project Structure & Module Organization
- `src/indieweb/`: Django app with IndieAuth, Micropub, and Webmention logic plus `management/`, `templatetags/`, `templates/`, and `static/`.
- `tests/`: Pytest suite using `tests.settings` (set via `DJANGO_SETTINGS_MODULE`); mirrors app modules and holds fixtures.
- `docs/`: Sphinx documentation (`make docs` builds HTML).
- `examples/`, `example_project.py`, `client.py`: Reference integrations and smoke-test helpers.

## Build, Test, and Development Commands
- Install deps: `uv sync` (or `just install`).
- Run tests: `uv run pytest` (or `just test`); target specific tests with `uv run pytest tests/test_file.py::TestClass::test_case -v`.
- Type checks: `uv run mypy` (or `just typecheck`).
- Lint/format: `uv run ruff check .` and `uv run ruff format .` (line length 119, double quotes).
- Full matrix or pre-commit hooks: `tox` or `tox -e pre-commit`.
- Docs preview: `make docs` to rebuild Sphinx and open HTML locally.

## Coding Style & Naming Conventions
- Python 3.10+ with 4-space indentation; prefer explicit typing—public functions and classes should be type-annotated.
- Imports and formatting follow Ruff (`E,W,F,I,B,UP,DJ`); avoid unused symbols and dead code.
- Modules/files use `snake_case`, classes `PascalCase`, functions/methods `snake_case`, Django settings/constants `UPPER_SNAKE_CASE`.
- Keep Django app boundaries clean: views/handlers in `indieweb`, templates in `templates/indieweb/`, static assets under `static/indieweb/`.

## Testing Guidelines
- New behaviors need Pytest coverage under `tests/` with `test_*.py`; mirror module paths for discoverability.
- Tests run with coverage (`--cov-config=pyproject.toml`) and reuse the DB; reset or mark transactional tests if you change schema.
- For regression proofs, add focused tests near the bug; prefer fixtures over inline setup to avoid duplication.
- Use `pytest -k "keyword"` or `just test-one path::node` for fast iteration.

## Commit & Pull Request Guidelines
- Commit messages: short, imperative subjects (e.g., “Add Micropub handler validation”, “Document justfile workflows”); keep each commit scoped.
- Before opening a PR, run `uv run pytest`, `uv run mypy`, and `uv run ruff check .`; include notable outputs in the PR description.
- PRs should describe the change, user impact, and testing done; link related issues. Attach screenshots or API samples when altering user-facing behavior or responses.
- Update docs or examples when adding endpoints, handlers, or settings toggles; mention migration implications explicitly.

## Security & Configuration Tips
- Never commit secrets or tokens; rely on environment variables for client IDs, tokens, and target URLs.
- When adding new endpoints or handlers, validate input early and keep external HTTP calls behind clear, typed interfaces (see `indieweb` client patterns).
- Migrations live under `indieweb/migrations/`; run and check them in tests if schema changes occur.
