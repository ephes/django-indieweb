# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

## Priority 1

No current Priority 1 items.

## Priority 2

### Round 80 B39 integration

- [ ] Review and integrate parked grant/h-card fixes on `fix/r80-grants-hcard`.
  The review loop stopped with a recurring non-mapping profile-save warning;
  the final `_sync_fields_from_h_card` guard and expanded regression inputs
  address that path but still need a passing review. References:
  `src/indieweb/models.py`, `src/indieweb/h_card.py`,
  `src/indieweb/templatetags/indieweb_tags.py`, `tests/test_h_card.py`,
  `tests/test_models.py`, `docs/h-card.rst`, `docs/indieauth.rst`.
  Run full local pytest, mypy, Ruff/hooks, docs, migration/storage lanes;
  fetch/rebase before any merge. No runtime adoption is included.

## Priority 3

No current Priority 3 items.

## Priority 4

### Housekeeping

#### `WebmentionStatusView` default response privacy

`views.py:3314-3320` returns `source` / `target` URLs to any opaque-token holder by default; `INDIEWEB_WEBMENTION_STATUS_PUBLIC=True` already gates the public-safe shape. Consider flipping the default to public-safe, or scoping the diagnostic response to authenticated/staff requests. Documentation work; not a regression.

#### `WebmentionSourceSnapshot` retention / compression policy

`models.py:437` is `models.TextField()`; `processors._webmention_fetch_max_bytes()` defaults to 1 MiB. Each verified webmention persists up to ~1 MiB of attacker-controlled HTML. Document a snapshot retention policy (gzip the column, retain only the last N snapshots, or cap snapshot size lower than fetch size).

### WebSub Enhancements

No current WebSub Enhancements items.

### Micropub Enhancements and Extensions

No current Micropub Enhancements and Extensions items.

### Syndication and Storage Examples

No current Syndication and Storage Examples items.

### Webmention and Reader Boundaries

#### Nested author URL parsing isolation


- [ ] A nested child with a valid identity but a malformed URL-valued author
  (for example an unbalanced IPv6 bracket) can still raise before optional
  author URL sanitization, failing parent processing. Isolate malformed author
  URL parsing and preserve valid identity/sibling/parent processing with a
  synthetic regression. References: `WebmentionProcessor._extract_nested_response_author`,
  `_extract_nested_explicit_author`, `_is_author_url_reference`, and
  `_extract_author_properties` in `src/indieweb/processors.py`. Round 77 I3
  handles only `uid`/`url` identity candidates; it does not cover author URLs.

## Agent Workflow Improvements

No current Agent Workflow Improvements items.
