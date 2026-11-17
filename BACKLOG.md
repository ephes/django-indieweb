# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

Round 90 media ownership, mutation authority, outbound work limits, resend
reservations and bounded grant reconciliation are recorded in `DONE.md`.
Round 91 current token authority, owner-fenced revocation, bounded inventory
pages and private WebSub callback responses are also recorded there.

Round 92 admin, delivery verification and lease maintenance safeguards are
tracked in `DONE.md` as their bundles complete.

Round 93 credential/Webmention/profile admin ownership and bounded,
authoritative rate/inventory/profile lookup work are recorded in `DONE.md`.

Round 96 replay retention, wire grammar, CORS and media byte ownership
are recorded in `DONE.md`.

Round 97 configured spam-policy loading and strict decision validation are
recorded in `DONE.md`.

Round 100 Micropub decoded-path admission, exclusive local publication,
storage compensation and h-card byte budgets are recorded in `DONE.md`.

Round 101 WebSub empty-save semantics and legacy encryption-prefix migration
are recorded in `DONE.md`.

Round 105 bounded Webmention command input and private command diagnostics
are recorded in `DONE.md`.

Round 107 bounded h-card extraction, Webmention display projections and parser
admission authority/work ceilings (B39/B40)
are recorded in `DONE.md`.

Round 113 held-directory and durable static-site publication is recorded in `DONE.md`.

Round 122 strict profile JSON admission and current source-read bearer authority
are recorded in `DONE.md`.

Round 128 Webmention receive and nested-display database authority is recorded in `DONE.md`.

Round 131 debug-client credential origin confinement and the Micropub bearer
wire contract are recorded in `DONE.md`.

## Priority 1

No current Priority 1 items.

## Priority 2

No current Priority 2 items.

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

No current Webmention and Reader Boundaries items.

## Agent Workflow Improvements

No current Agent Workflow Improvements items.
