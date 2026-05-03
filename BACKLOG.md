# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

## Priority 1

### Webmentions Reliability and Compliance

No current Priority 1 items.

## Priority 3

### API Hardening

No current API Hardening items.

### Tooling and Maintainability

- [ ] Add a `just loc` line-counting workflow.
  - References: `justfile`, `pyproject.toml`, `../kptncook/justfile`.
  - Outcome: running `just loc` produces repository line-count summaries using the same `uv run count-lines-of-code` workflow used in `../kptncook`, with any required dependency or tool configuration documented.
- [ ] Remove the `django-model-utils` runtime dependency safely.
  - References: `pyproject.toml`, `src/indieweb/migrations/0001_initial.py`.
  - Outcome: initial migrations no longer import `model_utils.fields`, and the dependency can be removed without breaking fresh installs.

## Priority 4

### Micropub Enhancements and Extensions

- [ ] Add WebSub support.
- [ ] Support additional Micropub post types.

## Agent Workflow Improvements

- [ ] Evaluate local, gitignored agent session summaries.
  - Outcome: decide whether to add a private session-summary hook or script for Codex and Claude Code.
  - Constraint: do not commit raw transcripts by default because they may contain secrets, prompts, command output, or unrelated private context.
- [ ] Add a curated agent learnings file if repeated repo-specific mistakes emerge.
  - Outcome: future agents get concise, reviewed guidance rather than raw transcript dumps.
