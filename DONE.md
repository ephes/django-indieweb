# Done

Completed backlog items move here from `BACKLOG.md`. Keep entries concise, but include validation and documentation/changelog notes so future contributors can understand what changed.

## 2026-04-26

### Replace Beads with Markdown Backlog Workflow

- Removed Beads and Beadsflow as the project work-tracking system.
- Added `BACKLOG.md` for planned work and `DONE.md` for completed work.
- Linked the backlog from the project documentation.
- Updated agent instructions to use the Markdown workflow and to keep docs/changelog entries aligned with completed work.
- Documentation: updated `docs/development.rst` and `docs/index.rst`.
- Changelog: updated `docs/changelog.rst`.
- Validation: `uv run ruff check .`, `uv run mypy`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run pytest`, `uv build`, `git diff --check`, and `uv run --python 3.13 pre-commit run --all-files` all passed.
