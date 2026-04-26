# Repository Guidelines

## Project Structure & Module Organization
- `src/indieweb/`: Django app with IndieAuth, Micropub, and Webmention logic plus `management/`, `templatetags/`, `templates/`, and `static/`.
- `tests/`: Pytest suite using `tests.settings` (set via `DJANGO_SETTINGS_MODULE`); mirrors app modules and holds fixtures.
- `docs/`: Sphinx documentation (`just docs` builds HTML).
- `examples/`, `example_project.py`, `client.py`: Reference integrations and smoke-test helpers.

## Build, Test, and Development Commands
- Install deps: `uv sync` (or `just install`).
- Run tests: `uv run pytest` (or `just test`); target specific tests with `uv run pytest tests/test_file.py::TestClass::test_case -v`.
- Type checks: `uv run mypy` (or `just typecheck`).
- Lint/format: `uv run ruff check .` and `uv run ruff format .` (line length 119, double quotes).
- Full matrix or configured hooks: `tox` or `tox -e hooks`.
- Docs preview: `just docs` to rebuild Sphinx and open HTML locally.

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

## Backlog Workflow
- This project no longer uses Beads. Track planned work in `BACKLOG.md` and move completed items to `DONE.md`.
- Before starting a backlog item, read the full item and any referenced files, docs, specs, or upstream issues.
- When completing a backlog item, remove it from `BACKLOG.md` and add an entry to `DONE.md` with the completion date, summary, validation, documentation note, and changelog note.
- Update `docs/changelog.rst` when a completed item changes behavior, fixes a bug, adds a feature, changes configuration, or affects users.
- Update project documentation when implementation behavior, configuration, public APIs, workflows, examples, or user-facing usage changes.
- Work is not complete until code, tests, documentation, and changelog entries are consistent. If docs or changelog updates are not needed, say so in the `DONE.md` entry.

## Commit & Pull Request Guidelines
- Commit messages: short, imperative subjects (e.g., “Add Micropub handler validation”, “Document justfile workflows”); keep each commit scoped.
- Before opening a PR, run `uv run pytest`, `uv run mypy`, and `uv run ruff check .`; include notable outputs in the PR description.
- PRs should describe the change, user impact, and testing done; link related issues. Attach screenshots or API samples when altering user-facing behavior or responses.
- Update docs or examples when adding endpoints, handlers, or settings toggles; mention migration implications explicitly.

## Security & Configuration Tips
- Never commit secrets or tokens; rely on environment variables for client IDs, tokens, and target URLs.
- When adding new endpoints or handlers, validate input early and keep external HTTP calls behind clear, typed interfaces (see `indieweb` client patterns).
- Migrations live under `indieweb/migrations/`; run and check them in tests if schema changes occur.

## Landing the Plane (Session Completion)

**When ending a work session**, complete the steps below and stop at the staging boundary. The agent does not commit or push on its own.

**Workflow:**

1. **Record remaining work** - Add follow-up items to `BACKLOG.md`.
2. **Run quality gates** (if code changed) - Tests, linters, builds. Report results.
3. **Update backlog status** - Move completed items from `BACKLOG.md` to `DONE.md`; update docs and changelog when needed.
4. **Summarize for the user** - Report what changed, the validation results, and any open questions. Wait.
5. **Wait for explicit commit approval** - The user reviews the working-tree changes and asks for a commit. Approval is per-commit, not standing.
6. **Hand off** - Provide context for the next session.

**Critical rules:**
- **Pushing is a manual user action.** The agent never runs `git push`, `git push --force`, `gh pr create`, or any other command that publishes work to a remote. Not at session end, not when CI is green, not when a plan or backlog item says "push at the end". If a push seems needed, say so and stop.
- **Committing requires explicit, in-conversation approval.** Do not run `git commit` on your own, even when all gates pass. "Approved once" is not "approved forever".
- It is correct to end a session with local commits the user has not yet pushed; that is the user's job. Never try to "finish" a session by pushing.
- If a commit happens prematurely, surface it immediately and ask whether to amend, revert, or leave it. Do not push to "fix" it.
