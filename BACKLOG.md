# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

## Priority 1

### Webmentions Reliability and Compliance

- [ ] Make Webmention receiving asynchronous.
  - Reference: `src/indieweb/views.py`.
  - Outcome: the receiver returns an accepted/queued response and processing happens outside the request path; tests cover slow or timing-out sources.
- [ ] Complete the Webmention authorship fallback chain.
  - Reference: `src/indieweb/processors.py`.
  - Outcome: authorship extraction supports `rel=author` and page-level h-card fallback where appropriate.
- [ ] Evaluate Webmention vouch support.
  - Outcome: decide whether to support the `vouch` parameter; if yes, add model, receiver, sender, tests, and docs.
- [ ] Evaluate Salmentions support.
  - Outcome: decide whether to detect and send salmentions; if yes, add tests and documentation.

### Micropub Media Endpoint and Uploads

- [ ] Add a Micropub media endpoint.
  - References: `docs/concepts.rst`, `docs/micropub.rst`.
  - Outcome: media endpoint follows the Micropub spec, with storage integration, tests, and docs.
- [ ] Handle multipart file uploads in Micropub form parsing.
  - Reference: `src/indieweb/views.py`.
  - Outcome: uploaded files are passed through the media flow rather than ignored.
- [ ] Document and test media uploads.
  - Outcome: examples and regression coverage exist for media endpoint and upload behavior.

## Priority 2

### Documentation Audit

- [ ] Audit IndieWeb docs for stale settings, commands, and behavior notes.
  - Known issues: `docs/development.rst` references `make -C docs html`, but the current workflow uses `just docs` or `sphinx-build`.
  - Outcome: documentation matches current IndieAuth, Micropub, Webmention, and development workflows.
- [ ] Close h-card utility coverage gaps and confirm support status.
  - Reference: `src/indieweb/h_card.py`.
  - Outcome: normalization and validation edge cases are covered by focused tests, and docs accurately describe supported h-card behavior.
- [ ] Clean up TODO and future-enhancement notes after related changes ship.

### Token Management UI

- [ ] Add token revocation UI.
  - Outcome: users can revoke tokens and docs describe the workflow.

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
