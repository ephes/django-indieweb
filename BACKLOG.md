# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

## Priority 1

No current Priority 1 items.

## Priority 2

No current Priority 2 items.

## Priority 3

### API Hardening

- [ ] Require or strongly encourage signed WebSub deliveries; add replay protection, lease bounds, and signature-algorithm preference.
  References: `src/indieweb/websub.py`, `src/indieweb/views.py`, `src/indieweb/admin.py`, `tests/test_websub.py`, `tests/test_websub_subscriber.py`, `docs/`.
  `validate_websub_delivery_signature()` returns success when a subscription has no secret, leaving authenticity dependent on the callback token URL. Strongly recommend (or optionally require) WebSub secrets and document the callback-token-only risk. Track last-seen body digest+timestamp per subscription and reject duplicate deliveries within a window (no replay protection today). Clamp `confirmed_lease` to a configurable range (e.g. 5 min – 30 days); today hub-supplied values are unbounded. When both `X-Hub-Signature` (sha1) and `X-Hub-Signature-256` are present, prefer the strongest header and consider gating sha1 behind opt-in. Require ≥20 bytes for `hub.secret` when provided; reject empty strings distinctly from `None`. Hash/encrypt subscription `secret` and `pending_secret` at rest, exclude them from `WebSubSubscriptionAdmin`, mask `callback_token`, and override `WebSubDeliveryAttemptAdmin.has_delete_permission` to preserve audit integrity.

## Priority 4

### Housekeeping

No current Housekeeping items.

### WebSub Enhancements

No current WebSub Enhancements items.

### Micropub Enhancements and Extensions

No current Micropub Enhancements and Extensions items.

### Syndication and Storage Examples

No current Syndication and Storage Examples items.

### Webmention and Reader Boundaries

No current Webmention and Reader Boundaries items.

## Agent Workflow Improvements

No current Agent Workflow Improvements items.
