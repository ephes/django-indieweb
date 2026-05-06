# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

## Priority 1

### Webmentions Reliability and Compliance

- [ ] Add Salmention resend cooldown, success cutoff, and failure drop policy.
  References: `src/indieweb/senders.py` (`resend_salmentions`, `_record_outbound_target`), `src/indieweb/models.py` (`WebmentionOutboundTarget`), `tests/test_webmention_sender.py`, `tests/test_send_webmentions_command.py`, `docs/webmention.rst`.
  The shared SSRF-safe HTTP slice screens current and historical targets before discovery and delivery, but `resend_salmentions` still has no operator-tunable resend policy. Add coherent state for consecutive failures, a cooldown for historical-only resends, a success cutoff so already-successful historical targets are not re-pinged forever, and a drop/delete rule after N consecutive failures. Include migration coverage and command-output expectations.

- [ ] Harden Webmention source-link verification against non-rendered HTML and text-only matches.
  References: `src/indieweb/processors.py` (`_html_links_to_target` ~line 122, `_text_links_to_target` ~line 875), `tests/test_webmention_processor.py`.
  The verifier matches `<a href>` inside `<template>` and `<noscript>` (BeautifulSoup's `html.parser` does not extract tags from inside HTML comments, so that path is not affected), and accepts plain-text URL tokens that the source page never renders as a link. Both bypass Webmention spec §3.2.2. Skip non-rendered ancestors before searching for hrefs; only accept the text-token path when the same content's `html` also contains a real `<a href>`. Tests should include `<template>`, `<noscript>`, and text-only-token cases.

### IndieAuth and Token Security

- [ ] Restore CSRF protection for the IndieAuth consent POST and close the unauthenticated `action=deny` open redirect.
  References: `src/indieweb/views.py` (`AuthView` at line 609; deny branch at lines 736-743), `src/indieweb/templates/indieweb/consent.html`, `tests/test_auth_endpoint.py`, `tests/test_consent_screen.py`.
  `AuthView` is fully CSRF-exempt. The legacy IndieAuth verification POST (`_verify_auth_code`) is a protocol POST and should remain exempt, but the `action in {approve, deny}` branches must require a valid CSRF token. Additionally the deny branch executes its redirect *before* `request.user.is_authenticated`, so an unauthenticated attacker with a self-submitting form bounces any visitor to any HTTPS URL with `?error=access_denied&state=...`; move the auth gate above the deny branch (or require CSRF on deny). Decorate the consent GET with `@xframe_options_deny` and emit `Content-Security-Policy: frame-ancestors 'none'` to defeat clickjacking. Move inline `<style>` blocks from `consent.html:45-100` and `tokens.html:52-94` into the existing `static/css/indieweb.css` (or supply a CSP-nonce hook) so the new CSP does not require `'unsafe-inline'`. Tests: cross-site POSTs without CSRF rejected; unauthenticated `action=deny` rejected; valid consent submissions still work.

- [ ] Tighten IndieAuth bearer-token parsing and 401 response hygiene; drop POST-body `Authorization` fallback.
  References: `src/indieweb/views.py` (`TokenAuthMixin.authenticated` ~line 562; `_authorization_bearer_token` ~line 941), `tests/test_token_endpoint.py`, `tests/test_auth_endpoint.py`.
  Bearer parsing uses `parts[-1]`, silently accepting `Authorization: Bearer foo bar` and using `bar`. Require exactly two parts and a case-insensitive `bearer` scheme. `TokenAuthMixin.authenticated` reads `request.POST.get("Authorization")` as a fallback (RFC 6750 prohibits this transport; bodies leak to access logs and are CSRF-replayable) — drop the fallback; if RFC 6750 form-body transport is needed, switch to the spec-mandated `access_token=` parameter gated on `Content-Type: application/x-www-form-urlencoded`. Add `Cache-Control: no-store` and a `WWW-Authenticate` header to 401 responses.

- [ ] Add `unique=True` to `Auth.key`/`Token.key` and rotate `Token.key` on reissue.
  References: `src/indieweb/models.py:39, 68`, `src/indieweb/views.py` (`TokenAuthMixin.authenticated` ~line 562; `TokenView.post` token reissue path ~line 820), migrations, `tests/test_token_endpoint.py`, `tests/test_token_management.py`.
  `Auth.key` and `Token.key` are non-unique today. `TokenAuthMixin.authenticated` (`views.py:568`) and the auth-code lookup at `views.py:886` only catch `DoesNotExist`, so a key collision raises `MultipleObjectsReturned` and turns auth/token exchange into a 500. Add `unique=True` migrations and tighten the exception handlers. Token reissuance via `get_or_create` returns the same row, so the bearer key is never rotated for the lifetime of the `(me, client_id, scope, owner)` tuple — rotate `Token.key` on every reissue (clear the field and re-save to trigger `GenKeyMixin`). Land independently of the hash-at-rest task.

- [ ] Require token exchange `redirect_uri` to match the issued authorization request, with full normalization.
  References: `src/indieweb/views.py` (`TokenView.post` ~line 890; `_normalize_redirect_uri` at line 369), `tests/test_token_endpoint.py`, IndieAuth/OAuth authorization code flow specs.
  `TokenView.post()` only compares `redirect_uri` when the client submits one. Require it whenever the stored grant has one. `_normalize_redirect_uri` only lowercases scheme/host — it does not collapse default ports, lowercase percent-encoded triplets, normalise trailing slashes, or IDNA-encode hosts, so registered `https://example.org/cb` mismatches submitted `https://example.org:443/cb`. Apply full normalisation on both submitted and stored values. Tests: omitted, mismatched, matching, and equivalent-but-different-form pairs.

## Priority 2

### API Hardening

- [ ] Authenticate the IndieAuth token introspection endpoint per RFC 7662 §2.1.
  References: `src/indieweb/views.py` (introspection view ~lines 949-994), `src/indieweb/urls.py:23`, `tests/test_token_endpoint.py`, `docs/`.
  The endpoint currently accepts any request and returns `scope`, `me`, `client_id`, and expiry, turning a stolen token into a global validity oracle. Require a bearer credential (or HTTP Basic resource-server credential) and authorise the caller (token owner, or a configured resource-server credential). When the fix lands, document the new credential format in `docs/`; existing operators relying on the unauthenticated endpoint will need a migration note. Tests: unauthenticated POST → 401; unrelated token → no information leak; valid resource-server credential → introspection result.

- [ ] Gate JSON Micropub create/update against server-managed properties.
  References: `src/indieweb/views.py` (form allow-list ~lines 78-102; JSON path ~lines 1045-1046; `_handle_update`), `tests/test_micropub_create.py`, `tests/test_micropub_actions.py`, `tests/test_micropub_endpoint.py`.
  The JSON Micropub create path passes `data["properties"]` verbatim, bypassing the form-path allow-list `MICROPUB_FORM_CREATE_PROPERTIES` for fields the form path never accepts (e.g. `uid`, `author`). Apply an explicit deny-list of server-managed keys on both JSON and form paths before invoking `create_entry`. Apply the same gating to `update`: deny `replace`/`add`/`delete` on server-managed properties.

- [ ] Refuse CORS credentials when `Access-Control-Allow-Origin: *` is configured.
  References: `src/indieweb/cors.py`, `tests/test_cors.py`, `docs/configuration.rst`.
  When `INDIEWEB_CORS_ALLOWED_ORIGINS = "*"` and `INDIEWEB_CORS_ALLOW_CREDENTIALS = True`, the response echoes any `Origin` and sets `Access-Control-Allow-Credentials: true`. Refuse to emit credentials with wildcard origins (drop the credentials header or refuse to enable CORS), warn at startup, and document the combination as unsupported. Also: ensure `Vary: Origin` is set on rejection responses; guard against double-write of `Access-Control-Allow-Origin` if downstream middleware already set it.

## Priority 3

### API Hardening

- [ ] Add production client identity, `me`-binding, and PKCE hardening options for IndieAuth.
  References: `src/indieweb/views.py` (`_client_id_allowed` ~line 315), `src/indieweb/templates/indieweb/consent.html`, `tests/test_auth_endpoint.py`, `tests/test_token_endpoint.py`, `docs/`.
  Default `client_id` validation is permissive; the validator hook receives the raw URL with no normalisation, so allow-lists by exact match miss case-only variants. Normalise `client_id` (lowercase scheme/host, IDNA) before invoking the validator. Add/document settings for stricter client validation, requiring PKCE for public clients, and optionally requiring `S256` only. The consent screen displays the client-supplied `me` value verbatim — bind `me` to the logged-in user's configured profile or, at minimum, render the resolved profile URL alongside the request and warn on mismatch. (Note: `_client_id_allowed` already fails closed when the configured validator is unimportable — that aspect is correct and does not need changing.)

- [ ] Store access tokens hashed at rest.
  References: `src/indieweb/models.py`, `src/indieweb/views.py`, migrations, `tests/test_token_endpoint.py`, `tests/test_token_management.py`, `docs/`.
  `Token.key` is stored as a bearer secret in plaintext. Add a hashed-token storage path that returns the raw token only at issuance, authenticates by comparing a derived hash (with `hmac.compare_digest`), and provides a migration plan for existing plaintext tokens. Update admin/token-management displays so raw token values are not exposed; mask `Token.key` in `TokenAdmin` and drop `state` from `AuthAdmin.search_fields`. Land after the unique-keys task in P1.

- [ ] Strengthen Micropub media upload validation and serving guidance.
  References: `src/indieweb/views.py` (`_micropub_media_storage_name` ~line 147; `_upload_type_allowed` ~line 170), `tests/test_micropub_media.py`, `docs/configuration.rst:351`, `docs/micropub.rst:470`.
  Media uploads are filtered by client-supplied `content_type` and preserve the submitted filename suffix. Combined with the documented `INDIEWEB_MEDIA_ALLOWED_TYPES = None` option, this allows arbitrary `.html`/`.svg`/`.phtml` files to be persisted. Sniff actual format with `imghdr`/`filetype`, derive the storage suffix from the validated content-type (not the client filename), and reject mismatches between sniffed type, declared content-type, and suffix. Cap multipart upload count per request and enforce an aggregate byte cap (not just per-file). Document `X-Content-Type-Options: nosniff`, `Content-Disposition: attachment` for non-image media, separate-origin serving, and tight `DATA_UPLOAD_*` settings. Update `docs/configuration.rst` and `docs/micropub.rst` to attach a security warning to `INDIEWEB_MEDIA_ALLOWED_TYPES = None`.

- [ ] Strengthen Micropub property validation.
  References: `src/indieweb/views.py` (JSON/form parse paths, `_handle_*`, `_action_url`), `tests/test_micropub_create.py`, `tests/test_micropub_actions.py`, `docs/`.
  Apply `URLValidator(schemes=["http","https"])` to URL-typed Micropub properties (photo/audio/video/in-reply-to/like-of/repost-of/bookmark-of/syndication). Sanitise `mp-slug` (strip path separators, control chars, leading dots). Require Micropub action URLs to share host with the request. Parse `Content-Type` with `email.message.Message` rather than exact-match comparison so `application/json; charset=utf-8` is recognised as JSON.

- [ ] Document Micropub adapter ownership responsibilities and mark in-memory handler unsafe.
  References: `src/indieweb/handlers.py` (`InMemoryMicropubHandler` ~lines 310-348), `src/indieweb/interfaces.py`, `README.rst:75`, `docs/index.rst:92`.
  The reference `InMemoryMicropubHandler` ignores the `user` argument that the views pass in. Docs already point hosts at `MicropubContentHandler`, so the in-memory class is an example, not a recommended base — but it stands as a misleading example. Make the abstract base raise `NotImplementedError` with an explicit ownership requirement in the docstring; add a `# UNSAFE: example only — performs no ownership check` comment in the in-memory handler; add an "Adapter responsibilities" section to README and docs/index calling out the host's ownership-check duty for update/delete/undelete/source/media.

- [ ] Add hardened default rate-limit guidance and fix limiter primitives for public protocol endpoints.
  References: `src/indieweb/rate_limit.py`, `src/indieweb/views.py`, `docs/`, `tests/test_rate_limiting.py`.
  Built-in rate limiting is disabled unless `INDIEWEB_RATE_LIMITS` is configured; document recommended production limits for auth, token, introspection, Micropub, media, Webmention, Webmention status, and WebSub callback endpoints. Cover proxy-aware client IP guidance (the limiter intentionally ignores `X-Forwarded-For`). Replace `sha256(REMOTE_ADDR)` keying with HMAC keyed by `SECRET_KEY` (the bare digest of an IPv4 is trivially reversible). The `cache.add` + `cache.incr` pair is not atomic with redis/memcached — document best-effort behaviour and recommend a Lua-script-based limiter for hardening; fall back `Retry-After` to `config.window` when the reset key was evicted.

- [ ] Make Webmention status URLs non-enumerable or privacy-aware.
  References: `src/indieweb/views.py` (`WebmentionStatusView` ~line 2025), `src/indieweb/models.py`, migrations if needed, `tests/test_webmention_endpoint.py`.
  `WebmentionStatusView` is unauthenticated and exposes sequential integer IDs returning `source_url`, `target_url`, `vouch_url`, status, and verification timestamps. Replace integer URLs with opaque tokens, gate access on ownership/staff, or restrict the response to public-safe states (verified only) and fields (no `vouch_url`). Add tests proving unrelated Webmention records cannot be enumerated for private metadata.

- [ ] Require or strongly encourage signed WebSub deliveries; add replay protection, lease bounds, and signature-algorithm preference.
  References: `src/indieweb/websub.py`, `src/indieweb/views.py`, `src/indieweb/admin.py`, `tests/test_websub.py`, `tests/test_websub_subscriber.py`, `docs/`.
  `validate_websub_delivery_signature()` returns success when a subscription has no secret, leaving authenticity dependent on the callback token URL. Strongly recommend (or optionally require) WebSub secrets and document the callback-token-only risk. Track last-seen body digest+timestamp per subscription and reject duplicate deliveries within a window (no replay protection today). Clamp `confirmed_lease` to a configurable range (e.g. 5 min – 30 days); today hub-supplied values are unbounded. When both `X-Hub-Signature` (sha1) and `X-Hub-Signature-256` are present, prefer the strongest header and consider gating sha1 behind opt-in. Require ≥20 bytes for `hub.secret` when provided; reject empty strings distinctly from `None`. Hash/encrypt subscription `secret` and `pending_secret` at rest, exclude them from `WebSubSubscriptionAdmin`, mask `callback_token`, and override `WebSubDeliveryAttemptAdmin.has_delete_permission` to preserve audit integrity.

## Priority 4

### Housekeeping

- [ ] Tighten test/dev settings and dependency pinning.
  References: `tests/settings.py`, `pyproject.toml`, `tox.ini`.
  `tests/settings.py:17` ships a hardcoded `SECRET_KEY` with `DEBUG=True` — load from env with a sentinel default (`"insecure-test-key-do-not-use"`). `pyproject.toml` only pins Django with an upper bound; add lower bounds for `httpx`, `beautifulsoup4`, and `mf2py` (driven by known CVEs) and ship a `uv` lockfile / SBOM with releases. Add a tox env that runs full migrations (current `addopts` use `--no-migrations`).

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
