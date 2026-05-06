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

No current Tooling and Maintainability items.

## Priority 4

### WebSub Enhancements

No current WebSub Enhancements items.

### Micropub Enhancements and Extensions

No current Micropub Enhancements and Extensions items.

### Syndication and Storage Examples

No current Syndication and Storage Examples items.

### Webmention and Reader Boundaries

- [ ] Add Webmention.io import/display guidance without replacing built-in Webmention processing.
  - Outcome: document how a host project could outsource collection to Webmention.io or import/display Webmention.io JF2 data alongside django-indieweb's built-in ``Webmention`` model, including sanitization expectations and mention type mapping. Make clear when using Webmention.io is an alternative integration choice rather than a missing core protocol endpoint.
  - References: local ``src/indieweb/models.py``, ``src/indieweb/processors.py``, ``src/indieweb/templatetags/webmention_tags.py``, ``docs/webmention.rst``, and ``tests/test_webmention_*.py``; Indiekit ``/Users/jochen/src/getindiekit-indiekit/packages/endpoint-webmention-io/README.md``, ``lib/controllers/webmentions.js``, ``lib/utils.js``, and ``docs/plugins/endpoints/webmention-io.md`` at ``1ee20d06``; Webmention.io API docs ``https://webmention.io/``.
  - Scope exclusions: do not replace django-indieweb's receive/send Webmention endpoints, add a Webmention.io API token setting to core, or add a bundled Webmention management dashboard in this item.

## Agent Workflow Improvements

- [ ] Add a curated agent learnings file if repeated repo-specific mistakes emerge.
  - Outcome: future agents get concise, reviewed guidance rather than raw transcript dumps.
