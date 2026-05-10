# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

## Priority 1

No current Priority 1 items.

## Priority 2

No current Priority 2 items.

## Priority 3

### Token endpoint and introspection: `Cache-Control: no-store` on success

RFC 6749 §5.1 mandates `Cache-Control: no-store` on token-endpoint responses; RFC 7662 §2.2 strongly recommends it for introspection. The 401 path already sets it (`views.py:1253-1256`); the 200/201 success paths do not. Add to `TokenView.send_token` (`views.py:1644-1655`), `TokenIntrospectionView._active_response` (`views.py:1869-1879`), and `_inactive_response` (`views.py:1829-1830`).

### Consent screen: `Cache-Control: no-store` and `Referrer-Policy: no-referrer`

`AuthView.get` renders `client_id`, `redirect_uri`, `state`, `me`, `scope` into HTML and currently sets only `X-Frame-Options` / `Content-Security-Policy: frame-ancestors 'none'` (`views.py:1473-1476`). Add `Cache-Control: no-store` and `Referrer-Policy: no-referrer` on the consent GET response and on the redirect emitted by `_handle_consent` that carries `code` / `state` / `iss`.

### `_redact_auth_code` should honor `INDIEWEB_LOG_REDACTION`

`_redact_auth_code` (`views.py:1221-1227`) unconditionally returns `code[:6] + "..."`. With a 32-char `get_random_string` (charset 62), six characters is ~35 bits and is inconsistent with the redaction policy operators opted into. Replace call sites with `log_redaction.redact_token`, or have the helper consult `_resolve_mode` and emit a digest in redact mode.

### Unredacted `client_id` / `token.owner` in logger sites

Several lines emit `client_id={client_id}` (a URL) or `token.owner` (Django username) without redaction, defeating the user-correlation primitive `INDIEWEB_LOG_REDACTION` is meant to prevent. Sibling lines on the same view do redact (`views.py:1341, 1399, 1583`). Apply `redact_url` / hashed-id helper at: `views.py:1306, 1682, 1686, 1742, 1804, 1848`.

### `notify_websub` management command: redact `result.error`

`commands/notify_websub.py:60-62` writes `result.error` (up to 500 chars of the hub response body) verbatim to stdout, bypassing `INDIEWEB_LOG_REDACTION`. Pass through `redact_url` (or strip URL-shaped substrings) for parity with the redacted topic/hub URLs already routed through the helper.

### CORS preflight: emit `Vary: Origin` on wildcard rejection

`cors.py:142-145` adds `Vary: Origin` only when `not config.allow_all_origins`; the wildcard branch's 405 rejection is therefore cacheable across origins. Always emit `Vary: Origin` on preflight rejections.

### Per-method rate-limit counter multiplies effective allowance

`rate_limit.py:88-94` keys the counter on `:{method}:`, and `RateLimitMixin.dispatch` (`rate_limit.py:143-148`) increments before `super().dispatch`, so unsupported-method requests still consume cache slots and the effective per-IP limit is `limit × distinct-methods-tried`. Drop `method` from the key (limits are per-endpoint, not per-method), or normalize all non-allowed methods to a single bucket.

### Legacy code-verification POST should consume the auth code on success

`AuthView._verify_auth_code` (`views.py:1568-1599`) returns `{"me": auth.me}` on a successful match without calling `auth.delete()`. The token endpoint's `select_for_update` + delete-count gate (`views.py:1800-1810`) is the single-use pattern; the legacy verification path should match so a stolen 60-second-window code cannot be reused as a `me`-validity oracle.

### `_handle_consent` upsert should be atomic

`views.py:1540-1555` runs `existing = Auth.objects.get(...)` / `existing.delete()` / `Auth.objects.create(...)` outside `transaction.atomic()`. Two concurrent approves for the same `(owner, client_id, scope, me)` race the delete and `create` can hit `IntegrityError` on `unique_together`, surfacing as a 500 to the legitimate user. Wrap in `transaction.atomic()` with `select_for_update`, or use `update_or_create`. Reliability rather than privilege issue.

### `Token.objects.get_or_create(scope=None)` row proliferation on Postgres/MySQL

`unique_together = ("me", "client_id", "scope", "owner")` does not collapse on NULL on Postgres/MySQL. Each token exchange for a no-scope auth code runs the `create` branch, accumulating rows. Coerce `scope=None` to `""` for the storage key, or add a partial unique index. Affected: `views.py:1623-1629`; `models.py:247, 251`.

### `_check_redirect_uri`: reject submitted `redirect_uri` when stored value is empty

`views.py:1692-1701` only rejects when both the submitted and the stored `auth.redirect_uri` are populated. Currently-issued codes always have a stored `redirect_uri` (consent and `required_params` enforce it), so the gap is latent — but defensive code should add a final branch rejecting `auth.redirect_uri` empty + submitted-set as a mismatch.

### WebSub: reject negative `Content-Length`

`websub.delivery_content_length_too_large` (`websub.py:977-986`) parses negative values via `int("-1")` and the `parsed > max_bytes` comparison is False, so the early reject is skipped. The post-read length check still bounds the body, but treat `parsed < 0` as malformed and reject early.

### WebSub: pin algorithm-name vs header-name suffix invariant with a regression test

`_signature_headers` (`websub.py:994-1003`) accepts `X-Hub-Signature-256: sha1=<digest>` and trusts the algorithm token rather than the header name. Currently safe because sha1 is off by default. Add a test asserting that `X-Hub-Signature-256: sha1=...` is rejected even when sha1 is otherwise allowed, so a future change conditioning trust on the header name cannot regress.

### WebSub delivery-attempt retention policy

`WebSubDeliveryAttempt` rows are written for every callback POST and never pruned (`websub.py:1216-1225`; `models.py:803-829`). Add `INDIEWEB_WEBSUB_DELIVERY_ATTEMPT_RETENTION_DAYS` plus a pruning command or documented operator workflow so a noisy hub or leaked active callback URL cannot grow the diagnostics table indefinitely.

### WebSub denial and verification state updates should lock rows

`record_websub_denial` (`websub.py:847-909`) and `confirm_websub_verification` (`websub.py:780-844`) branch from in-memory subscription state and then save. Wrap the read/branch/save paths in `transaction.atomic()` with `select_for_update()` so concurrent denial/confirmation callbacks cannot demote a just-confirmed row or defeat the renewal lease ratchet.

### WebSub callback token existence oracle

`WebSubCallbackView.get` returns distinguishable 404 vs 400/200/204 responses for unknown vs known callback tokens (`views.py:2921-2930`), and `post` returns 404 for unknown-or-inactive subscriptions (`views.py:2962-2966`). Token entropy is high, but a partial leak becomes testable. Return uniform 404 for tokens that do not match an active subscription, optionally with a small constant-time delay.

### Webmention templates: no-referrer image loads

Bundled Webmention author-photo `<img class="u-photo">` tags lack `referrerpolicy="no-referrer"` in `templates/indieweb/webmention_types/{like,mention,reply,repost,nested_response}.html`. Add `referrerpolicy="no-referrer"` (and consider `crossorigin="anonymous"`) so visitor browsers do not send the rendering page URL to attacker-chosen photo origins.

### Enforce nested-response URL validators on ingest

`WebmentionNestedResponse` URL fields have model validators, but `_upsert_nested_response` (`processors.py:1239-1271`) writes via `get_or_create` / `save(update_fields=...)` without `full_clean()`. `_first_url_identity` currently filters to HTTP(S), but the invariant is producer-side. Call `full_clean(exclude=...)` before save or add explicit assertions/tests at the ingest boundary.

### Webmention Link header parser should be quote-aware

`WebmentionSender._parse_link_header` (`senders.py:230-238`) splits Link entries on bare commas, so an RFC 8288 quoted parameter containing a comma can mis-pair a `rel="webmention"` token with another URL. Replace with a quote-aware parser and add regression coverage for quoted commas.

### Micropub action POSTs should reject multipart before parsing action

`MicropubView` / `MicropubMediaView` call `request.POST.get("action")` before per-action authorization (`views.py:2080-2090, 2170-2181, 2745-2755`). For multipart requests this invokes Django upload handlers before dispatch. Reject multipart for action verbs that never accept files before reading `request.POST`.

### Micropub JSON properties must be a mapping

JSON Micropub create/update handling assumes `properties` is a mapping (`views.py:2025-2034, 2285-2297, 2340-2346`). A string value can bypass membership checks and then raise `TypeError` into a 500. Add an `isinstance(properties, dict)` guard in `_parse_json_request`.

### Token and cookie debug prints in `client.py`

`client.py:113-115` prints issued bearer tokens, and `client.py:23-25, 39, 45` print raw cookies. Keep the debug helper useful without normalizing credential leaks: redact by default or require an explicit `INDIEWEB_DEBUG_TOKEN=1` opt-in for full values.

### `log_redaction.redact_token` prefix and mode parsing

`log_redaction.redact_token` preserves an 8-character token prefix in passthrough mode (`log_redaction.py:77`), and `_resolve_mode` accepts only exact `"redact"` while silently treating `"REDACT"`, `"true"`, or booleans as passthrough. Trim the prefix or default-redact when `DEBUG=False`, and log/document non-canonical `INDIEWEB_LOG_REDACTION` values.

### Rate-limit cache increment fallback can lose increments

`rate_limit.py:118-122` handles `cache.incr` `ValueError` by unconditionally setting the counter to `1`. Under cache eviction pressure, concurrent requests can both fall into the fallback and lose one increment. Retry `cache.add` / `cache.incr` once or document the accepted burst behavior.

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
