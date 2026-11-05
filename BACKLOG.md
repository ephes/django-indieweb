# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

## Priority 1

No current Priority 1 items.

## Priority 2

No current Priority 2 items.

## Priority 3

No current Priority 3 items.

## Priority 4

### Housekeeping

#### Document or backfill migration `0026` replay-state drop

`migrations/0026_drop_recent_accepted_delivery_digests.py:19-23` drops the JSON column without backfilling into `WebSubAcceptedDelivery` rows. Brief replay-protection gap during deploy: a hub retrying an already-accepted delivery within the configured window (default 300 s) immediately after the migration runs could be re-accepted. Either add a `RunPython` step that copies digests forward, or document the deploy-window gap explicitly in `docs/changelog.rst` so operators schedule during a quiet period.

#### `WebmentionStatusView` default response privacy

`views.py:3314-3320` returns `source` / `target` URLs to any opaque-token holder by default; `INDIEWEB_WEBMENTION_STATUS_PUBLIC=True` already gates the public-safe shape. Consider flipping the default to public-safe, or scoping the diagnostic response to authenticated/staff requests. Documentation work; not a regression.

#### `WebmentionSourceSnapshot` retention / compression policy

`models.py:437` is `models.TextField()`; `processors._webmention_fetch_max_bytes()` defaults to 1 MiB. Each verified webmention persists up to ~1 MiB of attacker-controlled HTML. Document a snapshot retention policy (gzip the column, retain only the last N snapshots, or cap snapshot size lower than fetch size).

#### Sanity-check HEAD-discovered Webmention endpoints against GET

`WebmentionSender.discover_endpoint` accepts a HEAD-discovered endpoint without checking whether a following GET would advertise the same endpoint (`senders.py:165-178`). Each hop remains SSRF-screened, so this is delivery accuracy rather than a direct network bypass. Document the accepted behavior or add a cheap GET sniff before sending.

#### Strip interior `..` from Micropub slugs

`MicropubView._sanitize_slug_value` (`views.py:2314-2320`) strips control characters, slashes, and leading dots, but leaves values like `foo..bar`. Handlers must still defend before path joins, but stripping interior `..` is cheap hardening.

#### Move `example_project.py` runtime template into a real template file

`example_project.py:118-148` builds a `django.template.Template` from a hardcoded literal per request. It is not currently exploitable because the source is constant, but it normalizes a runtime-template pattern. Move the markup to a real template file.

#### Add clickjacking middleware to `example_project.py`

`example_project.py` omits `django.middleware.clickjacking.XFrameOptionsMiddleware`. The IndieAuth consent view sets its own frame protections, but copy/paste users inherit a non-default middleware list missing global clickjacking protection.

#### Validate h-card mailto email shape before rendering

`templates/indieweb/h-card.html` renders `Profile.email` as a `mailto:` URL without validating email shape. Malformed values are percent-encoded and inert, but confusing. Add an `EmailValidator` filter or skip rendering when the value is not an addr-spec.

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
