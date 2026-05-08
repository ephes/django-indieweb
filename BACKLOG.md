# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

## Priority 1

### Security Residuals

## Priority 2

### Security Residuals

- [ ] Revisit WebSub replay-history cap semantics for high-volume topics.
  References: `src/indieweb/websub.py` (`DEFAULT_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX`,
  `_delivery_replay_history_max`, `delivery_is_replay`,
  `record_websub_delivery`), `docs/websub.rst`, `docs/configuration.rst`,
  `tests/test_websub_subscriber.py`. The current default retains 64 accepted
  body digests within a 300-second window; busy topics can evict older digests
  that are still inside the configured replay window. Consider sizing by
  window volume, using an unbounded-by-count option for signed deployments, or
  documenting the operational tradeoff more explicitly.

## Priority 3

### API Hardening

- [ ] Add a configurable URL policy for Micropub source and media hooks.
  References: `src/indieweb/views.py` (`_handle_source_query`,
  `MicropubMediaView._handle_source_by_url_query`,
  `MicropubMediaView._handle_delete`), `src/indieweb/handlers.py`,
  `docs/micropub.rst`, `docs/configuration.rst`,
  `tests/test_micropub_source.py`, `tests/test_micropub_media.py`. Entry
  source, media source-by-URL, and media delete pass submitted URLs unchanged
  to host handlers. Keep handler ownership authoritative, but add an optional
  view-level policy hook or allowlist for accepted entry/media URL hosts so
  deployments can reject cross-origin, storage-external, or malformed URLs
  before handler dispatch. Avoid a hard same-host rule because media may live
  on storage or CDN hosts.

- [ ] Document injected HTTP clients as trusted test/integration-only escape
  hatches. References: `src/indieweb/processors.py`,
  `src/indieweb/senders.py`, `src/indieweb/websub.py`,
  `docs/webmention.rst`, `docs/websub.rst`, `docs/configuration.rst`,
  `docs/api.rst`. Several APIs accept an injected `httpx.Client`; when a
  caller provides one, DNS-based SSRF blocking and IP pinning are skipped.
  Public documentation should mirror the source docstrings, recommend leaving
  `client` unset in production, and explain that injected clients are trusted
  transports for tests or tightly controlled integrations.

- [ ] Add an optional public-safe Webmention status response mode. References:
  `src/indieweb/views.py` (`WebmentionStatusView`), `docs/webmention.rst`,
  `docs/api.rst`, `tests/test_webmention_endpoint.py`. Status URLs use opaque
  high-entropy tokens, but a leaked status URL reveals `source`, `target`,
  `status`, and `verified_at`. Add a setting to return only minimal status
  fields, or document the existing response as token-holder diagnostics that
  can expose private source/target URLs.

## Priority 4

### Housekeeping

- [ ] Add privacy-oriented logging guidance or redaction mode. References:
  `src/indieweb/views.py`, `src/indieweb/processors.py`,
  `src/indieweb/websub.py`, `docs/configuration.rst`. Authorization codes and
  bearer tokens are redacted, but logs still include client IDs,
  `redirect_uri`, `state`, `me`, Webmention source/target URLs, and handler
  URL parameters. Add deployment guidance for log retention/redaction, or add a
  setting/helper that redacts privacy-sensitive URL and state values in
  protocol logs.

- [ ] Validate inbound protocol field lengths before persistence. References:
  `src/indieweb/views.py`, `src/indieweb/processors.py`,
  `src/indieweb/models.py`, `tests/test_webmention_endpoint.py`,
  `tests/test_auth_endpoint.py`, `tests/test_token_endpoint.py`. Public and
  protocol-facing views validate URL syntax but do not consistently reject
  values that exceed backing model field lengths before `get_or_create()` or
  `create()` calls. In queued Webmention deployments, overlong but syntactically
  valid `source`, `target`, or `vouch` URLs can reach
  `_store_webmention_submission()` before the processing try/except boundary;
  authorization parameters such as `state`, `scope`, `client_id`,
  `redirect_uri`, and `me` have similar authenticated-user robustness gaps.
  Return protocol-appropriate 400 responses before database writes and add
  regression coverage for overlong fields.

### WebSub Enhancements

No current Priority 4 WebSub Enhancements items.

### Micropub Enhancements and Extensions

No current Micropub Enhancements and Extensions items.

### Syndication and Storage Examples

No current Syndication and Storage Examples items.

### Webmention and Reader Boundaries

No current Webmention and Reader Boundaries items.

## Agent Workflow Improvements

No current Agent Workflow Improvements items.
