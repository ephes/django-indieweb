# Done

Completed backlog items move here from `BACKLOG.md`. Keep entries concise, but include validation and documentation/changelog notes so future contributors can understand what changed.

## 2026-04-26

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
