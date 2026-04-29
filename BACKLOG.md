# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

## Priority 1

### Webmentions Reliability and Compliance

- [ ] Make Webmention receiving asynchronous.
  - Reference: `src/indieweb/views.py`.
  - Outcome: the receiver returns an accepted/queued response and processing happens outside the request path; tests cover slow or timing-out sources.
- [ ] Evaluate Webmention vouch support.
  - Outcome: decide whether to support the `vouch` parameter; if yes, add model, receiver, sender, tests, and docs.
- [ ] Evaluate Salmentions support.
  - Outcome: decide whether to detect and send salmentions; if yes, add tests and documentation.

## Priority 3

### API Hardening

- [ ] Add configurable rate limiting for IndieWeb endpoints.
  - Reference: `docs/api.rst`.
  - Outcome: rate limits are documented, configurable, and covered by tests.
- [ ] Add configurable CORS header support.
  - Reference: `docs/api.rst`.
  - Outcome: CORS behavior is documented and covered by tests.

### Tooling and Maintainability

- [ ] Standardize test style on pytest.
  - References: `tests/`, `AGENTS.md`, `CLAUDE.md`.
  - Outcome: document pytest as the preferred style for new tests, identify legacy `django.test.TestCase`/unittest-style files, and convert or schedule conversions in focused slices without mixing pytest parametrization into `TestCase` classes.
- [ ] Add a GitHub Actions workflow for pull requests and pushes to `develop`.
  - Outcome: CI runs the tox matrix, mypy, Ruff, prek hooks, and Sphinx with warnings as errors.
- [ ] Pin Django to a supported version range and test supported Django versions.
  - References: `pyproject.toml`, `tox.ini`.
  - Outcome: supported Django/Python combinations are explicit and exercised in tox.
- [ ] Update Ruff target version to Python 3.10.
  - Reference: `pyproject.toml`.
  - Outcome: `tool.ruff.target-version` matches `requires-python = ">=3.10"`.
- [ ] Add a coverage gate.
  - Reference: `pyproject.toml`.
  - Outcome: coverage has a documented `fail_under` threshold based on the current baseline.
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
