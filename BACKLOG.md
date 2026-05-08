# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

## Priority 1

No current Priority 1 items.

## Priority 2

### Security Residuals

No current Priority 2 Security Residuals items.

## Priority 3

### API Hardening

No current Priority 3 API Hardening items.

## Priority 4

### Housekeeping

No current Priority 4 Housekeeping items.

### WebSub Enhancements

- [ ] Optionally enqueue the WebSub delivery hook out of the request thread.
  - References: `SECURITY_ANALYSIS.md` WebSub sync-hook finding; `src/indieweb/websub.py` (`process_websub_delivery`); `src/indieweb/views.py` (WebSub callback view).
  - Current state: the configured `INDIEWEB_WEBSUB_DELIVERY_HOOK` runs synchronously inside the request thread, mirroring the pre-`INDIEWEB_WEBMENTION_ENQUEUE` Webmention design.
  - Desired outcome: add `INDIEWEB_WEBSUB_DELIVERY_ENQUEUE` analogous to the Webmention enqueue setting, with documentation and tests for the queued path.

### Micropub Enhancements and Extensions

No current Micropub Enhancements and Extensions items.

### Syndication and Storage Examples

No current Syndication and Storage Examples items.

### Webmention and Reader Boundaries

- [ ] Tighten h-card render-time URL validation as defense-in-depth.
  - References: `SECURITY_ANALYSIS.md` h-card render finding; `src/indieweb/templates/indieweb/h-card.html`; `src/indieweb/models.py` (`Profile._validate_h_card_urls`); `src/indieweb/h_card.py`.
  - Current state: `Profile.save()` runs `full_clean()` which validates h-card URLs, but Django's default `URLValidator()` permits `ftp(s)://`, `mailto:` interpolations have no validator, and bypass paths (`bulk_update`, `update()`, raw SQL, fixtures with `bypass_validation`) skip validation entirely. Several `<a href>`/`<img src>` interpolations also lack `rel="nofollow noopener"`/`referrerpolicy="no-referrer"`.
  - Desired outcome: restrict h-card URL schemes to `http`/`https` at the model layer, sanitize at render with the existing `sanitize_remote_webmention_url`, and add `rel`/`referrerpolicy` on outbound author/photo links.

## Agent Workflow Improvements

No current Agent Workflow Improvements items.
