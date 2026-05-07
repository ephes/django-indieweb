# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

## Priority 1

No current Priority 1 items.

## Priority 2

No current Priority 2 items.

## Priority 3

### API Hardening

- [ ] Document Micropub adapter ownership responsibilities and mark in-memory handler unsafe.
  References: `src/indieweb/handlers.py` (`InMemoryMicropubHandler` ~lines 310-348), `src/indieweb/interfaces.py`, `README.rst:75`, `docs/index.rst:92`.
  The reference `InMemoryMicropubHandler` ignores the `user` argument that the views pass in. Docs already point hosts at `MicropubContentHandler`, so the in-memory class is an example, not a recommended base — but it stands as a misleading example. Make the abstract base raise `NotImplementedError` with an explicit ownership requirement in the docstring; add a `# UNSAFE: example only — performs no ownership check` comment in the in-memory handler; add an "Adapter responsibilities" section to README and docs/index calling out the host's ownership-check duty for update/delete/undelete/source/media.

- [ ] Add hardened default rate-limit guidance and fix limiter primitives for public protocol endpoints.
  References: `src/indieweb/rate_limit.py`, `src/indieweb/views.py`, `docs/`, `tests/test_rate_limiting.py`.
  Built-in rate limiting is disabled unless `INDIEWEB_RATE_LIMITS` is configured; document recommended production limits for auth, token, introspection, Micropub, media, Webmention, Webmention status, and WebSub callback endpoints. Cover proxy-aware client IP guidance (the limiter intentionally ignores `X-Forwarded-For`). Replace `sha256(REMOTE_ADDR)` keying with HMAC keyed by `SECRET_KEY` (the bare digest of an IPv4 is trivially reversible). The `cache.add` + `cache.incr` pair is not atomic with redis/memcached — document best-effort behaviour and recommend a Lua-script-based limiter for hardening; fall back `Retry-After` to `config.window` when the reset key was evicted.

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
