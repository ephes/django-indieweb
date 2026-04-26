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

## Development Setup

This project uses:
- Python 3.10+ (supports 3.10, 3.11, 3.12, 3.13)
- Django
- uv for packaging and dependency management
- Ruff for linting and formatting (line length: 119)
- Pre-commit hooks for code quality

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

# Run tests with coverage
coverage run -m pytest tests && coverage html && open htmlcov/index.html

# Run full test matrix with tox
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

# Run all pre-commit hooks
tox -e pre-commit
# Or
pre-commit run --all-files
```

### Documentation
```bash
# Build Sphinx documentation and preview locally
just docs
```

## Backlog Workflow

- This project no longer uses Beads. Track planned work in `BACKLOG.md` and move completed items to `DONE.md`.
- Before starting a backlog item, read the full item and any referenced files, docs, specs, or upstream issues.
- When completing a backlog item, remove it from `BACKLOG.md` and add an entry to `DONE.md` with the completion date, summary, validation, documentation note, and changelog note.
- Update `docs/changelog.rst` when a completed item changes behavior, fixes a bug, adds a feature, changes configuration, or affects users.
- Update project documentation when implementation behavior, configuration, public APIs, workflows, examples, or user-facing usage changes.
- Work is not complete until code, tests, documentation, and changelog entries are consistent. If docs or changelog updates are not needed, say so in the `DONE.md` entry.

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

## Key Dependencies

- Django
- django-model-utils
- django-braces
- pytz
- setuptools

## Testing Guidelines

- **Framework**: Pytest with pytest-django
- **Test location**: New behaviors need coverage under `tests/` with `test_*.py`; mirror module paths for discoverability
- **Coverage**: Tests run with coverage (`--cov-config=pyproject.toml`)
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
- **Pre-commit hooks** for:
  - Trailing whitespace
  - End of file fixing
  - YAML/TOML validation
  - Python upgrades (3.10+)
  - Django upgrades (4.1+)
  - Ruff linting and formatting
  - djhtml for template formatting

## Commit & Pull Request Guidelines

- **Commit messages**: Short, imperative subjects (e.g., "Add Micropub handler validation", "Document justfile workflows")
- **Commit scope**: Keep each commit focused on a single logical change
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
- **Documentation**: Update docs or examples when adding endpoints, handlers, or settings toggles
- **Migrations**: Mention migration implications explicitly

### Definition of Done

A feature is NOT considered complete until:

1. **All tests pass** - Run `uv run pytest` to ensure no regressions
2. **MyPy type checking passes** - Run `uv run mypy` with no type errors
3. **Pre-commit hooks pass** - Run `pre-commit run --all-files`
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
