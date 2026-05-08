# Security Analysis

Date: 2026-05-06 (initial); updated 2026-05-06 with second-pass deep review across the full codebase, then revised after independent claim-verification review; updated 2026-05-07 after implementation verification and residual-risk review.

This document summarises a security review of `django-indieweb` as a third-party Django app. It focuses on risks when the app's public IndieWeb endpoints are installed on an internet-facing Django site.

The first pass identified five high-priority findings plus several supporting ones. The second pass dispatched six parallel reviewers (IndieAuth/token, Webmention receive, Webmention sender + Micropub, WebSub, cross-cutting infrastructure, templates/h-card/static assets). An independent third pass verified each new claim against the source and downgraded several findings whose evidence did not support a High severity for a third-party Django app. This revision reflects those corrections.

## Overall Risk

- **Low risk** if only h-card/template helpers are used and protocol endpoints are not exposed.
- **Medium risk** if IndieAuth/Micropub are exposed only with strict production configuration, trusted users, rate limits, and hardened media storage.
- **High risk** if Webmention processing and the bundled Webmention rendering templates are exposed publicly with defaults.

The most urgent remaining production blockers are:

1. (resolved 2026-05-07) ~~Residual SSRF DNS rebinding / TOCTOU risk~~. The
   shared outbound helpers in ``http_client.py`` now resolve the URL host
   once, validate every returned IP, and connect to the resolved IP literal
   while the original ``Host`` header is preserved and the original hostname
   is forwarded as ``extensions["sni_hostname"]`` for HTTPS. The pin is
   re-applied on every redirect hop. A DNS rebinding host that resolves to a
   public address during validation and to a private address during the
   subsequent connect is now caught before the second connection is made.
2. (resolved 2026-05-07) ~~Residual Webmention parser recursion DoS risk~~.
3. (resolved 2026-05-07) ~~Residual WebSub replay window gap~~.

Former production blockers that were verified fixed by 2026-05-07 include Webmention stored XSS/unsafe remote URL rendering, IndieAuth consent CSRF/open redirect, authorization-code one-time-use gaps, token exchange `redirect_uri` binding, token parsing/reissue hardening, Micropub media sniffing, introspection authentication, token hashing at rest, CORS wildcard credentials, and WebSub signature/lease/secret hardening.

## Verification Status 2026-05-07

The 2026-05-07 verification pass reviewed `SECURITY_ANALYSIS.md` against the current source and ran focused security regression tests:

```bash
uv run pytest tests/test_http_client.py tests/test_webmention_endpoint.py tests/test_webmention_processor.py tests/test_webmention_templatetags.py tests/test_auth_endpoint.py tests/test_consent_screen.py tests/test_token_endpoint.py tests/test_micropub_endpoint.py tests/test_micropub_create.py tests/test_micropub_media.py tests/test_cors.py tests/test_rate_limiting.py tests/test_websub.py tests/test_websub_subscriber.py tests/test_admin.py -q --no-cov
```

Result: `792 passed in 41.31s`.

The pass found no new token, consent, Micropub media/property, CORS, admin-secret, or stored-XSS regressions beyond the three residual issues listed above.

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

**Status:** Resolved and verified 2026-05-07. Remote Webmention `content_html`
and nested response HTML are sanitized with an allowlist before persistence and
again before bundled template rendering; remote author URL/photo values are
restricted to absolute HTTP(S) URLs; bundled Webmention links now include
`rel="nofollow noopener ugc"` and `referrerpolicy="no-referrer"`; and
`webmention_endpoint_link` uses `format_html`. Regression coverage exists for
script/event/SVG/form/iframe/style stripping and unsafe `javascript:`/`data:`
author URL fields.

**References:**

- `src/indieweb/processors.py` (`_extract_author_properties` ~line 1085; persistence path that calls `.save()` without `full_clean()` at lines 293, 497)
- `src/indieweb/models.py` (`Webmention.author_url`, `Webmention.author_photo`)
- `src/indieweb/templates/indieweb/webmention_types/{like,reply,mention,repost,nested_response}.html`
- `src/indieweb/templatetags/webmention_tags.py:65-66` (`mark_safe` on f-string)

Two related XSS surfaces on Webmention-derived data:

1. **`content_html|safe`**: remote source `content.html` is stored in `Webmention.content_html` and rendered with `|safe` in `reply.html:27`, `mention.html:27` (also via `truncatewords_html`), and `nested_response.html:41`. Remote `<script>`, event-handler attributes, SVG, `javascript:` links, etc. reach the rendered page unfiltered.

2. **Unvalidated URL schemes on Webmention author fields**: `Webmention.author_url` and `Webmention.author_photo` are persisted via `.save()` rather than `full_clean()`, so Django's `URLValidator` is never run. A `javascript:` `author_url` executes when a visitor clicks the author link in any of `like.html:7`, `repost.html:7`, `reply.html:9`, `mention.html:8`, or `nested_response.html:11`. A `data:image/svg+xml,<svg onload=...>` `author_photo` fires under permissive CSPs in the corresponding `<img>` tags. (h-card profile URL fields stored via `Profile.save()` are validated, because `Profile.save()` does call `full_clean()` — see `models.py:398`. As of 2026-05-08, those fields and the synced `Profile.url`/`Profile.photo_url` columns are restricted to `http`/`https` at the model layer and re-sanitized at template render time via the `h_card_safe_url` filter, closing bypass paths such as `QuerySet.update`, `bulk_update`, raw SQL, and fixture loads.)

3. **`mark_safe` on an interpolated f-string in a templatetag**: `webmention_tags.webmention_endpoint_link` builds `f'<link rel="webmention" href="{endpoint_url}" />'` and `mark_safe`s it. Safe today because the endpoint URL is project-controlled, but defensive — should use `format_html`.

**Recommended fixes:**

- Sanitise `content_html` with a strict allowlist sanitizer (Bleach or equivalent). Strip dangerous tags, attributes, CSS, event handlers, and URL protocols. Prefer plain-text rendering by default; make rich HTML opt-in.
- Validate URL schemes (`http`/`https` only) before persisting `Webmention.author_url`/`author_photo`. Either call `full_clean()` from the Webmention processor or attach a stricter `URLValidator(schemes=["http","https"])` to those model fields. (Django's `URLValidator` rejects `mailto:` regardless of `schemes`; if `mailto:` author URLs are intentionally supported, add a custom validator that combines `URLValidator` with an explicit `mailto` short-circuit.)
- Replace `mark_safe(f"...")` in `webmention_tags.py:65-66` with `format_html`.
- Add `rel="nofollow noopener ugc"` and `referrerpolicy="no-referrer"` to outbound Webmention author/source links (currently only `rel="nofollow"`).
- Add regression tests submitting `<script>` payloads in `content_html` and `javascript:`/`data:` schemes in `author_url`/`author_photo` to prove malicious values do not reach rendered output.

### 2. SSRF Across All Outbound HTTP Paths

**Severity:** High

**Status:** Resolved 2026-05-07. The shared outbound HTTP helper screens URL
syntax, private/loopback/link-local/reserved IP literals, DNS names that
resolve to blocked addresses, and unsafe redirects; direct receive, sender,
WebSub subscribe, and WebSub publish paths route through it with explicit
TLS verification and bounded redirects. As of 2026-05-07 the helper resolves
the URL host once, validates every returned IP, and connects to the resolved
IP literal while preserving the original ``Host`` header and forwarding the
original hostname as ``extensions["sni_hostname"]`` for HTTPS, closing the
DNS rebinding / TOCTOU window. The pin is re-applied on every redirect hop.

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

**Status:** Partially resolved 2026-05-07. Webmention source/vouch fetches and
sender fetches now stream decoded content with a default 1 MiB cap and tighter
timeouts; Webmention nested-response extraction and primary
`_search_for_mentioning_entry` traversal have depth/item limits; WebSub delivery
checks `Content-Length` before reading and enforces a configured body-size cap.
Remaining gap: fallback Webmention h-entry and h-card search paths such as
`_search_for_any_h_entry`, `_search_items_for_h_card`,
`_search_items_for_h_card_id`, and page-level h-card collection are still
recursive and uncapped. The inline WebSub host hook also remains a deployment
hardening consideration.

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

**Status:** Resolved 2026-05-06. Browser consent `action=approve` and
`action=deny` POSTs now run Django's CSRF check while the legacy IndieAuth
authorization-code verification POST remains CSRF-exempt. The consent
authentication gate now runs before approve/deny redirect handling, so
unauthenticated denial submissions no longer redirect to client-supplied
`redirect_uri` values. The consent screen now emits `X-Frame-Options: DENY`
and `Content-Security-Policy: frame-ancestors 'none'`, and bundled consent and
token-management inline styles moved into `static/css/indieweb.css`.

**References:**

- `src/indieweb/views.py` (`AuthView` at line 609; deny branch at lines 736-743)
- `src/indieweb/templates/indieweb/consent.html:23`

Historical finding:

`AuthView` inherited `CSRFExemptMixin`, which exempted the entire view including the logged-in browser approve/deny POST. The template rendered `{% csrf_token %}` but the exemption meant the token was not enforced.

Worse, the deny branch executed the redirect *before* the `request.user.is_authenticated` check. Combined with the CSRF exemption, an unauthenticated attacker could host a self-submitting form that bounced any visitor to any HTTPS URL with `?error=access_denied&state=<attacker_value>`. This both phished and provided an OAuth-style state-injection primitive.

**Recommended fixes:**

- Split CSRF behaviour: the legacy IndieAuth verification POST (`_verify_auth_code`) is a protocol POST and should remain CSRF-exempt; the `action in {approve, deny}` branches must require a valid CSRF token.
- Move the `is_authenticated` gate above the deny branch, or require CSRF on deny too.
- Decorate the consent GET with `@xframe_options_deny` and add `Content-Security-Policy: frame-ancestors 'none'` to defeat clickjacking.
- Tests: cross-site-style POSTs without CSRF rejected; unauthenticated `action=deny` rejected; valid consent submissions still succeed.

### 5. Authorization Code Single-Use Is Incomplete

**Severity:** High

**Status:** Resolved 2026-05-06 for the authorization-code single-use slice.
`TokenView.post` now consumes a matched `Auth` row on PKCE failures,
`redirect_uri` mismatches, scope mismatches, and expired-code failures before
returning the existing `invalid_grant` response. Token endpoint logs now redact
authorization codes. Resolved 2026-05-06 for the adjacent bearer parsing,
key uniqueness, duplicate-lookup handling, and token reissue rotation slice:
bearer headers must now be strict two-part `Authorization: Bearer <token>`
values, POST-body `Authorization` fallback is removed, token-protected 401
responses include `Cache-Control: no-store` and `WWW-Authenticate: Bearer`,
`Auth.key` and `Token.key` are unique, duplicate-key lookups fail closed, and
token reissue rotates the existing row's bearer key.

**References:**

- `src/indieweb/views.py` (`TokenView.post` deletion at line 921; PKCE deletion paths at 844; mismatch returns at 893/903)

Historical finding:

Only PKCE failure and the happy path delete the authorization code. Mismatched `redirect_uri` and mismatched `scope` paths return errors but leave the code intact, so a leaked code can be probed for the full 60-second TTL with different `redirect_uri`/`scope` values until one is accepted.

**Related issues found in the same review:**

- Authorization codes were interpolated into log records cleartext (`views.py:873`); tokens were already truncated. Resolved 2026-05-06.
- `Auth.key` and `Token.key` were not `unique=True` (`models.py:39, 68`), and duplicate-key lookups could raise `MultipleObjectsReturned`. Resolved 2026-05-06.
- `_authorization_bearer_token` and `TokenAuthMixin.authenticated` (`views.py:941`) used `parts[-1]`, accepting `Authorization: Bearer foo bar` and silently using `bar`. Resolved 2026-05-06.
- Token reissuance via `get_or_create` (`views.py:820`) returned the same row without rotating the bearer key. Resolved 2026-05-06.

**Recommended fixes:**

- Call `auth.delete()` in every grant-validation failure path inside the token exchange `try:` block.
- Redact authorization codes in log records (e.g. `code[:6] + "..."`).
- Add `unique=True` to `Auth.key` and `Token.key`; tighten the `MultipleObjectsReturned` handler.
- Require `parts[0].lower() == "bearer"` and exactly two parts in bearer parsing.
- Rotate `Token.key` on every reissue (clear and re-save to trigger `GenKeyMixin`).

### 6. Token Endpoint Does Not Require `redirect_uri` on Exchange

**Severity:** Medium/High

**Status:** Resolved 2026-05-06. Token exchange now requires `redirect_uri`
when the matched authorization code stores one. Omitted required values and
mismatches return the existing `invalid_grant` response and consume the matched
auth code. Matching now normalizes scheme/host case, IDNA host form, default
ports, percent-encoded triplet case, and root empty-path/`/` equivalence while
preserving non-default ports, non-root paths, and query strings. Malformed
submitted `redirect_uri` values remain pre-lookup `invalid_grant` failures and
do not delete unrelated auth-code rows.

**References:**

- `src/indieweb/views.py` (`TokenView.post` ~line 890; `_normalize_redirect_uri` at line 369)

Historical finding:

`TokenView.post()` compared `redirect_uri` only if the client submitted one. If an authorisation code was issued with a redirect URI, the exchange should require the same value. Otherwise a leaked code could be redeemed with only the `client_id`, unless PKCE was used.

In addition, `_normalize_redirect_uri` only lowercased scheme/host. It did not collapse default ports, lowercase percent-encoded triplets, normalise trailing slashes, or IDNA-encode host names, so registered `https://example.org/cb` mismatched submitted `https://example.org:443/cb` and vice versa.

**Recommended fixes:**

- Require `redirect_uri` whenever the stored authorisation grant has one.
- Normalise both submitted and stored values: lowercase scheme/host, IDNA-encode, collapse default ports, lowercase percent-encoded triplets.
- Tests: omitted, mismatched, matching, and equivalent-but-different-form redirect URIs.
- Consider requiring PKCE (preferably `S256`) for public clients.

### 7. Outbound Sender Exfiltration via Attacker-Controlled Links (Conditional)

**Severity:** High when the sender is run automatically against published content that may contain user-influenced HTML; Medium otherwise (operator-only manual runs against trusted-author content).

**Status:** Resolved 2026-05-07. Sender target filtering rejects unsafe
HTTP(S) URL forms and private IP literals before discovery; discovery,
content fetches, delivery, and Salmention resend paths use the shared safe
HTTP helpers with size limits and retry/drop policies. As of 2026-05-07 the
shared helpers also pin connections to the resolved IP, so the DNS
rebinding / TOCTOU gap that previously inherited from finding 2 is closed.

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

**Status:** Resolved and verified 2026-05-07. Uploads are sniffed with
`filetype`, sniffed type must match the declared part content type and any
submitted suffix, stored suffixes are derived from the validated type, and
request-level upload count plus aggregate byte caps are enforced. Documentation
now covers media serving headers and storage isolation.

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

**Status:** Resolved and verified 2026-05-07; tightened 2026-05-07.
Introspection now requires a strict bearer caller credential, supports
self-introspection via the bearer header, returns inactive for unrelated-owner
target tokens, and as of 2026-05-07 also restricts target tokens to the
caller's own ``client_id`` after policy normalization. Hosts that need a
broader policy can configure the new
``INDIEWEB_TOKEN_INTROSPECTION_AUTHORIZER`` callable, which fails closed on
import errors, callable exceptions, non-callable values, and non-bool return
values.

**References:** `src/indieweb/views.py:949-994`, `src/indieweb/urls.py:23`.

RFC 7662 §2.1 requires the introspection endpoint to authenticate the caller. The current view accepts any request and returns scope, `me`, `client_id`, and expiry for any token an attacker possesses. This is a privacy/spec issue rather than a direct auth bypass — exploitation requires possession of a high-entropy token — but it lets an attacker turn a stolen token into a global validity oracle and confirm scope/expiry without proof of capture timing.

**Recommendation:** Require a bearer token (or HTTP Basic resource-server credential). Authorise the caller as the token's owner or a configured resource-server credential. Tests: unauthenticated POST → 401; valid resource-server credential → result; unrelated token → no information leak.

### Micropub Adapter Ownership Is Documentation Debt

**Severity:** Medium

**Status:** Resolved 2026-05-07. The abstract handler methods now raise
`NotImplementedError`, the in-memory handler is documented as an unsafe
development/testing example, and docs call out host-owned ownership checks for
content and media operations.

**References:** `src/indieweb/handlers.py:310-348` (`InMemoryMicropubHandler`), `src/indieweb/views.py` (`_handle_update`/`_handle_delete`/`_handle_undelete`/`_handle_source_query`), `README.rst:75`, `docs/index.rst:92`.

The Micropub views pass `self.token.owner` to the adapter. The reference `InMemoryMicropubHandler` ignores the `user` argument, but the documentation tells hosts to subclass `MicropubContentHandler`, not the in-memory class. This is therefore guidance debt rather than a direct app-level IDOR: hosts that follow the docs implement their own adapter and bear ownership-check responsibility, but the in-memory class stands as a misleading example.

**Recommendation:** Make the abstract base raise `NotImplementedError` with an explicit ownership requirement in the docstring. Mark the in-memory handler as `# UNSAFE: example only — performs no ownership check`. Document the host's ownership-check responsibility prominently.

### Bearer Token Accepted From POST Body

**Severity:** Medium

**Status:** Resolved 2026-05-06.

**References:** `src/indieweb/views.py:562` (`TokenAuthMixin.authenticated`).

Historical finding:

`TokenAuthMixin.authenticated` read `request.POST.get("Authorization")` as a fallback. Form bodies are written to proxy access logs and are replayable in CSRF-style attacks. RFC 6750 prohibits this transport; the spec-mandated alternative is the `access_token=` form parameter and only on `Content-Type: application/x-www-form-urlencoded`.

The fallback is now removed. Token-protected resource views accept only strict bearer headers and return 401 failures with `Cache-Control: no-store` and `WWW-Authenticate: Bearer`.

### JSON Micropub Path Bypasses Property Allow-List

**Severity:** Medium

**Status:** Resolved and verified 2026-05-07. JSON and form create paths reject
server-managed properties, update operations reject mutations to
server-managed properties, and URL-typed create properties are validated before
handler dispatch.

**References:** `src/indieweb/views.py:78-102` (form allow-list), `src/indieweb/views.py:1045` (JSON path passes properties verbatim).

The JSON Micropub create path passes `data["properties"]` verbatim to the handler, bypassing the form-path allow-list `MICROPUB_FORM_CREATE_PROPERTIES`. The form-path allow-list does include `published` and `url`, so those are not bypass examples; however a token with `create` scope can smuggle properties the form path never accepts, such as `uid` or `author`, through JSON. The same gap applies to `update`, where `replace`/`add`/`delete` operations are not gated on which properties may be modified.

**Recommendation:** Apply an explicit deny-list of server-managed keys (e.g. `uid`, `author`, plus any host-defined `_owner`/internal keys) on both JSON and form paths before invoking `create_entry`. Apply the same gating to `update`.

### WebSub Subscription Secrets and Token-Equivalent Fields Are Editable in Admin

**Severity:** Medium

**Status:** Resolved and verified 2026-05-07. WebSub shared secrets are
encrypted at rest and masked in admin, `Token.key` is hashed at rest and masked
in admin, `Auth.state` is no longer searchable, and WebSub delivery-attempt
admin rows are read-only/non-deletable.

**References:** `src/indieweb/admin.py:98` (WebSub fieldsets), `src/indieweb/admin.py:160` (`TokenAdmin` exposes `key`), `src/indieweb/admin.py:196` (`AuthAdmin.search_fields` includes `state`), `src/indieweb/models.py:308-310` (`secret`/`pending_secret` as plain `CharField`).

`WebSubSubscriptionAdmin` lists `secret` and `pending_secret` in editable fieldsets. Any staff user with view-only permissions sees the active HMAC key, defeating signature authenticity. The Token admin exposes `Token.key` in the change form; the `Auth` admin's `search_fields` includes `state`, enabling staff-side enumeration of IndieAuth state values. Practical exposure depends on admin-user policy but the surface is unnecessary.

**Recommendation:** Hash or encrypt subscription secrets at rest; remove `secret`/`pending_secret`/`callback_token` from admin entirely (or render as masked under `is_superuser`). Strip secrets from `__str__` and any logging. Drop `state` from `AuthAdmin.search_fields`; mask `Token.key` in `TokenAdmin`. Override `WebSubDeliveryAttemptAdmin.has_delete_permission` to `False` to preserve audit integrity.

### CORS Wildcard + Credentials Bypasses Origin Check

**Severity:** Medium

**Status:** Resolved and verified 2026-05-07. Wildcard origins combined with
`INDIEWEB_CORS_ALLOW_CREDENTIALS=True` now log a warning and emit wildcard CORS
without `Access-Control-Allow-Credentials`.

`src/indieweb/cors.py:97-109` — when `INDIEWEB_CORS_ALLOWED_ORIGINS = "*"` and `INDIEWEB_CORS_ALLOW_CREDENTIALS = True`, the response echoes any `Origin` and sets `Access-Control-Allow-Credentials: true`. Since Micropub and Media use bearer-token auth (not cookies), this is not a single-step browser-session takeover; but any cross-origin site can ride a session-authenticated browser request whose token is provided via cookie-bridged adapters or page-level fetch tooling.

**Recommendation:** Refuse to honour credentials when wildcard origins are configured (drop the credentials header or refuse to enable CORS) and warn at startup. Document this combination as unsupported.

### Rate Limiter Identity Hash Is Trivially Reversible; Counter Is Not Atomic

**Severity:** Medium

**Status:** Partially resolved 2026-05-07. Client identities are now HMACed with
`SECRET_KEY`, cache-key versioning was bumped, and `Retry-After` falls back to
the configured window if the reset marker is missing. The limiter remains
documented as best-effort under contention rather than a strict atomic limiter.

`rate_limit.py:86-88, 110-117` — `sha256(REMOTE_ADDR)` of an IPv4 is trivially reversible by exhaustive enumeration (4 billion keys), so the digest is not a privacy control. The `cache.add` + `cache.incr` pair is not atomic under contention with redis/memcached, allowing burst-over-limit.

**Recommendation:** HMAC the IP with `SECRET_KEY`. Document the limiter as best-effort and recommend a redis Lua-script-based limiter for hardening. Fall back `Retry-After` to `config.window` when the reset key was evicted.

### WebmentionStatusView Leaks Vouch URL and Pending Metadata Anonymously

**Severity:** Medium (refines first-pass enumeration finding)

**Status:** Resolved and verified 2026-05-07. Status URLs now use opaque
`status_token` values instead of sequential IDs, and public status JSON no
longer includes Vouch URLs or Vouch timestamps.

`views.py:2025` — `WebmentionStatusView` is unauthenticated and its sequential `<int:pk>` URL exposes every Webmention's `source_url`, `target_url`, `vouch_url`, status, and verification timestamps. This leaks attacker-probe pending state, vouch URLs that may be private, and any private/draft post URL that happens to be a Webmention target.

**Recommendation:** Replace integer IDs with opaque tokens, gate access on ownership/staff, or restrict the response to public-safe states (verified only) and fields (no `vouch_url`).

### Webmention Source Verification Is Too Permissive

**Severity:** Medium

**Status:** Resolved and verified 2026-05-07 for the source-link proof. HTML
verification skips non-rendered ancestors and plain-text URL tokens are no
longer accepted as standalone source-link proof. The separate residual parser
recursion issue is tracked under finding 3.

`processors.py:122, 875` — `_html_links_to_target` matches `<a href>` inside non-rendered ancestors such as `<template>` and `<noscript>` (BeautifulSoup's `html.parser` does not extract tags from inside HTML comments, and `<script>`/`<style>` content is parsed as text, so those paths are not affected). `_text_links_to_target` matches plain-text URL tokens that the source page never renders as a link. Both bypass the Webmention spec §3.2.2 requirement that the source actually link to the target.

**Recommendation:** Skip non-rendered ancestors (`<template>`, `<noscript>`, `<head>` except canonical/related rels) in `_html_links_to_target`. Only accept the text-token path when the same content's `html` also contains a real `<a href>`.

### WebSub: No Replay Protection, No Lease Bounds, Algorithm Confusion

**Severity:** Medium

**Status:** Partially resolved 2026-05-07. WebSub signatures now prefer the
strongest accepted algorithm, `sha1` is disabled by default, leases are clamped,
shared secrets have byte-length bounds, secret headers are handled with
case-insensitive request headers, and a replay window rejects duplicate latest
accepted bodies. Remaining gap: only the latest accepted delivery digest is
tracked, so replaying an older body after a different accepted body is not
detected.

- `websub.py:630-653` — signed deliveries have no nonce/timestamp/freshness check; a captured payload replays forever.
- `websub.py:159-168, 458-465` — `lease_seconds` is unbounded; a hub returning `10**12` produces effectively-permanent subscriptions.
- `websub.py:644-652` — when both `X-Hub-Signature` (sha1) and `X-Hub-Signature-256` (sha256) are present, either-validates wins, allowing a hub to downgrade to sha1.
- `websub.py:621-627` — `_signature_headers` uses fixed-case keys; works with `request.headers` (case-insensitive) but not with plain dict callers.
- `websub.py:290-292, 378` — empty/short `hub.secret` is silently accepted as "no secret"; spec says the secret must be ≥1 byte and ≤200 bytes.

**Recommendations:** Track last-seen body digest+timestamp per subscription. Clamp lease to `[5 min, 30 days]` (configurable). Prefer the strongest signature header present; gate sha1 behind opt-in. Normalise header lookups. Require ≥20 bytes for `hub.secret` when provided.

### Client Trust Is Permissive by Default

**Status:** Mitigated 2026-05-07. Client IDs are normalized before policy hooks
and an explicit `INDIEWEB_ALLOWED_CLIENT_IDS` allowlist is available. The
default remains permissive for backwards compatibility and should be hardened
by production deployments.

By default, structurally valid `client_id` URLs are accepted unless `INDIEWEB_CLIENT_ID_VALIDATOR` is configured. The validator hook receives the raw URL with no normalisation, so allow-lists by exact match miss case-only variants. (Note: when configured but unimportable, the hook DOES fail closed at `views.py:315`; that aspect is correct.)

**Recommendation:** Document strict production client validation. Normalise `client_id` (lowercase scheme/host, IDNA) before invoking the validator.

### `me` Is Not Bound to the Logged-In User and Is Echoed on the Consent Screen

**Status:** Resolved 2026-05-07. Deployments can enable strict
`INDIEWEB_BIND_ME_TO_USER`; the consent screen now shows the configured profile
URL and a mismatch warning when the requested `me` differs from the logged-in
user's profile URL.

The authorisation request accepts and stores arbitrary `me` values; the consent screen displays this client-supplied value verbatim, providing a phishing surface where a hostile client renders `me=https://victim.example/` to mislead the user.

**Recommendation:** Add a setting/hook to bind `me` to the logged-in user's configured IndieWeb identity. On the consent screen, display the resolved (server-validated) profile URL alongside the requested `me` and warn on mismatch.

### Access Tokens Are Stored in Plaintext

**Status:** Resolved and verified 2026-05-07. `Token.key` is now an
`hmac-sha256$` digest at rest; raw bearer tokens are returned only at issuance
or reissue, and authentication/introspection compare derived hashes.

`Token.key` is stored directly in the database. A database-read compromise yields live bearer tokens. `Auth.key` and `Token.key` are now unique, and duplicate-key lookups fail closed, but token hashes at rest are still not implemented.

**Recommendation:** Store only a hash; return the raw token at issuance only; authenticate by comparing derived hashes (with `hmac.compare_digest`).

### Micropub Property Validation Gaps

**Status:** Resolved and verified 2026-05-07. URL-typed create properties are
validated as HTTP(S), Micropub action URLs must be relative/local or same-host
absolute URLs, `mp-slug` is sanitized, and JSON content types with parameters
are parsed as JSON.

- `mp-slug` and `mp-syndicate-to` reach the handler unsanitised.
- Photo/audio/video/in-reply-to/like-of/repost-of/bookmark-of/syndication URL fields are not validated as `http(s)://`; `javascript:` and `file:///` reach the handler.
- `_action_url`/`_handle_delete` accept any URL; adapters that key on URL substrings can be tricked by cross-origin URLs.
- `request.content_type` is compared exactly to `application/json`, so `application/json; charset=utf-8` falls into the form-encoded branch.

**Recommendation:** Apply `URLValidator(schemes=["http","https"])` to URL-typed Micropub properties at the view boundary. Require Micropub action URLs to share host with the request. Parse the media type with `email.message.Message`/`cgi.parse_header`.

### Rate Limiting Is Disabled by Default

**Status:** Mitigated 2026-05-07. The optional limiter remains disabled by
default for compatibility, but documentation now includes hardened production
starting points and proxy-aware `REMOTE_ADDR` guidance.

`INDIEWEB_RATE_LIMITS` defaults to disabled across auth, token, introspection, Micropub, media, Webmention, Webmention status, and WebSub callback endpoints.

**Recommendation:** Document hardened production limits per endpoint. Consider shipping conservative defaults or a helper settings snippet. Cover proxy-aware client IP guidance (the limiter intentionally ignores `X-Forwarded-For`).

### Test Settings Hardcode `SECRET_KEY` and `DEBUG=True`

**Status:** Resolved 2026-05-07. Test settings now load `SECRET_KEY` from
`DJANGO_INDIEWEB_TEST_SECRET_KEY` with an explicit insecure sentinel default,
and `DEBUG` is env-overridable.

`tests/settings.py:17` ships a hardcoded key with `DEBUG=True`. Low risk since it is test-only, but a project that mistakenly imports `tests.settings` runs with that combination.

**Recommendation:** Load from env with a sentinel default (`"insecure-test-key-do-not-use"`).

### Dependency Pinning

**Status:** Resolved 2026-05-07. Runtime lower bounds were added for `httpx`,
`beautifulsoup4`, and `mf2py`, `uv.lock` is tracked, and release docs include
SBOM generation.

`pyproject.toml` only pins Django with an upper bound. Downstream installs may pull vulnerable `httpx`, `beautifulsoup4`, or `mf2py`.

**Recommendation:** Add lower bounds for known-CVE versions; ship a `uv` lockfile and SBOM with releases.

### Inline Styles in Bundled Templates

**Status:** Resolved 2026-05-06. Bundled consent and token-management inline
styles moved into `static/css/indieweb.css`.

`consent.html:45-100` and `tokens.html:52-94` carry inline `<style>` blocks. Operators with strict CSPs (no `'unsafe-inline'`, no hash/nonce) will see broken rendering or be forced to weaken CSP.

**Recommendation:** Move styles into `static/css/indieweb.css` or provide a CSP-nonce hook.

### WebSub Deliveries Without Secrets Rely on Callback Token Only

**Status:** Mitigated 2026-05-07. Production deployments can require signed
deliveries with `INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES`; docs recommend
secrets for production subscriptions. Unsigned delivery remains accepted by
default when no subscription secret is configured, preserving callback-token-only
compatibility.

`validate_websub_delivery_signature()` returns success when a subscription has no secret. Authenticity then depends on the unguessable callback URL token. Combined with the WebSub renewal logic, secrets persist across re-verifications even when a hub returns a new `hub.secret`-less response.

**Recommendation:** Strongly recommend or optionally require WebSub secrets for subscriptions where supported. Rotate `Subscription.callback_token` on every successful resubscribe. Clear `secret` on successful re-verify when `pending_secret_set` is False.

## Remaining Fix Order

The three production blockers identified in the 2026-05-07 verification pass
were resolved on 2026-05-07:

1. SSRF connection pinning landed (see finding 2 / 7); ``http_client.py`` now
   resolves once and connects to a checked IP literal while preserving Host
   header and TLS SNI.
2. Webmention parser fallback traversals are now iterative and share the
   primary-scan depth/breadth budgets.
3. WebSub deliveries now retain a bounded multi-digest replay history per
   subscription within the configured replay window.

## Documentation Impact

Documentation updates have landed alongside each fix. ``AGENTS.md`` did not
need a change.

## Current Backlog Coverage

The three residual items found during the 2026-05-07 verification pass are mirrored in `BACKLOG.md` as current planned work. Historical issues marked resolved above have corresponding entries in `DONE.md`.
