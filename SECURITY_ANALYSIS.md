# Security Analysis

Date: 2026-05-06 (initial); updated 2026-05-06 with second-pass deep review across the full codebase, then revised after independent claim-verification review.

This document summarises a security review of `django-indieweb` as a third-party Django app. It focuses on risks when the app's public IndieWeb endpoints are installed on an internet-facing Django site.

The first pass identified five high-priority findings plus several supporting ones. The second pass dispatched six parallel reviewers (IndieAuth/token, Webmention receive, Webmention sender + Micropub, WebSub, cross-cutting infrastructure, templates/h-card/static assets). An independent third pass verified each new claim against the source and downgraded several findings whose evidence did not support a High severity for a third-party Django app. This revision reflects those corrections.

## Overall Risk

- **Low risk** if only h-card/template helpers are used and protocol endpoints are not exposed.
- **Medium risk** if IndieAuth/Micropub are exposed only with strict production configuration, trusted users, rate limits, and hardened media storage.
- **High risk** if Webmention processing and the bundled Webmention rendering templates are exposed publicly with defaults.

The most urgent production blockers are:

1. Stored XSS via `|safe` rendering of remote `content_html` AND via attacker-controlled URL schemes (e.g. `javascript:`/`data:`) in `Webmention.author_url` / `Webmention.author_photo`, neither of which is scheme-validated before persistence.
2. SSRF on every outbound HTTP path: Webmention source/vouch fetches, outbound Webmention discovery and delivery, WebSub subscribe POSTs, and WebSub publish (`notify_hubs`) — none filter loopback / private / link-local / metadata addresses, and the redirect helper does not re-resolve and re-check after DNS resolution.
3. CSRF exemption on the logged-in IndieAuth consent flow PLUS an unauthenticated open-redirect via the `action=deny` branch of the same view.
4. Authorization codes are not invalidated on `redirect_uri` or scope mismatch (only PKCE failure deletes them), so a leaked code can be probed for the full TTL.

## Positive Security Properties

The codebase already has several good security choices:

- Bearer tokens and WebSub callback tokens use Django crypto helpers.
- Access tokens support expiration.
- Micropub operations enforce per-operation scopes on every action verb (create / update / delete / undelete / source / media).
- Bearer tokens are not accepted in the query string.
- Micropub media filenames are unguessable UUID-based storage keys.
- Redirect URI and client ID validation reject fragments, userinfo, and non-HTTP(S) schemes.
- The configured `INDIEWEB_CLIENT_ID_VALIDATOR` fails closed when import fails (`views.py:315`).
- `Profile.save()` calls `full_clean()` (`models.py:398`), so h-card profile URL fields are validated by Django's `URLValidator` on save (default schemes are `http`/`https`/`ftp`/`ftps`; `javascript:` and `data:` are rejected).
- WebSub HMAC delivery signatures are validated with `hmac.compare_digest` when a subscription secret is configured.
- WebSub callback URLs include high-entropy unguessable tokens (~382 bits).
- WebSub re-verification while `STATE_ACTIVE` checks `pending_mode == subscribe` before honouring (`websub.py:449`); the state machine is not silently rotated by replayed verification.
- Endpoint-scoped CORS support is configurable and disabled by default.
- A rate-limit framework exists (although it is disabled unless configured).
- `_client_identity` reads only `REMOTE_ADDR` and explicitly ignores `X-Forwarded-For` (verified by `tests/test_rate_limiting.py`).
- The token revocation endpoint correctly filters by owner and is CSRF-protected.
- The token-management view intentionally never displays `Token.key`.
- No raw SQL, `pickle`, `yaml.load`, `eval`, or `exec` anywhere in `src/` or `tests/`. No `RunPython`/`RunSQL` data migrations leak secrets.
- WebSub subscriptions are created only by trusted server code; there is no public "subscribe me" view, eliminating callback-poisoning attacks against arbitrary topics.
- WebSub callback view is correctly CSRF-exempt; authentication is by the unguessable callback token.
- Author rel=author resolution uses local h-cards only and does not perform a remote fetch (per the docstring at `processors.py:976-979`).

## High-Priority Findings

### 1. Stored XSS via Webmention HTML Rendering and Webmention URL Fields

**Severity:** Critical/High

**References:**

- `src/indieweb/processors.py` (`_extract_author_properties` ~line 1085; persistence path that calls `.save()` without `full_clean()` at lines 293, 497)
- `src/indieweb/models.py` (`Webmention.author_url`, `Webmention.author_photo`)
- `src/indieweb/templates/indieweb/webmention_types/{like,reply,mention,repost,nested_response}.html`
- `src/indieweb/templatetags/webmention_tags.py:65-66` (`mark_safe` on f-string)

Two related XSS surfaces on Webmention-derived data:

1. **`content_html|safe`**: remote source `content.html` is stored in `Webmention.content_html` and rendered with `|safe` in `reply.html:27`, `mention.html:27` (also via `truncatewords_html`), and `nested_response.html:41`. Remote `<script>`, event-handler attributes, SVG, `javascript:` links, etc. reach the rendered page unfiltered.

2. **Unvalidated URL schemes on Webmention author fields**: `Webmention.author_url` and `Webmention.author_photo` are persisted via `.save()` rather than `full_clean()`, so Django's `URLValidator` is never run. A `javascript:` `author_url` executes when a visitor clicks the author link in any of `like.html:7`, `repost.html:7`, `reply.html:9`, `mention.html:8`, or `nested_response.html:11`. A `data:image/svg+xml,<svg onload=...>` `author_photo` fires under permissive CSPs in the corresponding `<img>` tags. (h-card profile URL fields stored via `Profile.save()` are validated, because `Profile.save()` does call `full_clean()` — see `models.py:398`. Those fields are therefore not part of this finding, though they still permit `ftp`/`ftps` schemes by default and should be tightened to http/https in a separate hardening item.)

3. **`mark_safe` on an interpolated f-string in a templatetag**: `webmention_tags.webmention_endpoint_link` builds `f'<link rel="webmention" href="{endpoint_url}" />'` and `mark_safe`s it. Safe today because the endpoint URL is project-controlled, but defensive — should use `format_html`.

**Recommended fixes:**

- Sanitise `content_html` with a strict allowlist sanitizer (Bleach or equivalent). Strip dangerous tags, attributes, CSS, event handlers, and URL protocols. Prefer plain-text rendering by default; make rich HTML opt-in.
- Validate URL schemes (`http`/`https` only) before persisting `Webmention.author_url`/`author_photo`. Either call `full_clean()` from the Webmention processor or attach a stricter `URLValidator(schemes=["http","https"])` to those model fields. (Django's `URLValidator` rejects `mailto:` regardless of `schemes`; if `mailto:` author URLs are intentionally supported, add a custom validator that combines `URLValidator` with an explicit `mailto` short-circuit.)
- Replace `mark_safe(f"...")` in `webmention_tags.py:65-66` with `format_html`.
- Add `rel="nofollow noopener ugc"` and `referrerpolicy="no-referrer"` to outbound Webmention author/source links (currently only `rel="nofollow"`).
- Add regression tests submitting `<script>` payloads in `content_html` and `javascript:`/`data:` schemes in `author_url`/`author_photo` to prove malicious values do not reach rendered output.

### 2. SSRF Across All Outbound HTTP Paths

**Severity:** High

**References:**

- `src/indieweb/views.py` (`WebmentionEndpoint`)
- `src/indieweb/processors.py` (`_fetch_source` ~line 331, `_fetch_vouch` ~line 341)
- `src/indieweb/http_client.py:56` (redirect helper)
- `src/indieweb/senders.py` (`discover_endpoint` ~line 55, `fetch_content`, `send_webmention`, `extract_urls`)
- `src/indieweb/websub.py` (`_post_subscription_request` ~line 382, `notify_hubs` ~line 765)
- `src/indieweb/management/commands/notify_websub.py`

Every outbound HTTP path in the app uses `httpx` without filtering loopback, private, link-local, multicast, reserved, or metadata IP ranges, and the redirect helper screens only scheme/netloc syntactically. SSRF surfaces:

- **Webmention receive**: source and vouch fetches with attacker-controlled URLs.
- **Webmention sender**: endpoint discovery, content fetch, and POSTed delivery (note: practical risk depends on what content the sender operates on; see finding 7).
- **WebSub subscribe**: `_post_subscription_request` POSTs `hub.callback` and `hub.secret` to any operator-supplied (or templated) `hub_url`, including private/internal addresses.
- **WebSub publish**: `notify_hubs` POSTs to every URL in `INDIEWEB_WEBSUB_HUBS`.

Other contributing issues:

- The Webmention receive endpoint (`WebmentionEndpoint` at `views.py:1943`) constructs `URLValidator()` with no `schemes` argument for `source` and `target` (only the vouch validator restricts to http/https), so `ftp://` URLs are accepted at submission and persisted, where they later render as clickable links (compounding finding 1).
- `_fetch_source`/`_fetch_vouch` do not pin TLS verification explicitly; downstream env injection can downgrade.
- DNS rebinding: each request re-resolves DNS independently; redirects can land on a different IP.

**Recommended fixes:**

- Add a shared SSRF-safe HTTP helper in `http_client.py` that resolves DNS, rejects loopback / RFC1918 / link-local / multicast / reserved / `169.254.169.254` / IPv6 mapped variants, connects by IP with `Host` header, and re-applies the check on every redirect.
- Reuse the helper for **all** outbound calls: source fetch, vouch fetch, sender discovery / content / send, WebSub subscribe POST, WebSub publish.
- Restrict `WebmentionEndpoint` source/target validators to `URLValidator(schemes=["http","https"])`.
- Pin `verify=True` explicitly on every `httpx.Client`.
- Tests: direct private IPs, localhost names, DNS-to-private and redirect-to-private cases, allowed public URLs, and IPv6 bypass attempts.

### 3. Synchronous Webmention and WebSub Processing Cause DoS, Decompression Bombs, and Recursion DoS

**Severity:** High

**References:**

- `src/indieweb/views.py` (Webmention receive path; WebSub callback `views.py:1870`, `views.py:1898`)
- `src/indieweb/processors.py` (`_fetch_source` ~line 236/300, `_nested_h_entries` ~line 764, `_search_for_mentioning_entry` ~line 824)
- `src/indieweb/rate_limit.py`

When `INDIEWEB_WEBMENTION_ENQUEUE` is not configured, Webmentions are fetched, parsed, verified, and stored synchronously in the HTTP request. Both source and vouch fetches use `response.text` with no `max_bytes`. `httpx` auto-decompresses gzip/br, so a 1 MB gzip can decode to >1 GB; `raw_source_html` is then stored in the DB. Nested h-entry recursion (`_nested_h_entries`) and mentioning-entry search (`_search_for_mentioning_entry`) have no depth or breadth bound; a page with 50k nested h-entries triggers 50k DB ops.

The WebSub callback path has parallel issues:

- `request.body` is read fully into memory before the `INDIEWEB_WEBSUB_DELIVERY_MAX_BYTES` check; with Django's default `DATA_UPLOAD_MAX_MEMORY_SIZE` of 2.5 MB, attackers can flood 2 MB POSTs.
- The host delivery hook runs inline in the request thread.

**Recommended fixes:**

- Strongly recommend or require queued processing for both Webmention receive and WebSub deliveries in production (mirror `INDIEWEB_WEBMENTION_ENQUEUE` for WebSub).
- Stream responses with `httpx.Client.stream()` and abort once a configurable byte limit is exceeded.
- Tighten timeouts using `httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=2.0)` instead of single-valued long timeouts.
- Cap nested h-entry recursion depth (e.g. 8) and candidate count (e.g. 100).
- Check `Content-Length` before reading the WebSub callback body; document a tight `DATA_UPLOAD_MAX_MEMORY_SIZE`.
- Limit stored source snapshot size; document Webmention-specific rate limits.

### 4. CSRF-Exempt IndieAuth Consent POST and Unauthenticated Open Redirect

**Severity:** High

**References:**

- `src/indieweb/views.py` (`AuthView` at line 609; deny branch at lines 736-743)
- `src/indieweb/templates/indieweb/consent.html:23`

`AuthView` inherits `CSRFExemptMixin`, which exempts the entire view including the logged-in browser approve/deny POST. The template renders `{% csrf_token %}` but the exemption means the token is not enforced.

Worse, the deny branch executes the redirect *before* the `request.user.is_authenticated` check. Combined with the CSRF exemption, an unauthenticated attacker can host a self-submitting form that bounces any visitor to any HTTPS URL with `?error=access_denied&state=<attacker_value>`. This both phishes and provides an OAuth-style state-injection primitive.

**Recommended fixes:**

- Split CSRF behaviour: the legacy IndieAuth verification POST (`_verify_auth_code`) is a protocol POST and should remain CSRF-exempt; the `action in {approve, deny}` branches must require a valid CSRF token.
- Move the `is_authenticated` gate above the deny branch, or require CSRF on deny too.
- Decorate the consent GET with `@xframe_options_deny` and add `Content-Security-Policy: frame-ancestors 'none'` to defeat clickjacking.
- Tests: cross-site-style POSTs without CSRF rejected; unauthenticated `action=deny` rejected; valid consent submissions still succeed.

### 5. Authorization Code Single-Use Is Incomplete

**Severity:** High

**References:**

- `src/indieweb/views.py` (`TokenView.post` deletion at line 921; PKCE deletion paths at 844; mismatch returns at 893/903)

Only PKCE failure and the happy path delete the authorization code. Mismatched `redirect_uri` and mismatched `scope` paths return errors but leave the code intact, so a leaked code can be probed for the full 60-second TTL with different `redirect_uri`/`scope` values until one is accepted.

**Related issues found in the same review:**

- Authorization codes are interpolated into log records cleartext (`views.py:873`); tokens are already truncated.
- `Auth.key` and `Token.key` are not `unique=True` (`models.py:39, 68`). `TokenAuthMixin.authenticated` (`views.py:568`) and the auth-code lookup at `views.py:886` only catch `DoesNotExist`, so a key collision raises `MultipleObjectsReturned` and turns auth/token exchange into a 500.
- `_authorization_bearer_token` and `TokenAuthMixin.authenticated` (`views.py:941`) use `parts[-1]`, accepting `Authorization: Bearer foo bar` and silently using `bar`.
- Token reissuance via `get_or_create` (`views.py:820`) returns the same row, so the bearer key is never rotated for the lifetime of the `(me, client_id, scope, owner)` tuple.

**Recommended fixes:**

- Call `auth.delete()` in every grant-validation failure path inside the token exchange `try:` block.
- Redact authorization codes in log records (e.g. `code[:6] + "..."`).
- Add `unique=True` to `Auth.key` and `Token.key`; tighten the `MultipleObjectsReturned` handler.
- Require `parts[0].lower() == "bearer"` and exactly two parts in bearer parsing.
- Rotate `Token.key` on every reissue (clear and re-save to trigger `GenKeyMixin`).

### 6. Token Endpoint Does Not Require `redirect_uri` on Exchange

**Severity:** Medium/High

**References:**

- `src/indieweb/views.py` (`TokenView.post` ~line 890; `_normalize_redirect_uri` at line 369)

`TokenView.post()` compares `redirect_uri` only if the client submits one. If an authorisation code was issued with a redirect URI, the exchange should require the same value. Otherwise a leaked code can be redeemed with only the `client_id`, unless PKCE was used.

In addition, `_normalize_redirect_uri` only lowercases scheme/host. It does not collapse default ports, lowercase percent-encoded triplets, normalise trailing slashes, or IDNA-encode host names, so registered `https://example.org/cb` mismatches submitted `https://example.org:443/cb` and vice versa.

**Recommended fixes:**

- Require `redirect_uri` whenever the stored authorisation grant has one.
- Normalise both submitted and stored values: lowercase scheme/host, IDNA-encode, collapse default ports, lowercase percent-encoded triplets.
- Tests: omitted, mismatched, matching, and equivalent-but-different-form redirect URIs.
- Consider requiring PKCE (preferably `S256`) for public clients.

### 7. Outbound Sender Exfiltration via Attacker-Controlled Links (Conditional)

**Severity:** High when the sender is run automatically against published content that may contain user-influenced HTML; Medium otherwise (operator-only manual runs against trusted-author content).

**References:**

- `src/indieweb/senders.py` (`extract_urls` ~line 21; `_extract_external_target_urls` ~line 298; `discover_endpoint`/`send_webmention` ~line 216; `resend_salmentions` ~line 264)
- `src/indieweb/management/commands/send_webmentions.py`

`extract_urls` walks every `<a href>` in a published post; `_extract_external_target_urls` then filters to absolute external HTTP(S) URLs before delivery. The filter does NOT reject loopback, RFC1918, link-local, multicast, or `169.254.169.254` targets. If the source HTML can contain user-influenced content (multi-author CMS, comments, untrusted markdown) and the host wires the sender to fire automatically on save, an attacker plants a single `<a href="http://192.168.1.1/admin?...">` and the server delivers attacker-controlled `source`/`target`/`vouch` form fields to internal hosts on every send.

`resend_salmentions` re-POSTs to *every* historical target ever seen for a `source_url`, with no cooldown, throttle, or success cutoff — once an attacker URL is recorded in `WebmentionOutboundTarget`, the host pings it forever.

**Recommended fixes:**

- Reuse the SSRF-safe helper (finding 2) for every outbound HTTP call in `senders.py`.
- Apply the SSRF screen to the *target* URL before discovery, not just to redirect hops.
- Cap response body sizes; tighten per-phase timeouts.
- Add cooldowns and a success cutoff to `resend_salmentions`; drop history rows after N consecutive failures.
- Document that hosts which call the sender automatically on save MUST sanitise content for user-controlled URLs first, or use a deny-list of internal targets.

### 8. Micropub Media: No Magic-Byte Validation, Suffix from Client

**Severity:** High

**References:**

- `src/indieweb/views.py` (`_micropub_media_storage_name` ~line 147; `_upload_type_allowed` ~line 170)
- `docs/configuration.rst:351`, `docs/micropub.rst:470` (documenting `INDIEWEB_MEDIA_ALLOWED_TYPES = None`)

Media uploads are filtered by `upload.content_type` (client-controlled) and the saved path preserves the lowercased final filename suffix only. Combined with the documented `INDIEWEB_MEDIA_ALLOWED_TYPES = None` option, this allows arbitrary `.html` / `.svg` / `.phtml` files to be stored under MEDIA_URL. Even with the default allow-list, a client can declare `Content-Type: image/png` while uploading `evil.svg`, and the file is persisted with the `.svg` suffix it shipped.

**Recommended fixes:**

- Sniff actual format with `imghdr`/`filetype` (or a vetted equivalent) and reject mismatches between sniffed type, declared content-type, and filename suffix.
- Derive the storage suffix from the *validated* content-type, not the client-supplied filename. Maintain an explicit safe-suffix allow-list.
- Document required serving headers (`X-Content-Type-Options: nosniff`, `Content-Disposition: attachment` for non-image media), media on a separate origin, and `DATA_UPLOAD_MAX_NUMBER_FILES`/`DATA_UPLOAD_MAX_MEMORY_SIZE` settings.
- Cap multipart upload count per request; enforce an aggregate byte cap, not just per-file.

## Additional Findings

### IndieAuth Token Introspection Endpoint Is Unauthenticated

**Severity:** Medium

**References:** `src/indieweb/views.py:949-994`, `src/indieweb/urls.py:23`.

RFC 7662 §2.1 requires the introspection endpoint to authenticate the caller. The current view accepts any request and returns scope, `me`, `client_id`, and expiry for any token an attacker possesses. This is a privacy/spec issue rather than a direct auth bypass — exploitation requires possession of a high-entropy token — but it lets an attacker turn a stolen token into a global validity oracle and confirm scope/expiry without proof of capture timing.

**Recommendation:** Require a bearer token (or HTTP Basic resource-server credential). Authorise the caller as the token's owner or a configured resource-server credential. Tests: unauthenticated POST → 401; valid resource-server credential → result; unrelated token → no information leak.

### Micropub Adapter Ownership Is Documentation Debt

**Severity:** Medium

**References:** `src/indieweb/handlers.py:310-348` (`InMemoryMicropubHandler`), `src/indieweb/views.py` (`_handle_update`/`_handle_delete`/`_handle_undelete`/`_handle_source_query`), `README.rst:75`, `docs/index.rst:92`.

The Micropub views pass `self.token.owner` to the adapter. The reference `InMemoryMicropubHandler` ignores the `user` argument, but the documentation tells hosts to subclass `MicropubContentHandler`, not the in-memory class. This is therefore guidance debt rather than a direct app-level IDOR: hosts that follow the docs implement their own adapter and bear ownership-check responsibility, but the in-memory class stands as a misleading example.

**Recommendation:** Make the abstract base raise `NotImplementedError` with an explicit ownership requirement in the docstring. Mark the in-memory handler as `# UNSAFE: example only — performs no ownership check`. Document the host's ownership-check responsibility prominently.

### Bearer Token Accepted From POST Body

**Severity:** Medium

**References:** `src/indieweb/views.py:562` (`TokenAuthMixin.authenticated`).

`TokenAuthMixin.authenticated` reads `request.POST.get("Authorization")` as a fallback. Form bodies are written to proxy access logs and are replayable in CSRF-style attacks. RFC 6750 prohibits this transport; the spec-mandated alternative is the `access_token=` form parameter and only on `Content-Type: application/x-www-form-urlencoded`.

**Recommendation:** Drop the `request.POST["Authorization"]` fallback. If RFC 6750 form-body transport is needed, switch to `access_token=` gated on form-encoded content type. Add `Cache-Control: no-store` and a `WWW-Authenticate` header to 401 responses.

### JSON Micropub Path Bypasses Property Allow-List

**Severity:** Medium

**References:** `src/indieweb/views.py:78-102` (form allow-list), `src/indieweb/views.py:1045` (JSON path passes properties verbatim).

The JSON Micropub create path passes `data["properties"]` verbatim to the handler, bypassing the form-path allow-list `MICROPUB_FORM_CREATE_PROPERTIES`. The form-path allow-list does include `published` and `url`, so those are not bypass examples; however a token with `create` scope can smuggle properties the form path never accepts, such as `uid` or `author`, through JSON. The same gap applies to `update`, where `replace`/`add`/`delete` operations are not gated on which properties may be modified.

**Recommendation:** Apply an explicit deny-list of server-managed keys (e.g. `uid`, `author`, plus any host-defined `_owner`/internal keys) on both JSON and form paths before invoking `create_entry`. Apply the same gating to `update`.

### WebSub Subscription Secrets and Token-Equivalent Fields Are Editable in Admin

**Severity:** Medium

**References:** `src/indieweb/admin.py:98` (WebSub fieldsets), `src/indieweb/admin.py:160` (`TokenAdmin` exposes `key`), `src/indieweb/admin.py:196` (`AuthAdmin.search_fields` includes `state`), `src/indieweb/models.py:308-310` (`secret`/`pending_secret` as plain `CharField`).

`WebSubSubscriptionAdmin` lists `secret` and `pending_secret` in editable fieldsets. Any staff user with view-only permissions sees the active HMAC key, defeating signature authenticity. The Token admin exposes `Token.key` in the change form; the `Auth` admin's `search_fields` includes `state`, enabling staff-side enumeration of IndieAuth state values. Practical exposure depends on admin-user policy but the surface is unnecessary.

**Recommendation:** Hash or encrypt subscription secrets at rest; remove `secret`/`pending_secret`/`callback_token` from admin entirely (or render as masked under `is_superuser`). Strip secrets from `__str__` and any logging. Drop `state` from `AuthAdmin.search_fields`; mask `Token.key` in `TokenAdmin`. Override `WebSubDeliveryAttemptAdmin.has_delete_permission` to `False` to preserve audit integrity.

### CORS Wildcard + Credentials Bypasses Origin Check

**Severity:** Medium

`src/indieweb/cors.py:97-109` — when `INDIEWEB_CORS_ALLOWED_ORIGINS = "*"` and `INDIEWEB_CORS_ALLOW_CREDENTIALS = True`, the response echoes any `Origin` and sets `Access-Control-Allow-Credentials: true`. Since Micropub and Media use bearer-token auth (not cookies), this is not a single-step browser-session takeover; but any cross-origin site can ride a session-authenticated browser request whose token is provided via cookie-bridged adapters or page-level fetch tooling.

**Recommendation:** Refuse to honour credentials when wildcard origins are configured (drop the credentials header or refuse to enable CORS) and warn at startup. Document this combination as unsupported.

### Rate Limiter Identity Hash Is Trivially Reversible; Counter Is Not Atomic

**Severity:** Medium

`rate_limit.py:86-88, 110-117` — `sha256(REMOTE_ADDR)` of an IPv4 is trivially reversible by exhaustive enumeration (4 billion keys), so the digest is not a privacy control. The `cache.add` + `cache.incr` pair is not atomic under contention with redis/memcached, allowing burst-over-limit.

**Recommendation:** HMAC the IP with `SECRET_KEY`. Document the limiter as best-effort and recommend a redis Lua-script-based limiter for hardening. Fall back `Retry-After` to `config.window` when the reset key was evicted.

### WebmentionStatusView Leaks Vouch URL and Pending Metadata Anonymously

**Severity:** Medium (refines first-pass enumeration finding)

`views.py:2025` — `WebmentionStatusView` is unauthenticated and its sequential `<int:pk>` URL exposes every Webmention's `source_url`, `target_url`, `vouch_url`, status, and verification timestamps. This leaks attacker-probe pending state, vouch URLs that may be private, and any private/draft post URL that happens to be a Webmention target.

**Recommendation:** Replace integer IDs with opaque tokens, gate access on ownership/staff, or restrict the response to public-safe states (verified only) and fields (no `vouch_url`).

### Webmention Source Verification Is Too Permissive

**Severity:** Medium

`processors.py:122, 875` — `_html_links_to_target` matches `<a href>` inside non-rendered ancestors such as `<template>` and `<noscript>` (BeautifulSoup's `html.parser` does not extract tags from inside HTML comments, and `<script>`/`<style>` content is parsed as text, so those paths are not affected). `_text_links_to_target` matches plain-text URL tokens that the source page never renders as a link. Both bypass the Webmention spec §3.2.2 requirement that the source actually link to the target.

**Recommendation:** Skip non-rendered ancestors (`<template>`, `<noscript>`, `<head>` except canonical/related rels) in `_html_links_to_target`. Only accept the text-token path when the same content's `html` also contains a real `<a href>`.

### WebSub: No Replay Protection, No Lease Bounds, Algorithm Confusion

**Severity:** Medium

- `websub.py:630-653` — signed deliveries have no nonce/timestamp/freshness check; a captured payload replays forever.
- `websub.py:159-168, 458-465` — `lease_seconds` is unbounded; a hub returning `10**12` produces effectively-permanent subscriptions.
- `websub.py:644-652` — when both `X-Hub-Signature` (sha1) and `X-Hub-Signature-256` (sha256) are present, either-validates wins, allowing a hub to downgrade to sha1.
- `websub.py:621-627` — `_signature_headers` uses fixed-case keys; works with `request.headers` (case-insensitive) but not with plain dict callers.
- `websub.py:290-292, 378` — empty/short `hub.secret` is silently accepted as "no secret"; spec says the secret must be ≥1 byte and ≤200 bytes.

**Recommendations:** Track last-seen body digest+timestamp per subscription. Clamp lease to `[5 min, 30 days]` (configurable). Prefer the strongest signature header present; gate sha1 behind opt-in. Normalise header lookups. Require ≥20 bytes for `hub.secret` when provided.

### Client Trust Is Permissive by Default

By default, structurally valid `client_id` URLs are accepted unless `INDIEWEB_CLIENT_ID_VALIDATOR` is configured. The validator hook receives the raw URL with no normalisation, so allow-lists by exact match miss case-only variants. (Note: when configured but unimportable, the hook DOES fail closed at `views.py:315`; that aspect is correct.)

**Recommendation:** Document strict production client validation. Normalise `client_id` (lowercase scheme/host, IDNA) before invoking the validator.

### `me` Is Not Bound to the Logged-In User and Is Echoed on the Consent Screen

The authorisation request accepts and stores arbitrary `me` values; the consent screen displays this client-supplied value verbatim, providing a phishing surface where a hostile client renders `me=https://victim.example/` to mislead the user.

**Recommendation:** Add a setting/hook to bind `me` to the logged-in user's configured IndieWeb identity. On the consent screen, display the resolved (server-validated) profile URL alongside the requested `me` and warn on mismatch.

### Access Tokens Are Stored in Plaintext

`Token.key` is stored directly in the database. A database-read compromise yields live bearer tokens. `Auth.key` and `Token.key` are also not `unique=True`, so a (vanishingly unlikely) collision raises `MultipleObjectsReturned`.

**Recommendation:** Store only a hash; return the raw token at issuance only; authenticate by comparing derived hashes (with `hmac.compare_digest`). Add `unique=True` migrations for both keys.

### Micropub Property Validation Gaps

- `mp-slug` and `mp-syndicate-to` reach the handler unsanitised.
- Photo/audio/video/in-reply-to/like-of/repost-of/bookmark-of/syndication URL fields are not validated as `http(s)://`; `javascript:` and `file:///` reach the handler.
- `_action_url`/`_handle_delete` accept any URL; adapters that key on URL substrings can be tricked by cross-origin URLs.
- `request.content_type` is compared exactly to `application/json`, so `application/json; charset=utf-8` falls into the form-encoded branch.

**Recommendation:** Apply `URLValidator(schemes=["http","https"])` to URL-typed Micropub properties at the view boundary. Require Micropub action URLs to share host with the request. Parse the media type with `email.message.Message`/`cgi.parse_header`.

### Rate Limiting Is Disabled by Default

`INDIEWEB_RATE_LIMITS` defaults to disabled across auth, token, introspection, Micropub, media, Webmention, Webmention status, and WebSub callback endpoints.

**Recommendation:** Document hardened production limits per endpoint. Consider shipping conservative defaults or a helper settings snippet. Cover proxy-aware client IP guidance (the limiter intentionally ignores `X-Forwarded-For`).

### Test Settings Hardcode `SECRET_KEY` and `DEBUG=True`

`tests/settings.py:17` ships a hardcoded key with `DEBUG=True`. Low risk since it is test-only, but a project that mistakenly imports `tests.settings` runs with that combination.

**Recommendation:** Load from env with a sentinel default (`"insecure-test-key-do-not-use"`).

### Dependency Pinning

`pyproject.toml` only pins Django with an upper bound. Downstream installs may pull vulnerable `httpx`, `beautifulsoup4`, or `mf2py`.

**Recommendation:** Add lower bounds for known-CVE versions; ship a `uv` lockfile and SBOM with releases.

### Inline Styles in Bundled Templates

`consent.html:45-100` and `tokens.html:52-94` carry inline `<style>` blocks. Operators with strict CSPs (no `'unsafe-inline'`, no hash/nonce) will see broken rendering or be forced to weaken CSP.

**Recommendation:** Move styles into `static/css/indieweb.css` or provide a CSP-nonce hook.

### WebSub Deliveries Without Secrets Rely on Callback Token Only

`validate_websub_delivery_signature()` returns success when a subscription has no secret. Authenticity then depends on the unguessable callback URL token. Combined with the WebSub renewal logic, secrets persist across re-verifications even when a hub returns a new `hub.secret`-less response.

**Recommendation:** Strongly recommend or optionally require WebSub secrets for subscriptions where supported. Rotate `Subscription.callback_token` on every successful resubscribe. Clear `secret` on successful re-verify when `pending_secret_set` is False.

## Recommended Fix Order

1. Sanitise Webmention HTML; validate URL schemes on Webmention author fields and the templatetag `mark_safe` site.
2. Add a single SSRF-safe HTTP helper and route every outbound HTTP path through it (Webmention receive, Webmention sender, WebSub subscribe, WebSub publish). Restrict source/target URL validators to http/https.
3. Restore CSRF protection for IndieAuth consent approve/deny POSTs; move the authentication gate above the deny branch; add `xframe_options_deny` and `frame-ancestors 'none'`.
4. Delete authorisation codes on every grant-validation failure; redact codes in logs; rotate token keys on reissue; require strict bearer-token parsing.
5. Add Webmention/WebSub fetch size limits, response streaming, queue guidance, and rate-limit defaults; cap nested h-entry recursion; check `Content-Length` before reading WebSub body.
6. Require token-exchange `redirect_uri` matching with full normalisation (default ports, IDNA, percent-encoding).
7. Add Micropub media magic-byte validation, derive suffix from validated content-type, cap multipart counts, document safe serving headers.
8. Authenticate the introspection endpoint per RFC 7662.
9. Drop the POST-body `Authorization` fallback; apply the JSON-path Micropub property allow-list; gate `update` on server-managed properties.
10. Refuse CORS credentials when `Access-Control-Allow-Origin: *` is configured.
11. Add stricter IndieAuth client/PKCE/`me` policy options (incl. consent-screen warning when `me` does not match the logged-in user's profile).
12. Hash access tokens at rest; add `unique=True` to `Auth.key`/`Token.key`.
13. Mask WebSub subscription secrets, Token.key, and Auth.state in the admin; preserve delivery-attempt audit records; document Micropub adapter ownership responsibilities.
14. Make Webmention status URLs non-enumerable or privacy-aware; harden source-link verification against non-rendered ancestors and plain-text-only matches.
15. Require or strongly recommend signed WebSub deliveries; add replay protection, lease bounds, and signature-algorithm preference.

## Documentation Impact

Several findings are partially or wholly documentation/guidance items. When the corresponding code fixes land, the user-facing docs must change in the same release:

- **`INDIEWEB_MEDIA_ALLOWED_TYPES = None`** (`docs/configuration.rst:351`, `docs/micropub.rst:470`): currently documented as a way to disable type filtering. Add an explicit security warning that this disables file-type validation entirely and requires the host to serve media on a separate origin with `X-Content-Type-Options: nosniff` and `Content-Disposition: attachment`.
- **Micropub adapter ownership**: README and docs/index point hosts at `MicropubContentHandler`. Add a prominent section ("Adapter responsibilities") that the adapter MUST enforce ownership on update/delete/undelete/source — referencing the `user` argument and the in-memory example as `# UNSAFE`.
- **Media serving headers**: docs/configuration should describe required serving headers and storage isolation when the host serves media themselves.
- **CORS configuration**: docs/configuration.rst should explicitly call out that wildcard `Access-Control-Allow-Origin` with `Access-Control-Allow-Credentials: true` is unsupported, and the app will refuse to emit credentials in that combination once the fix lands.
- **WebSub secret handling**: docs should recommend secrets for all production subscriptions, document the callback-token-only risk for unsigned deliveries, and warn against operator-supplied hub URLs that resolve to private addresses.
- **Token introspection authentication**: when the fix lands, docs must show the resource-server credential format and behaviour change. Operators relying on the current unauthenticated endpoint will need a migration note.
- **Rate limit defaults**: when defaults change, docs/configuration must list the new floors and the proxy-aware-IP guidance (the limiter intentionally ignores `X-Forwarded-For`).
- **`AGENTS.md`**: no change needed.

## Current Backlog Coverage

The recommended work is mirrored in `BACKLOG.md`, restructured after this revision so that each task corresponds to a single coherent PR.
