# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

## Priority 1

### Webmentions Reliability and Compliance

- [ ] Investigate the currently reported Webmention breakage.
  - Reference: GH-15.
  - Outcome: reproduction steps and failing regression coverage exist before implementation changes.
- [ ] Fix broken Webmention behavior.
  - Depends on the investigation item above.
  - Outcome: expected Webmention receive/process/display behavior is restored with regression tests.
- [ ] Complete Webmention spec compliance.
  - Reference: GH-13.
  - Outcome: implementation behavior is aligned with the Webmention spec and documented.

### Micropub Core CRUD and Queries

- [ ] Verify Micropub create flow and content creation end to end.
  - References: `docs/concepts.rst`, `tests/test_micropub_create.py`, `src/indieweb/views.py`.
  - Outcome: create behavior is covered by tests and docs no longer contain stale claims.
- [ ] Implement Micropub update/delete/undelete actions.
  - References: `src/indieweb/views.py`, `docs/api.rst`, `docs/concepts.rst`, `docs/micropub.rst`.
  - Outcome: update/delete/undelete work through the configured handler with tests and docs.
- [ ] Implement Micropub source query.
  - References: `src/indieweb/views.py`, `docs/concepts.rst`.
  - Outcome: source queries return supported entry data with read-scope enforcement.

### Auth Scopes and Token Management

- [ ] Implement `client_id` access control for token authorization.
  - Reference: `src/indieweb/views.py`.
  - Outcome: token authorization validates the client according to documented rules.
- [ ] Enforce token scopes for Micropub and IndieAuth operations.
  - Outcome: read, create, update, delete, and undelete operations enforce appropriate scopes and return spec-appropriate errors.
- [ ] Add token expiration handling.
  - Current issue: `TokenView.send_token()` returns `expires_in=10` without corresponding expiration enforcement.
  - Outcome: token lifetime behavior and response metadata are consistent.

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

- [ ] Audit Micropub docs for stale functionality notes.
  - References: `docs/concepts.rst`, `docs/micropub.rst`.
  - Outcome: documentation matches the current implementation.
- [ ] Verify h-card support and update docs.
  - Reference: GH-14.
  - Outcome: close or document the h-card support gap with tests/docs as needed.
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
