# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

## Priority 1

No current Priority 1 items.

## Priority 2

No current Priority 2 items.

## Priority 3

### IndieAuth endpoints parse multipart bodies before authentication

`AuthView` (`_csrf_failure_response` and `post` read `request.POST.get("action")`) and `TokenView` read `request.POST` for unauthenticated clients, so a `multipart/form-data` body runs Django's upload handlers before any check. IndieAuth requests are form-encoded, but Django's test client and some HTML forms default to multipart, so rejecting it (415) is a compatibility change: decide whether to reject multipart outright or to cap it with tight `DATA_UPLOAD_MAX_*`/`FILE_UPLOAD_*` guidance, then update the many tests that post multipart today. References: `src/indieweb/views.py` (`AuthView`, `TokenView`).

## Priority 4

### Housekeeping

#### Document or backfill migration `0026` replay-state drop

`migrations/0026_drop_recent_accepted_delivery_digests.py:19-23` drops the JSON column without backfilling into `WebSubAcceptedDelivery` rows. Brief replay-protection gap during deploy: a hub retrying an already-accepted delivery within the configured window (default 300 s) immediately after the migration runs could be re-accepted. Either add a `RunPython` step that copies digests forward, or document the deploy-window gap explicitly in `docs/changelog.rst` so operators schedule during a quiet period.

#### `WebmentionStatusView` default response privacy

`views.py:3314-3320` returns `source` / `target` URLs to any opaque-token holder by default; `INDIEWEB_WEBMENTION_STATUS_PUBLIC=True` already gates the public-safe shape. Consider flipping the default to public-safe, or scoping the diagnostic response to authenticated/staff requests. Documentation work; not a regression.

#### `WebmentionSourceSnapshot` retention / compression policy

`models.py:437` is `models.TextField()`; `processors._webmention_fetch_max_bytes()` defaults to 1 MiB. Each verified webmention persists up to ~1 MiB of attacker-controlled HTML. Document a snapshot retention policy (gzip the column, retain only the last N snapshots, or cap snapshot size lower than fetch size).

#### `_get_local_profile` profile URL canonical lookup

The 2026-05-10 Medium fix restricted local-profile author rewrites to source pages on the current Django `Site` domain and normalized the source/author domains before trusting them. The remaining low-priority gap is exact `Profile.objects.get(url=author_url)` matching (`processors.py`) for same-site source pages: case, default-port, IDNA, or trailing-slash variants may fail to match the intended local profile. Consider canonical matching against stored profile URLs or a normalized indexed field.

#### Tighten `NON_RENDERED_LINK_ANCESTORS` (and Vouch proof location)

`processors.py:64` excludes only `noscript` and `template`; an `<a href>` inside `<head>`, foreign content (SVG/MathML), or CSS-hidden ancestors still satisfies the rendered-anchor invariant. Self-attestation by the source author bounds practical impact, but tightening the ancestor list (or, for Vouch proof, requiring the link inside an h-card or visible body region) closes the silent-vouch concern.

#### `_extract_external_target_urls` case-insensitive same-domain compare

`senders.py:567-583` compares `urlparse(...).netloc` with `==`. A link `https://Example.COM/x` from a source on `https://example.com/` is treated as cross-domain and produces a self-mention. Lowercase both sides (or use `_origin_for_url` from `http_client.py:233`) and strip default ports.

#### `send_webmention` vouch URL: comment intent or pass `default_address_resolver`

`senders.py:326` calls `validate_safe_http_url(vouch, resolver=None)` (syntactic only). The vouch URL is not fetched on this path, so this is future-proofing. Either add a comment documenting the intentional `resolver=None`, or pass `default_address_resolver` to be consistent and let the comment be the future-proof note.

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

#### Layered `httpx.Timeout` for `WebmentionSender`

`senders.py:108-110, 167, 336` use scalar timeouts (10 s HEAD, 30 s POST). With `WEBMENTION_MAX_REDIRECTS = 5` (`http_client.py:16`), worst-case wall-clock is ~180 s per POST delivery (initial + 5 redirects × 30 s) and ~60 s per HEAD discovery. A hostile endpoint that slow-rolls writes without exceeding any single phase timeout can sustain that. Replace with `SAFE_HTTP_DEFAULT_TIMEOUT`-style `httpx.Timeout(connect, read, write, pool)` and a per-call deadline.

### Micropub Enhancements and Extensions

No current Micropub Enhancements and Extensions items.

### Syndication and Storage Examples

No current Syndication and Storage Examples items.

### Webmention and Reader Boundaries

#### Opt-in `INDIEWEB_WEBMENTION_STRICT_REDIRECTS`

`senders.py:330-338` does not opt into `cross_origin_strip`, so `request_with_webmention_redirects` replays the source/target POST body cross-origin up to five hops (`http_client.py:300-326`). Each hop is still SSRF-screened, but the sender becomes an opaque endpoint pivot for attacker-controlled redirect chains. Add an opt-in `INDIEWEB_WEBMENTION_STRICT_REDIRECTS` setting that flips `cross_origin_strip=True` for operators who do not need bug-for-bug compatibility with quirky endpoints.

## Agent Workflow Improvements

No current Agent Workflow Improvements items.
