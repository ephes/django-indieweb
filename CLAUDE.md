# Django IndieWeb Project

This is a Django application that implements IndieWeb protocols including IndieAuth and Micropub endpoints.

## Project Structure & Module Organization

- `src/indieweb/` - Django app with IndieAuth, Micropub, and Webmention logic
  - `models.py` - Django models
  - `views.py` - IndieAuth and Micropub endpoint views
  - `urls.py` - URL routing
  - `migrations/` - Database migrations
  - `management/` - Django management commands
  - `templatetags/` - Custom template tags
  - `templates/` - HTML templates
  - `static/` - Static assets

- `tests/` - Pytest suite using `tests.settings` (set via `DJANGO_SETTINGS_MODULE`)
  - Mirrors app modules and holds fixtures
  - `test_auth_endpoint.py` - IndieAuth tests
  - `test_micropub_endpoint.py` - Micropub tests
  - `test_token_endpoint.py` - Token endpoint tests
  - `test_models.py` - Model tests

- `docs/` - Sphinx documentation (`just docs` builds HTML)
- `examples/`, `example_project.py`, `client.py` - Reference integrations and smoke-test helpers
- `BACKLOG.md` - Planned work items, grouped by priority. The single source of truth for upcoming work; this project no longer uses Beads or any external issue tracker.
- `DONE.md` - Completed backlog items, append-only, grouped by date. Each entry records the completion date, summary, validation commands, documentation note, and changelog note.
- `AGENTS.md` - Repository guidelines for any agent or contributor; keep in sync with this file.

## Development Setup

This project uses:
- Python 3.10+ (supports 3.10, 3.11, 3.12, 3.13, 3.14)
- Django
- uv for packaging and dependency management
- Ruff for linting and formatting (line length: 119)
- prek hooks for code quality

## Build, Test, and Development Commands

### Installation
```bash
# Install dependencies
uv sync

# Or using justfile
just install
```

### Testing
```bash
# Run all tests
uv run pytest

# Or using justfile
just test

# Target specific tests
uv run pytest tests/test_file.py::TestClass::test_case -v

# Run tests matching a keyword
uv run pytest -k "keyword"

# Or using justfile for single test
just test-one tests/test_file.py::TestClass::test_case

# Run tests with coverage and the configured coverage gate
uv run pytest

# Generate and open an HTML coverage report
uv run pytest --cov-report=html
open htmlcov/index.html

# Run the supported Python/Django matrix with tox
tox
```

### Type Checking
```bash
# Run mypy type checks
uv run mypy

# Or using justfile
just typecheck
```

### Linting & Formatting
```bash
# Run ruff linting
uv run ruff check .

# Format code with ruff
uv run ruff format .

# Fix linting issues automatically
uv run ruff check --fix .

# Run all configured hooks
tox -e hooks
# Or
uv run prek run --all-files
```

### Documentation
```bash
# Build Sphinx documentation and preview locally
just docs
```

### Build & Clean
```bash
# Clean build artifacts
just clean
```

### Building & Publishing
```bash
# Build the package
uv build

# Upload to PyPI
uv publish --token your_token
```

## Backlog Workflow

This project tracks all planned work in `BACKLOG.md` and all completed work in `DONE.md`. There is no external issue tracker. Keep both files current as part of every change — they are the project plan.

### `BACKLOG.md`

- Markdown checklist grouped by priority (`## Priority 1`, `## Priority 2`, ...).
- Each item includes enough detail for an agent or contributor to implement without consulting an external system: affected files (`Reference:`/`References:`), the desired outcome, and any upstream links when useful.
- Before starting a backlog item, read the full item plus all referenced files, docs, specs, and upstream issues. Do not start work on summaries alone.
- When the scope of an item changes, edit the item in place rather than starting a parallel one.

### `DONE.md`

- Append-only log of completed work, grouped under date headers (`## YYYY-MM-DD`) with one `### <Item title>` per completed item.
- Each entry records: the completion date, a concise summary of what changed, the validation commands that were run (e.g. `uv run pytest`, `uv run mypy`, ...), a documentation note, and a changelog note.
- If documentation or the changelog did not need an update for that item, say so explicitly in the entry. Silence is not acceptable.

### Completing a Backlog Item

When finishing a backlog item:

1. Remove the item from `BACKLOG.md`.
2. Add a corresponding entry to `DONE.md`.
3. Update `docs/changelog.rst` when the change affects behavior, fixes a bug, adds a feature, changes configuration, or affects users.
4. Update the rest of the project documentation when implementation behavior, configuration, public APIs, workflows, examples, or user-facing usage changes.
5. Treat the work as incomplete until code, tests, documentation, changelog, `BACKLOG.md`, and `DONE.md` are all consistent.

Keep this section aligned with `AGENTS.md`. If you change the workflow in one file, update the other.

## Agent Session Materials

- Keep raw agent transcripts, prompts, command output, and local session summaries private and untracked.
- If a local summary is useful, write it under `.agent-summaries/` or use a `codex-session-*.md`/`claude-session-*.md` file; these paths are gitignored.
- Do not add hooks or scripts that scrape agent or terminal transcripts into tracked files by default.
- Promote only concise, reviewed, repo-specific guidance into tracked documentation; use the curated learnings backlog item for that work.

## Key Dependencies

- Django
- django-braces
- pytz
- setuptools

## Testing Guidelines

- **Framework**: Pytest with pytest-django
- **Preferred style**: New tests should use pytest functions or plain pytest classes with fixtures and plain `assert`
- **Database tests**: Use `@pytest.mark.django_db` or the `db` fixture for tests that need database access
- **Legacy TestCase tests**: Do not mix `pytest.mark.parametrize` into `django.test.TestCase` classes. Convert existing
  `TestCase` files to pytest in focused maintenance slices instead of opportunistically rewriting them during unrelated
  feature work
- **Test location**: New behaviors need coverage under `tests/` with `test_*.py`; mirror module paths for discoverability
- **Coverage**: Tests run with coverage for the `indieweb` package and enforce the documented `fail_under` gate in
  `pyproject.toml`
- **Database**: Reuse enabled for faster tests; reset or mark transactional tests if you change schema
- **Migrations**: Disabled during tests
- **Django settings**: `tests.settings`
- **Regression tests**: For regression proofs, add focused tests near the bug; prefer fixtures over inline setup to avoid duplication
- **Fast iteration**: Use `pytest -k "keyword"` or `just test-one path::node` for quick feedback

## Coding Style & Naming Conventions

- **Python version**: 3.10+ with 4-space indentation
- **Type annotations**: Prefer explicit typing—public functions and classes should be type-annotated
  - Use `list`, `dict`, `set`, `tuple` instead of `List`, `Dict`, `Set`, `Tuple`
  - Use pipe notation `|` instead of `Optional[]` (e.g., `str | None` instead of `Optional[str]`)
  - Use `from typing import Any` when needed, but prefer built-in types
- **Formatting**: Ruff for linting and formatting with 119 character line length
- **Imports**: Follow Ruff rules (`E,W,F,I,B,UP,DJ`); avoid unused symbols and dead code
- **Naming conventions**:
  - Modules/files: `snake_case`
  - Classes: `PascalCase`
  - Functions/methods: `snake_case`
  - Django settings/constants: `UPPER_SNAKE_CASE`
- **Django boundaries**: Keep app boundaries clean
  - Views/handlers in `indieweb`
  - Templates in `templates/indieweb/`
  - Static assets under `static/indieweb/`
- **prek hooks** for:
  - Trailing whitespace
  - End of file fixing
  - YAML/TOML validation
  - Python upgrades (3.10+)
  - Django upgrades (4.1+)
  - Ruff linting and formatting
  - djhtml for template formatting

## Commit & Pull Request Guidelines

### Pushing Is Manual. Committing Needs Approval.

**Pushing is a manual user action.** The user pushes — not the agent, not a hook, not a script the agent runs. Never run `git push`, `git push --force`, `git push --force-with-lease`, `gh pr create`, `gh pr merge`, or any other command that publishes work to a remote. There are no exceptions — not "the user said push last time", not "the plan says push at the end", not "everything is green and the branch is ready", not "the previous session pushed". If a push seems needed, say so and stop. The user runs it themselves, out of band.

**Committing requires explicit, in-conversation approval.** Do not run `git commit` on your own. Even when all quality gates are green and the implementation looks complete, the user reviews the working-tree changes before they become commits.

- After finishing implementation work, stop at the staging boundary: report what changed, summarize validation results, and wait.
- The user will ask you to commit explicitly. If they do not, do not commit. Approval to commit is *not* approval to push.
- "Approved once" is not "approved forever": each commit needs its own go-ahead.
- This rule applies even if a previously written plan, prompt, handoff document, or backlog item says "commit and push at the end". Treat those as descriptions of the eventual outcome, not as standing authorization.
- It is correct and expected to end a session with local commits the user has not yet pushed; that is the user's job.
- If you commit prematurely, surface it immediately and ask whether to amend, revert, or leave it. Never try to "fix" a premature commit by pushing it.

### Commit Mechanics (once the user has approved)

- **Commit messages**: Short, imperative subjects (e.g., "Add Micropub handler validation", "Document justfile workflows").
- **Commit scope**: Keep each commit focused on a single logical change.
- **Before opening a PR**:
  - Run `uv run pytest` - Ensure all tests pass
  - Run `uv run mypy` - No type errors
  - Run `uv run ruff check .` - No linting issues
  - Include notable outputs in the PR description
- **PR description should include**:
  - Description of the change and user impact
  - Testing done
  - Link to related issues
  - Screenshots or API samples when altering user-facing behavior or responses
- **Documentation**: Update docs or examples when adding endpoints, handlers, or settings toggles.
- **Migrations**: Mention migration implications explicitly.

### Definition of Done

A feature is NOT considered complete until:

1. **All tests pass** - Run `uv run pytest` to ensure no regressions
2. **MyPy type checking passes** - Run `uv run mypy` with no type errors
3. **Configured hooks pass** - Run `uv run prek run --all-files`
4. **New functionality has tests** - Add comprehensive tests for any new features
5. **Documentation is updated** - Update relevant docs if behavior changes

Always verify these before considering any implementation complete.

## Security & Configuration Tips

- **Never commit secrets**: Never commit secrets or tokens; rely on environment variables for client IDs, tokens, and target URLs
- **Input validation**: When adding new endpoints or handlers, validate input early
- **Clear interfaces**: Keep external HTTP calls behind clear, typed interfaces (see `indieweb` client patterns)
- **Migrations**: Migrations live under `indieweb/migrations/`; run and check them in tests if schema changes occur

## Notes

- Main branch is `develop`
- Documentation at https://django-indieweb.readthedocs.io/
- Source at https://github.com/ephes/django-indieweb
