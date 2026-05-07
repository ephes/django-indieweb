# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

## Priority 1

### Security Residuals

- [ ] Pin SSRF-safe outbound HTTP connections to checked addresses.
  - References: `SECURITY_ANALYSIS.md` finding 2; `src/indieweb/http_client.py`; `src/indieweb/processors.py`; `src/indieweb/senders.py`; `src/indieweb/websub.py`; `tests/test_http_client.py`; sender/Webmention/WebSub tests.
  - Current state: the shared helper validates URL syntax, rejects blocked IP literals, rejects DNS names that resolve to blocked addresses, and re-checks redirect targets, but it then hands the original hostname to `httpx` for the actual connection. That allows DNS rebinding/time-of-check-time-of-use bypasses.
  - Desired outcome: bind the safety check to the actual socket connection by connecting to a checked IP address while preserving the original Host header and TLS SNI semantics, re-apply the same rule on every redirect, keep explicit TLS verification, and cover public, private, DNS-to-private, redirect-to-private, and DNS-rebinding cases in tests.

## Priority 2

### Security Residuals

- [ ] Cap all Webmention parser fallback traversals.
  - References: `SECURITY_ANALYSIS.md` finding 3; `src/indieweb/processors.py` (`_search_for_any_h_entry`, `_search_items_for_h_card`, `_search_items_for_h_card_id`, `_collect_page_level_h_cards`, existing traversal limit helpers); `tests/test_webmention_processor.py`.
  - Current state: source/vouch fetches and primary nested-response/mentioning-entry scans have byte, depth, and item-count limits, but several fallback microformats traversal paths are still recursive and uncapped.
  - Desired outcome: apply a single traversal budget consistently across primary and fallback h-entry/h-card searches, avoid recursion-limit crashes on deep input, preserve existing authorship/source-selection behavior for normal pages, and add regression tests with deep and wide trees.

- [ ] Track multiple recent WebSub delivery digests for replay protection.
  - References: `SECURITY_ANALYSIS.md` WebSub replay residual; `src/indieweb/websub.py` (`delivery_is_replay`, `record_websub_delivery`); `src/indieweb/models.py` (`WebSubSubscription`, `WebSubDeliveryAttempt`); `tests/test_websub_subscriber.py`.
  - Current state: WebSub rejects an immediate duplicate body within the replay window, but only the latest accepted delivery digest is remembered. Payload A can be replayed after a legitimate payload B.
  - Desired outcome: keep a bounded replay cache/history per subscription across the configured replay window, reject A/B/A replays, expire old digests predictably, and document any migration or retention implications.

## Priority 3

### API Hardening

- [ ] Authenticate token introspection per RFC 7662 §2.1 with a same-`client_id` rule.
  - References: `SECURITY_ANALYSIS.md` "Token Introspection" finding; `src/indieweb/views.py:1382-1394`; `tests/test_token_endpoint.py`.
  - Current state: a same-owner caller token can introspect any other active token of the same Django user, including tokens issued to a different `client_id` / scope / `me`. The endpoint requires a caller token but does not restrict cross-client lookups.
  - Desired outcome: gate introspection so a caller can only see tokens issued to its own `client_id`, or an explicit resource-server credential, with a configurable hook for hosts that need broader access. Add tests covering same-client, cross-client, and cross-owner cases.

- [ ] Hash authorization codes at rest and mask them in admin.
  - References: `SECURITY_ANALYSIS.md` "Plaintext authorization codes" residual; `src/indieweb/models.py` (`Auth`, `GenKeyMixin`); `src/indieweb/admin.py` (`AuthAdmin`).
  - Current state: `Auth.key` is stored plaintext. The 60-second TTL bounds exposure but a DB-read attacker within that window can issue tokens, and the admin change form exposes the plaintext code.
  - Desired outcome: hash `Auth.key` analogously to `Token.key` (HMAC-SHA256 with `SECRET_KEY`), expose only a `masked_key` in `AuthAdmin`, add a data migration for any in-flight rows, and keep all token-exchange paths working. Add regression tests for issuance + lookup + introspection.

- [ ] Cap response size on the Webmention sender's outbound POST helper.
  - References: `SECURITY_ANALYSIS.md` finding 7 / response-size residual; `src/indieweb/senders.py` (`request_with_webmention_redirects` callers); `src/indieweb/http_client.py`; `tests/test_webmention_sender.py`.
  - Current state: the WebSub hub callers now pass `max_bytes` to `request_with_safe_redirects`, but the Webmention sender still uses `request_with_webmention_redirects` without a body cap, so a hostile webmention endpoint can return an unbounded response and force the sender to buffer it.
  - Desired outcome: thread `max_bytes` through `request_with_webmention_redirects` (defaulting to a configurable cap) and add tests that an oversized response is surfaced as a delivery failure rather than buffered.

## Priority 4

### Housekeeping

- [ ] Replace the `unittest.mock` module-name guard in `stream_with_safe_redirects` with an explicit kwarg.
  - References: `src/indieweb/http_client.py:234-236`; `tests/test_http_client.py`; sender/WebSub tests using `Mock` clients.
  - Current state: streaming is short-circuited when `client.__class__.__module__ == "unittest.mock"` so legacy mocks keep working, but a future caller wrapping a real `httpx.Client` could silently disable max-bytes enforcement.
  - Desired outcome: introduce an explicit kwarg (e.g. `_skip_streaming=True`) used by the affected tests, drop the module-name guard, and verify all existing call sites still pass.

- [ ] Add `xframe_options_deny` to the token management view.
  - References: `SECURITY_ANALYSIS.md` "tokens.html clickjacking" residual; `src/indieweb/views.py` (`TokenManagementView`); `src/indieweb/templates/indieweb/tokens.html`.
  - Current state: Django's default middleware sets `X-Frame-Options: SAMEORIGIN` on the revoke page; the consent screen already enforces `DENY`.
  - Desired outcome: decorate the token management view with `@xframe_options_deny` (and a matching `frame-ancestors 'none'` CSP), mirroring the consent screen's posture. Add a regression test asserting the header.

### WebSub Enhancements

- [ ] Optionally enqueue the WebSub delivery hook out of the request thread.
  - References: `SECURITY_ANALYSIS.md` WebSub sync-hook finding; `src/indieweb/websub.py` (`process_websub_delivery`); `src/indieweb/views.py` (WebSub callback view).
  - Current state: the configured `INDIEWEB_WEBSUB_DELIVERY_HOOK` runs synchronously inside the request thread, mirroring the pre-`INDIEWEB_WEBMENTION_ENQUEUE` Webmention design.
  - Desired outcome: add `INDIEWEB_WEBSUB_DELIVERY_ENQUEUE` analogous to the Webmention enqueue setting, with documentation and tests for the queued path.

- [ ] Clamp `INDIEWEB_WEBSUB_MIN_LEASE_SECONDS` / `_MAX_LEASE_SECONDS` to a sane range.
  - References: `SECURITY_ANALYSIS.md` "WebSub lease bounds" residual; `src/indieweb/websub.py` (`_confirmed_lease_bounds`).
  - Current state: each setting falls back to its default when `_positive_int` returns `None`, but the configured pair is not range-checked, so `min=1, max=10**12` is accepted.
  - Desired outcome: clamp confirmed-lease bounds to a documented sane range (e.g. 60 seconds to 90 days), warn on out-of-range configuration, and add tests.

### Micropub Enhancements and Extensions

No current Micropub Enhancements and Extensions items.

### Syndication and Storage Examples

No current Syndication and Storage Examples items.

### Webmention and Reader Boundaries

- [ ] Tighten h-card render-time URL validation as defense-in-depth.
  - References: `SECURITY_ANALYSIS.md` h-card render finding; `src/indieweb/templates/indieweb/h-card.html`; `src/indieweb/models.py` (`Profile._validate_h_card_urls`); `src/indieweb/h_card.py`.
  - Current state: `Profile.save()` runs `full_clean()` which validates h-card URLs, but Django's default `URLValidator()` permits `ftp(s)://`, `mailto:` interpolations have no validator, and bypass paths (`bulk_update`, `update()`, raw SQL, fixtures with `bypass_validation`) skip validation entirely. Several `<a href>`/`<img src>` interpolations also lack `rel="nofollow noopener"`/`referrerpolicy="no-referrer"`.
  - Desired outcome: restrict h-card URL schemes to `http`/`https` at the model layer, sanitize at render with the existing `sanitize_remote_webmention_url`, and add `rel`/`referrerpolicy` on outbound author/photo links.

- [ ] Wrap concurrent Webmention receives in `transaction.atomic` + `select_for_update`.
  - References: `SECURITY_ANALYSIS.md` Webmention race residual; `src/indieweb/processors.py:289-296`; `tests/test_webmention_processor.py`.
  - Current state: two concurrent `POST /webmention/` requests for the same `(source, target)` pair can stomp each other's `verified` state.
  - Desired outcome: serialize the verify+update sequence per row so the second receive observes and preserves the first's outcome; add a regression test.

## Agent Workflow Improvements

No current Agent Workflow Improvements items.
