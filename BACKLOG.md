# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

## Priority 1

### Security Residuals

## Priority 2

### Security Residuals

## Priority 3

### API Hardening

No current Priority 3 API Hardening items.

## Priority 4

### Housekeeping

- [ ] Add privacy-oriented logging guidance or redaction mode. References:
  `src/indieweb/views.py`, `src/indieweb/processors.py`,
  `src/indieweb/websub.py`, `docs/configuration.rst`. Authorization codes and
  bearer tokens are redacted, but logs still include client IDs,
  `redirect_uri`, `state`, `me`, Webmention source/target URLs, and handler
  URL parameters. Add deployment guidance for log retention/redaction, or add a
  setting/helper that redacts privacy-sensitive URL and state values in
  protocol logs.

- [ ] Validate inbound protocol field lengths before persistence. References:
  `src/indieweb/views.py`, `src/indieweb/processors.py`,
  `src/indieweb/models.py`, `tests/test_webmention_endpoint.py`,
  `tests/test_auth_endpoint.py`, `tests/test_token_endpoint.py`. Public and
  protocol-facing views validate URL syntax but do not consistently reject
  values that exceed backing model field lengths before `get_or_create()` or
  `create()` calls. In queued Webmention deployments, overlong but syntactically
  valid `source`, `target`, or `vouch` URLs can reach
  `_store_webmention_submission()` before the processing try/except boundary;
  authorization parameters such as `state`, `scope`, `client_id`,
  `redirect_uri`, and `me` have similar authenticated-user robustness gaps.
  Return protocol-appropriate 400 responses before database writes and add
  regression coverage for overlong fields.

### WebSub Enhancements

No current Priority 4 WebSub Enhancements items.

### Micropub Enhancements and Extensions

No current Micropub Enhancements and Extensions items.

### Syndication and Storage Examples

No current Syndication and Storage Examples items.

### Webmention and Reader Boundaries

No current Webmention and Reader Boundaries items.

## Agent Workflow Improvements

No current Agent Workflow Improvements items.
