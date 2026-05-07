# Done

Completed backlog items move here from `BACKLOG.md`. Keep entries concise, but include validation and documentation/changelog notes so future contributors can understand what changed.

## 2026-05-07

### Tighten test/dev settings and dependency pinning

- Changed ``tests.settings`` to load ``SECRET_KEY`` from
  ``DJANGO_INDIEWEB_TEST_SECRET_KEY`` with the explicit
  ``insecure-test-key-do-not-use`` sentinel default, and made test ``DEBUG``
  env-overridable through ``DJANGO_INDIEWEB_TEST_DEBUG`` while preserving the
  existing default.
- Added runtime dependency lower bounds for ``httpx``, ``beautifulsoup4``, and
  ``mf2py`` while keeping the existing Django support range and tracked
  ``uv.lock`` release lockfile.
- Added ``py313-django52-migrations`` to tox so the suite can run once with
  Django migrations enabled despite the default pytest ``--no-migrations``
  setting. Added a ``just sbom`` recipe that exports a CycloneDX SBOM from the
  locked runtime dependency graph into ``dist/`` for releases.
- Backlog: removed the completed Priority 4 housekeeping item from
  ``BACKLOG.md``. No migrations were needed.
- Documentation: updated ``README.rst``, ``CONTRIBUTING.rst``, and
  ``docs/development.rst`` for the migration-enabled tox environment and
  release SBOM workflow.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased note for the
  test settings, dependency floor, tox, and SBOM workflow changes.
- Validation: ``uv lock`` passed; ``uv lock --check`` passed; ``uv run pytest
  tests/test_project_metadata.py -q --no-cov`` passed (5 passed); targeted
  ``uv run ruff check`` and ``uv run ruff format --check`` passed; ``just
  sbom`` passed; ``tox -e py313-django52-migrations`` passed (1168 passed with
  migrations enabled); ``uv run pytest`` passed (1168 passed, coverage gate
  reached at 90.29%); ``uv run mypy`` passed; ``uv run ruff check .`` passed;
  ``uv run ruff format . --check`` passed; ``uv run sphinx-build -W -b html
  docs docs/_build/html`` passed; ``uv run python manage.py makemigrations
  --check --dry-run`` passed; ``uv run prek run --all-files`` passed; and
  ``git diff --check`` passed. Post-review checks also passed after
  strengthening the project-metadata tests and adding the tox override comment:
  ``uv run pytest tests/test_project_metadata.py -q --no-cov``, targeted
  ``uv run ruff check``, targeted ``uv run ruff format --check``, and ``tox c
  -e py313-django52-migrations``.

### Harden rate-limit keys and document Micropub adapter ownership

- Changed endpoint rate-limit cache keys to HMAC-digest client identities with
  Django's ``SECRET_KEY`` instead of storing bare SHA-256 digests of
  ``REMOTE_ADDR`` values. Cache-key versioning moved to ``v2`` so existing
  deployments naturally start fresh windows after upgrade.
- Kept the optional built-in limiter disabled by default, but made exceeded
  limits fall back to the configured ``window`` for ``Retry-After`` when the
  cache reset marker has been evicted.
- Clarified that ``MicropubContentHandler`` implementations must enforce
  host-owned user/content/media ownership before source, update, delete,
  undelete, list, and media operations. Abstract operation bodies now raise
  ``NotImplementedError`` and the bundled in-memory handler is marked as an
  unsafe development/testing example that performs no ownership checks.
- Backlog: removed the completed Priority 3 Micropub adapter ownership and
  rate-limit hardening items from ``BACKLOG.md``. No migrations were needed.
- Documentation: updated ``README.rst``, ``docs/index.rst``,
  ``docs/configuration.rst``, ``docs/api.rst``, and ``docs/micropub.rst`` for
  adapter responsibilities, production rate-limit starting points,
  proxy-aware ``REMOTE_ADDR`` guidance, HMAC cache keying, best-effort cache
  primitive semantics, and ``Retry-After`` fallback behavior.
- Changelog: updated ``docs/changelog.rst`` with Unreleased notes for the
  rate-limit hardening and Micropub adapter ownership clarification.
- Review follow-up: aligned README, docs index, and handler docstring wording
  to explicitly include content/media listing in the host-owned ownership
  boundary; tightened the ``Retry-After`` fallback regression test to call the
  fallback helper with a known-missing reset key instead of patching the shared
  cache ``get`` method or relying on request-path cache eviction.
- Validation: ``uv run pytest tests/test_rate_limiting.py -q --no-cov`` passed
  (14 passed); targeted ``uv run ruff check`` passed; targeted ``uv run ruff
  format --check`` passed; ``uv run pytest`` passed (1163 passed, coverage
  gate reached at 90.29%); ``uv run mypy`` passed; ``uv run ruff check .``
  passed; ``uv run ruff format . --check`` passed; ``just docs`` passed; and
  ``uv run prek run --all-files`` passed; ``git diff --check`` passed.
  Post-review targeted checks also passed: ``uv run pytest
  tests/test_rate_limiting.py -q --no-cov``, targeted ``uv run ruff check``,
  targeted ``uv run ruff format --check``, and ``just docs``.

### Store bearer tokens hashed at rest and privatize Webmention status URLs

- Changed ``Token.key`` to store ``hmac-sha256$`` HMAC digests instead of raw
  bearer values. The token endpoint now returns the raw token only at issuance
  or reissue, authentication and introspection look up the derived digest and
  compare with ``hmac.compare_digest``, and migration ``0020`` hashes existing
  plaintext token rows in place.
- Masked token secrets in Django admin through ``TokenAdmin.masked_key`` and
  removed transient ``Auth.state`` values from ``AuthAdmin.search_fields``.
  The browser token-management UI continues to show only token metadata.
- Added opaque ``Webmention.status_token`` values via migration ``0020`` and
  changed Webmention receive ``Location`` headers plus the named status route
  to use ``/indieweb/webmention/<status-token>/`` instead of sequential
  primary-key URLs.
- Removed Vouch URLs and Vouch verification timestamps from public Webmention
  status JSON while preserving source, target, status, and ``verified_at``.
- Backlog: removed the completed Priority 3 token-at-rest and Webmention
  status privacy items from ``BACKLOG.md``.
- Documentation: updated ``docs/api.rst``, ``docs/indieauth.rst``,
  ``docs/webmention.rst``, ``docs/configuration.rst``, and ``docs/tutorial.rst``
  for hashed token storage, the ``SECRET_KEY`` token-hash dependency, opaque
  status URLs, and Vouch metadata no longer being exposed by status responses.
- Changelog: updated ``docs/changelog.rst`` with Unreleased security notes for
  hashed bearer-token storage and non-enumerable Webmention status URLs.
- Validation: ``uv run pytest tests/test_token_endpoint.py
  tests/test_token_management.py tests/test_admin.py
  tests/test_webmention_endpoint.py tests/test_rate_limiting.py -q --no-cov``
  passed (169 passed); ``uv run pytest`` passed (1161 passed, coverage gate
  reached at 90.12%); ``uv run mypy`` passed; ``uv run ruff check .`` passed;
  ``uv run ruff format . --check`` passed; ``just docs`` passed; ``uv run
  python manage.py makemigrations --check --dry-run`` passed; ``uv run prek
  run --all-files`` passed on rerun after hooks normalized files; and ``git
  diff --check`` passed.

### Strengthen Micropub media upload validation and serving guidance

- Sniffed Micropub media uploads with ``filetype`` before storage, compared
  sniffed type, submitted part content type, and filename suffix, and rejected
  unknown or mismatched uploads with the existing ``invalid_request`` media
  responses before any storage write.
- Changed stored media names to keep unguessable ``indieweb/media/`` keys
  while deriving the filename suffix from the validated media type rather than
  the client filename. Multipart create uploads still preserve URL-valued
  ``photo`` properties and clean up already-saved files when a later save
  fails.
- Added ``INDIEWEB_MEDIA_MAX_UPLOAD_COUNT`` and
  ``INDIEWEB_MEDIA_MAX_UPLOAD_TOTAL_BYTES`` so direct media uploads and
  multipart ``photo`` create uploads enforce request-level count and aggregate
  byte limits. Unknown-size uploads are rejected.
- Backlog: removed the completed Priority 3 Micropub media upload validation
  and serving guidance item from ``BACKLOG.md``. No migrations were needed.
- Documentation: updated ``docs/configuration.rst`` and ``docs/micropub.rst``
  for content sniffing, suffix derivation, count/aggregate limits, disabled
  allowlist semantics, and defensive serving guidance.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased Micropub input
  hardening security note.
- Review follow-up: documented the ``filetype`` sniff byte window and slug
  sanitization boundary in code comments.
- Validation: ``uv sync`` passed; ``uv run pytest
  tests/test_micropub_media.py tests/test_micropub_create.py
  tests/test_micropub_actions.py -q --no-cov`` passed (199 passed); ``uv run
  pytest`` passed (1157 passed, coverage gate reached at 90.14%); ``uv run
  mypy`` passed; ``uv run ruff check .`` passed; ``uv run ruff format .
  --check`` passed; ``uv run prek run --all-files`` passed; and ``just docs``
  passed.

### Strengthen Micropub property validation

- Validated URL-valued Micropub create properties before handler dispatch for
  JSON and form requests: ``photo``, ``audio``, ``video``,
  ``in-reply-to``, ``like-of``, ``repost-of``, ``bookmark-of``, and
  ``syndication`` now require absolute HTTP(S) URLs while generated local
  media URLs remain accepted.
- Sanitized ``mp-slug`` values before forwarding them to handlers by stripping
  path separators, control characters, and leading dots, omitting the property
  when sanitization leaves no value.
- Required update/delete/undelete action URLs to be relative/local or
  same-host absolute URLs before handler dispatch, while keeping relative
  in-memory handler URLs valid. JSON Micropub bodies with
  ``application/json`` parameters such as ``charset=utf-8`` are now parsed as
  JSON.
- Backlog: removed the completed Priority 3 Micropub property validation item
  from ``BACKLOG.md``. No migrations were needed.
- Documentation: updated ``docs/micropub.rst`` for create URL validation,
  ``mp-slug`` sanitization, same-host action URLs, and JSON content-type
  parameter handling. No separate configuration setting was added for this
  item.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased Micropub input
  hardening security note.
- Review follow-up: preserved empty Microformats2 arrays for URL-valued create
  properties instead of rejecting them, and normalized explicit default ports
  when comparing same-host action URLs.
- Validation: ``uv sync`` passed; ``uv run pytest
  tests/test_micropub_media.py tests/test_micropub_create.py
  tests/test_micropub_actions.py -q --no-cov`` passed (199 passed); ``uv run
  pytest`` passed (1157 passed, coverage gate reached at 90.14%); ``uv run
  mypy`` passed; ``uv run ruff check .`` passed; ``uv run ruff format .
  --check`` passed; ``uv run prek run --all-files`` passed; and ``just docs``
  passed.

### Refuse wildcard CORS credentials and harden CORS caching

- Changed built-in CORS so ``INDIEWEB_CORS_ALLOWED_ORIGINS = "*"`` combined
  with ``INDIEWEB_CORS_ALLOW_CREDENTIALS = True`` logs a warning, keeps
  ``Access-Control-Allow-Origin: *``, and never emits
  ``Access-Control-Allow-Credentials: true``.
- Added ``Vary: Origin`` for origin-dependent explicit-allowlist decisions,
  including disallowed-origin actual responses and rejected preflights, while
  preserving true wildcard responses without ``Vary``.
- Preserved downstream ``Access-Control-Allow-Origin`` headers instead of
  overwriting them, and avoided adding incoherent credential headers when a
  downstream CORS decision already exists.
- Backlog: removed the completed Priority 2 CORS wildcard-credentials item
  from ``BACKLOG.md``. No migrations were needed.
- Documentation: updated ``docs/configuration.rst`` and ``docs/api.rst`` for
  unsupported wildcard credentials, rejection ``Vary`` behavior, and
  downstream-header preservation.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased CORS hardening
  note.
- Validation: ``uv run pytest tests/test_cors.py -q --no-cov`` passed (32
  passed); targeted ``uv run ruff check`` passed; and final full-gate results
  are recorded below in this session's IndieAuth hardening entry.

### Add IndieAuth client identity, me-binding, and PKCE hardening options

- Normalized ``client_id`` policy inputs before
  ``INDIEWEB_CLIENT_ID_VALIDATOR`` and resource-server policy checks by
  lowercasing scheme/host and converting Unicode hostnames to IDNA ASCII form
  while preserving stored submitted values, path, query, and port semantics.
- Added ``INDIEWEB_ALLOWED_CLIENT_IDS`` as an exact normalized client allowlist
  for production deployments. Misconfigured allowlist entries fail closed.
- Added opt-in PKCE policy settings:
  ``INDIEWEB_REQUIRE_PKCE`` rejects omitted PKCE before issuing authorization
  codes, and ``INDIEWEB_REQUIRE_PKCE_S256`` rejects omitted or ``plain`` PKCE
  and updates metadata to advertise only ``S256``.
- Added consent-screen local identity context from
  ``user.indieweb_profile.url`` and a mismatch warning. Added
  ``INDIEWEB_BIND_ME_TO_USER`` to fail closed when submitted ``me`` does not
  match the configured profile URL or when strict binding is enabled without a
  profile URL.
- Backlog: removed the completed Priority 3 IndieAuth client identity /
  ``me`` / PKCE hardening item from ``BACKLOG.md``. No migrations were needed.
- Documentation: updated ``docs/configuration.rst``, ``docs/api.rst``, and
  ``docs/indieauth.rst`` for normalized client policy inputs, the new
  allowlist, PKCE policy settings, metadata behavior, consent context, and
  strict ``me`` binding.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased IndieAuth
  hardening note.
- Validation: ``uv run pytest tests/test_auth_endpoint.py -q --no-cov``
  passed (91 passed); ``uv run pytest tests/test_consent_screen.py -q
  --no-cov`` passed (25 passed); ``uv run pytest
  tests/test_token_endpoint.py -q --no-cov`` passed (96 passed); ``uv run
  pytest tests/test_micropub_endpoint.py -q --no-cov`` passed (95 passed);
  targeted ``uv run ruff check`` passed; ``uv run pytest`` passed (1116
  passed, coverage gate reached at 90.34%); ``uv run mypy`` passed; ``uv run
  ruff check .`` passed; ``uv run ruff format . --check`` passed; ``uv run
  prek run --all-files`` passed; ``uv run sphinx-build -W -b html docs
  docs/_build/html`` passed; and ``git diff --check`` passed.

### Authenticate token introspection and gate server-managed Micropub properties

- Hardened ``POST /indieweb/token/introspect/`` so callers must authenticate
  with a strict ``Authorization: Bearer <caller-token>`` header before active
  token metadata can be returned. Caller tokens must be active, unexpired,
  owned by an active Django user, and accepted by
  ``INDIEWEB_CLIENT_ID_VALIDATOR``.
- Preserved bearer-header self-introspection when no form ``token`` field is
  submitted. A valid caller token can introspect itself or another active
  token owned by the same Django user; cross-owner, unknown, deleted, expired,
  inactive-owner, disallowed-client, and duplicate target-token lookups return
  the stable inactive JSON response to authenticated callers.
- Added Micropub server-managed property gating for ``uid`` and ``author``.
  JSON, simple JSON, and form-encoded creates now reject those properties with
  ``400 invalid_request`` before ``create_entry()`` is called. ``action=update``
  rejects ``replace``, ``add``, delete-list, and delete-map operations naming
  those properties before ``update_entry()`` is called.
- Preserved ordinary Micropub properties and command/extension properties such
  as ``mp-slug``, ``mp-channel``, ``mp-photo-alt``, ``mp-syndicate-to``, and
  ``post-status`` as handler-owned values.
- Backlog: removed the completed Priority 2 token introspection
  authentication item and the completed Priority 2 Micropub server-managed
  property gating item from ``BACKLOG.md``. No migrations were needed.
- Documentation: updated ``docs/api.rst`` and ``docs/indieauth.rst`` for
  authenticated token introspection, self-introspection, same-owner target
  authorization, inactive no-leak semantics, and 401 response headers. Updated
  ``docs/api.rst`` and ``docs/micropub.rst`` for create/update rejection of
  ``uid`` and ``author`` while preserving command properties. No
  ``docs/configuration.rst`` update was needed because no new operator setting
  was added. Searched ``README.rst`` and docs for stale introspection and
  Micropub property wording.
- Changelog: updated ``docs/changelog.rst`` with Unreleased security notes for
  authenticated introspection and Micropub server-managed property rejection.
- Validation: ``uv run pytest tests/test_token_endpoint.py -q --no-cov``
  passed (92 passed); ``uv run pytest tests/test_micropub_create.py -q
  --no-cov`` passed (39 passed); ``uv run pytest tests/test_micropub_actions.py
  -q --no-cov`` passed (40 passed); ``uv run pytest
  tests/test_micropub_endpoint.py -q --no-cov`` passed (94 passed);
  targeted ``uv run ruff check`` passed; ``uv run pytest
  tests/test_rate_limiting.py -q --no-cov`` passed (12 passed); ``uv run
  pytest`` passed (1094 passed, coverage gate reached at 90.49%); ``uv run
  mypy`` passed; ``uv run ruff check .`` passed; ``uv run ruff format .
  --check`` passed; ``uv run sphinx-build -W -b html docs docs/_build/html``
  passed; ``uv run prek run --all-files`` passed; and ``git diff --check``
  passed.

## 2026-05-06

### Harden Webmention source verification and Salmention resend policy

- Hardened receive-side Webmention source-link verification so links inside
  non-rendered ``<template>`` and ``<noscript>`` ancestors, links hidden inside
  HTML comments, and plain-text URL tokens in microformats content no longer
  verify a source link. Rendered ``href`` links and microformats URL
  properties keep the existing conservative canonical target matching.
- Added Salmention resend policy state to ``WebmentionOutboundTarget`` via
  migration ``0019``: ``last_attempted_at`` and ``consecutive_failures``.
  ``WebmentionSender.resend_salmentions()`` now applies a historical-only
  resend cooldown, successful-target cutoff, and consecutive-failure
  drop/delete policy while current targets remain eligible for delivery.
- Updated resend history maintenance so no-endpoint outcomes count as failures,
  failures increment the consecutive counter, successful deliveries reset it,
  and historical-only rows are deleted when they reach the configured failure
  threshold. Dry-run preview reports skips/drops without sending or mutating
  history.
- Updated ``send_webmentions --salmention-resend`` dry-run and send output to
  surface policy skips/drops and to keep skipped targets out of sent-result
  counts.
- Backlog: removed the completed Priority 1 Webmention source-link hardening
  item and Salmention resend-policy item from ``BACKLOG.md``.
- Documentation: updated ``docs/webmention.rst`` for rendered-link
  verification, text-token rejection, Salmention policy semantics, command
  output, and dry-run behavior. Updated ``docs/configuration.rst`` for
  ``INDIEWEB_SALMENTION_RESEND_COOLDOWN_SECONDS``,
  ``INDIEWEB_SALMENTION_SUCCESS_CUTOFF_SECONDS``, and
  ``INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES``. Searched ``README.rst``;
  no update was needed because it only has generic Webmention references.
- Changelog: updated ``docs/changelog.rst`` with Unreleased notes for the
  source-link verification hardening, new migration, Salmention policy
  settings, no-endpoint failure accounting, and command/dry-run output.
- Review follow-up: normalized historical-only post-attempt failure drops so
  the sender marks them with the same ``skipped``/``failure_drop``/``dropped``
  result fields as pre-attempt policy drops, keeping command summaries and
  output consistent. Removed the unused ``attempted`` argument from
  ``_record_outbound_target`` and clarified that the plain-text URL-token
  helper must not be used as standalone source-link proof.
- Validation: ``uv run pytest tests/test_webmention_processor.py -q
  --no-cov`` passed (125 passed); ``uv run pytest
  tests/test_webmention_sender.py -q --no-cov`` passed (62 passed); ``uv run
  pytest tests/test_send_webmentions_command.py -q --no-cov`` passed (18
  passed); ``uv run pytest tests/test_webmention_models.py -q --no-cov``
  passed (28 passed); targeted ``uv run ruff check`` passed; ``uv run python
  manage.py makemigrations --check --dry-run --settings=tests.settings``
  passed with no changes detected; ``uv run python manage.py migrate
  --settings=tests.settings`` applied all migrations including ``0019``;
  ``uv run pytest`` passed (1078 passed, coverage gate reached at 90.40%);
  ``uv run mypy`` passed; ``uv run ruff check .`` passed; ``uv run ruff format
  . --check`` passed; ``uv run sphinx-build -W -b html docs docs/_build/html``
  passed; ``uv run prek run --all-files`` passed; and ``git diff --check``
  passed.

### Restore consent CSRF protection and require redirect_uri-bound token exchange

- Restored CSRF enforcement for IndieAuth browser consent ``action=approve``
  and ``action=deny`` POSTs while preserving the legacy authorization-code
  verification POST as a CSRF-exempt protocol request.
- Moved the consent authentication gate before approve/deny redirect handling
  so unauthenticated denial submissions no longer redirect to client-provided
  ``redirect_uri`` values.
- Added clickjacking protection to the consent screen with
  ``X-Frame-Options: DENY`` and ``Content-Security-Policy: frame-ancestors
  'none'``. Moved bundled consent and token-management inline styles into
  ``src/indieweb/static/css/indieweb.css``.
- Hardened token exchange so a code issued with ``redirect_uri`` must be
  redeemed with one. Submitted and stored values are compared after
  normalizing scheme/host case, IDNA host forms, default ports,
  percent-encoded triplet case, and root empty-path/``/`` equivalence while
  preserving non-default ports, non-root paths, and query semantics.
- Backlog: removed the completed Priority 1 IndieAuth consent CSRF/open
  redirect item and the completed Priority 1 token-exchange
  ``redirect_uri`` matching item from ``BACKLOG.md``. No migrations were
  needed.
- Documentation: updated ``docs/api.rst``, ``docs/indieauth.rst``, and
  ``docs/configuration.rst`` for consent CSRF enforcement, frame protections,
  static bundled styles, and token-exchange ``redirect_uri`` matching.
  ``SECURITY_ANALYSIS.md`` now marks only the fixed consent CSRF/open redirect
  and token-exchange ``redirect_uri`` findings resolved while leaving
  unrelated findings open.
- Changelog: updated ``docs/changelog.rst`` with Unreleased security notes for
  the consent and token-exchange hardening.
- Review follow-up: hardened ``_normalize_redirect_uri`` so pathological
  historical stored values that fail URL parsing, IDNA encoding, or port
  parsing do not raise during token exchange; such rows now fail cleanly as
  mismatches and are consumed. Clarified the generic CSRF configuration docs
  and removed an over-specific inline-style assertion from the consent tests.
- Validation: ``uv run pytest tests/test_auth_endpoint.py -q --no-cov``
  passed (81 passed); ``uv run pytest tests/test_consent_screen.py -q
  --no-cov`` passed (21 passed); ``uv run pytest
  tests/test_token_endpoint.py -q --no-cov`` passed (91 passed); ``uv run
  ruff check src/indieweb/views.py tests/test_auth_endpoint.py
  tests/test_consent_screen.py tests/test_token_endpoint.py`` passed; ``uv
  run pytest`` passed (1063 passed, coverage gate reached at 90.67%); ``uv run
  mypy`` passed; ``uv run ruff check .`` passed; ``uv run ruff format .
  --check`` passed; ``uv run prek run --all-files`` passed; ``uv run
  sphinx-build -W -b html docs docs/_build/html`` passed; and ``git diff
  --check`` passed.

### Tighten IndieAuth bearer parsing and rotate unique token keys on reissue

- Tightened shared bearer-token parsing so token-protected resource views and
  token introspection accept only exactly two-part
  ``Authorization: Bearer <token>`` headers with a case-insensitive bearer
  scheme. Malformed bearer headers now fail closed instead of using the last
  whitespace-delimited fragment.
- Removed the Micropub/resource-server POST-body ``Authorization`` fallback.
  Access tokens remain unsupported in query strings.
- Added ``Cache-Control: no-store`` and ``WWW-Authenticate: Bearer`` to 401
  authentication failures from token-protected resource views while preserving
  the existing ``authentication error`` body and status.
- Added model and migration-level uniqueness for ``Auth.key`` and
  ``Token.key``. Migration ``0018_alter_auth_key_alter_token_key`` rotates
  accidental duplicate historical keys before adding the unique constraints so
  pathological existing databases can apply the migration.
- Added defensive ``MultipleObjectsReturned`` handling for token
  authentication, token introspection, token exchange auth-code lookup, and
  legacy Auth verification so duplicate-key races or pre-constraint rows fail
  as authentication/token-exchange failures instead of 500s.
- Changed token reissue to reuse the existing ``Token`` row, refresh
  ``expires_at``, rotate ``Token.key``, return HTTP 200, and return the new
  bearer key. The old bearer key stops authenticating immediately.
- Review follow-up: changed the defensive duplicate auth-code exchange path to
  delete all rows matching the submitted ``code`` and ``client_id`` before
  returning ``invalid_grant``, preserving one-time-use behavior for
  pathological pre-constraint data.
- Backlog: removed the completed Priority 1 bearer-parser/401-hygiene item and
  the completed Priority 1 unique-key/token-rotation item from
  ``BACKLOG.md``.
- Documentation: updated ``docs/api.rst``, ``docs/indieauth.rst``, and
  ``docs/micropub.rst`` for strict bearer headers, removal of POST-body
  ``Authorization``, 401 response headers, and token reissue rotation.
  ``SECURITY_ANALYSIS.md`` now marks the fixed bearer parsing, POST fallback,
  key uniqueness, duplicate-lookup, and token reissue issues resolved while
  leaving unrelated token hashing and admin-secret work open.
- Changelog: updated ``docs/changelog.rst`` with Unreleased security notes for
  strict bearer parsing, 401 hygiene, key uniqueness, duplicate-key handling,
  and token reissue rotation.
- Validation: ``uv run pytest tests/test_token_endpoint.py -q --no-cov``
  passed (81 passed); ``uv run pytest tests/test_auth_endpoint.py -q
  --no-cov`` passed (81 passed); ``uv run pytest
  tests/test_micropub_endpoint.py -q --no-cov`` passed (94 passed); ``uv run
  pytest tests/test_token_management.py -q --no-cov`` passed (9 passed);
  ``uv run ruff check src/indieweb/views.py src/indieweb/models.py
  tests/test_token_endpoint.py tests/test_auth_endpoint.py
  tests/test_micropub_endpoint.py tests/test_token_management.py`` passed;
  ``uv run python manage.py makemigrations --check --dry-run
  --settings=tests.settings`` passed with no changes detected; ``uv run
  python manage.py migrate --settings=tests.settings`` applied all migrations
  including ``0018`` successfully; ``uv run pytest`` passed (1046 passed,
  coverage gate reached at 90.68%); ``uv run mypy`` passed; ``uv run ruff
  check .`` passed; ``uv run ruff format . --check`` passed; ``uv run
  prek run --all-files`` passed; ``uv run sphinx-build -W -b html docs
  docs/_build/html`` passed; and ``git diff --check`` passed.

### Make IndieAuth authorization codes single-use on every failure path

- Updated ``TokenView.post`` so once a submitted authorization code resolves to
  an ``Auth`` row, every grant-validation failure consumes that row before
  returning the existing ``invalid_grant`` response.
- Preserved pre-lookup validation behavior for missing parameters, malformed
  ``redirect_uri`` values, invalid ``client_id`` values, and unknown codes so
  unrelated authorization-code rows are not deleted.
- Kept successful token exchange behavior intact while confirming success still
  deletes the authorization code.
- Redacted authorization codes in token endpoint logs, including missing
  parameter logs, unknown-code logs, and successful exchange logs, without
  changing existing token redaction.
- Added regression coverage proving PKCE, ``redirect_uri``, and ``scope``
  failures consume the matched authorization code and cannot be replayed for a
  token.
- Backlog: removed the completed Priority 1 IndieAuth authorization-code
  single-use item from ``BACKLOG.md``. No migrations were needed.
- Documentation: no user-facing docs beyond the changelog needed changes
  because response bodies, status codes, content types, settings, and public
  usage remain unchanged. ``SECURITY_ANALYSIS.md`` now marks the fixed
  authorization-code single-use finding resolved while leaving related token
  hardening issues open.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased security note.
- Validation: ``uv run pytest tests/test_token_endpoint.py -q --no-cov``
  passed (66 passed); ``uv run pytest tests/test_auth_endpoint.py -q
  --no-cov`` passed (80 passed); ``uv run ruff check src/indieweb/views.py
  tests/test_token_endpoint.py tests/test_auth_endpoint.py`` passed; ``uv run
  pytest`` passed (1026 passed, coverage gate reached at 90.56%); ``uv run
  mypy`` passed; ``uv run ruff check .`` passed; ``uv run ruff format .
  --check`` passed; ``uv run prek run --all-files`` passed; ``uv run
  sphinx-build -W -b html docs docs/_build/html`` passed; and ``git diff
  --check`` passed.

### Add shared SSRF-safe HTTP handling and synchronous Webmention/WebSub resource limits

- Added shared outbound HTTP safety helpers in ``src/indieweb/http_client.py``
  for absolute HTTP(S)-only validation, DNS-backed blocked-IP checks,
  redirect re-checking, explicit TLS verification on built-in clients, and
  decoded response byte limits.
- Routed Webmention source/Vouch fetching, Webmention sender discovery/content
  fetch/delivery, sender target filtering, Vouch payload validation, WebSub
  subscribe/unsubscribe requests, and WebSub publisher notifications through
  the shared safety path.
- Tightened ``POST /indieweb/webmention/`` URL validation so ``source``,
  ``target``, and ``vouch`` accept only HTTP(S).
- Added Webmention source/Vouch decoded-size limits, tighter fetch timeouts,
  nested response depth/candidate caps, and mentioning-entry search work caps.
- Hardened WebSub callback body handling by rejecting oversized
  ``Content-Length`` before reading the body where possible and preserving the
  existing body-size/content-type/signature/hook behavior for accepted bodies.
- Added regression coverage for private/loopback/metadata/IPv6/IPv4-mapped
  IPv6 URLs, DNS-to-private rejection, redirect-to-private rejection, allowed
  public mocked requests, endpoint scheme validation, oversized source
  handling, recursion caps, unsafe sender targets/Vouch, unsafe WebSub hubs,
  and WebSub callback content-length behavior.
- Backlog: removed the completed Priority 1 SSRF and synchronous DoS/resource
  limit items from ``BACKLOG.md``. Added a precise follow-up for Salmention
  resend cooldown/success-cutoff/failure-drop policy because that subpoint
  needs its own state/migration and command-output design.
- Documentation: updated ``docs/configuration.rst``, ``docs/webmention.rst``,
  and ``docs/websub.rst`` with new settings, HTTP(S)-only validation behavior,
  queue/rate-limit/body-size guidance, and operator-controlled WebSub hub
  guidance.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased security note.
- Validation: ``uv run pytest tests/test_webmention_processor.py
  tests/test_webmention_endpoint.py tests/test_webmention_sender.py
  tests/test_send_webmentions_command.py -q --no-cov`` passed (224 passed);
  ``uv run pytest tests/test_websub.py tests/test_websub_subscriber.py
  tests/test_notify_websub_command.py -q --no-cov`` passed (58 passed);
  ``uv run pytest tests/test_rate_limiting.py -q --no-cov`` passed
  (12 passed); ``uv run ruff check
  src/indieweb/http_client.py src/indieweb/processors.py
  src/indieweb/senders.py src/indieweb/websub.py src/indieweb/views.py
  tests/test_webmention_processor.py tests/test_webmention_endpoint.py
  tests/test_webmention_sender.py tests/test_websub.py
  tests/test_websub_subscriber.py`` passed; ``uv run pytest`` passed
  (1021 passed, coverage gate reached at 90.07%); ``uv run mypy`` passed;
  ``uv run ruff check .`` passed; ``uv run ruff format . --check`` passed;
  ``uv run prek run --all-files`` passed; ``uv run sphinx-build -W -b html
  docs docs/_build/html`` passed; and ``git diff --check`` passed.
- Follow-up risks: the helper performs DNS resolution and rejects unsafe
  resolved addresses before each request and redirect. It does not implement a
  custom transport that pins the already-validated IP address through the
  underlying TCP/TLS connection; deployments with strict DNS-rebinding threat
  models should combine this with egress firewalling or a dedicated outbound
  proxy.
- Review follow-up: changed Webmention source/Vouch and sender content fetches
  to use streamed decoded reads under the byte cap before materializing text,
  fixed IPv6 literal handling so public IPv6 literals can pass while blocked
  IPv6 ranges still fail, removed the hidden DNS-bypass branch from the
  non-streaming redirect helper, and made Webmention target host comparison
  case-insensitive. A Mock-client fallback remains only in the streaming helper
  for legacy unit-test compatibility; production callers instantiate real
  ``httpx.Client`` objects and use the resolver-backed streaming path.

### Sanitize remote Webmention HTML and Webmention author URL fields before display

- Added a shared Webmention sanitizer using ``nh3``. Processor-owned
  ``Webmention.content_html`` and ``WebmentionNestedResponse.content_html`` are
  allowlist-sanitized before persistence, while remote author URL/photo fields
  are blanked unless they are absolute HTTP(S) URLs.
- Applied the same sanitizer in ``show_webmentions`` before bundled templates
  render rows, so older stored Webmention and nested-response data is cleaned
  for bundled output without requiring a migration.
- Replaced ``webmention_endpoint_link`` f-string ``mark_safe`` usage with
  ``format_html`` and added regression coverage for escaping malicious custom
  endpoint arguments.
- Hardened bundled Webmention author/source links with
  ``rel="nofollow noopener ugc"`` and ``referrerpolicy="no-referrer"``; added
  the same outbound-link attributes to the h-card organization URL link.
- Added focused regression tests for script/event-handler/SVG/form/iframe/style
  payloads, unsafe ``javascript:``/``data:`` URL attributes, disallowed remote
  URL schemes, relative links inside remote HTML, nested response payloads,
  existing stored unsafe rows, and link attribute expectations.
- Backlog: removed the completed Priority 1 Webmention XSS item from
  ``BACKLOG.md``. No migrations were needed.
- Documentation: updated ``docs/webmention.rst`` with the sanitizer behavior,
  HTTP(S)-only remote author URL/photo policy, and custom-template guidance.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased security note.
- Review follow-up: fixed the ``ruff`` B018 report for the intentional malformed
  port probe and hardened sanitized remote HTML so relative ``href``/``cite``
  attributes are dropped instead of rendering same-origin-looking links.
- Validation: ``uv run pytest tests/test_webmention_processor.py
  tests/test_webmention_templatetags.py tests/test_h_card_templatetags.py -q``
  ran 155 selected tests successfully but exited non-zero because the
  repo-wide coverage gate reports 39.01% on this subset; ``uv run pytest
  tests/test_webmention_processor.py tests/test_webmention_templatetags.py
  tests/test_h_card_templatetags.py -q --no-cov`` passed (155 passed);
  ``uv run ruff check .`` passed; ``uv run ruff check src/indieweb/processors.py
  src/indieweb/templatetags/webmention_tags.py
  tests/test_webmention_processor.py tests/test_webmention_templatetags.py
  tests/test_h_card_templatetags.py`` passed; ``uv run ruff format . --check``
  passed after formatting; ``uv run sphinx-build -W -b html docs
  docs/_build/html`` passed; ``uv run pytest`` passed (997 passed, coverage
  gate reached at 90.60%); ``uv run mypy`` passed; ``uv run prek run
  --all-files`` passed; ``git diff --check`` passed; ``uv sync`` passed; and
  ``uv build`` passed.
- Follow-up risks: this slice intentionally did not change Webmention
  source/target SSRF handling, Webmention source-link verification, status URL
  privacy, or broader protocol endpoint hardening; those remain separate
  backlog items.

### Add curated agent learnings file

- Added ``AGENT_LEARNINGS.md`` as a small tracked guidance file for repeated,
  reviewed repo-specific agent lessons: backlog/DONE completion mechanics,
  Sphinx validation without staging ``docs/_build``, ``prek`` hook usage,
  pytest guidance for legacy ``django.test.TestCase`` files, and host-owned
  protocol boundary wording.
- Preserved the privacy boundary from the prior session-material evaluation:
  raw transcripts, prompts, command output, generated summaries, and private
  local context remain untracked and should not be promoted into the curated
  file.
- Backlog: removed the completed Agent Workflow Improvements item from
  ``BACKLOG.md``. No migrations were needed.
- Documentation: linked the curated file from ``AGENTS.md``. ``CLAUDE.md``
  already points to ``AGENTS.md``, so no separate Claude-specific duplication
  was needed. No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased
  developer-agent workflow note for the curated guidance file.
- Compatibility: no production runtime behavior, dependencies, migrations,
  models, settings, templates, endpoint URLs, endpoint semantics, public APIs,
  package metadata, hooks, scripts, CI jobs, transcript scraping, or generated
  docs changed for this slice.
- Follow-up risks: future updates to ``AGENT_LEARNINGS.md`` should stay short
  and require reviewed repo-specific evidence; generic agent advice and raw
  session material should remain out of tracked files.
- Validation: ``git diff --check`` (passed), ``git ls-files docs/_build
  --modified --others --exclude-standard`` (no output), ``uv run ruff check .``
  (passed), ``uv run ruff format . --check`` (92 files already formatted),
  ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed),
  ``uv run mypy`` (no issues), ``uv run pytest`` (980 passed, coverage gate
  passed at 90.54%), and ``uv run prek run --all-files`` (passed).

### Add Webmention.io import/display guidance without replacing built-in Webmention processing

- Documented Webmention.io as an optional host-owned integration choice, not a
  missing django-indieweb core endpoint and not a replacement for the built-in
  receive/send Webmention support.
- Added guidance for two host-owned patterns: advertising Webmention.io's
  external endpoint on selected pages instead of the built-in endpoint, and
  fetching Webmention.io JF2 from host code for display/import alongside
  verified django-indieweb ``Webmention`` rows.
- Documented conservative JF2 mapping guidance for ``wm-source``/``url``,
  ``wm-target``, author fields, content fields, timestamps, and common
  ``wm-property`` values. ``in-reply-to``, ``like-of``, and ``repost-of`` map
  to the built-in ``reply``, ``like``, and ``repost`` vocabulary; unknown
  values can fall back to ``mention`` or host-owned types.
- Clarified that ``bookmark-of`` and ``rsvp`` require host-owned handling or a
  lossy ``mention`` fallback because built-in ``Webmention`` and
  ``WebmentionNestedResponse`` mention-type choices do not include
  ``bookmark`` or ``rsvp``.
- Added safety guidance that Webmention.io JF2 and ``content.html`` are
  untrusted external content. Hosts must sanitize external HTML before
  rendering it or storing it in fields such as ``content_html`` that the
  bundled templates render with ``|safe``.
- Backlog: removed the completed Priority 4 Webmention.io guidance item from
  ``BACKLOG.md``. No migrations were needed.
- Documentation: updated ``docs/webmention.rst`` with the main guidance and
  updated ``docs/concepts.rst``, ``docs/configuration.rst``, and
  ``docs/api.rst`` with concise boundary notes. No generated docs under
  ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased documentation
  note.
- Compatibility: built-in Webmention endpoint behavior, sender behavior,
  processor verification, spam/Vouch behavior, Salmention behavior, async queue
  behavior, models, migrations, settings, templates, template tags, response
  shapes, dependencies, and tests are unchanged. No Webmention.io endpoint, API
  client, token setting, dashboard, model, import command, parser, scheduler,
  queue integration, or display tag was added.
- Follow-up risks: host projects that use Webmention.io still need their own
  account/token management, endpoint advertisement policy, API client, polling
  or webhook strategy, cache, moderation, sanitization, deduplication, target
  ownership checks, unsupported-type modeling, and reconciliation with
  processor-verified django-indieweb rows.
- Validation: ``uv run sphinx-build -W -b html docs docs/_build/html``
  (passed), ``git ls-files docs/_build --modified --others
  --exclude-standard`` (no output), ``uv run ruff check .`` (passed), ``uv run
  ruff format . --check`` (92 files already formatted), ``git diff --check``
  (passed), ``uv run mypy`` (no issues in 44 source files), ``uv run pytest``
  (980 passed, coverage gate passed at 90.54%), and ``uv run prek run
  --all-files`` (passed).

### Document Microsub and reader-side protocol non-goals

- Documented django-indieweb's protocol boundary: the package supports
  IndieAuth, Micropub publishing, Webmention, and WebSub publisher/subscriber
  helper workflows, but does not implement Microsub or other reader-side
  resource-server behavior.
- Clarified that reader-oriented IndieAuth extension scopes such as ``read``,
  ``follow``, ``mute``, ``block``, ``channels``, and similar strings may be
  requested, normalized, stored on auth codes and tokens, and returned by token
  issuance/introspection as opaque scope strings.
- Clarified that those reader scopes do not grant built-in django-indieweb
  behavior. The package still does not provide Microsub channels, feed
  fetching, following, muting, blocking, reader timelines, reader UI, a
  Microsub endpoint, a reader model, a parser, a scheduler, or a Microsub
  setting.
- Clarified that built-in IndieAuth metadata intentionally advertises only
  ``create``, ``update``, ``delete``, ``undelete``, and ``media`` because those
  are the bundled resource-server scopes. Reader scopes remain unadvertised.
- Clarified that Micropub ``q=channel`` and ``mp-channel`` are publishing-side
  configuration/command features, not Microsub channel support.
- Backlog: removed the completed Priority 4 Microsub and reader-side protocol
  non-goals item from ``BACKLOG.md``. No migrations were needed.
- Documentation: updated ``docs/concepts.rst``, ``docs/indieauth.rst``,
  ``docs/api.rst``, and ``docs/configuration.rst`` with concise non-goal,
  scope, metadata, endpoint inventory, and host-owned reader behavior
  guidance. No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased documentation
  note.
- Compatibility: endpoint behavior, token issuance, token introspection, scope
  normalization, Micropub scope gates, built-in metadata response shape,
  models, migrations, settings, and dependencies are unchanged.
- Follow-up risks: host projects that want reader-side protocols still need
  their own Microsub or reader endpoints, authorization policy, channel/feed
  models, following/muting/blocking semantics, feed fetching, timeline storage,
  UI, metadata/discovery behavior, and documentation.
- Validation: ``uv run sphinx-build -W -b html docs docs/_build/html``
  (passed), ``git ls-files docs/_build --modified --others
  --exclude-standard`` (no output), ``uv run ruff check .`` (passed), ``uv
  run ruff format . --check`` (92 files already formatted), ``git diff
  --check`` (passed), ``uv run mypy`` (no issues in 44 source files), ``uv
  run pytest`` (980 passed, coverage gate passed at 90.54%), and ``uv run prek
  run --all-files`` (passed).

### Document host-owned WebSub workflow examples for delivery processing and lease renewal

- Added tested examples in ``examples/websub_workflows.py`` for host-owned
  WebSub subscriber workflows. The examples show a delivery hook shaped for
  ``INDIEWEB_WEBSUB_DELIVERY_HOOK``, compact queue payload handoff, worker-side
  delegation to host-owned feed parsing and persistence, explicit lease
  renewal, and delivery-attempt pruning.
- Kept django-indieweb's boundary unchanged. The examples do not add a WebSub
  hub, automatic topic discovery, hidden network calls, background scheduler,
  queue dependency, feed parser, feed-entry model, retry policy, raw delivery
  body storage, or automatic pruning.
- Added focused tests for delivery payload queueing, delivery hook queue
  resolution, worker delegation, missing-subscription handling, candidate
  renewal with an injected requester, renewal exception capture, delivery
  attempt pruning, and retention validation.
- Backlog: removed the completed Priority 4 WebSub workflow examples item from
  ``BACKLOG.md``. No migrations were needed.
- Documentation: updated ``docs/websub.rst`` with host-owned delivery queue,
  worker parsing boundary, explicit lease renewal, and pruning examples;
  updated ``docs/configuration.rst`` with links from the WebSub delivery hook
  and model/command settings; updated ``docs/concepts.rst`` to remove this
  slice from future work. No generated docs under ``docs/_build`` were edited
  or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased
  documentation/examples note.
- Compatibility: WebSub endpoint behavior, callback validation, signature
  validation, model fields, migrations, settings contracts, and public helper
  signatures are unchanged. The new examples are opt-in host code.
- Follow-up risks: hosts still need their own queue implementation, worker
  retry policy, feed parsing, entry persistence, subscription ownership model,
  lease-renewal schedule, secret rotation policy, hub allowlist, and retention
  window.
- Validation: ``uv run pytest tests/test_websub_workflow_examples.py -q
  --no-cov`` (10 passed), ``uv run pytest tests/test_websub_subscriber.py
  tests/test_notify_websub_command.py -q --no-cov`` (40 passed), ``uv run
  ruff check .`` (passed), ``uv run ruff format . --check`` (92 files already
  formatted), ``uv run mypy`` (no issues in 44 source files), ``uv run
  sphinx-build -W -b html docs docs/_build/html`` (passed), ``git ls-files
  docs/_build --modified --others --exclude-standard`` (no output), ``git
  diff --check`` (passed), ``uv run pytest`` (980 passed, coverage gate passed
  at 90.54%), and ``uv run prek run --all-files`` (passed).

### Add static-site and storage-boundary Micropub handler examples

- Added tested examples in ``examples/static_site_micropub.py`` for host-owned
  static-site Micropub handlers. The examples map Micropub properties to
  Markdown paths, public URLs, YAML-compatible front matter, body content, and
  returned ``MicropubEntry`` values without changing endpoint behavior.
- Added conservative mapping helpers for ``mp-slug``/fallback slug generation,
  note/article/photo-like classification, published-date path segments, common
  front matter fields, and preservation of the original Micropub properties.
- Added storage-boundary examples for explicit local filesystem roots, explicit
  Django storage instances, and Git-backed repository adapters. The filesystem
  example rejects target collisions instead of silently overwriting an existing
  post. The Git example delegates to a host adapter only; it does not add
  credentials, network calls, commits, pushes, branch policy, or deploy
  automation.
- Added an ``IndexedMediaHooksMixin`` example that delegates ``list_media()``,
  ``get_media()``, and ``delete_media()`` to a durable host-owned media index
  so django-indieweb does not infer storage paths or deletion policy from
  submitted URLs.
- Added focused tests for property-to-document mapping, slug fallback,
  note/article/photo-like output, dict-shaped property values, local-root
  writes, collision rejection, escape rejection, explicit Django storage
  delegation, Git-adapter delegation, and media-index hook delegation.
- Backlog: removed the completed Priority 4 static-site/storage-boundary item
  from ``BACKLOG.md``. No migrations were needed.
- Documentation: updated ``docs/micropub.rst`` with static-site, filesystem,
  Django storage, Git-backed adapter, source-query/update/delete, and media
  index boundary guidance; updated ``docs/configuration.rst`` with
  ``INDIEWEB_MICROPUB_HANDLER`` guidance; updated ``docs/concepts.rst`` with
  the static-site boundary. No generated docs under ``docs/_build`` were
  edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased
  documentation/examples note.
- Compatibility: Micropub endpoint behavior, scopes, auth, CORS, rate
  limiting, media uploads, handler method signatures, and response shapes are
  unchanged. The new examples are opt-in host code.
- Follow-up risks: hosts still need their own durable URL-to-path index,
  collision resolution policy, update/delete/undelete semantics,
  rendering/build/deploy workflow, repository credentials, media metadata
  index, media authorization, and storage deletion audit trail.
- Validation: ``uv run pytest tests/test_static_site_micropub_examples.py -q
  --no-cov`` (11 passed), ``uv run pytest tests/test_micropub_media.py
  tests/test_micropub_create.py tests/test_micropub_actions.py
  tests/test_micropub_source.py -q --no-cov`` (169 passed), ``uv run ruff
  check .`` (passed), ``uv run ruff format . --check`` (90 files already
  formatted), ``uv run mypy`` (no issues in 44 source files), ``uv run
  sphinx-build -W -b html docs docs/_build/html`` (passed), ``git ls-files
  docs/_build --modified --others --exclude-standard`` (no output), ``git
  diff --check`` (passed), ``uv run pytest`` (970 passed, coverage gate passed
  at 90.54%), and ``uv run prek run --all-files`` (passed).

## 2026-05-05

### Add Micropub media source and delete extension points

- Added optional host-owned media hooks on ``MicropubContentHandler``:
  ``list_media(user, limit=None, offset=0, filter=None)``,
  ``get_media(url, user)``, and ``delete_media(url, user)``. The default
  methods are unsupported and do not require existing custom handlers to
  change.
- Added ``MicropubMediaItem`` and ``MicropubMediaList`` result dataclasses for
  hook responses. django-indieweb normalizes successful media source responses
  to ``{"properties": ...}`` items and adds a ``url`` property from the media
  item URL when a hook omits it.
- Added ``GET /indieweb/media/?q=source`` with the existing bearer-token,
  expired-token, inactive-owner, ``INDIEWEB_CLIENT_ID_VALIDATOR``, rate-limit,
  CORS, and exact ``media`` scope behavior. List mode dispatches to
  ``list_media()`` with optional ``limit``, ``offset``, and ``filter``; by-URL
  mode dispatches to ``get_media(url, user)``.
- Added media ``POST action=delete`` dispatch before the upload-only validation
  path. Form-encoded delete requests and JSON object bodies are accepted when
  they include ``url``. Successful deletes return ``204 No Content``.
- Preserved direct media upload behavior: multipart ``file`` uploads still use
  the existing Django storage name generation, size limit, content-type
  allowlist, error mapping, and ``201 Created`` ``Location`` response. Multipart
  Micropub create ``photo`` uploads remain unchanged.
- Kept the storage boundary conservative. django-indieweb does not maintain a
  built-in media index, infer storage paths from arbitrary URLs, delete
  ``default_storage`` files without a host hook, add a media management UI,
  transform media, or add a non-Django storage abstraction.
- Error behavior: missing hooks return ``501 not_implemented``; missing/empty,
  unknown, or hook-rejected media URLs return ``400 invalid_request``;
  malformed media list ``limit``/``offset`` values return
  ``400 invalid_request``; unexpected hook exceptions return ``500`` and are
  logged with ``logger.exception``.
- Backlog: removed the completed Priority 4 media source/delete item from
  ``BACKLOG.md``. No migrations were needed.
- Documentation: updated ``docs/micropub.rst``, ``docs/api.rst``, and
  ``docs/configuration.rst`` with the host-owned hook boundary, response
  shapes, scope policy, errors, and the explicit no-new-setting/no-built-in-index
  behavior. No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased media
  source/delete extension-point note.
- Compatibility: content Micropub ``q=config``, ``q=media-endpoint``,
  ``q=post-types``, ``q=source`` for posts, update/delete/undelete actions,
  direct media uploads, multipart create uploads, token authentication, client
  ID validation, CORS, rate limiting, and built-in IndieAuth metadata scopes are
  preserved apart from the additive media endpoint ``GET`` and delete branches.
- Follow-up risks: hosts still need to implement their own durable media
  index, metadata extraction, storage deletion policy, audit trail, thumbnails,
  transforms, and UI if they want those capabilities.
- Validation: ``uv run pytest tests/test_micropub_media.py -q --no-cov`` (79
  passed), ``uv run pytest tests/test_micropub_queries.py
  tests/test_micropub_endpoint.py -q --no-cov`` (181 passed), ``uv run pytest
  tests/test_cors.py tests/test_rate_limiting.py -q --no-cov`` (41 passed),
  ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (88 files
  already formatted), ``uv run mypy`` (no issues in 44 source files), ``uv run
  sphinx-build -W -b html docs docs/_build/html`` (passed), ``git ls-files
  docs/_build --modified --others --exclude-standard`` (no output), ``git
  diff --check`` (passed), ``uv run pytest`` (958 passed, coverage gate passed
  at 90.54%), and ``uv run prek run --all-files`` (passed).

### Preserve Micropub command properties and define draft-scope semantics

- Extended form-encoded Micropub create parsing so submitted ``mp-slug``,
  ``mp-channel``, ``mp-photo-alt``, ``mp-syndicate-to``, and ``post-status``
  values are preserved for ``MicropubContentHandler.create_entry()`` as
  normalized property arrays.
- Added ``mp-channel[]``, ``mp-photo-alt[]``, and ``mp-syndicate-to[]`` array
  notation support while preserving existing category comma-splitting and
  media upload behavior. Command properties are not comma-split.
- Kept JSON create behavior unchanged: Microformats2 JSON ``properties`` are
  still passed through unchanged, including command properties and
  ``post-status``.
- Kept command execution host-owned. django-indieweb preserves submitted
  command values but does not generate slugs, choose channels, write
  ``mp-photo-alt`` into files or media metadata, syndicate, enqueue
  syndication, store drafts, filter drafts, or add a draft workflow.
- Defined the conservative built-in ``draft`` scope policy. ``draft`` remains
  an opaque/host-owned extension scope that can be requested and stored but is
  not advertised in built-in IndieAuth metadata and does not satisfy
  ``create`` or ``update``. ``post-status=draft`` creates still require
  ``create`` or legacy ``post``; ``create draft`` succeeds because ``create``
  is present.
- Added parser and scope regression tests in ``tests/test_micropub_create.py``
  and ``tests/test_micropub_endpoint.py`` for single-value command
  properties, array command properties, ``post-status=draft``, JSON
  pass-through, and ``draft`` scope rejection.
- Backlog: removed the completed Priority 4 command-property/draft-scope item
  from ``BACKLOG.md``. No migrations were needed.
- Documentation: updated ``docs/micropub.rst``, ``docs/api.rst``, and
  ``docs/indieauth.rst`` with command-property shapes, form and JSON examples,
  host-owned execution boundaries, and conservative ``draft`` scope semantics.
  No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased note for
  form-encoded command-property preservation, JSON pass-through compatibility,
  host-owned command execution, and ``draft`` scope semantics.
- Compatibility: existing Micropub create, update, delete, undelete,
  ``q=config``, ``q=source``, ``q=category``, ``q=channel``,
  ``q=media-endpoint``, ``q=post-types``, ``q=syndicate-to``, default ``GET``,
  media upload, token authentication, scope gating, CORS, rate limiting, and
  built-in IndieAuth metadata scopes remain unchanged beyond additive
  form-property preservation.
- Follow-up risks: media source/delete hooks, static-site/storage handler
  examples, actual syndication execution, draft-only permission policies,
  channel routing, slug generation, and alt-text persistence remain explicitly
  host-owned or separate backlog work.
- Validation: ``uv run pytest tests/test_micropub_create.py
  tests/test_micropub_endpoint.py tests/test_micropub_actions.py -q --no-cov``
  (155 passed), ``uv run pytest tests/test_micropub_queries.py
  tests/test_micropub_media.py -q --no-cov`` (129 passed), ``uv run pytest
  tests/test_cors.py tests/test_rate_limiting.py -q --no-cov`` (40 passed),
  ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (88
  files already formatted), ``uv run mypy`` (no issues in 44 source files),
  ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``git
  ls-files docs/_build --modified --others --exclude-standard`` (no output),
  ``git diff --check`` (passed), ``uv run pytest`` (918 passed, coverage gate
  passed at 90.56%), and ``uv run prek run --all-files`` (passed).

### Route Micropub syndication targets through handler configuration

- Updated ``GET /indieweb/micropub/?q=syndicate-to`` to read the configured
  ``MicropubContentHandler.get_config(user)`` ``syndicate-to`` list instead of
  returning an unconditional empty list.
- Kept the built-in/default handler behavior unchanged: no configured targets
  returns ``{"syndicate-to": []}``.
- Added defensive handling for custom handlers. Missing or non-list
  ``syndicate-to`` values return an empty list rather than raising, while
  ``q=config`` preserves a custom handler's configured ``syndicate-to`` value
  unchanged.
- Preserved authentication and scope behavior. ``q=syndicate-to`` remains
  token-required only and does not require ``create``, ``update``, ``delete``,
  ``undelete``, ``media``, or any other operation scope.
- Backlog: removed the completed Priority 4 syndication-target item from
  ``BACKLOG.md``. No migrations were needed.
- Documentation: updated ``docs/micropub.rst`` and ``docs/api.rst`` with the
  handler-backed response shape, default empty behavior, expected target fields
  (``uid``, ``name``, optional ``service`` metadata, optional ``checked``), and
  the host-owned syndication boundary. No generated docs under ``docs/_build``
  were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased note for the
  handler-backed ``q=syndicate-to`` response, defensive empty-list behavior,
  default-handler compatibility, no-scope-gate behavior, and explicit
  syndicator/plugin exclusions.
- Compatibility: existing Micropub create, update, delete, undelete,
  ``q=config``, ``q=source``, ``q=category``, ``q=channel``,
  ``q=media-endpoint``, ``q=post-types``, default ``GET``, media upload, token
  authentication, scope gating, CORS, and rate-limit behavior remains
  unchanged beyond the direct ``q=syndicate-to`` response now reflecting
  custom handler configuration.
- Follow-up risks: actual cross-posting, webhook-triggered syndication,
  syndicator credentials, syndicator plugins, ``mp-syndicate-to`` form
  forwarding, wider ``mp-*`` command-property preservation, and draft-scope
  semantics remain out of scope and are owned by separate backlog items or host
  code.
- Validation: ``uv run pytest tests/test_micropub_queries.py
  tests/test_micropub_endpoint.py tests/test_micropub_create.py -q --no-cov``
  (203 passed), ``uv run pytest tests/test_cors.py tests/test_rate_limiting.py
  -q --no-cov`` (40 passed), ``uv run ruff check .`` (passed), ``uv run ruff
  format . --check`` (88 files already formatted), ``uv run mypy`` (no
  issues), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed),
  ``git ls-files docs/_build --modified --others --exclude-standard`` (no
  output), ``git diff --check`` (passed), ``uv run pytest`` (908 passed,
  coverage gate passed at 90.56%), and ``uv run prek run --all-files``
  (passed).

### Advertise and document audio/video Micropub post types

- Added built-in ``audio`` and ``video`` post-type entries to the default
  ``MicropubContentHandler.get_config()`` ``post-types`` list. The advertised
  shapes are ``audio``/``video`` plus optional ``content`` and ``category``:
  ``{"type": "audio", "name": "Audio", "properties": ["audio", "content",
  "category"]}`` and ``{"type": "video", "name": "Video", "properties":
  ["video", "content", "category"]}``.
- Kept the behavior boundary narrow: django-indieweb continues to normalize
  and forward URL-valued ``audio`` and ``video`` form properties to the
  configured handler, while host code decides how submitted properties map to
  models, persistence, and rendering.
- Preserved custom handler authority. Handlers that override ``post-types``
  still control the exact ``q=config`` and direct ``q=post-types``
  advertisement.
- Backlog: removed the completed Priority 4 Micropub item from ``BACKLOG.md``.
  No migrations were needed.
- Documentation: updated ``docs/micropub.rst`` and ``docs/api.rst`` with the
  default audio/video post-type entries, direct-query behavior, host-owned
  persistence/rendering boundary, and explicit exclusions. No generated docs
  under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased note for the
  audio/video post-type advertisement, normalized property forwarding, custom
  handler authority, and explicit media-processing exclusions.
- Compatibility: existing Micropub create, update, delete, undelete,
  ``q=config``, direct ``q=post-types``, ``q=source``, ``q=category``,
  ``q=channel``, ``q=syndicate-to``, media upload, token authentication, scope
  gating, CORS, and rate-limit behavior remains unchanged beyond the additive
  default post-type advertisement.
- Follow-up risks: media source/delete hooks, command properties, draft-scope
  semantics, and syndication routing remain out of scope and are owned by
  separate backlog items. Advertising audio/video post types does not add
  transcoding, players, storage models, media processing, media-management UI,
  or media deletion semantics.
- Validation: ``uv run pytest tests/test_micropub_create.py
  tests/test_micropub_queries.py -q --no-cov`` (100 passed),
  ``uv run pytest tests/test_micropub_media.py -q --no-cov`` (39 passed),
  ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (88 files
  already formatted), ``uv run mypy`` (no issues), ``uv run sphinx-build -W -b
  html docs docs/_build/html`` (passed), ``git ls-files docs/_build --modified
  --others --exclude-standard`` (no output), ``git diff --check`` (passed),
  ``uv run pytest`` (889 passed, coverage gate passed at 90.54%), and
  ``uv run prek run --all-files`` (passed).

### Add Micropub supported-vocabulary and direct config subqueries

- Added direct ``GET /indieweb/micropub/?q=media-endpoint`` and
  ``GET /indieweb/micropub/?q=post-types`` configuration subqueries. The media
  endpoint query returns the same effective value as ``q=config``, preserving a
  truthy custom handler value and otherwise injecting the bundled media
  endpoint as an absolute URL. The post-types query returns the configured
  handler's ``post-types`` list under the ``post-types`` JSON key.
- Kept ``MicropubContentHandler.get_config(user)`` authoritative for custom
  config. The view now builds one copied effective config payload before
  injecting view-owned defaults, so direct subqueries and ``q=config`` share
  the same values without mutating handler-owned dicts.
- Added ``post-type`` filtering for ``q=post-types`` plus the same
  ``filter``/``limit``/``offset`` policy used by other list-valued config
  queries. Missing or non-list ``post-types`` config returns an empty list;
  unknown ``post-type`` or unmatched ``filter`` values return an empty list;
  malformed ``limit`` or ``offset`` returns ``400 invalid_request``.
- Updated ``q=config`` discovery to advertise ``media-endpoint`` and
  ``post-types`` in the ``q`` array, while documenting that standalone
  ``q=properties`` and unrelated extension query names such as ``q=contacts``
  remain unsupported.
- Backlog: removed the completed Priority 4 Micropub item from ``BACKLOG.md``.
  No migrations were needed.
- Documentation: updated ``docs/micropub.rst`` and ``docs/api.rst`` with direct
  query examples, response shapes, filtering behavior, scope behavior,
  custom-handler authority, and unsupported query boundaries. No generated docs
  under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased note for the
  direct config subqueries, query discovery update, filtering/error policy,
  custom-handler behavior, and explicit exclusions.
- Compatibility: existing Micropub create, update, delete, undelete,
  ``q=config`` aggregate shape, ``q=category``, ``q=channel``, ``q=source``,
  ``q=syndicate-to``, default ``GET``, media upload, token authentication,
  scope gating, CORS, and rate-limit behavior remains unchanged beyond the
  additive direct subqueries and expanded ``q`` advertisement.
- Follow-up risks: advertising audio/video post types, ``mp-*`` command
  properties, draft-scope semantics, media source/delete hooks, and syndication
  routing remain explicitly out of scope and are owned by separate backlog
  items.
- Validation: ``uv run pytest tests/test_micropub_queries.py
  tests/test_micropub_endpoint.py tests/test_micropub_media.py
  tests/test_micropub_create.py -q --no-cov`` (222 passed),
  ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (88 files
  already formatted), ``git diff --check`` (passed), ``uv run pytest`` (888
  passed, coverage gate passed at 90.54%), ``uv run mypy`` (no issues),
  ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed),
  ``git ls-files docs/_build --modified --others --exclude-standard`` (no
  output), and ``uv run prek run --all-files`` (passed).

### Add Micropub source-list pagination and filtering

- Added ``GET /indieweb/micropub/?q=source`` list mode when no ``url`` parameter
  is supplied. The endpoint now calls the optional
  ``MicropubContentHandler.list_entries(user, limit=..., offset=..., filter=...)``
  hook and returns JSON shaped as ``{"items": [...], "paging": {...}}``. Items
  are Microformats-style source objects with ``type`` and ``properties``; list
  mode adds a ``url`` property from ``MicropubEntry.url`` when the handler did
  not already include one so clients can submit that URL to source-by-URL,
  update, delete, or undelete requests.
- Added ``MicropubEntryList`` as the list hook result. Existing custom handlers
  are not forced into a new abstract method: the base ``list_entries()`` method
  returns ``None``, and the view maps that unsupported capability to
  ``501 not_implemented``. Handler ``ValueError`` in list mode maps to
  ``400 invalid_request``; unexpected exceptions still map to ``500`` and are
  logged.
- Pagination/filtering policy: ``limit`` and ``offset`` are non-negative
  integers; malformed values return ``400 invalid_request``. Omitted ``limit``
  defaults to ``20`` to avoid unbounded source-list responses, and omitted
  ``offset`` defaults to ``0``. ``filter`` is passed through to the handler as a
  free-form string. The bundled in-memory handler supports accurate ``total``
  after filtering and before pagination, plus case-insensitive substring
  matching against a stable JSON serialization of each source item.
- Preserved existing ``GET ?q=source&url=...`` behavior: the endpoint still
  requires ``update`` scope, returns full source content as
  ``{"type": [...], "properties": {...}}``, returns selective
  ``properties[]`` responses as ``{"properties": {...}}``, returns
  ``400 invalid_request`` for empty or unknown submitted URLs and handler
  ``ValueError``, and returns ``500`` for unexpected handler exceptions.
- Backlog: removed the completed Priority 4 Micropub item from ``BACKLOG.md``.
  No migrations were needed.
- Documentation: updated ``docs/micropub.rst`` with source-list examples,
  response shape, default limit, filter/limit/offset policy, unsupported-handler
  behavior, and boundaries; updated ``docs/api.rst`` with endpoint reference
  details and error cases. No generated docs under ``docs/_build`` were edited
  or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased note for the
  source-list hook, response shape, pagination/filtering policy,
  unsupported-handler behavior, compatibility guarantees, and explicit
  exclusions.
- Compatibility: existing Micropub create, update, delete, undelete,
  source-by-URL, ``properties[]`` filtering, ``q=config``, ``q=category``,
  ``q=channel``, ``q=syndicate-to``, default ``GET``, media upload, scope
  gating, token authentication, CORS, and rate-limit behavior remains unchanged
  apart from the additive list-mode branch for ``GET ?q=source`` without
  ``url``.
- Follow-up risks: cursor ``after``/``before`` pagination, bundled post
  storage/search, direct configuration subqueries (``q=media-endpoint``,
  ``q=post-types``, supported vocabulary), media source/delete hooks,
  ``mp-*`` command properties, draft-scope semantics, and syndication routing
  remain explicitly out of scope and are owned by separate backlog items.
- Validation: ``uv run pytest tests/test_micropub_source.py
  tests/test_micropub_endpoint.py tests/test_micropub_queries.py -q --no-cov``
  (149 passed), ``uv run pytest tests/test_micropub_create.py
  tests/test_micropub_actions.py tests/test_micropub_media.py -q --no-cov``
  (100 passed), ``uv run pytest tests/test_cors.py tests/test_rate_limiting.py
  -q --no-cov`` (40 passed), ``uv run ruff check .`` (passed),
  ``uv run ruff format . --check`` (88 files already formatted),
  ``uv run mypy`` (no issues), ``uv run sphinx-build -W -b html docs
  docs/_build/html`` (passed), ``git ls-files docs/_build --modified --others
  --exclude-standard`` (no output), ``git diff --check`` (passed),
  ``uv run pytest`` (857 passed, coverage gate passed at 90.51%), and
  ``uv run prek run --all-files`` (passed).

### Add Micropub category, channel, and query-discovery support

- Added ``GET /indieweb/micropub/?q=category`` and ``?q=channel`` using the configured
  ``MicropubContentHandler.get_config(user)`` as the authoritative data source. ``q=category``
  returns the handler's ``categories`` list under the JSON key ``categories``; ``q=channel``
  returns the handler's ``channels`` list under ``channels``. Missing ``categories`` or
  ``channels`` keys in a custom handler config return an empty list rather than raising.
- Added ``filter``, ``limit``, and ``offset`` support for both list-valued queries. ``filter``
  is matched case-insensitively as a substring against string items, or against a stable JSON
  serialization of dict items so common fields such as ``uid`` and ``name`` are searchable
  without per-handler configuration. ``limit`` and ``offset`` must be non-negative integers;
  malformed values (non-integers, negative numbers, or floats) return ``400 invalid_request``
  rather than being silently coerced to zero. The order of operations is filter → offset →
  limit.
- Added query discovery to ``GET /indieweb/micropub/?q=config``. The response now includes a
  ``q`` array advertising only the query names django-indieweb implements
  (``config``, ``source``, ``syndicate-to``, ``category``, ``channel``); direct configuration
  subqueries such as ``q=media-endpoint`` and ``q=post-types`` are intentionally not advertised
  because they are owned by a separate backlog item. The bundled handler now also includes
  default empty ``categories`` and ``channels`` keys, and the view copies the handler config
  before injecting ``media-endpoint`` and ``q`` so cached or shared handler-owned dicts are not
  mutated across requests.
- ``q=category`` and ``q=channel`` are token-required only (no scope gate), matching existing
  ``q=config`` and ``q=syndicate-to`` behavior. Existing Micropub create, update, delete,
  undelete, ``q=source``, ``q=config``, ``q=syndicate-to``, ``GET`` with no ``q``, media
  upload, CORS, and rate-limit semantics remain unchanged.
- Backlog: removed the completed Priority 4 Micropub item from ``BACKLOG.md``. No migrations
  were needed.
- Documentation: updated ``docs/micropub.rst`` with category/channel query behavior, examples,
  filter/limit/offset policy, and query discovery in ``q=config``; updated ``docs/api.rst``
  with endpoint reference details for ``q=category`` and ``q=channel``, the new ``q``
  advertisement in ``q=config``, the no-scope-gate listing, and the ``400 invalid_request``
  listing for malformed ``limit``/``offset``. No generated docs under ``docs/_build`` were
  edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased note for category/channel
  queries, the ``q`` advertisement, default empty ``categories``/``channels`` config, the
  filter/limit/offset policy, the malformed-input behavior, the no-scope-gate guarantee, and
  the explicit out-of-scope items.
- Compatibility: existing Micropub endpoint behavior (create, update, delete, undelete,
  ``q=source``, ``q=config`` aggregate response shape, ``q=syndicate-to``, default ``GET``,
  media uploads, scope gating, token authentication, CORS, and rate limiting) is unchanged
  beyond the additive ``q``/``categories``/``channels`` keys and the two new query branches.
  Custom handlers that already returned ``categories``/``channels`` keys continue to work
  unchanged.
- Follow-up risks: Indiekit-style channel routing on create/update, ``mp-channel`` command
  property forwarding, ``GET ?q=source`` post-list pagination, direct configuration subqueries
  (``q=media-endpoint``, ``q=post-types``, supported-vocabulary), and host-owned syndication
  target routing remain explicitly out of scope and are owned by separate backlog items.
- Validation: ``uv run pytest tests/test_micropub_endpoint.py tests/test_micropub_create.py
  tests/test_micropub_source.py tests/test_micropub_actions.py tests/test_micropub_media.py
  tests/test_micropub_queries.py -q --no-cov`` (232 passed),
  ``uv run pytest tests/test_cors.py tests/test_rate_limiting.py -q --no-cov`` (passed),
  ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (88 files already
  formatted), ``uv run mypy`` (no issues), ``uv run sphinx-build -W -b html docs
  docs/_build/html`` (passed), ``git ls-files docs/_build --modified --others
  --exclude-standard`` (no output), ``git diff --check`` (passed), ``uv run pytest`` (full
  suite passed with coverage gate), and ``uv run prek run --all-files`` (passed).

### Add IndieAuth token introspection

- Added the bundled ``POST /indieweb/token/introspect/`` endpoint with the stable URL name
  ``token-introspection``. The endpoint accepts a form ``token`` value or falls back to
  ``Authorization: Bearer <token>`` as the token being checked, and always returns JSON.
- Active introspection responses include ``active``, ``me``, ``client_id``, ``scope``, ``iat``, and ``exp`` when the
  token has an expiration. Inactive responses are the stable shape ``{"active": false}`` for missing, unknown,
  deleted/revoked, expired, inactive-owner, and ``INDIEWEB_CLIENT_ID_VALIDATOR``-disallowed tokens, without disclosing
  which condition applied.
- Updated server metadata to advertise the absolute ``introspection_endpoint`` only now that the endpoint exists. The
  endpoint is CSRF-exempt, participates in configured CORS for ``POST``, and uses the optional
  ``token_introspection`` rate-limit key.
- Backlog: removed the completed Priority 3 API Hardening item from ``BACKLOG.md``. No migrations were needed.
- Documentation: updated IndieAuth, API, and configuration docs with token introspection request/response behavior,
  metadata advertisement, CORS/rate-limit behavior, and boundaries. No generated docs under ``docs/_build`` were edited
  or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased note for token introspection, metadata advertisement,
  CORS/rate-limit support, and intentional exclusions.
- Compatibility: existing authorization-code issuance and exchange behavior remains intact, including legacy
  ``response_type``/``grant_type`` omissions, ``token_type=Bearer``, JSON/form success negotiation, PKCE, scope
  matching, one-time auth code use, token expiration, CORS, rate limiting, and the browser token-management UI. The
  introspection endpoint does not create tokens, refresh expiration, delete rows, mutate token state, or expose full
  bearer token keys.
- Follow-up risks: protocol token revocation, refresh tokens, and user-info/profile claims remain out of scope and are
  not advertised. The existing ``/indieweb/tokens/`` pages remain authenticated browser UI for users to delete their own
  token rows, not an OAuth/IndieAuth revocation endpoint.
- Validation: ``uv run pytest tests/test_token_endpoint.py tests/test_auth_endpoint.py -q --no-cov`` (143 passed),
  ``uv run pytest tests/test_cors.py tests/test_rate_limiting.py -q --no-cov`` (40 passed),
  ``uv run pytest tests/test_token_endpoint.py tests/test_token_management.py tests/test_auth_endpoint.py -q --no-cov``
  (152 passed), ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (87 files already formatted),
  ``uv run mypy`` (no issues), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed),
  ``git ls-files docs/_build --modified --others --exclude-standard`` (no output), ``git diff --check`` (passed),
  ``uv run pytest`` (801 passed, coverage gate passed at 90.28%), and ``uv run prek run --all-files`` (passed).

### Tighten IndieAuth authorization and token wire compatibility

- Added backwards-compatible IndieAuth/OAuth wire handling: authorization GET accepts omitted ``response_type`` for
  legacy clients, accepts ``response_type=code``, and rejects any other present value; token POST accepts omitted
  ``grant_type`` for legacy clients, accepts ``grant_type=authorization_code``, and rejects any other present value.
- Added explicit JSON success negotiation for profile-code verification and token exchange. JSON is returned only when
  ``Accept: application/json`` is explicitly preferred; default and wildcard-only requests keep the legacy
  ``application/x-www-form-urlencoded`` body. Access-token responses now include ``token_type=Bearer`` in both form and
  JSON formats, while preserving the existing ``201`` newly-created and ``200`` reissued-token status semantics.
- Added ``iss`` to successful authorization approval redirects using the same request-derived issuer policy as bundled
  metadata, such as ``https://example.com/indieweb/`` for the standard mount. Denial redirects intentionally omit
  ``iss`` because the IndieAuth spec says clients must not assume error responses came from the intended authorization
  server.
- Added read-only CORS support to the public IndieAuth metadata view for configured ``GET`` requests. The endpoint
  remains public and is not covered by ``INDIEWEB_RATE_LIMITS``.
- Backlog: removed the completed Priority 3 API Hardening item from ``BACKLOG.md``. Token introspection remains the
  next API hardening item and still owns adding a real introspection endpoint plus any ``introspection_endpoint``
  metadata advertisement.
- Documentation: updated IndieAuth, API, and configuration docs with the compatibility policy, JSON negotiation,
  ``token_type=Bearer``, authorization-response ``iss`` behavior, denial behavior, issuer guidance, and metadata CORS
  behavior. No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased note for the compatibility changes and metadata CORS
  follow-up.
- Compatibility: existing auth-code, state, legacy ``me``, redirect-uri query merging, PKCE, scope normalization, scope
  matching, one-time auth code use, token expiration, CORS, and rate-limit behavior remains intact. This slice did not
  add token introspection, protocol token revocation, refresh tokens, user-info/profile claims beyond the existing
  profile-code verification response, Pushed Authorization Requests, password setup, or Indiekit's signed-JWT
  authorization-code model.
- Follow-up risks: future introspection work should update metadata only when the real endpoint exists. Protocol
  revocation, richer user-info/profile claims, refresh tokens, and client-facing canonical issuer choices for
  host-level well-known deployments remain separate decisions.
- Validation: ``uv run pytest tests/test_auth_endpoint.py tests/test_consent_screen.py tests/test_token_endpoint.py -q
  --no-cov`` (147 passed), ``uv run pytest tests/test_cors.py tests/test_rate_limiting.py -q --no-cov`` (38 passed),
  ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (87 files already formatted), ``uv run mypy`` (no
  issues), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed),
  ``git ls-files docs/_build --modified --others --exclude-standard`` (no output), ``git diff --check`` (passed),
  ``uv run pytest`` (789 passed, coverage gate passed at 90.18%), and ``uv run prek run --all-files`` (passed).

## 2026-05-03

### Add IndieAuth server metadata and discovery endpoints

- Added the public ``/indieweb/auth/metadata/`` IndieAuth authorization-server metadata endpoint. The response is JSON
  with absolute issuer, authorization endpoint, token endpoint, ``code`` response type, ``authorization_code`` grant
  type, current PKCE methods (``plain`` and ``S256``), built-in Micropub scopes (``create``, ``update``, ``delete``,
  ``undelete``, and ``media``), and service documentation.
- Added the reusable ``IndieAuthMetadataView`` so host projects can route the same view at
  ``/.well-known/oauth-authorization-server`` without django-indieweb assuming root URL ownership. The mounted
  endpoint derives the issuer from the common app mount prefix; the well-known route derives it from the site root.
- Backlog: removed the completed Priority 3 API Hardening item from ``BACKLOG.md``. The follow-up IndieAuth wire
  compatibility item still owns authorization-response ``iss`` work, and the introspection item still owns adding and
  advertising ``introspection_endpoint``.
- Review follow-up: added ``grant_types_supported`` to match the token endpoint's authorization-code exchange behavior,
  pointed ``service_documentation`` at the human-readable IndieAuth docs, cleaned up the bearer-header public-access
  regression test, documented canonical metadata URL selection before future ``iss`` work, and clarified that
  script-prefix well-known deployments are handled by the common-prefix issuer branch. Re-review follow-up renamed the
  new configuration section to avoid duplicating the existing ``URL Configuration`` heading.
- Documentation: updated IndieAuth, API, and configuration docs with metadata response fields, profile-page discovery
  guidance, host URLconf guidance for well-known publication, and canonical metadata URL guidance. No generated docs
  under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased note for the new public metadata endpoint and its
  intentional exclusions.
- Compatibility: existing IndieAuth authorization, token exchange, token management, Micropub, Webmention, WebSub,
  CORS, and rate-limit behavior remains unchanged. The metadata endpoint is public and does not require login or a
  bearer token. This slice intentionally did not add token introspection, protocol revocation, refresh tokens,
  user-info/profile claims, Indiekit password setup, Pushed Authorization Requests, or Indiekit's signed-JWT auth-code
  model.
- Follow-up risks: future ``iss`` redirect behavior should remain sequenced after this issuer work; future token
  introspection should update metadata only when a real endpoint exists. The metadata advertises preferred built-in
  scopes and does not advertise legacy ``post`` or unsupported reader-side scopes such as ``read``, ``follow``,
  ``mute``, ``block``, or ``channels``.
- Validation: ``uv run pytest`` (776 passed, coverage gate passed at 90.30%),
  ``uv run pytest tests/test_auth_endpoint.py tests/test_token_endpoint.py -q --no-cov`` (122 passed),
  ``uv run pytest tests/test_cors.py tests/test_rate_limiting.py -q --no-cov`` (36 passed),
  ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (87 files already formatted), ``uv run mypy``
  (no issues), ``uv run prek run --all-files`` (passed),
  ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed),
  ``git ls-files docs/_build --modified --others --exclude-standard`` (no output), and ``git diff --check`` (passed).

### Fill Indiekit comparison backlog

- Completed the four Indiekit comparison tracks against the local Indiekit checkout at ``1ee20d06`` and the example
  config checkout at ``b11b749``. The comparison covered IndieAuth/token metadata and wire behavior, Micropub/media
  extension queries and command properties, storage/preset/syndication architecture, and Webmention/WebSub/reader-side
  boundaries.
- Replaced the temporary ``BACKLOG.md`` comparison scaffold with concrete django-indieweb follow-up items under API
  Hardening, Micropub Enhancements and Extensions, WebSub Enhancements, Syndication and Storage Examples, and
  Webmention and Reader Boundaries.
- Backlog: added implementable slices for IndieAuth metadata/discovery, IndieAuth token wire compatibility, token
  introspection boundaries, Micropub category/channel/query discovery, source-list pagination/filtering, direct config
  subqueries, ``mp-*``/draft semantics, media source/delete hooks, audio/video post-type advertisement, handler-backed
  syndication targets, static-site/storage examples, WebSub host workflow examples, Webmention.io guidance, and
  Microsub/reader-side non-goal documentation.
- Review follow-up: tightened the broad IndieAuth wire-compatibility item to make ``iss`` sequencing depend on server
  metadata work, clarified that the WebSub renewal/delivery slice is documentation/example work, and noted that
  audio/video post-type advertisement should follow the direct ``q=post-types`` query decision.
- Documentation: no Sphinx docs were changed in this slice. ``BACKLOG.md`` and ``DONE.md`` are the project-planning
  records updated for the completed comparison.
- Changelog: no ``docs/changelog.rst`` update was needed because this slice changed backlog/planning bookkeeping only;
  it did not change runtime behavior, public APIs, settings, endpoint semantics, examples, or user-facing Sphinx docs.
- Compatibility: no protocol behavior, models, migrations, endpoint URLs, settings, templates, tests, or generated docs
  were changed. The new backlog items distinguish real gaps from intentional non-goals so future implementation slices
  can preserve django-indieweb's host-owned storage and rendering boundaries.
- Follow-up risks: the backlog intentionally does not propose copying Indiekit's all-in-one content-store, publication
  preset, syndicator, password-auth, Webmention.io dashboard, WebSub hub, or Microsub reader architecture into core.
  Future implementation slices still need to choose exact URL names and compatibility modes for IndieAuth metadata,
  token introspection, Micropub extension queries, and media listing/deletion hooks.
- Validation: ``git diff --check`` (passed). Final staging/status checks are recorded in the implementer report.

### Harden WebSub subscriber denial, lease maintenance, and delivery diagnostics

- Added ``hub.mode=denied`` callback handling for tokenized WebSub subscriber verification ``GET`` requests. Denials
  validate the exact topic URL, record bounded ``hub.reason`` diagnostics, clear pending state, and return
  ``204 No Content`` when accepted. Initial subscribe denials move rows to ``denied``; active renewal denials preserve
  the current active lease and secret while dropping staged renewal state; unsubscribe denials restore the row to
  ``active`` so deliveries can continue.
- Added denial diagnostics on ``WebSubSubscription`` plus metadata-only ``WebSubDeliveryAttempt`` history rows for
  recorded delivery attempts. The delivery history stores received time, content type, byte size, SHA-256 digest,
  signature algorithm, status code, and bounded error text, but never raw hub delivery bodies or parsed feed content.
- Added read-only lease/operator workflows: ``get_websub_expired_subscriptions()``,
  ``get_websub_renewal_candidates()``, ``summarize_websub_leases()``, and
  ``python manage.py websub_subscriptions``. These list expired subscriptions and renewal candidates without background
  jobs or hidden hub network calls.
- Review follow-up: kept inbound denial reasons separate from outbound request diagnostics, tightened lease-helper
  typing and reuse, removed tautological summary fields, documented delivery-attempt retention expectations, documented
  that renewal candidates include expired subscriptions, and made delivery-attempt admin rows non-editable while still
  allowing operator deletion for retention.
- Backlog: added the bundled WebSub follow-up item to ``BACKLOG.md`` before implementation, then removed it after
  completion.
- Documentation: updated WebSub, API, configuration, and concepts docs. No generated docs under ``docs/_build`` were
  edited or staged.
- Changelog: updated ``docs/changelog.rst`` with Unreleased notes for denial handling, delivery-attempt history,
  lease-inspection helpers, and the read-only management command.
- Compatibility: publisher-side WebSub helpers and ``notify_websub`` semantics remain backward-compatible. Subscriber
  callback URLs, CSRF exemption, CORS exclusion, rate-limit key behavior, signed delivery validation, and staged-secret
  renewal semantics are preserved. Intentional additions are one migration, denial fields on ``WebSubSubscription``,
  the ``WebSubDeliveryAttempt`` model/admin, lease helper APIs, and the ``websub_subscriptions`` command.
- Follow-up risks: lease renewal remains intentionally host/operator-owned; django-indieweb still does not provide a
  hub service, automatic discovery, background scheduler, feed parser, content persistence, or raw delivery archive.
- Validation: ``uv run pytest tests/test_websub_subscriber.py -q --no-cov`` (35 passed),
  ``uv run pytest tests/test_websub.py tests/test_websub_templatetags.py tests/test_notify_websub_command.py -q
  --no-cov`` (22 passed), ``uv run pytest tests/test_cors.py tests/test_rate_limiting.py -q --no-cov`` (36 passed),
  ``DJANGO_SETTINGS_MODULE=tests.settings uv run python -m django makemigrations indieweb --check --dry-run`` (no
  changes), ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (87 files already formatted), and
  ``uv run mypy`` (no issues). Full final gate results are recorded in the implementer report.

### Add WebSub subscriber callback support

- Added ``WebSubSubscription`` persistence for host-level subscriber state keyed by hub URL, topic URL, and an
  unguessable callback token. The model tracks pending verification mode, requested/confirmed lease seconds, lease
  expiration, optional ``hub.secret`` material, request diagnostics, latest delivery metadata, and timestamps.
- Added ``request_websub_subscription()`` for explicit subscribe/unsubscribe requests using WebSub form fields
  ``hub.mode``, ``hub.callback``, ``hub.topic``, optional ``hub.lease_seconds``, and optional ``hub.secret``. Hub
  network failures and non-2xx responses are captured in the result and on the subscription row.
- Review follow-up: active subscription renewals now remain ``active`` while verification is pending, preserve existing
  lease metadata on renewal request failure, and keep the active ``hub.secret`` in place until a renewal with a new
  secret is verified. Rejected or failed renewal requests restore the previous pending-secret state. Renewals that omit
  ``secret`` clear any stale staged secret, and ``secret=""`` can stage removal of the active secret after verification.
  Overlong secrets are rejected before a subscription row or hub request is created.
- Review follow-up: malformed WebSub delivery size/content-type settings are logged and fall back to the documented
  defaults instead of raising from the callback path; docs now call out that hub/topic URL validation is syntactic and
  host applications should apply their own allowlist for user-influenced hub URLs.
- Added the CSRF-exempt ``/indieweb/websub/<token>/`` subscriber callback. Verification ``GET`` requests echo
  ``hub.challenge`` only for matching pending subscribe/unsubscribe rows, record hub lease metadata for confirmed
  subscribes, and mark confirmed unsubscribes as unsubscribed. Delivery ``POST`` requests require active subscriptions,
  enforce delivery size/content-type settings, validate HMAC signatures when a secret is stored, record delivery
  metadata, and optionally call ``INDIEWEB_WEBSUB_DELIVERY_HOOK`` without parsing or storing feed content.
- Backlog: removed the completed WebSub subscriber callback item from ``BACKLOG.md``.
- Documentation: updated WebSub, API, configuration, concepts, README, and index docs. No generated docs under
  ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with Unreleased notes for the new model/migration, callback endpoint,
  settings, helper API, signed delivery validation, CSRF/CORS/rate-limit behavior, and host-hook contract.
- Compatibility: existing publisher-side WebSub helpers and ``notify_websub`` command semantics remain
  backward-compatible. Intentional additions are one model/migration, one tokenized callback URL, subscriber helper
  APIs, subscriber settings, and the optional ``websub_callback`` rate-limit key. No WebSub hub service, automatic
  discovery, background lease renewal, or host content-storage semantics were added.
- Follow-up risks: lease renewal/cleanup workflows and richer delivery processing remain host-owned or future slices;
  the first callback slice records only latest delivery diagnostics rather than keeping a delivery history table.
- Validation: ``uv run pytest tests/test_websub.py tests/test_websub_templatetags.py tests/test_notify_websub_command.py
  -q --no-cov`` (22 passed), ``uv run pytest tests/test_websub_subscriber.py -q --no-cov`` (16 passed),
  ``uv run pytest tests/test_cors.py tests/test_rate_limiting.py -q --no-cov`` (36 passed),
  ``DJANGO_SETTINGS_MODULE=tests.settings uv run python -m django makemigrations indieweb --check --dry-run`` (no
  changes), ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (85 files already formatted),
  ``uv run mypy`` (no issues), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), plus the full final
  gate results recorded in the implementer report.

### Support Micropub event and RSVP post types

- Expanded the default ``MicropubContentHandler.get_config()`` ``post-types`` advertisement with ``event`` and
  ``rsvp`` shapes. RSVP is advertised as a separate post type because clients commonly expose RSVP as its own create
  mode, while the wire format remains handler-owned h-entry properties.
- Expanded form-encoded create parsing to forward event properties ``summary``, ``description``, ``start``, ``end``,
  and ``url`` plus RSVP ``rsvp`` as normalized property arrays. Existing common h-entry properties still pass through,
  including h-entry-style ``content`` on event-like posts.
- Preserved JSON create pass-through, including ``type: ["h-event"]`` payloads and nested Microformats2 objects, and
  did not add event/RSVP models, templates, calendar feeds, timezone normalization, Webmention RSVP display, or host
  storage semantics.
- Backlog: removed the completed Micropub event/RSVP item from ``BACKLOG.md``.
- Documentation: updated Micropub, API, concepts, README/index feature language, and changelog docs. No generated docs
  under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased Micropub event/RSVP note.
- Compatibility: existing note/article/photo/reply/bookmark/like/repost behavior, JSON create behavior, media uploads,
  source query, update/delete/undelete, token scopes, CORS, rate limiting, models, and endpoint URLs remain unchanged.
- Follow-up risks: host applications still need explicit storage/rendering policies for event and RSVP semantics.
- Validation: ``uv run pytest tests/test_micropub_create.py tests/test_micropub_endpoint.py -q --no-cov`` (113 passed),
  ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (85 files already formatted), ``uv run mypy`` (no
  issues), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), plus the full final gate results recorded
  in the implementer report.

### Refresh product backlog planning

- Refilled the now-empty Priority 4 product/protocol backlog with two concrete next slices: WebSub subscriber callback
  support and Micropub event/RSVP post types. The WebSub item is explicitly a staged subscriber design and
  implementation slice, not a publisher helper change or hub-service implementation.
- Review follow-up: split the WebSub subscriber item under its own WebSub backlog subheading and tightened event
  vocabulary wording around ``h-event`` ``summary``/``description`` versus h-entry ``content`` forwarding.
- Tightened docs so completed publisher-side WebSub support and common Micropub post-type advertisement are described as
  available, while subscriber callbacks, hub roles, and event/RSVP Micropub support remain future backlog work.
- Backlog: added future items only. No completed product implementation item was removed from ``BACKLOG.md`` in this
  slice; this ``DONE.md`` entry records the completed roadmap/backlog reset task itself.
- Documentation: updated Concepts, Micropub, and WebSub docs. No generated docs under ``docs/_build`` were edited or
  staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased documentation/planning note.
- Compatibility: no runtime code, models, migrations, endpoint URLs, settings, templates, public APIs, endpoint
  semantics, or protocol behavior changed.
- Validation: ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (82 files already formatted),
  ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``git ls-files docs/_build --modified --others
  --exclude-standard`` (no output), ``git diff --check`` (passed), and final staged checks are recorded in the
  implementer report for this slice.

### Add WebSub support

- Added publisher-side WebSub support, which is the WebSub role appropriate for this reusable Django app because host
  projects own the topic resources and feeds. The package now exposes typed helpers in ``indieweb.websub`` for validated
  hub configuration, ``rel=hub``/``rel=self`` discovery links, HTTP ``Link`` headers, and explicit hub notifications.
- Added ``websub_link_tags`` so templates can render WebSub discovery links for host-owned topic pages or feeds.
- Added ``notify_websub`` as an operator/deployment command for explicit topic-change notifications. Notifications use
  the WebSub publisher form fields ``hub.mode=publish`` and ``hub.url=<topic>`` and return/report per-hub results
  without raising for network failures or non-2xx hub responses.
- Review follow-up: added a direct empty-hub regression test, short-circuited ``notify_hubs()`` before opening an HTTP
  client when no hubs are configured, and documented that injected clients are trusted to control their own redirect
  policy.
- Backlog: removed the completed ``Add WebSub support`` Priority 4 item from ``BACKLOG.md``. This slice intentionally
  does not add a WebSub hub service, subscriber callback endpoint, models, migrations, lease tracking, signature
  validation, or automatic network calls.
- Documentation: added ``docs/websub.rst`` and updated API, configuration, module, index, README, concepts, Micropub,
  and management/template-tag documentation. No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased WebSub publisher-support note.
- Compatibility: no existing IndieAuth, Micropub, media, Webmention, token, CORS, rate-limit, template, model,
  migration, endpoint URL, or endpoint semantic behavior changed. Network calls happen only when a host explicitly
  calls ``notify_hubs()`` or runs ``notify_websub``.
- Validation: ``uv run pytest tests/test_websub.py tests/test_websub_templatetags.py tests/test_notify_websub_command.py
  -q --no-cov`` (22 passed), ``DJANGO_SETTINGS_MODULE=tests.settings uv run python -m django makemigrations indieweb
  --check --dry-run`` (no changes), ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (82 files
  already formatted), ``uv run mypy`` (no issues), ``uv run pytest`` (730 passed; required 88.0%, total 89.80%),
  ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``uv run prek run --all-files`` (passed),
  ``git ls-files docs/_build --modified --others --exclude-standard`` (no output), and ``git diff --check`` (passed).

### Support additional Micropub post types

- Expanded the default ``MicropubContentHandler.get_config()`` ``post-types`` list to advertise note, article, photo,
  reply, bookmark, like, and repost shapes while keeping the existing handler contract intact.
- Expanded form-encoded create parsing so ``bookmark-of``, ``like-of``, ``repost-of``, URL-valued ``audio``, and
  URL-valued ``video`` properties are forwarded as normalized property arrays to the configured handler. JSON create,
  source query, update/delete/undelete actions, direct media upload, and multipart ``photo`` upload behavior are
  preserved.
- Backlog: removed the completed ``Support additional Micropub post types`` Priority 4 item from ``BACKLOG.md``.
- Documentation: updated Micropub and API docs with the advertised post types and forwarded h-entry properties. No
  generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased Micropub post-type note.
- Compatibility: no host storage semantics were added for these post types; host applications continue to decide how
  their configured handler persists the forwarded properties. No models, migrations, endpoint URLs, token scopes, media
  storage rules, CORS behavior, or rate-limit behavior changed.
- Validation: ``uv run pytest tests/test_micropub_create.py tests/test_micropub_endpoint.py tests/test_micropub_media.py
  tests/test_micropub_source.py -q --no-cov`` (157 passed), ``uv run ruff check .`` (passed),
  ``uv run ruff format . --check`` (82 files already formatted), ``uv run mypy`` (no issues), ``uv run pytest`` (730
  passed; required 88.0%, total 89.80%), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed),
  ``uv run prek run --all-files`` (passed), and ``git diff --check`` (passed).

### Add a `just loc` line-counting workflow

- Added ``src/indieweb/loc.py`` and exposed it through the ``count-lines-of-code`` project script, so
  ``uv run count-lines-of-code`` works from this package without importing from the sibling ``kptncook`` checkout.
  The command prefers ``cloc`` when it is installed and otherwise falls back to a package-local Python counter over
  tracked text files. Both paths print language, repository-area, and directory summaries.
- Added the ``just loc`` recipe as the stable developer workflow entry point.
- Added focused tests for the package-local fallback, ``cloc`` CSV aggregation, path bucketing, and subprocess error
  handling.
- Review follow-up: tightened generated-directory exclusion matching for nested single-name directories, made equal
  line/file-count sorting deterministic by name, and documented that the ``cloc`` summary parser intentionally keeps
  the ``SUM`` row supplied by ``cloc``.
- Backlog: removed the completed ``just loc`` Priority 3 tooling item from ``BACKLOG.md``.
- Documentation: documented ``just loc`` in ``docs/development.rst`` and the development command summary. No generated
  docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased developer-tooling note for the new line-count workflow.
- Compatibility: no production runtime behavior, dependencies, migrations, models, settings, templates, endpoint URLs,
  endpoint semantics, or public APIs changed. The new module is only exposed as a developer console script.
- Follow-up: no follow-up remains for the line-count workflow. ``uv lock`` confirmed the project metadata remained
  resolvable; adding the script did not require a lockfile content change.
- Validation: ``uv lock`` (resolved 74 packages), ``uv run ruff format src/indieweb/loc.py tests/test_loc.py`` (2 files
  reformatted), ``just loc`` (passed; used the installed ``cloc`` path and printed language, area, and directory
  tables), ``uv run count-lines-of-code`` (passed with the same output shape),
  ``uv run pytest tests/test_loc.py -q --no-cov`` (7 passed), ``uv run ruff check .`` (passed),
  ``uv run ruff format . --check`` (76 files already formatted), ``uv run mypy`` (no issues),
  ``uv run pytest`` (703 passed; required 88.0%, total 89.52%),
  ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``uv run prek run --all-files`` (passed),
  ``git ls-files docs/_build --modified --others --exclude-standard`` (no output), and ``git diff --check`` (passed).

### Evaluate local, gitignored agent session summaries

- Decided not to add an automated hook or committed script for Codex or Claude Code session summaries. Raw transcripts,
  prompts, command output, and generated summaries can contain secrets or unrelated private context, so scraping or
  storing them automatically from a tracked workflow would be too risky by default.
- Reserved private local paths in ``.gitignore`` for optional user-authored summaries or transcript exports:
  ``.agent-summaries/``, ``.agent-transcripts/``, ``codex-session-*.md``, and ``claude-session-*.md``.
- Documented the policy in ``AGENTS.md`` and ``CLAUDE.md``: local session material stays untracked, hooks must not
  scrape transcripts into tracked files by default, and only concise reviewed repo-specific guidance should be promoted
  into tracked documentation.
- Backlog: removed the completed evaluation item from ``BACKLOG.md``. The separate ``Add a curated agent learnings
  file if repeated repo-specific mistakes emerge`` item remains open because this evaluation did not identify reviewed
  repo-specific learnings that should be committed now.
- Documentation: updated repository agent guidance only. No raw transcripts, prompts, command output, generated
  summaries, or private session material were added.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased note because this changes the documented developer-agent
  workflow and gitignore policy.
- Compatibility: no production runtime behavior, dependencies, migrations, models, settings, templates, endpoint URLs,
  endpoint semantics, public APIs, or package metadata changed for this slice.
- Follow-up: keep the curated learnings backlog item open and use it only for concise, reviewed guidance if repeated
  repo-specific mistakes appear.
- Validation: ``rg -n "agent|summary|session|codex|claude|transcript|learnings" .gitignore AGENTS.md CLAUDE.md
  BACKLOG.md DONE.md docs README.rst CONTRIBUTING.rst`` (confirmed the prior state and final policy locations),
  ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (76 files already formatted),
  ``uv run mypy`` (no issues), ``uv run pytest`` (703 passed; required 88.0%, total 89.52%),
  ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``uv run prek run --all-files`` (passed),
  ``git ls-files docs/_build --modified --others --exclude-standard`` (no output), and ``git diff --check`` (passed).

### Remove the django-model-utils runtime dependency safely

- Replaced the historical ``model_utils.fields.AutoCreatedField`` and ``AutoLastModifiedField`` usages in
  ``src/indieweb/migrations/0001_initial.py`` with Django-native ``models.DateTimeField`` definitions using the same
  ``default=django.utils.timezone.now``, ``editable=False``, and verbose-name arguments those fields deconstructed to.
  The existing ``0005`` migration still transitions ``Auth`` and ``Token`` timestamp state to
  ``auto_now_add=True``/``auto_now=True``, matching the current models.
- Removed ``django-model-utils`` from ``pyproject.toml`` runtime dependencies and refreshed ``uv.lock`` so the package
  entry and ``django-indieweb`` dependency metadata no longer include it. ``uv sync`` removed
  ``django-model-utils==5.0.0`` from the local environment.
- Backlog: removed the completed dependency-cleanup item from ``BACKLOG.md``.
- Documentation: removed the stale ``model_utils`` autodoc mock from ``docs/conf.py`` and removed
  ``django-model-utils`` from the ``CLAUDE.md`` key-dependencies list. No generated docs under ``docs/_build`` were
  edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased dependency note for removing
  ``django-model-utils`` after replacing the historical migration field references with Django-native fields.
- Compatibility: no production runtime behavior, models, endpoint URLs, templates, settings, public APIs, endpoint
  semantics, or current migration behavior changed. The migration edit preserves the historical initial schema shape
  while removing the import-time dependency on ``model_utils`` for fresh installs.
- Follow-up: no follow-up remains for this dependency-removal slice. The unrelated ``just loc`` backlog item remains
  open.
- Validation: ``uv lock`` (resolved 74 packages; removed ``django-model-utils v5.0.0``), ``uv sync`` (removed
  ``django-model-utils==5.0.0`` from the local environment),
  ``uv run python - <<'PY' ... importlib.util.find_spec('model_utils') ... PY`` (printed ``None``), the
  ``DJANGO_SETTINGS_MODULE=tests.settings`` migration import proof with ``django.setup()`` and
  ``import_module('indieweb.migrations.0001_initial')`` (printed ``Migration``),
  ``DJANGO_SETTINGS_MODULE=tests.settings uv run python -m django makemigrations indieweb --check --dry-run`` (no
  changes), ``DJANGO_SETTINGS_MODULE=tests.settings uv run python -m django migrate --database default --run-syncdb
  --noinput --verbosity 1`` (fresh in-memory SQLite migration application passed through
  ``indieweb.0015_webmention_outbound_target``), ``uv run ruff check .`` (passed),
  ``uv run ruff format . --check`` (74 files already formatted), ``uv run mypy`` (no issues),
  ``uv run pytest`` (696 passed; required 88.0%, total 89.34%),
  ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``uv run prek run --all-files`` (passed),
  ``git ls-files docs/_build --modified --others --exclude-standard`` (no output), and ``git diff --check`` (passed).

### Pin Django to a supported version range and test supported Django versions

- Pinned the runtime Django dependency to ``Django>=5.2.13,<6.1`` and added Django 5.2/6.0 framework classifiers so
  the package policy names the currently supported stable Django series instead of allowing future untested major/minor
  releases.
- Verified the policy against official Django documentation on 2026-05-03: Django 5.2 LTS supports Python 3.10, 3.11,
  3.12, 3.13, and 3.14; Django 6.0 supports Python 3.12, 3.13, and 3.14; Django 4.2 is listed as an unsupported
  previous release after extended support ended on April 7, 2026.
- Replaced the broad tox Python-only envlist with explicit ``py310-django52``, ``py311-django52``,
  ``py312-django52``, ``py313-django52``, ``py314-django52``, ``py312-django60``, ``py313-django60``, and
  ``py314-django60`` environments. Each tox env constrains Django to the intended series and prints the active Python
  and Django versions before running ``pytest`` inside tox's own virtualenv, preserving the configured pytest-cov
  coverage gate from ``pyproject.toml``.
- Review follow-up: tightened the Django 6.0 tox floor to ``Django>=6.0.4,<6.1`` to mirror the explicit Django 5.2
  patch floor, simplified the shared tox description, and documented that tox's explicit test dependencies must stay
  aligned with the ``pyproject.toml`` dev group.
- Updated GitHub Actions to run each supported tox environment with the matching ``actions/setup-python`` version,
  including Python 3.14 rows for both supported Django series.
- Backlog: removed the completed Django support-matrix item from ``BACKLOG.md``.
- Documentation: updated ``docs/development.rst``, ``CONTRIBUTING.rst``, ``README.rst``, and ``CLAUDE.md`` with the
  supported Python/Django matrix and tox guidance. No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased support-policy/tooling note.
- Compatibility: no production behavior, migrations, models, settings, templates, endpoint URLs, endpoint semantics,
  runtime features, or public APIs changed. Dependency changes were limited to the Django support-policy range and
  lockfile metadata.
- Follow-up: full Python 3.10, 3.11, and 3.12 matrix coverage is expected to run on GitHub Actions because those
  interpreters were not installed locally. Local tox validation covered Python 3.13 and Python 3.14 across both
  supported Django series.
- Validation: ``uv lock`` (resolved 75 packages), ``uv run tox -e py313-django52,py313-django60`` (both passed; each
  printed Python 3.13.12 with Django 5.2.13 or 6.0.4; 696 passed; required 88.0%, total 89.34%),
  ``uv run tox -e py314-django52,py314-django60`` (both passed; each printed Python 3.14.4 with Django 5.2.13 or
  6.0.4; 696 passed; required 88.0%, total 89.34%), ``uv run ruff check .`` (passed),
  ``uv run ruff format . --check`` (74 files already formatted), ``uv run mypy`` (no issues), ``uv run pytest``
  (696 passed; required 88.0%, total 89.34%), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed),
  ``uv run prek run --all-files`` (passed, including YAML/TOML validation), ``git ls-files docs/_build --modified
  --others --exclude-standard`` (no output), ``git diff --check`` (passed), review follow-up
  ``uv run tox list`` (listed all eight supported envs), ``uv run tox -e py313-django60,py314-django60`` (both passed;
  printed Django 6.0.4), ``uv run prek run --all-files`` (passed), and ``git diff --check`` (passed).

### Add a GitHub Actions workflow for pull requests and pushes to develop

- Added ``.github/workflows/ci.yml`` with pull request and push triggers scoped to ``develop`` plus concurrency
  cancellation for superseded runs on the same ref.
- CI now has a tox matrix job for the existing ``py310``, ``py311``, ``py312``, and ``py313`` tox environments using
  matching ``actions/setup-python`` versions and ``uv run tox -e <env>``. The tox command delegates to the existing
  ``uv run pytest`` path, so the configured pytest-cov coverage gate remains enforced in CI.
- Added a Python 3.13 quality/docs job for ``uv run mypy``, ``uv run ruff check .``,
  ``uv run ruff format . --check``, ``uv run prek run --all-files``, and
  ``uv run sphinx-build -W -b html docs docs/_build/html``.
- Backlog: removed the completed GitHub Actions workflow item from ``BACKLOG.md``.
- Documentation: updated ``docs/development.rst`` and ``CONTRIBUTING.rst`` with a concise CI note for the PR/develop
  workflow. No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased developer-tooling note because CI changes the project
  workflow.
- Compatibility: no production behavior, dependencies, migrations, models, settings, templates, endpoint URLs, endpoint
  semantics, runtime feature behavior, or public APIs changed.
- Follow-up: full Python 3.10-3.13 tox coverage is expected to run on GitHub Actions. Locally, only Python 3.13 was
  available on PATH, so the local tox validation covered ``py313`` and did not run ``py310``, ``py311``, or ``py312``.
  The remaining Priority 3 tooling slices are the Django support matrix, ``just loc`` workflow, and safe
  ``django-model-utils`` dependency cleanup.
- Validation: ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (74 files already formatted),
  ``uv run mypy`` (no issues), ``uv run pytest`` (696 passed; required 88.0%, total 89.34%),
  ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``uv run prek run --all-files`` (passed,
  including YAML validation), ``uv run tox -e py313`` (passed; 696 passed; required 88.0%, total 89.34%),
  ``git diff --check`` (passed), and ``git ls-files docs/_build --modified --others --exclude-standard``
  (no output).

### Add a coverage gate

- Added pytest-cov coverage collection to the default ``uv run pytest`` workflow with ``--cov=indieweb`` and
  ``--cov-report=term-missing`` while keeping the existing coverage source, omit, and exclude configuration.
- Measured the current full-suite baseline with ``uv run pytest --cov=indieweb --cov-report=term-missing``: 696 tests
  passed with 89% total coverage over ``src/indieweb``. Configured ``fail_under = 88`` as a conservative floor based on
  that baseline so harmless local rounding/noise should not fail the suite.
- Backlog: removed the completed coverage-gate item from ``BACKLOG.md``.
- Documentation: updated ``AGENTS.md``, ``CLAUDE.md``, ``docs/development.rst``, ``CONTRIBUTING.rst``, and
  ``README.rst`` so the standard test workflow and HTML coverage-report command match the enforced gate. No generated
  docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased developer-tooling note because the default test workflow
  now enforces coverage.
- Compatibility: no production behavior, dependencies, migrations, models, settings, templates, endpoint URLs, endpoint
  semantics, runtime feature behavior, or public APIs changed.
- Follow-up: local coverage enforcement is complete; the remaining Priority 3 tooling slices are the CI workflow,
  Django support matrix, ``just loc`` workflow, and safe ``django-model-utils`` dependency cleanup. CI wiring for the
  coverage gate remains part of the separate GitHub Actions backlog item.
- Validation: ``uv run pytest --cov=indieweb --cov-report=term-missing`` measured the baseline (696 passed, 89%
  total coverage), ``uv run pytest`` enforced the configured gate (696 passed; required 88.0%, total 89.34%),
  ``uv run mypy`` (no issues), ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (74 files already
  formatted), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), and ``git diff --check`` (passed).

### Update Ruff target version to Python 3.10

- Updated ``tool.ruff.target-version`` in ``pyproject.toml`` from ``py39`` to ``py310`` so Ruff's lint and formatting
  rules match the package's declared ``requires-python = ">=3.10"`` compatibility floor.
- Added the explicit ``strict=True`` argument to the fixed-length auth-view ``zip()`` that Ruff now requires under the
  corrected target version.
- Backlog: removed the completed Ruff target-version item from ``BACKLOG.md``.
- Documentation: no project documentation page update was needed because contributor/development docs describe the Ruff
  commands and Python support range without naming the internal Ruff target-version setting. No generated docs under
  ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased developer-tooling note because this changes project
  tooling configuration.
- Compatibility: no dependencies, migrations, models, settings, templates, endpoint URLs, endpoint semantics, runtime
  behavior, or public APIs changed. The single production-code edit is a lint-required explicit ``zip(strict=True)``
  on same-length internal auth-view parameter lists, preserving existing behavior while staying Python 3.10-compatible.
  The change keeps Ruff rewrites compatible with the existing Python 3.10 minimum rather than raising the package
  support floor.
- Follow-up: the remaining Priority 3 tooling slices are the CI workflow, Django support matrix, coverage gate,
  ``just loc`` workflow, and safe ``django-model-utils`` dependency cleanup.
- Validation: ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (74 files already formatted),
  ``uv run pytest tests/test_auth_endpoint.py -q`` (71 passed), ``uv run mypy`` (no issues), ``uv run pytest`` (696
  passed), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``git diff --check`` (passed), and
  ``git diff --cached --check`` (passed).

### Convert Webmention template tag legacy TestCase tests to pytest style

- Converted ``tests/test_webmention_templatetags.py`` from a ``django.test.TestCase`` class to pytest fixtures and
  module-level test functions with plain ``assert`` statements.
- Preserved Webmention template-tag coverage for endpoint link tags, ``show_webmentions`` rendering and type filtering,
  nested response display rules, duplicate suppression, nested ordering, top-level-only counts, count ``as`` variables,
  template-specific markup, DEBUG error handling, integer/count template behavior, and the prefetch query-count
  assertion. The former ``subTest`` status loop now uses pytest parametrization.
- This completes the remaining legacy ``TestCase`` cleanup thread from the pytest-standardization work; no legacy
  ``django.test.TestCase`` test files remain after verification.
- Backlog: removed the completed Webmention template-tag conversion item from ``BACKLOG.md``.
- Documentation: no project documentation update was needed because this was a test-only maintenance refactor with no
  behavior, workflow, public API, configuration, or user-facing usage change. No generated docs under ``docs/_build``
  were edited or staged.
- Changelog: no changelog update was needed because no behavior, bug fix, feature, configuration, workflow, or
  user-facing change shipped in this slice.
- Compatibility: no production code, dependencies, migrations, models, settings, templates, endpoint URLs, endpoint
  semantics, template tag behavior, or public APIs changed.
- Follow-up: no remaining test-style cleanup is known for legacy ``django.test.TestCase`` files; the next open tooling
  slices remain the CI, Django support matrix, Ruff target-version, coverage gate, ``just loc``, and dependency cleanup
  items in ``BACKLOG.md``.
- Validation: ``uv run pytest tests/test_webmention_templatetags.py -q`` (28 passed),
  ``uv run pytest tests/test_webmention_templatetags.py tests/test_webmention_models.py -q`` (56 passed),
  ``uv run pytest tests/test_h_card_templatetags.py tests/test_h_card_integration.py
  tests/test_webmention_templatetags.py -q`` (40 passed), ``uv run pytest tests/test_admin.py
  tests/test_profile_admin.py tests/test_admin_json_widget.py tests/test_webmention_sender.py
  tests/test_send_webmentions_command.py tests/test_webmention_templatetags.py -q`` (120 passed),
  ``uv run pytest`` (696 passed), ``uv run mypy`` (no issues), ``uv run ruff check .`` (passed),
  ``uv run ruff format . --check`` (74 files already formatted),
  ``rg "django\.test import TestCase|TestCase\(" tests`` (no matches), ``git diff --check`` (passed), and
  ``git diff --cached --check`` (passed).

## 2026-05-02

### Convert Webmention sender and command legacy TestCase tests to pytest style

- Converted ``tests/test_webmention_sender.py`` and ``tests/test_send_webmentions_command.py`` from
  ``django.test.TestCase`` classes to pytest fixtures and module-level test functions with plain ``assert`` statements.
- Preserved Webmention sender coverage for URL extraction, duplicate handling, endpoint discovery from headers and HTML,
  redirect handling, send success/failure/network errors, bulk send flow, outbound target history writes/updates,
  Vouch propagation, ``record_history=False``, no-endpoint behavior, and Salmention resend current/history/both union
  behavior. The endpoint redirect subtest and success-code loop now use pytest parametrization.
- Preserved ``send_webmentions`` command coverage for invalid source/Vouch URLs, provided/fetched/stdin content,
  fetch failures, dry-run output and no-send behavior, ordinary send summaries, Salmention resend sender calls, Vouch
  pass-through, provenance/no-endpoint output, no-results output, and dry-run union/no-history-write behavior.
- Remaining legacy ``TestCase`` file is ``tests/test_webmention_templatetags.py``; the focused backlog item for that
  follow-up remains in ``BACKLOG.md``.
- Backlog: removed the completed sender/command conversion item from ``BACKLOG.md``.
- Documentation: no project documentation update was needed because this was a test-only maintenance refactor with no
  behavior, workflow, public API, configuration, or user-facing usage change. No generated docs under ``docs/_build``
  were edited or staged.
- Changelog: no changelog update was needed because no behavior, bug fix, feature, configuration, workflow, or
  user-facing change shipped in this slice.
- Compatibility: no production code, dependencies, migrations, models, settings, templates, endpoint URLs, endpoint
  semantics, management-command behavior, sender behavior, or public APIs changed.
- Validation: ``uv run pytest tests/test_webmention_sender.py tests/test_send_webmentions_command.py -q`` (68 passed),
  ``uv run pytest tests/test_webmention_models.py tests/test_webmention_sender.py tests/test_send_webmentions_command.py
  -q`` (96 passed), ``uv run pytest tests/test_admin.py tests/test_profile_admin.py tests/test_admin_json_widget.py
  tests/test_webmention_sender.py tests/test_send_webmentions_command.py -q`` (92 passed), ``uv run pytest`` (694
  passed), ``uv run mypy`` (no issues), ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (74 files
  already formatted), ``git diff --check`` (passed), and ``git diff --cached --check`` (passed).

### Convert admin legacy TestCase tests to pytest style

- Converted ``tests/test_admin.py`` from ``django.test.TestCase`` classes to pytest fixtures and module-level test
  functions with plain ``assert`` statements.
- Preserved admin coverage for ``Webmention``, ``Token``, and ``Auth`` registration; Webmention changelist columns,
  filters, search, and change view; Token changelist, readonly fields, and no-add permission; and Auth changelist,
  readonly-all-fields behavior, and no-add permission. Explicit ``response.status_code == 200`` assertions now preserve
  the status checks previously implied by ``assertContains``.
- Remaining legacy ``TestCase`` files are ``tests/test_send_webmentions_command.py``,
  ``tests/test_webmention_sender.py``, and ``tests/test_webmention_templatetags.py``. Focused backlog items remain for
  those follow-up slices.
- Backlog: removed the completed admin conversion item from ``BACKLOG.md``.
- Documentation: no project documentation update was needed because this was a test-only maintenance refactor with no
  behavior, workflow, public API, configuration, or user-facing usage change. No generated docs under ``docs/_build``
  were edited or staged.
- Changelog: no changelog update was needed because no behavior, bug fix, feature, configuration, workflow, or
  user-facing change shipped in this slice.
- Compatibility: no production code, dependencies, migrations, models, settings, templates, endpoint URLs, endpoint
  semantics, or public APIs changed.
- Validation: ``uv run pytest tests/test_admin.py tests/test_profile_admin.py tests/test_admin_json_widget.py -q``
  (24 passed), ``uv run pytest tests/test_h_card_extra_classes.py tests/test_h_card_templatetags.py
  tests/test_h_card_integration.py tests/test_profile_admin.py tests/test_admin_json_widget.py tests/test_admin.py -q``
  (40 passed), ``uv run pytest`` (688 passed), ``uv run mypy`` (no issues), ``uv run ruff check .`` (passed),
  ``uv run ruff format . --check`` (74 files already formatted), ``git diff --check`` (passed), and
  ``git diff --cached --check`` (passed).

### Standardize test style on pytest

- Documented pytest function/fixture style as the preferred style for new tests in ``AGENTS.md``, ``CLAUDE.md``, ``CONTRIBUTING.rst``, and ``docs/development.rst``. The guidance explicitly says not to mix ``pytest.mark.parametrize`` into legacy ``django.test.TestCase`` classes and to convert existing legacy files in focused maintenance slices.
- Audited the remaining legacy ``django.test.TestCase`` inventory. Converted the low-risk h-card/profile-admin group to pytest style: ``tests/test_h_card_extra_classes.py``, ``tests/test_h_card_templatetags.py``, ``tests/test_h_card_integration.py``, ``tests/test_profile_admin.py``, and ``tests/test_admin_json_widget.py``. The conversions replaced class ``setUp`` methods with fixtures and Django ``TestCase`` assertions with plain ``assert`` while preserving behavior.
- Remaining legacy ``TestCase`` files are ``tests/test_admin.py``, ``tests/test_send_webmentions_command.py``, ``tests/test_webmention_sender.py``, and ``tests/test_webmention_templatetags.py``. ``tests/test_webmention_processor.py``, ``tests/test_webmention_endpoint.py``, ``tests/test_rate_limiting.py``, and ``tests/test_cors.py`` still import ``unittest.mock`` helpers only; they are not legacy ``TestCase`` files.
- Backlog: removed the completed broad standardization item from ``BACKLOG.md`` and added focused follow-ups for admin tests, Webmention sender/command tests, and Webmention template tag tests.
- Documentation: updated repository instructions, contributor docs, and development docs for pytest preferred style. No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased developer-workflow note for the pytest style guidance and focused conversion.
- Validation: ``uv run pytest tests/test_h_card_extra_classes.py tests/test_h_card_templatetags.py tests/test_h_card_integration.py tests/test_profile_admin.py tests/test_admin_json_widget.py -q`` (26 passed), ``uv run pytest tests/test_cors.py tests/test_rate_limiting.py -q`` (34 passed), ``uv run pytest`` (688 passed), ``uv run mypy`` (no issues), ``uv run ruff check .`` (passed), ``uv run ruff format . --check`` (74 files already formatted), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``git diff --check`` (passed), and ``git diff --cached --check`` (passed).
- Compatibility: no production code, dependencies, migrations, models, settings, templates, endpoint URLs, endpoint semantics, or public APIs changed.

### Add configurable CORS header support

- Added optional built-in CORS support backed by a package-local ``CorsMixin`` and ``indieweb.cors`` helper. ``INDIEWEB_CORS_ALLOWED_ORIGINS`` is disabled by default, accepts exact origin allowlists or the explicit ``"*"`` allow-all value, and covers the public protocol endpoint keys/classes ``auth``, ``token``, ``micropub``, ``media``, ``webmention``, and ``webmention_status``.
- Allowed origins receive ``Access-Control-Allow-Origin`` on actual endpoint responses without changing the existing status, body, content type, authentication behavior, scope checks, rate limiting, Micropub handler flow, media upload validation/storage, Webmention processing, async enqueueing, token expiration, Salmention behavior, or endpoint URLs. Explicit allow-all without credentials sends ``*``; allow-all with ``INDIEWEB_CORS_ALLOW_CREDENTIALS=True`` echoes the request origin and sends ``Vary: Origin``. Disallowed origins receive no permissive CORS headers.
- Added configured preflight ``OPTIONS`` support with ``204 No Content``, ``Allow``, ``Access-Control-Allow-Methods``, ``Access-Control-Allow-Headers``, optional ``Access-Control-Max-Age``, and optional credentials headers. Preflights short-circuit before rate limiting, token DB lookup/authentication, Micropub handler calls, media storage, Webmention processing, and Webmention enqueue hooks.
- Preserved implementation boundary: CORS is opt-in, browser token-management UI views remain excluded, no dependency was added, no model/schema/migration change was added, endpoint URLs are unchanged, and authentication, authorization, scope, token expiration, PKCE, Vouch, Micropub handler, media upload, Webmention processing, async queue, Salmention, template, model, sender, and rate-limit semantics are unchanged except for configured CORS headers/preflight responses.
- Documentation: updated ``docs/api.rst`` with built-in CORS behavior, endpoint coverage, preflight shape, wildcard/credentials behavior, and token UI exclusion; updated ``docs/configuration.rst`` with ``INDIEWEB_CORS_ALLOWED_ORIGINS``, ``INDIEWEB_CORS_ALLOW_CREDENTIALS``, ``INDIEWEB_CORS_ALLOWED_HEADERS``, ``INDIEWEB_CORS_MAX_AGE``, and deployment-level middleware guidance. No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased entry for optional built-in endpoint CORS support.
- Backlog: removed the completed configurable CORS item from ``BACKLOG.md`` and marked API hardening as having no current items. No follow-up remains for this slice.
- Validation: ``uv run pytest tests/test_cors.py -q`` (24 passed), ``uv run pytest tests/test_rate_limiting.py tests/test_cors.py -q`` (34 passed), ``uv run pytest tests/test_auth_endpoint.py tests/test_token_endpoint.py tests/test_micropub_endpoint.py tests/test_micropub_media.py tests/test_webmention_endpoint.py tests/test_rate_limiting.py tests/test_cors.py -q`` (308 passed), ``uv run pytest`` (688 passed), ``uv run mypy`` (no issues), ``uv run ruff check .`` (passed), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``DJANGO_SETTINGS_MODULE=tests.settings uv run python -m django makemigrations indieweb --check --dry-run`` (no changes), ``uv build`` (passed), ``uv run prek run --all-files`` (passed after ``ruff format`` reformatted one existing rate-limit log line), and ``git diff --check`` (passed).

### Add configurable rate limiting for IndieWeb endpoints

- Added optional ``INDIEWEB_RATE_LIMITS`` support backed by Django's cache framework. The setting is disabled by default, accepts per-endpoint ``limit``/``window`` mappings, and covers the public protocol endpoint keys ``auth``, ``token``, ``micropub``, ``media``, ``webmention``, and ``webmention_status``.
- Counters are scoped by endpoint key, HTTP method, and the request ``REMOTE_ADDR`` client identity, with the identity hashed before use in cache keys. ``X-Forwarded-For`` is not trusted directly; proxy deployments must arrange a trusted ``REMOTE_ADDR`` before enabling IP-based limits.
- Exceeded configured limits return HTTP ``429`` with plain-text body ``rate limit exceeded`` and include ``Retry-After`` when the cache-backed window reset can be computed. Requests below the limit continue through the existing response paths unchanged.
- Preserved implementation boundary: rate limiting is opt-in, browser token-management UI views are not included, no dependency was added, no model/schema/migration change was added, endpoint URLs are unchanged, and authentication, authorization, scope, token expiration, Micropub handler, media upload, Webmention processing, async enqueueing, Salmention, template, sender, CORS, and global abuse-scoring semantics are unchanged except for configured ``429`` responses.
- Documentation: updated ``docs/api.rst`` with built-in rate-limit behavior and endpoint keys, updated ``docs/configuration.rst`` with ``INDIEWEB_RATE_LIMITS`` configuration, cache/client-identity notes, and removed the stale custom ``TokenView`` rate-limit workaround. No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased entry for optional cache-backed endpoint rate limiting.
- Backlog: removed the completed configurable endpoint rate-limiting item from ``BACKLOG.md``. No follow-up remains for this slice; configurable CORS remains a separate API hardening backlog item.
- Validation: ``uv run pytest tests/test_rate_limiting.py -q`` (10 passed), ``uv run pytest tests/test_token_endpoint.py tests/test_micropub_endpoint.py tests/test_micropub_media.py tests/test_webmention_endpoint.py tests/test_rate_limiting.py -q`` (213 passed), ``uv run ruff check src/indieweb/rate_limit.py src/indieweb/views.py tests/test_rate_limiting.py`` (passed), ``uv run mypy`` (no issues), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``uv run pytest`` (664 passed), ``uv run ruff check .`` (passed), ``DJANGO_SETTINGS_MODULE=tests.settings uv run python -m django makemigrations indieweb --check --dry-run`` (no changes), ``uv build`` (passed), ``uv run prek run --all-files`` (passed), and ``git diff --check`` (passed).

### Add an explicit management-command workflow for outbound Salmention resends

- Added ``send_webmentions --salmention-resend`` as an opt-in management-command wrapper around ``WebmentionSender.resend_salmentions()``. The default command path remains the ordinary current-link-only ``send_webmentions()`` workflow and still preserves the existing dry-run current-link preview behavior.
- Resend mode resolves content through the existing command path, including caller-provided ``--content`` and stdin via ``--content -``, validates and passes ``--vouch`` through, prints provenance labels for ``current``, ``history``, and ``both`` targets, and displays no-endpoint union targets as visible failures without changing sender semantics.
- Added resend dry-run preview logic that loads ``WebmentionOutboundTarget`` rows for exactly the provided ``source_url``, unions them with current external targets from the latest source content, rediscovers endpoints for display, labels provenance, and does not send Webmentions or write outbound target history.
- Preserved implementation boundary: no sender semantics change, no model schema or migration change, no Salmention setting, and no receive endpoint, processor, async receive, Vouch receive, template, source snapshot, nested response, spam, or ordinary incoming Webmention behavior changes. No follow-up remains for the outbound Salmention management-command workflow itself.
- Documentation: updated ``docs/webmention.rst`` with the implemented command workflow, resend dry-run provenance output, stdin/content/Vouch behavior, and host/operator trigger examples; updated ``docs/configuration.rst`` so Salmention/model notes no longer describe the command wrapper as deferred. No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased entry for ``send_webmentions --salmention-resend`` and noted that default command behavior remains unchanged.
- Backlog: removed the completed management-command workflow item from ``BACKLOG.md``.
- Validation: ``uv run pytest tests/test_send_webmentions_command.py -q`` (16 passed), ``uv run ruff check src/indieweb/management/commands/send_webmentions.py tests/test_send_webmentions_command.py`` (passed), ``uv run pytest tests/test_send_webmentions_command.py tests/test_webmention_sender.py tests/test_webmention_models.py -q`` (90 passed, 5 subtests passed), ``DJANGO_SETTINGS_MODULE=tests.settings uv run python -m django makemigrations indieweb --check --dry-run`` (no changes), ``uv run mypy`` (no issues), ``uv run ruff check .`` (passed), ``uv run pytest`` (654 passed), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``uv build`` (passed), ``uv run prek run --all-files`` (passed), and ``git diff --check`` (passed).

### Record outbound target history from ordinary Webmention sends and add a Salmention resend sender API

- Updated ``WebmentionSender.send_webmentions()`` with a backwards-compatible ``record_history=True`` parameter. Ordinary sends still select only current external absolute HTTP(S) links, skip relative and same-domain URLs, return the existing per-target delivery shape, and omit ordinary results/history rows when no endpoint is discovered.
- Ordinary delivered attempts now create or refresh ``WebmentionOutboundTarget`` rows keyed by the exact ``source_url`` and ``target_url`` strings used in the send payload. Repeated sends update the existing row while preserving ``first_sent_at`` and refreshing endpoint diagnostics, ``last_sent_at``, latest status/success/error fields, latest Vouch URL, and diagnostic ``last_seen_in_source_at``.
- Added ``WebmentionSender.resend_salmentions(source_url, html_content=None, vouch_url=None)``. The helper fetches content when needed, sends to the exact-source union of current external links and stored historical targets, rediscovers endpoints before delivery, labels results with ``provenance`` as ``current``, ``history``, or ``both``, passes Vouch through, returns visible no-endpoint failures for union targets, and refreshes target history for attempted current and historical targets without marking historical-only targets as currently seen. Post-review refinement preserved existing endpoint diagnostics and avoided advancing sent timestamps when no endpoint is found and no Webmention POST is made.
- Preserved implementation boundary: no ``send_webmentions --salmention-resend`` flag, no management-command behavior/output change, no model schema or migration change, and no receive endpoint, processor, async receive, Vouch receive, template, settings, or incoming Webmention behavior changes.
- Documentation: updated ``docs/webmention.rst`` for ordinary history recording, ``record_history=False``, implemented ``resend_salmentions()``, no-endpoint resend result behavior, and the still-deferred command workflow; updated ``docs/configuration.rst`` so the Salmention/model notes describe sender usage rather than foundation-only storage. No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased entry for ordinary outbound history recording and the new sender resend API, explicitly noting that the management-command resend workflow remains deferred.
- Backlog: removed this completed sender/history item from ``BACKLOG.md`` and kept ``Add an explicit management-command workflow for outbound Salmention resends`` open.
- Validation: ``uv run pytest tests/test_webmention_sender.py -q`` (46 passed, 5 subtests passed), ``uv run pytest tests/test_webmention_models.py tests/test_webmention_sender.py tests/test_send_webmentions_command.py -q`` (83 passed, 5 subtests passed), ``DJANGO_SETTINGS_MODULE=tests.settings uv run python -m django makemigrations indieweb --check --dry-run`` (no changes), ``uv run mypy`` (no issues), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``uv run ruff check src/indieweb/senders.py tests/test_webmention_sender.py`` (passed after fixing one line-length issue), ``uv run pytest`` (647 passed), ``uv run ruff check .`` (passed), ``uv build`` (passed), ``git diff --check`` (passed), and ``uv run prek run --all-files`` (passed after ``ruff format`` reformatted the sender test file).

### Add outbound Webmention target-history storage

- Added ``WebmentionOutboundTarget`` as a django-indieweb-managed outbound Webmention target-history model, separate from incoming ``Webmention`` rows, receive-side source snapshots, and nested response rows.
- The model stores exact HTTP(S) ``source_url``/``target_url`` strings with a named uniqueness constraint, endpoint diagnostics, first/latest send timestamps, latest status/result/error fields, latest Vouch URL, diagnostic ``last_seen_in_source_at``, and created/modified timestamps. URL variants are preserved as distinct strings; no receive-side canonicalization policy is applied to outbound history keys.
- Added migration ``0015_webmention_outbound_target`` and focused model tests for creation, defaults, HTTP(S) URL validation, exact pair uniqueness, exact-string identity variants, result/timestamp persistence, and string representation.
- Preserved implementation boundary: no ordinary-send history recording, no ``WebmentionSender.resend_salmentions()``, no ``record_history`` parameter, no ``send_webmentions --salmention-resend`` flag, and no sender, command, receive endpoint, processor, async receive, Vouch, template, or Salmention setting behavior changes.
- Documentation: updated ``docs/configuration.rst`` to list seven models and describe the table as schema/storage foundation only; updated ``docs/webmention.rst`` so support status distinguishes available outbound target-history storage from still-deferred sender/command resend workflows. No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased entry for the outbound target-history model/migration and explicitly scoped sender/command resend workflows as deferred.
- Backlog: removed the completed target-history storage item from ``BACKLOG.md`` and kept the sender API/history recording and management-command resend workflow follow-ups open.
- Validation: ``uv run pytest tests/test_webmention_models.py -q`` (28 passed), ``DJANGO_SETTINGS_MODULE=tests.settings uv run python -m django makemigrations indieweb --check --dry-run`` (no changes), ``uv run pytest`` (632 passed), ``uv run mypy`` (no issues), ``uv run ruff check .`` (passed), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``uv run prek run --all-files`` (passed), ``uv build`` (passed), and ``git diff --check`` (passed).

### Design outbound target tracking for sending Salmentions

- Designed outbound Salmention sending as a hybrid responsibility: django-indieweb should own durable outbound target history for original source URL and target URL pairs, while host applications own the signal that an accepted downstream response has been incorporated into the rendered original permalink and should trigger a resend.
- Documented the future target-history contract: exact absolute HTTP(S) source URL and target URL strings used for delivery, endpoint diagnostics, first/last sent timestamps, latest status/result/error, latest Vouch URL, and diagnostic current-content last-seen tracking. Resend target sets are bounded to freshly extracted current links for the source plus recorded historical targets for that same source.
- Documented the explicit future resend workflow: a `WebmentionSender.resend_salmentions(...)` helper and an optional `send_webmentions --salmention-resend` command mode should resend to the union of current and prior targets after the host app or operator confirms the source permalink was updated. Existing ordinary `WebmentionSender.send_webmentions(...)` and default `send_webmentions` command behavior remain unchanged in this design slice.
- Added focused follow-up backlog items for the outbound target-history model/migration, sender API/history recording, and management-command resend workflow.
- Review follow-up clarified that receive-side source snapshot and nested-response models now support receive-side Salmention comparison/rendering, that `last_seen_in_source_at` is diagnostic rather than the source of current-versus-historical resend provenance, that a future `record_history` sender escape hatch should be preserved, and that old-target import/backfill tooling is not required for the first resend-capable implementation.
- Implementation deferred: no model, migration, sender, command, receive endpoint, processor, async receive, Vouch, or template code changed.
- Documentation: updated `docs/webmention.rst` with the outbound target-tracking and resend-workflow design, and updated `docs/configuration.rst` so the no-setting/model guidance remains accurate. No generated docs under `docs/_build` were edited or staged.
- Changelog: updated `docs/changelog.rst` with the outbound Salmention design/support-status entry.
- Validation: `uv run sphinx-build -W -b html docs docs/_build/html` (passed), `uv run prek run --all-files` (passed), `uv run ruff check .` (passed), and `git diff --check` (passed). Code was not changed, so sender/command tests, full pytest, mypy, and build were not required.

## 2026-05-01

### Expose nested Salmention responses in template queries and rendering

- Updated ``show_webmentions`` to keep querying verified top-level ``Webmention`` rows by target URL while prefetching verified ``WebmentionNestedResponse`` children for those rows. The tag attaches template-ready child lists without per-parent or per-child queries.
- Rendered verified nested children inline under verified parent replies through a child-specific template partial. Child rendering supports reply, like, repost, and mention wording, preserves ordinary top-level templates, and leaves ``webmention_count`` top-level-only.
- Added duplicate-display suppression so a verified direct top-level Webmention to the same target wins over an inline nested child with the same ``identity`` or ``response_url``. When the same child identity is discovered under multiple displayed parents, only the first parent in the existing top-level ordering renders it.
- Review follow-up optimized the unfiltered ``show_webmentions`` path to derive direct top-level source URLs from already materialized rows, keeping the common nested rendering path to two queries while preserving type-agnostic duplicate suppression for filtered views.
- Preserved endpoint, processor, async receive, Vouch, source snapshot, child storage, and outbound Salmention behavior. The outbound target-tracking backlog item remains open.
- Documentation: updated ``docs/webmention.rst`` and ``docs/configuration.rst`` with nested rendering, duplicate suppression, child ordering, and count semantics. No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased nested rendering entry and removed stale wording that described nested rendering as still unsupported.
- Validation: ``uv run pytest tests/test_webmention_templatetags.py tests/test_webmention_models.py -q`` (43 passed, 3 subtests passed), ``uv run pytest tests/test_webmention_templatetags.py tests/test_webmention_processor.py tests/test_webmention_endpoint.py -q`` (165 passed, 3 subtests passed), ``uv run pytest`` (621 passed), ``uv run mypy`` (no issues), ``uv run ruff check .`` (passed), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``uv run prek run --all-files`` (passed after ``ruff format`` reformatted one file on the first run), ``uv build`` (passed), and ``git diff --check`` (passed).

### Add nested response storage and duplicate comparison for receiving Salmentions

- Added ``WebmentionNestedResponse`` rows related to parent ``Webmention`` submissions, keyed uniquely by parent and stable nested response identity. Child rows store response URL when available, author/content/published/type fields, current status, first/last-seen and verified timestamps, a compact parsed nested ``h-entry`` snapshot, and a parsed snapshot digest.
- Updated ``WebmentionProcessor`` so successful verified parent processing reads the previous ``WebmentionSourceSnapshot`` nested identity set before overwriting it, extracts stable nested ``h-entry`` candidates from the current parsed parent source, upserts current child rows, and marks disappeared children ``missing`` without deleting historical fields. Entries without stable identity are not promoted to durable child rows.
- Review follow-up tightened duplicate child updates so current displayable fields are refreshed consistently with the latest parsed nested snapshot, skipped overlong stable identities that cannot fit the storage field, documented the previous-snapshot comparison hook, and added regression coverage for empty current child fields, all children disappearing, and overlong identities.
- Preserved ordinary Webmention, Vouch, spam, duplicate receive, source snapshot, and async receive semantics. Failed fetches, ``410 Gone``, non-HTML responses, missing target links, Vouch failures, and spam classifications do not create or update child rows from failed source content. Queued receive requests still do not instantiate the processor, fetch, parse, verify Vouch, spam-check, compare snapshots, or write child rows; worker processing through ``process_queued_webmention()`` performs those writes.
- Kept nested response rendering, template exposure, nested-inclusive counts, outbound Salmention sending, and outbound target tracking out of scope. The template rendering and outbound target-tracking backlog items remain open.
- Documentation: updated ``docs/webmention.rst`` with the implemented child persistence/comparison behavior and remaining Salmention gaps; updated ``docs/configuration.rst`` for the model list and no-setting note. No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased nested response storage/comparison entry.
- Validation: ``uv run pytest tests/test_webmention_models.py tests/test_webmention_processor.py tests/test_webmention_endpoint.py -q`` (156 passed), ``uv run pytest`` (611 passed), ``uv run mypy`` (no issues), ``uv run ruff check .`` (passed), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``uv run prek run --all-files`` (passed), ``uv build`` (passed), ``DJANGO_SETTINGS_MODULE=tests.settings uv run python -m django makemigrations indieweb --check --dry-run`` (no changes), and ``git diff --check`` (passed).

## 2026-04-30

### Add source snapshot persistence for receiving Salmentions

- Added a related ``WebmentionSourceSnapshot`` model for submitted ``Webmention`` rows, with the latest raw source HTML, final fetched source URL, SHA-256 digest, fetch timestamp, normalized parsed parent ``h-entry``, known nested response identities, and created/modified timestamps.
- Updated ``WebmentionProcessor`` so successful verified processing stores or updates the one-to-one source snapshot after source fetch, HTML/content checks, target-link verification, microformats2 parsing, Vouch checks, and spam checks have passed. Duplicate receives update the existing parent row and snapshot row.
- Preserved ordinary Webmention, Vouch, spam, duplicate receive, and async receive semantics. Failure paths do not clear or replace the last successful snapshot, snapshot storage failures do not demote an otherwise verified parent Webmention, Vouch success does not refresh away parsed fields, and queued receive requests still do not instantiate the processor, fetch, parse, spam-check, verify Vouch, or write snapshots.
- Kept full Salmention receiving out of scope: no nested child response rows, no nested comparison, no nested rendering, no outbound Salmention sending, and no Salmention setting were added. The nested response storage/comparison and rendering backlog items remain open.
- Documentation: updated ``docs/webmention.rst`` with implemented snapshot persistence and remaining Salmention gaps; updated ``docs/configuration.rst`` for the no-setting note and model list. No generated docs under ``docs/_build`` were edited or staged.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased source snapshot persistence entry.
- Validation: ``uv run pytest tests/test_webmention_processor.py::TestWebmentionProcessor::test_processor_preserves_verified_status_when_source_snapshot_write_fails tests/test_webmention_processor.py::TestWebmentionProcessor::test_processor_preserves_parsed_fields_after_successful_vouch_verification -q`` (2 passed), ``uv run pytest tests/test_webmention_models.py tests/test_webmention_processor.py tests/test_webmention_endpoint.py -q`` (142 passed), ``uv run pytest`` (597 passed), ``uv run mypy`` (no issues), ``uv run ruff check .`` (passed), ``uv run sphinx-build -W -b html docs docs/_build/html`` (passed), ``uv run prek run --all-files`` (passed), ``uv build`` (passed), and ``git diff --check`` (passed).

### Design persistence for receiving Salmentions

- Designed the receiving-side Salmention persistence/display model against the current Webmention architecture and deliberately deferred schema/protocol implementation. The current `Webmention` row remains the top-level submitted `source_url`/`target_url` notification; future receive support should add a related source snapshot model and a separate related child response model rather than reusing `Webmention` for nested replies.
- Documented the source snapshot contract: store latest raw source HTML, final fetched URL, a content digest, fetch timestamp, normalized parsed parent `h-entry`, and known nested response identities so duplicate receives can compare current source state against previously stored contents.
- Documented the nested response contract: key children by stable nested `h-entry` identity, prefer URL-valued `uid`/`url` and then HTML `id` resolved against the parent source final URL, store content/author/published/type/status/snapshot fields, keep spam/moderation independent, and keep Vouch metadata attached only to the submitted parent Webmention.
- Documented display/query semantics: verified child responses should render inline under their parent Webmention; child displayability depends on the parent remaining verified; direct top-level Webmentions should suppress duplicate inline children for the same response; `show_webmentions` can keep querying verified top-level rows by `target_url` and prefetch verified children; `webmention_count` should keep its current top-level count unless an explicit nested-inclusive API is added.
- Preserved ordinary Webmention behavior: no endpoint, processor, model, migration, template, Vouch, async receive, duplicate receive, or status-response code changed. Future Salmention fetch/parse/compare work remains assigned to `WebmentionProcessor`, worker paths, management commands, or explicit helper APIs outside the queued receive request path.
- Added follow-up backlog items for source snapshot persistence, nested response storage/duplicate comparison, and template query/rendering exposure. The separate outbound Salmention target-tracking design item remains open.
- Documentation: updated `docs/webmention.rst` with the receive-side persistence design and refined `docs/configuration.rst` to point to that design. No `docs/api.rst` update was needed because endpoint/status response shapes did not change. No generated docs under `docs/_build` were updated.
- Changelog: updated `docs/changelog.rst` with an Unreleased receive-side Salmention persistence design entry.
- Validation: `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv run ruff check .`, `git diff --check`, `git diff --cached --check`, and `git diff --cached --stat` passed.

### Evaluate Salmentions support

- Evaluated the Salmention living specification against the current Webmention receive/send architecture and deliberately deferred implementation. Receiving Salmentions requires storing fetched source contents for later comparison, detecting newly nested response ``h-entry`` items on duplicate receives, and representing/displaying nested child responses; the current ``Webmention`` model stores one flattened parsed mention per submitted ``source``/``target`` pair and does not keep source snapshots or nested response identities.
- Sending Salmentions also requires state the current sender layer does not track: the prior outbound target set for an original post and a reliable application signal that a newly accepted downstream response has been incorporated into the original post permalink. The existing ``WebmentionSender`` and ``send_webmentions`` command can explicitly resend ordinary Webmentions for a source URL, but that is not enough to claim Salmention sending support.
- Preserved ordinary Webmention behavior: no endpoint, processor, model, sender, command, Vouch, async receive, duplicate receive, or template code changed.
- Added follow-up backlog items to design receiving-side source snapshot/nested-response persistence and sending-side outbound target tracking/resend workflow before implementing Salmentions.
- Documentation: updated ``docs/webmention.rst`` with the Salmention support status and rationale, and ``docs/configuration.rst`` to state that no Salmention setting exists today. No ``docs/api.rst`` update was needed because endpoint/status response shapes did not change. No generated docs under ``docs/_build`` were updated.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased Salmention support-status entry.
- Validation: ``uv run pytest tests/test_webmention_processor.py tests/test_webmention_endpoint.py -q``, ``uv run pytest tests/test_webmention_sender.py tests/test_send_webmentions_command.py -q``, ``uv run pytest``, ``uv run mypy``, ``uv run ruff check .``, ``uv run sphinx-build -W -b html docs docs/_build/html``, ``uv run prek run --all-files``, ``uv build``, ``git diff --check``, and ``git diff --cached --stat`` passed.

### Add Webmention Vouch trust-policy setting

- Added ``INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY`` for receiver-side Vouch trust decisions in ``WebmentionProcessor``. The configured callable receives keyword arguments for the ``Webmention`` row, submitted source/target, submitted Vouch URL, and optional final Vouch URL after redirects. It must accept both the submitted URL and final URL for verification to continue.
- Kept ``INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS`` as the default/simple policy when no callable is configured. When a callable is configured, it owns URL trust decisions; the built-in domain allowlist is not applied unless the callable chooses to read it.
- Hardened receiver behavior so policy import failures, non-callable policy values, callable exceptions, and required Vouch mode without any trust policy or trusted domains all fail Vouch verification closed. Ordinary Webmentions and optional Vouch storage remain unchanged when Vouch is not required and no trust settings are configured.
- Preserved the async receive boundary: the endpoint still validates and persists optional ``vouch`` metadata and queues the row without importing/calling the trust policy, instantiating ``WebmentionProcessor``, or fetching source/voucher URLs.
- Documentation: updated ``docs/configuration.rst`` and ``docs/webmention.rst`` with the callable contract, precedence, fail-closed behavior, async boundary, and required-mode guidance. No ``docs/api.rst`` update was needed because endpoint/status response shapes did not change. No generated docs under ``docs/_build`` were updated.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased Vouch trust-policy entry.
- Validation: ``uv run pytest tests/test_webmention_processor.py tests/test_webmention_endpoint.py -q``, ``uv run pytest tests/test_webmention_sender.py tests/test_send_webmentions_command.py -q``, ``uv run pytest``, ``uv run mypy``, ``uv run ruff check .``, ``uv run sphinx-build -W -b html docs docs/_build/html``, ``uv run prek run --all-files``, ``uv build``, ``git diff --check``, and ``git diff --cached --stat`` passed.

### Evaluate Webmention vouch support

- Evaluated the IndieWeb Vouch living specification and current Webmention receive/send architecture, and implemented a conservative support slice rather than deferring. The receive endpoint accepts an optional ``vouch`` form parameter, validates it as an HTTP(S) URL, persists it on ``Webmention.vouch_url``, and includes stored Vouch metadata in the status endpoint.
- Preserved the asynchronous receive boundary: queued mode validates and stores submitted Vouch metadata, calls the configured enqueue hook, and returns ``202 Accepted`` without fetching source or voucher URLs or instantiating ``WebmentionProcessor`` in the request path.
- Added processor-owned Vouch verification behind explicit receiver policy. ``INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS`` enables verification against the configured Django ``Site`` domain plus approved voucher domains; ``INDIEWEB_WEBMENTION_VOUCH_REQUIRED`` makes missing or unverifiable vouchers fail in processor/worker paths. Failed Vouch checks mark the row ``failed`` without clearing parsed fields.
- Added outgoing opt-in support via ``WebmentionSender.send_webmention(..., vouch=...)``, ``WebmentionSender.send_webmentions(..., vouch_url=...)``, and ``python manage.py send_webmentions --vouch ...``.
- Added focused tests for optional receive-side ``vouch`` validation, async persistence without processing, malformed Vouch rejection before enqueueing, duplicate receives preserving existing Vouch and parsed state, queued helper Vouch propagation, trusted/untrusted/missing Vouch processor behavior, outgoing sender payloads, and command-line ``--vouch`` handling.
- Documentation: updated ``docs/webmention.rst``, ``docs/api.rst``, and ``docs/configuration.rst`` with the support status, receive/send workflows, async behavior, model/status fields, and new settings. No generated docs under ``docs/_build`` were updated.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased Webmention Vouch support entry.
- Validation: ``uv run pytest tests/test_webmention_endpoint.py -q``, ``uv run pytest tests/test_webmention_processor.py tests/test_webmention_endpoint.py -q``, ``uv run pytest tests/test_webmention_sender.py -q``, ``uv run pytest``, ``uv run mypy``, ``uv run ruff check .``, ``uv run sphinx-build -W -b html docs docs/_build/html``, ``uv run prek run --all-files``, ``uv build``, ``git diff --check``, and ``git diff --cached --stat`` passed.

## 2026-04-29

### Make Webmention receiving asynchronous

- Added optional receive-side async queue integration with the ``INDIEWEB_WEBMENTION_ENQUEUE`` setting. When configured, ``POST /indieweb/webmention/`` validates the request, creates or reuses the submitted ``source``/``target`` ``Webmention`` row, calls the configured enqueue hook with the row's primary key, and returns ``202 Accepted`` with a status ``Location`` without fetching the source URL or calling ``WebmentionProcessor.process_webmention()`` in the request path.
- Preserved backwards-compatible synchronous receiving when the enqueue hook is unset: valid requests still call ``WebmentionProcessor`` inline and return ``201 Created`` with the existing status ``Location`` semantics.
- Added ``indieweb.processors.process_queued_webmention(webmention_id)`` so queue workers can load the existing row and run the existing processor behavior, keeping source fetching, target verification, parsing, spam checks, signals, and status transitions inside ``WebmentionProcessor``.
- Added focused tests for queued ``202`` responses, persisted-id enqueueing, duplicate-row reuse without clearing parsed/verified fields, validation failures before enqueueing, processor-not-called behavior in async mode, enqueue failure/misconfiguration handling, and the queued processing helper.
- Documentation: updated ``docs/webmention.rst``, ``docs/api.rst``, and ``docs/configuration.rst`` with the async receive flow, ``INDIEWEB_WEBMENTION_ENQUEUE`` callable contract, queued response semantics, worker helper, synchronous fallback, and fail-closed enqueue errors. No generated docs under ``docs/_build`` were updated.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased async Webmention receiving entry.
- Validation: ``uv run pytest tests/test_webmention_endpoint.py -q``, ``uv run pytest tests/test_webmention_processor.py tests/test_webmention_endpoint.py -q``, ``uv run pytest``, ``uv run mypy``, ``uv run ruff check .``, ``uv run sphinx-build -W -b html docs docs/_build/html``, ``uv run prek run --all-files``, ``uv build``, ``git diff --check``, and ``git diff --cached --stat`` passed.

### Document and test media uploads

- Added a focused end-to-end regression test proving the documented direct media upload flow: a token with ``create media`` uploads an image to ``POST /indieweb/media/``, receives an absolute ``Location`` with an empty ``201`` response body, and then uses that exact URL as the ``photo`` property in a JSON ``POST /indieweb/micropub/`` create request.
- The test captures the configured Micropub handler and asserts ``create_entry()`` receives ``photo: [media_location]`` from the direct media endpoint before the create response returns ``201`` with an absolute ``Location``.
- Documentation: checked ``docs/micropub.rst``, ``docs/api.rst``, ``docs/configuration.rst``, and ``docs/tutorial.rst``. No documentation changes were needed because they already describe the direct media endpoint flow, multipart create uploads, shared upload validation settings, scope distinction, deployment warnings, and error response shapes accurately. No generated docs under ``docs/_build`` were updated.
- Changelog: no changelog update was needed because this slice added regression coverage and backlog bookkeeping only, with no behavior, public API, configuration, or user-facing documentation change.
- Validation: ``uv run pytest tests/test_micropub_media.py -q``, ``uv run pytest tests/test_micropub_create.py tests/test_micropub_media.py -q``, ``uv run pytest``, ``uv run mypy``, ``uv run ruff check .``, ``uv run sphinx-build -W -b html docs docs/_build/html``, ``uv run prek run --all-files``, ``uv build``, and ``git diff --check`` passed.

### Handle multipart file uploads in Micropub form parsing

- Updated `POST /indieweb/micropub/` multipart create parsing so uploaded `photo` file parts are no longer ignored.
- Extracted shared private media upload helpers in `src/indieweb/views.py` so multipart create uploads and the direct `/indieweb/media/` endpoint use the same unguessable storage naming, `INDIEWEB_MEDIA_MAX_UPLOAD_BYTES` size limit, `INDIEWEB_MEDIA_ALLOWED_TYPES` content-type allowlist, Django storage backend, and absolute URL generation.
- Multipart create uploads validate all submitted `photo` files before saving any, and clean up already-saved files if a later storage save fails, so a rejected batch does not leave known partial-upload orphans.
- Preserved URL-valued `photo` form properties and appended stored upload URLs to the same `photo` property list before calling `MicropubContentHandler.create_entry()`. Multiple uploaded `photo` files are supported through `request.FILES.getlist("photo")`.
- Kept scope behavior operation-based: multipart create uploads require `create` or the legacy `post` alias, while direct `/indieweb/media/` uploads continue to require `media`.
- Added focused regression tests for one uploaded photo, multiple uploaded photos, mixed URL-valued and uploaded photos, URL-only photo create behavior, oversized uploads, disallowed content types, storage `OSError`, and create/post scope behavior.
- Documentation: updated `docs/micropub.rst`, `docs/api.rst`, `docs/concepts.rst`, `docs/configuration.rst`, and `docs/tutorial.rst`; checked `README.rst` and `docs/index.rst` and no update was needed because their summaries were already broad enough. No generated docs under `docs/_build` were updated.
- Changelog: updated `docs/changelog.rst` with an Unreleased multipart create upload entry.
- Validation: `uv run pytest tests/test_micropub_media.py -q`, `uv run pytest tests/test_micropub_create.py -q`, `uv run pytest tests/test_micropub_endpoint.py tests/test_micropub_create.py tests/test_micropub_media.py -q`, `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, `git diff --check`, and `git diff --cached --stat` passed.

### Add a Micropub media endpoint

- Added `indieweb:media` at `/indieweb/media/` for Micropub media endpoint uploads.
- Reused the existing bearer-token authentication path, including expired-token rejection, inactive-owner rejection, and `INDIEWEB_CLIENT_ID_VALIDATOR` resource-server checks.
- Required the exact `media` scope for uploads, matching common Micropub client practice while keeping create/update/delete scopes separate.
- Accepted `multipart/form-data` requests with a `file` part, rejected uploads larger than `INDIEWEB_MEDIA_MAX_UPLOAD_BYTES` (default 10 MiB), rejected content types outside `INDIEWEB_MEDIA_ALLOWED_TYPES` (default common image/audio/video MIME types), stored accepted uploads through Django's configured storage backend under unguessable `indieweb/media/` keys, and returned `201 Created` with an absolute `Location` header.
- Updated `GET /indieweb/micropub/?q=config` to advertise an absolute `media-endpoint` URL at the view layer unless a custom `MicropubContentHandler.get_config()` implementation already provides one.
- Left multipart files sent directly to `/indieweb/micropub/` as follow-up work; regular Micropub create parsing still ignores uploaded files in this slice.
- Documentation: updated `README.rst`, `CONTRIBUTING.rst`, `docs/api.rst`, `docs/micropub.rst`, `docs/concepts.rst`, `docs/configuration.rst`, `docs/tutorial.rst`, `docs/index.rst`, and `docs/indieauth.rst`; no generated docs under `docs/_build` were updated.
- Changelog: updated `docs/changelog.rst` with an Unreleased media endpoint entry.
- Validation: `uv run pytest tests/test_micropub_media.py -q`, `uv run pytest tests/test_micropub_endpoint.py tests/test_micropub_create.py -q`, `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, `git diff --check`, and `git diff --cached --stat` passed.

### Clean up TODO and future-enhancement notes after related changes ship

- Audited current TODO, limitation, unsupported-feature, future-enhancement, and "not yet implemented" notes across `README.rst`, `docs/`, `src/`, `tests/`, and `BACKLOG.md`, excluding generated docs under `docs/_build`.
- Clarified current support-status wording for the remaining Micropub media endpoint/upload gap, built-in rate limiting, and built-in CORS support so those notes map to open backlog work rather than shipped IndieAuth, Micropub, Webmention, or token-management behavior.
- Reworded the Micropub multipart upload inline comment to point at the media endpoint backlog work, and clarified tutorial/example handler `NotImplementedError` stubs as example-specific mappings.
- Updated stale test commentary around create/post scope requirements without changing test behavior.
- Left still-valid future work notes in place for open backlog items: Micropub media endpoint and multipart uploads, WebSub, Webmention vouch, Salmentions, rate limiting, CORS, additional Micropub post types, CI, dependency cleanup, and related tooling items. Also left current Webmention remote author-page fetching limitations in place because they still match implementation behavior.
- Documentation: updated `docs/concepts.rst`, `docs/micropub.rst`, `docs/api.rst`, and `docs/tutorial.rst`; checked `docs/indieauth.rst`, `docs/configuration.rst`, `docs/webmention.rst`, current historical `docs/changelog.rst` entries, `src/indieweb/views.py`, and `src/indieweb/handlers_example.py` in context. No generated docs under `docs/_build` were updated.
- Changelog: updated `docs/changelog.rst` with an Unreleased documentation-cleanup note because current user-facing support/status wording changed.
- Validation: `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv run ruff check .`, `git diff --check`, `uv run pytest`, `uv run mypy`, and `uv build` passed.
- Staging check: `git diff --cached --stat` was reviewed after staging.

### Add Token Revocation UI

- Added an authenticated browser token management page at `indieweb:tokens` (`/indieweb/tokens/`) that lists only the current user's IndieAuth/Micropub access tokens with client, identity, scope, created/modified, expiration, and active/expired metadata while never displaying full bearer token keys.
- Added a CSRF-protected `POST` revoke action at `indieweb:token-revoke` (`/indieweb/tokens/<pk>/revoke/`) that deletes only tokens owned by the logged-in user. Missing or foreign token IDs return `404`, `GET` does not revoke, and deleting a token immediately stops that bearer token from authenticating Micropub requests.
- Added focused pytest coverage in `tests/test_token_management.py` for login redirects, owner-only listing, empty-state rendering, active/expired indicators, owned-token revocation, CSRF enforcement, revoked-token authentication failure, foreign-token protection, and GET safety.
- Documentation: updated `docs/indieauth.rst`, `docs/api.rst`, `docs/configuration.rst`, and `docs/concepts.rst` with the token management workflow, URL, CSRF POST revocation behavior, owner boundary, and distinction from the token endpoint protocol. No generated docs under `docs/_build` were updated.
- Changelog: updated `docs/changelog.rst` with an Unreleased entry for the new browser token management UI.
- Validation: `uv run pytest tests/test_token_endpoint.py tests/test_micropub_endpoint.py -q`, `uv run pytest tests/test_token_management.py -q`, `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, `git diff --check`, and `git diff --cached --stat` passed.

### Close H-Card Utility Coverage Gaps and Confirm Support Status

- Added focused pytest coverage for h-card utility behavior in `tests/test_h_card.py`, covering recursive hyphen-to-underscore property normalization, scalar-to-list normalization, nested `adr`/`org` normalization, invalid top-level validation inputs, invalid nested `adr`/`org` list items, first top-level h-card selection, no-h-card parsing, base-URL resolution, and nested parsed `h-adr` property-name normalization.
- Reviewed `src/indieweb/h_card.py`, `src/indieweb/models.py`, `src/indieweb/templatetags/indieweb_tags.py`, and `src/indieweb/templates/indieweb/h-card.html` against the documented h-card support surface; no implementation changes were needed, and the existing consumer tests remained part of targeted validation.
- Documentation: checked `docs/h-card.rst`; no h-card documentation update needed because the support/status wording still matches current behavior.
- Changelog: no changelog update needed because this was test-only coverage and backlog bookkeeping, with no behavior, public API, configuration, or user-facing documentation change.
- Validation: `uv run pytest tests/test_h_card.py -q`, `uv run pytest tests/test_h_card.py tests/test_h_card_extra_classes.py tests/test_h_card_integration.py tests/test_h_card_templatetags.py tests/test_profile_models.py -q`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, and `git diff --check` passed.

### Audit IndieWeb Docs for Stale Settings, Commands, and Behavior Notes

- Audited the current development, contributor, README, Sphinx, IndieAuth, Micropub, Webmention, h-card, configuration, backlog, and changelog documentation against the current project workflow and recent endpoint behavior.
- Corrected current workflow guidance to prefer ``just docs`` for local preview and ``uv run sphinx-build -W -b html docs docs/_build/html`` for docs validation; updated ``just docs`` to run the same warning-as-error Sphinx build directly instead of shelling through ``make -C docs``.
- Corrected current contributor workflow notes to use the Markdown backlog/DONE workflow, ``prek`` hooks, local tox matrix validation, and the current docs build command.
- Corrected current behavior summaries and examples so README, index, API, concepts, Micropub, tutorial, and Webmention docs mention source query, update/delete/undelete, current Micropub query support, token expiration fields, PKCE fields, and canonical same-page author h-card URL matching where those summaries had lagged behind the detailed docs.
- No change needed after audit: ``docs/indieauth.rst`` already covered PKCE, ``client_id`` validation, token expiration, scope normalization, token-exchange scope matching, and per-operation Micropub scopes; ``docs/h-card.rst`` already matched current h-card model/template-tag/parser support; the token lifetime and ``INDIEWEB_CLIENT_ID_VALIDATOR`` sections in ``docs/configuration.rst`` already matched current behavior; current limitations in ``docs/concepts.rst`` and ``docs/micropub.rst`` still match open backlog items for token revocation UI, media endpoint/uploads, WebSub, and additional post types.
- Left open: the adjacent h-card utility coverage item and the broader TODO/future-enhancement cleanup item remain in ``BACKLOG.md`` because this slice did not add h-card tests or exhaustively resolve all future-enhancement notes.
- Documentation: updated ``README.rst``, ``CONTRIBUTING.rst``, ``docs/development.rst``, ``docs/index.rst``, ``docs/api.rst``, ``docs/concepts.rst``, ``docs/configuration.rst``, ``docs/micropub.rst``, ``docs/tutorial.rst``, and ``docs/webmention.rst``.
- Changelog: updated ``docs/changelog.rst`` with an Unreleased documentation-audit bullet.
- Validation: ``uv run sphinx-build -W -b html docs docs/_build/html``, ``just docs``, ``uv run prek run --all-files``, ``uv run pytest``, ``uv run mypy``, ``uv run ruff check .``, ``uv build``, and ``git diff --check`` passed.

### Align Webmention Author H-Card URL Matching with Canonical URL Matching

- Updated receive-side Webmention same-page author lookup in `src/indieweb/processors.py` so h-card `url` properties are compared with the existing `_urls_match()` conservative canonical URL policy instead of exact string membership.
- Matching policy: explicit URL-valued `p-author` references and local `rel=author` links resolve against the final fetched source URL, preserve same-document fragment `id` lookup first, then match same-page h-card `u-url` values with the existing target-verification policy. That policy ignores fragments, lowercases scheme and host, treats a leading `www.` hostname as equivalent, treats one trailing slash on non-root paths as equivalent, and compares query parameters independent of order while preserving duplicate key/value pairs. Non-string h-card URL property values are ignored defensively.
- Preserved behavior: unmatched explicit author URL references still fall back to URL-as-name, `rel=author` with no matching h-card can still fall through to a single page-level h-card, multiple page-level h-cards remain ambiguous, relative author/photo URLs continue to resolve against the final fetched source URL after redirects, and local `Profile` overrides still apply after an author is extracted.
- Out of scope: asynchronous Webmention receiving, remote author-page fetching, vouch support, Salmentions, and unrelated endpoint, target-link, redirect, source-removal, spam, or source/target storage behavior remain unchanged.
- Added focused regression tests in `tests/test_webmention_processor.py` for explicit author URL matches across trailing slash, leading `www.`, scheme/host case, ignored-fragment, and query-order variants; `rel=author` using the same canonical h-card URL matching path; malformed non-string h-card URL properties; unmatched URL-as-name fallback; fragment `id` matching; local `Profile` override after canonical h-card matching; and page-level h-card ambiguity behavior.
- Documentation: updated `docs/webmention.rst` with the canonical same-page author h-card matching policy. Checked `docs/api.rst`, `docs/concepts.rst`, and `docs/h-card.rst`; no changes were needed because endpoint/status response shapes, conceptual protocol wording, and local h-card model/template-tag usage did not change.
- Changelog: updated `docs/changelog.rst` with the receive-side author h-card URL matching fix.
- Validation: `uv run pytest tests/test_webmention_processor.py tests/test_webmention_endpoint.py -q`, `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, and `git diff --check` passed.

### Complete the Webmention Authorship Fallback Chain

- Added receive-side Webmention authorship fallbacks in `src/indieweb/processors.py` without changing endpoint responses, storage semantics, or network behavior.
- Authorship policy: explicit `h-entry` author data remains highest priority. Nested author `h-card` data is extracted directly; string author URL references are resolved against the final fetched source URL and matched to same-page `h-card` items by URL or same-document fragment id. If no h-card matches an explicit URL-valued author reference, the resolved URL is still used as both author URL and display name for backwards compatibility. When an entry has no explicit author, `rel=author` links are resolved against the final fetched source URL and matched to h-cards already present in the parsed source document. If `rel=author` yields no author, a single unambiguous page-level h-card outside an h-entry is used as fallback; multiple page-level h-cards are treated as ambiguous and no fallback author is guessed.
- Relative author URLs and author photo URLs resolve against the final fetched source URL after redirects, preserving the redirect behavior from the previous slice. Extracted local author URLs still pass through the existing `Profile` override so local profile fields replace parsed author fields.
- Out of scope: asynchronous Webmention receiving, remote author-page fetching, vouch support, Salmentions, and unrelated target-link, endpoint-domain, redirect, source-removal, spam, or source/target storage behavior remain unchanged.
- Follow-up: added a Priority 2 backlog item to align same-page author h-card URL matching with the conservative canonical URL matcher already used for Webmention target verification.
- Added focused regression tests in `tests/test_webmention_processor.py` for relative unmatched author URL fallback, same-page fragment `rel=author`, explicit author precedence over `rel=author` and page-level h-cards, relative `rel=author`, redirected final-URL `rel=author` base handling, single page-level h-card fallback, unresolved `rel=author` falling through to page-level fallback, conservative ambiguous page-level h-card handling, and local `Profile` override through a `rel=author`-extracted local author URL. Existing nested `p-author h-card`, same-page author URL reference, unmatched URL-as-name, redirect, source-removal, and endpoint tests remain covered.
- Documentation: updated `docs/webmention.rst` with the authorship extraction policy and remote-fetch limitation. Checked `docs/api.rst`, `docs/concepts.rst`, and `docs/h-card.rst`; no changes were needed because endpoint/status response shapes, conceptual protocol wording, and local h-card model/template-tag usage did not change.
- Changelog: updated `docs/changelog.rst` with the receive-side authorship fallback improvement.
- Validation: `uv run pytest tests/test_webmention_processor.py tests/test_webmention_endpoint.py -q`, `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, and `git diff --check` passed.

### Follow and Test HTTP Redirects in Webmention Receive and Send Paths

- Added shared Webmention HTTP redirect handling in `src/indieweb/http_client.py` with an explicit limit of 5 redirects per request. Redirects are followed only to `http` and `https` URLs after resolving relative `Location` values against the URL that produced the redirect; redirect loops and excessive chains fail through the same bounded limit.
- Receive-side policy: `WebmentionProcessor._fetch_source()` follows bounded redirects when fetching the submitted source URL, while `Webmention.source_url` and `Webmention.target_url` remain the submitted values. The final fetched URL is used as the microformats2 parsing base so relative author/photo URLs resolve against the actual source page. Final `410 Gone`, non-`200`, non-HTML, missing-target-link, unsupported redirect, and excessive-redirect outcomes use the existing failed-state path that clears `verified_at` and preserves parsed fields.
- Send-side policy: `WebmentionSender.discover_endpoint()` follows bounded redirects for both `HEAD` and fallback `GET`; relative `Link` and HTML endpoints discovered after redirects resolve against the final target page URL. `fetch_content()` follows the same bounded redirect policy. `send_webmention()` follows endpoint redirects for `301`, `302`, `303`, `307`, and `308` while preserving the original `POST` method and `source`/`target` form payload; final `200`, `201`, and `202` remain success, while redirect errors return the existing `{"success": False, ...}` shape.
- Out of scope: asynchronous Webmention receiving, authorship fallback changes, vouch support, Salmentions, and target-URL canonical redirect verification remain tracked separately in `BACKLOG.md` or intentionally unimplemented.
- Added focused regression tests in `tests/test_webmention_processor.py` for successful redirected source verification, preservation of submitted URLs, final-URL microformats base resolution, redirect-limit failure clearing stale `verified_at`, redirected non-HTML failure, and redirected non-`200` failure. Added focused tests in `tests/test_webmention_sender.py` for redirected endpoint discovery, final-URL relative endpoint resolution, redirected content fetches, preserved endpoint `POST` payloads, and safe failure shapes on redirect errors.
- Documentation: updated `docs/webmention.rst` with the receive/send redirect policy and endpoint `POST` behavior; checked `docs/api.rst` and `docs/concepts.rst` and no changes were needed because endpoint/status response shapes and conceptual IndieWeb wording did not change.
- Changelog: updated `docs/changelog.rst` with the explicit bounded Webmention redirect behavior fix.
- Validation: `uv run pytest tests/test_webmention_processor.py tests/test_webmention_sender.py tests/test_webmention_endpoint.py -q`, `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, and `git diff --check` passed.

## 2026-04-28

### Handle Source Removal and `410 Gone` Semantics for Existing Webmentions

- Added a shared failed-state update path in `src/indieweb/processors.py` so receive-side Webmention reprocessing consistently marks rows `failed` and clears `verified_at` when the source can no longer be verified.
- Source-removal policy: if an existing Webmention source returns `410 Gone`, or returns `200 text/html` but no longer links to the submitted target, the existing row is marked `failed`, `verified_at` is set to `NULL`, and the submitted `source_url`/`target_url` plus previously parsed author/content/published/mention-type fields are preserved. Other processor failure paths that mark a row `failed` also clear `verified_at`, but are not documented as explicit removal signals because they may be transient. Spam reclassification also clears `verified_at` and preserves previously parsed fields when a row is marked `spam`. If the source later returns valid HTML that links to the target again, reprocessing can mark the same row `verified` with a fresh timestamp.
- Out of scope: asynchronous Webmention receiving, redirect following, authorship fallback changes, vouch support, and Salmentions remain tracked separately in `BACKLOG.md`.
- Added focused regression tests in `tests/test_webmention_processor.py` for existing verified `410 Gone` handling, HTML sources that no longer link to the target, new `410 Gone` rows, failed-fetch timestamp clearing, spam reclassification timestamp clearing and parsed-field preservation, and re-verifying an existing failed row when the source link returns.
- Documentation: updated `docs/webmention.rst` with the reprocessing/source-removal behavior and field-preservation policy; checked `docs/api.rst` and `docs/concepts.rst` and no changes were needed because endpoint status response shape and conceptual Webmention wording did not change.
- Changelog: updated `docs/changelog.rst` with the receive-side source-removal and stale timestamp behavior fix.
- Validation: `uv run pytest tests/test_webmention_processor.py tests/test_webmention_endpoint.py -q`, `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, and `git diff --check` passed.

### Canonicalize URLs During Target-Link Verification

- Replaced receive-side Webmention target verification in `src/indieweb/processors.py` with parsed `href` extraction via BeautifulSoup and conservative canonical URL comparison, preserving the previous lenient "any `href` attribute" behavior while removing raw substring matching. The matching policy ignores fragments, lowercases scheme and host only, treats one leading `www.` hostname as equivalent, treats one trailing slash on non-root paths as equivalent, and sorts decoded query key/value pairs with `keep_blank_values=True` while preserving duplicate pairs. Userinfo and explicit ports must match exactly.
- Applied the same canonical URL comparison to microformats2 target matching for `in-reply-to`, `like-of`, `repost-of`, `bookmark-of`, and `mention-of`, plus parsed HTML `href` content and conservative plain-text URL-token fallback. Reply/like/repost classification now works when the source uses a supported target URL variant.
- Preserved storage semantics: `Webmention.source_url` and `Webmention.target_url` remain the submitted values. Endpoint domain validation in `WebmentionEndpoint.is_valid_target()` is unchanged.
- Out of scope: asynchronous receiving, redirect following, `410 Gone`/source-removal semantics beyond the existing behavior, and the full authorship fallback chain remain tracked separately in `BACKLOG.md`.
- Added focused regression tests in `tests/test_webmention_processor.py` for exact links, non-anchor `href` values, fragments in either source or submitted target, scheme/host case normalization, leading `www.`, trailing slash equivalence, root-path slash preservation, path case significance, query-parameter ordering, duplicate query pair preservation, different-path/query rejection, malformed href handling, process-level canonical target verification, dict-shaped microformats URL properties, plain-text URL-token fallback, and canonical microformats classification.
- Documentation: updated `docs/webmention.rst` with the receive-side target matching policy; checked `docs/api.rst` and `docs/concepts.rst` and no changes were needed because they do not document this target-link verification detail.
- Changelog: updated `docs/changelog.rst` with the Webmention target verification behavior fix.
- Validation: `uv run pytest tests/test_webmention_processor.py tests/test_webmention_endpoint.py -q`, `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, and `git diff --check` passed.

## 2026-04-26

### Decide and Implement IndieAuth-Side Scope Handling and Token-Issuance Semantics

- Added deterministic scope normalization on the IndieAuth issuance side (`src/indieweb/views.py`): scope strings are split on whitespace, duplicate tokens are removed while preserving first-seen order, and the result is joined with single spaces. `None`, empty, and whitespace-only input becomes no scope.
- Authorization requests now render normalized `scope` and `scope_list`, consent approval stores the normalized scope on the `Auth` row, and duplicate-auth cleanup keys on that normalized scope. Unknown scopes such as `profile`, `media`, and site-specific values are intentionally preserved rather than rejected because IndieAuth/Micropub scopes are extension-defined.
- The token endpoint now issues exactly the normalized scope stored with the auth code. If a token exchange includes `scope`, the submitted value is normalized and must match the stored auth-code scope exactly; mismatches return HTTP 400 `invalid_grant` with content type `application/x-www-form-urlencoded`, create no new token, and do not refresh an existing token. An explicitly empty `scope=` parameter normalizes to no scope, so it only succeeds for a no-scope auth code. Scope mismatches do not delete the `Auth` row, matching the redirect URI mismatch behavior because this is a request mismatch rather than proof of auth-code compromise.
- Upgrade note: duplicate-auth cleanup keys on the newly normalized scope. A pre-existing `Auth` row with an un-normalized scope string can briefly coexist with a newly approved normalized row, but auth codes are short-lived under `INDIWEB_AUTH_CODE_TIMEOUT` (default 60 seconds) and token exchange re-normalizes stored scopes before comparison.
- Added regression tests in `tests/test_auth_endpoint.py` for authorization GET normalization, unknown-scope preservation, and normalized consent storage, and in `tests/test_token_endpoint.py` for omitted scope, no-scope auth-code exchange without a submitted scope, exact matches, normalized-equivalent matches, empty `scope=` behavior, mismatch rejection, no-scope override rejection, no token creation/reissue on mismatch, and normalized token response scope.
- Documentation: updated `docs/indieauth.rst`, `docs/api.rst`, and `docs/concepts.rst` to document scope normalization, unknown-scope pass-through, and token-exchange scope matching semantics.
- Changelog: updated `docs/changelog.rst` with the scope issuance behavior change.
- Validation: `uv run pytest` baseline passed before implementation; after implementation `uv run pytest tests/test_auth_endpoint.py tests/test_token_endpoint.py tests/test_micropub_endpoint.py -q`, `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, and `git diff --check` passed.

### Implement Micropub Source Query

- Replaced the `501 Not Implemented` stub for `GET ?q=source` in `MicropubView.get` (`src/indieweb/views.py`) with dispatch into the configured `MicropubContentHandler.get_entry(url, user)`. The existing per-operation scope gate is unchanged: `GET ?q=source` still requires `update`, and scope failures still return HTTP 403 with the plain-text body `authorization error` before source-query dispatch.
- Wire formats and response codes:
  - Full source query: `GET /indieweb/micropub/?q=source&url=...` returns HTTP 200 with `Content-Type: application/json` and the Microformats-style body `{"type": entry.type, "properties": entry.properties}`.
  - Filtered source query: `GET /indieweb/micropub/?q=source&url=...&properties[]=content&properties[]=name` reads the W3C array form via `request.GET.getlist("properties[]")` and returns HTTP 200 with `{"properties": {requested_name: entry.properties[requested_name], ...}}`. Requested properties that are not present on the entry are omitted, not returned as empty arrays.
  - The filtered response intentionally omits `type`. W3C Micropub §3.7.2 says the full response includes all properties plus a `type` property when no properties are specified; its selective-properties examples return only the `properties` object. This slice follows that example shape.
  - Missing `url` returns HTTP 400 with body `invalid_request`. A handler `None` return (unknown URL or no permission as interpreted by the handler) also returns HTTP 400 `invalid_request` and logs a warning with the submitted URL repr. A handler `ValueError` also maps to HTTP 400 `invalid_request`, mirroring the action handlers for third-party handlers that use exceptions for "not found" despite the `get_entry` contract documenting `None`.
  - Unexpected handler exceptions other than `ValueError` return HTTP 500 and are logged with `logger.exception`.
- Added `tests/test_micropub_source.py` with source-query regression coverage for full source responses, filtered `properties[]` responses, multiple requested properties, omitted missing properties, all-requested-properties-unknown responses, missing/unknown URL handling, handler `ValueError`, JSON content type, and unexpected handler exceptions. Updated `tests/test_micropub_endpoint.py::test_get_source_query_accepts_update_scope` so it now expects the source handler's `400 invalid_request` path instead of the old `501`; the non-update-scope rejection test remains unchanged and continues to assert 403.
- Documentation: updated `docs/api.rst` (new Source Query subsection, source-query error cases, and scopes), `docs/micropub.rst` (quick-start query examples and error handling), `docs/concepts.rst` (removed source-query limitation/future-enhancement bullets), `docs/indieauth.rst` (security item #9 no longer says source is unimplemented), and `docs/tutorial.rst` (handler/source-query description and scope troubleshooting).
- Changelog: updated `docs/changelog.rst` with the source-query behavior and adjusted the earlier editing-support note so the Unreleased notes no longer describe source queries as a current 501 gap.
- Validation: `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, and `git diff --check` all passed.

### Implement Micropub Update, Delete, and Undelete Actions

- Replaced the `501 Not Implemented` stub for `POST action=update`/`delete`/`undelete` in `MicropubView.post` (`src/indieweb/views.py`) with real dispatch into the configured `MicropubContentHandler`. Per-operation scope enforcement (`update`/`delete`/`undelete`, shipped in `697e21e`) is unchanged; the new code runs *after* the scope gate. This is *partial* editing support: the Micropub Recommendation also requires `GET ?q=source` for servers that support updates, and that query continues to return `501 Not Implemented` after the scope check (tracked separately in the backlog; superseded by `Implement Micropub Source Query` on 2026-04-26).
- Wire formats and response codes:
  - `POST action=update` is JSON-only (per W3C Micropub §3.7). The body must be an object containing a string `url` and at least one of `replace`, `add`, `delete`. Per Micropub §3.4, values inside `replace`/`add` MUST be arrays and `delete` MUST be either a list of property-name strings or a map of property names to arrays of values. The view validates the operation shape (`MicropubView._validate_update_operations`) before forwarding to the handler so spec-non-conformant payloads (empty body, scalar operation values, malformed `delete`) are rejected with `400 invalid_request` rather than papered over by the handler's normalization. Form-encoded update bodies are rejected with `400 invalid_request`.
  - `POST action=delete` and `POST action=undelete` accept either form-encoded or JSON bodies; both require `url`. The view forwards `url` and the token's `owner` to `handler.delete_entry` / `handler.undelete_entry`.
  - Success on update/undelete returns `204 No Content` when the handler-returned entry's `url` equals the submitted `url`. When the handler returns an entry whose URL differs (Micropub §3.7/§3.10 permit this on update and undelete), the view returns `201 Created` with a `Location` header — absolute when the handler's URL is already absolute, otherwise built from the request via `request.build_absolute_uri`. Delete cannot relocate (the handler interface returns `None`); delete success is always `204`.
  - The handler's `ValueError` (entry unknown, or undelete URL not in the deleted set) is mapped to `400` with the plain-text body `invalid_request` and logged at `WARNING` (with the URL repr but no token material). The W3C Micropub Recommendation does not pin a specific code for "entry not found"; some implementations use `404`, but we chose `400 invalid_request` so action client errors look consistent with the IndieAuth and token endpoint conventions and so we don't have to guess handler-specific permission semantics.
  - Other handler exceptions (e.g. database failures, handler bugs) are mapped to `500 Internal Server Error` and logged at `ERROR` via `logger.exception` so stack traces stay in the server log rather than the response body. (Initial implementation mapped these to `400` too, which would have signalled a non-retryable client error for a server fault; corrected after code review.)
  - Missing `url` (form-encoded or JSON), malformed JSON, and JSON that does not decode to an object all return `400 invalid_request`.
- Hardened the JSON body parsing: a `POST` with `Content-Type: application/json` whose body fails to parse, or whose body parses to anything other than a JSON object, is rejected with `400 invalid_request` *before* scope and action dispatch. The new `MicropubView._reject_invalid_json` helper runs at the top of `post()`. Without this guard a malformed JSON body could fall through to the create path (because `_post_action` returned `None` on JSON parse failure, which dispatches as "create") and silently create an empty entry when the token had `create` scope; the corresponding regression test is `TestMicropubMalformedJsonBody`. The except clause covers `json.JSONDecodeError`, `UnicodeDecodeError` (raised by `json.loads` on invalid UTF-8 bytes such as `b"\xff"` — distinct from `JSONDecodeError`), and `AttributeError` (defensive). `_action_payload` and `_post_action` have the same except shape so they are safe to call independently of the top-of-`post()` guard.
- The view's URL handling is intentionally pass-through. The submitted `url` is forwarded to the handler verbatim; URL canonicalization (e.g. host/path normalization, absolute vs. relative key conventions) is the handler's responsibility. `InMemoryMicropubHandler` keys by the relative URL it generated (e.g. `/entries/1/`), so test requests use that form; a real handler may key by absolute URL.
- Added small helpers on `MicropubView` so `post()` stays under the McCabe limit: `_reject_invalid_json` (top-of-`post` JSON guard), `_action_payload` (parses the JSON body and rejects non-object payloads), `_action_url` (extracts `url` from form-encoded or JSON), `_invalid_request` (the `400 invalid_request` factory), `_action_response` (builds `204` or `201+Location` for update/undelete), `_validate_update_operations` (Micropub §3.4 validation of `replace`/`add`/`delete` shapes), and `_handle_update`/`_handle_delete`/`_handle_undelete` (one per action). `post()` now dispatches on the action string and falls through to the existing create path; the create path is otherwise unchanged.
- Added `tests/test_micropub_actions.py` with 32 view-level integration tests using a shared `InMemoryMicropubHandler` injected via `monkeypatch.setattr("indieweb.views.get_micropub_handler", ...)`: 8 update tests (replace/add/delete-as-list/delete-as-dict/combined success; unknown URL; missing URL; form-encoded rejection); 4 delete tests (form & JSON success; unknown URL; missing URL); 4 undelete tests (form & JSON success; not-in-deleted-set; missing URL); 5 malformed-JSON tests covering the create-fall-through risk and the invalid-UTF-8 path that previously escaped as 500 (the most important regression cases from the reviews); 7 update body-shape validation tests covering the §3.4 violations (empty body, scalar replace/add values, non-dict replace, scalar delete, dict-with-scalar-values delete, list-with-non-string delete); 3 unexpected-handler-exception tests asserting `500` (one per action); and a relocating-handler case asserting `201`+`Location` on update.
- Updated the existing scope-acceptance tests in `tests/test_micropub_endpoint.py` (`test_post_action_update_accepts_update_scope`, `test_post_action_delete_accepts_delete_scope`, `test_post_action_undelete_accepts_undelete_scope`) so they now expect `400 invalid_request` (the URL submitted is unknown to the fresh in-memory handler) instead of `501`. Their docstrings were updated to make clear they assert the scope gate accepts the scope (no 403); the body assertion is proof we reached the action handler. The scope-rejection tests (`test_post_action_*_rejects_*_scope`) are unchanged and still assert `403 authorization error`.
- Documentation: updated `docs/api.rst` (added `Update Action`, `Delete Action`, `Undelete Action` subsections with §3.4 validation rules and `500` mapping; refreshed Scopes; expanded the `400 invalid_request` listing to cover malformed JSON and operation-shape failures; added a `500 Internal Server Error` listing); `docs/micropub.rst` (added an `Update, Delete, Undelete` examples block; rewrote Error Handling — `204`, `201+Location` for update/undelete relocation only, `400 invalid_request` for client errors, `500` for unexpected handler exceptions; kept the `501` note for `GET ?q=source` only); `docs/concepts.rst` (rewrote Scopes; tightened Limitations and Future Enhancements to leave only `q=source`); `docs/indieauth.rst` (security item #9 no longer claims update/delete/undelete return 501); `docs/tutorial.rst` (no longer claims update/delete/undelete return 501; clarified that the in-memory handler implements all three but does not persist).
- Changelog: updated `docs/changelog.rst` with the partial-editing-support framing the review asked for.
- Validation: `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, and `git diff --check` all passed.

### Enforce Per-Operation Token Scopes on the Micropub Endpoint

- Operation-to-scope mapping. The W3C Micropub Recommendation (§5 Scope, https://www.w3.org/TR/micropub/#scope) allows servers to define their own granular scopes; it does not mandate this exact set of names. This mapping is the project's chosen policy, following Micropub's operation taxonomy and the conventional scope names that reference clients (Quill, Indigenous, Micropublish) request. The W3C Recommendation does not define a separate "read" scope, so `q=source` is gated on `update` here, matching the typical "read before update" use case used by reference implementations:
  - `POST` (no `action`) → `create`, with the legacy alias `post` still accepted
  - `POST action=update` → `update`
  - `POST action=delete` → `delete`
  - `POST action=undelete` → `undelete`
  - `GET ?q=source` → `update`
  - `GET ?q=config`, `GET ?q=syndicate-to`, `GET` (no `q`) → token-required, no scope gate
- Refactored `TokenAuthMixin.authorized` to take an optional `required_scope: str | None = None` parameter. With `required_scope=None` the call succeeds for any authenticated token; otherwise the stored `scope` is split on whitespace and the required scope must be present as an exact token. Substring matching is gone (the previous `"create" in scope` accepted `createXYZ`/`postscript`). Removed the scope check from `TokenAuthMixin.dispatch`, which now does authentication and the `client_id_allowed` check only — scope decisions live in the views that know which operation is being performed.
- Added `MicropubView._post_action`, `MicropubView._required_scope`, and `MicropubView._scope_authorized` helpers in `src/indieweb/views.py`. `_required_scope` returns the project-defined required scope for `(method, action, q)` (or `None` for "no gate"); `_scope_authorized` calls `self.authorized(...)` with that requirement and additionally accepts `post` whenever `create` is required (legacy alias). `MicropubView.get` and `MicropubView.post` call `_scope_authorized` first thing and return HTTP 403 with the unchanged plain-text body `authorization error` on failure. `_post_action` reads `action` from form-encoded POSTs *and* from JSON bodies (with type narrowing so the JSON branch satisfies mypy without `cast`s).
- The `update`/`delete`/`undelete` POST actions and the `q=source` GET query continue to return `501 Not Implemented` after the scope check passes; no Micropub handler bodies were added in this slice.
- `invalid_client` (the 403 added in the previous client_id slice) is unchanged. The new scope gate fires inside the view methods, after `TokenAuthMixin.dispatch` has already cleared authentication and the `client_id` policy.
- Existing scope tests in `tests/test_micropub_endpoint.py` (`test_create_scope_authorization`, `test_multiple_scopes_authorization`, `test_not_authorized`, `test_no_token`, `test_wrong_token`) and in `tests/test_micropub_create.py` (`test_missing_scope`) continue to pass without modification, confirming the `post`-as-`create`-alias and 403-body shape contracts.
- New regression tests in `tests/test_micropub_endpoint.py` cover every operation/scope pair: `POST` create accepts `create`/`post`/`create update delete`/`profile create` and rejects `update`/`delete`/`undelete`/`read`/empty/`createXYZ`/`postscript` (the substring-match negative case); `POST action=update` accepts `update`/`create update`/`update delete` and rejects `create`/`post`/`delete`/`undelete`/`read`/empty; `POST action=delete` accepts `delete`/`create delete`/`delete update` and rejects `create`/`post`/`update`/`undelete`/empty; `POST action=undelete` accepts `undelete`/`delete undelete`/`create undelete` and rejects `create`/`post`/`update`/`delete`/empty; `GET ?q=config`, `GET ?q=syndicate-to`, and `GET` with no `q` succeed for `create`/`post`/`update`/`delete`/`read`/empty/`None`; `GET ?q=source` accepts `update`/`create update`/`update delete` and rejects `create`/`post`/`delete`/`undelete`/`read`/empty.
- Documentation: updated `docs/api.rst` (rewrote the `Scopes` section to describe per-operation enforcement and exact-token matching; expanded the Micropub `403 Forbidden` listing with the per-operation requirements), `docs/indieauth.rst` (new Security Considerations item #9 covering the operation mapping, exact-token matching, the unchanged `authorization error` body, and the 501-after-scope-check behavior for unimplemented handlers), `docs/concepts.rst` (rewrote the `Scopes` listing and the Limitations list to match the now-enforced gates), and `docs/micropub.rst` (corrected the "post scope" claim in Quick Start and the testing section).
- Changelog: updated `docs/changelog.rst`.
- Validation: `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, and `git diff --check` all passed.

### Implement `client_id` Access Control for Token Authorization

- Added module-level helpers `_validate_client_id`, `_client_id_allowed`, and `_token_client_id_error` in `src/indieweb/views.py`. Structural validation requires a syntactically valid URL (via Django's `URLValidator`) using a scheme from `ALLOWED_REDIRECT_URI_SCHEMES` (`http`, `https`), no fragment delimiter at all (so `https://x#` is rejected, not just `https://x#section`), and no userinfo component — mirroring the just-shipped `_validate_redirect_uri` rule.
- Added the optional `INDIEWEB_CLIENT_ID_VALIDATOR` setting (default `None`). When unset, every structurally-valid `client_id` is permitted and there is no behavior change relative to the previous commit. When set to a dotted path resolving to a `(client_id: str) -> bool` callable (loaded via `django.utils.module_loading.import_string`, mirroring the `_get_spam_checker` pattern in `src/indieweb/processors.py`), the callable runs on top of structural validation. A misconfigured path that fails to import, or a callable that raises, fails closed at every call site.
- Wired structural validation and the configured validator into `AuthView.get` (rejects with HTTP 400 plain text — `invalid client_id` for structural failures, `invalid_client` for validator failures — before rendering the consent screen), `AuthView._handle_consent` (same shape, before creating any `Auth` row), and `AuthView._verify_auth_code` (the IndieAuth code-verification POST that returns the authenticated `me` for an existing `Auth` row — same shape, before any DB lookup, so a misconfigured or revoked validator cannot leave this path as a back door).
- Wired both checks into `TokenView.post` via the new `_token_client_id_error` helper. Failures return HTTP 400 with body `invalid_request` and content type `application/x-www-form-urlencoded`, matching the existing missing-`code` case. Extracted the PKCE block into a new `TokenView._check_pkce` helper to keep `TokenView.post` under the McCabe complexity limit; behavior is unchanged.
- Wired the configured validator into `TokenAuthMixin.dispatch` (resource-server path). When the stored token's `client_id` is rejected, the request returns HTTP 403 with body `invalid_client` (new — the existing scope-failure response `authorization error` is unchanged). Removed the now-implemented `# TODO implement access control based on client_id` comment from `TokenAuthMixin.authorized`. Stored `client_id` values are not re-validated structurally on use (matching the `redirect_uri` rule); the operator policy hook, however, IS applied on use because operator policy can evolve and revoke previously-allowed clients.
- Logging: structural rejections log at `INFO`; validator rejections (including misconfigured-path fail-closed) log at `WARNING` or `ERROR`, with `client_id` repr but never the bearer token. Matches the auth-hardening series style.
- Added regression tests covering: structural rejection of malformed `client_id` at the authorization GET, the consent approval POST, the code-verification POST, and the token endpoint POST (parametrized over invalid URL, `ftp://`, fragment delimiter, bare `#`, userinfo, `javascript:` scheme); validator-driven rejection at all four authorization/token paths and on the Micropub resource-server path; validator acceptance at the four affirmative sites; and fail-closed behavior on a misconfigured (non-importable) dotted path at the authorization GET, the code-verification POST, the token endpoint, and the Micropub endpoint. Test-only validator callables live in the new `tests/client_id_validators.py` module.
- Documentation: updated `docs/configuration.rst` (new `INDIEWEB_CLIENT_ID_VALIDATOR` section), `docs/api.rst` (new `400 invalid_request` and `403 invalid_client` cases on the token and Micropub endpoints, new `400 invalid client_id` and `400 invalid_client` cases on the authorization endpoint), and `docs/indieauth.rst` (new Security Considerations item #7 covering both structural validation and the operator policy hook).
- Changelog: updated `docs/changelog.rst`.
- Validation: `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, and `git diff --check` all passed.

### Add PKCE (RFC 7636) to IndieAuth Authorization and Token Exchange

- Added `Auth.code_challenge` (`CharField(max_length=128, null=True, blank=True)`) and `Auth.code_challenge_method` (`CharField(max_length=8, null=True, blank=True)`) plus migration `0011_auth_code_challenge`. Both fields are nullable so auth codes issued before this change keep working.
- Added module-level helpers `_validate_pkce_request` and `_verify_pkce` in `src/indieweb/views.py`. Validation enforces RFC 7636 character set (`[A-Za-z0-9._~-]`), the 43-128 character bounds for both challenge and verifier, defaults `code_challenge_method` to `plain` per RFC 7636 §4.3 when only `code_challenge` is sent, and rejects any method other than `S256` or `plain`. Verification implements `S256` as `BASE64URL-WITHOUT-PADDING(SHA256(verifier))` and `plain` as direct equality, with `hmac.compare_digest` for constant-time comparison.
- Wired validation into `AuthView.get` (rejects bad PKCE inputs with HTTP 400 before rendering the consent screen, and propagates the validated/defaulted `code_challenge` and `code_challenge_method` into the render context) and `AuthView.post` consent approval path (rejects bad inputs with HTTP 400 before creating the `Auth` row, persists `code_challenge` and the effective method otherwise).
- Updated the bundled `indieweb/consent.html` template so the consent form posts `code_challenge` and `code_challenge_method` back as hidden inputs whenever a challenge is present, and called this out in the consent-template-override example in `docs/indieauth.rst` so custom templates do not silently drop PKCE.
- Wired verification into `TokenView.post`. With a stored `code_challenge`, a missing or mismatched `code_verifier` is rejected as `invalid_grant`. A `code_verifier` submitted against a row with no stored challenge is also rejected as `invalid_grant`. A row with no stored challenge and no submitted verifier (legacy flow) continues to succeed. On any PKCE failure the auth row is deleted to preserve one-time-use semantics.
- Added regression tests covering: rejection of unsupported `code_challenge_method` values and malformed challenges at the authorization GET; default-to-`plain` behavior when only `code_challenge` is sent; the GET render context carrying PKCE values; the bundled consent template carrying the PKCE hidden inputs; an end-to-end GET → consent POST → token-exchange round-trip with a correct verifier; PKCE persistence on consent approve and rejection of bad PKCE inputs before the `Auth` row is created; legacy round-trip (no challenge, no verifier) at the token endpoint; rejection when the challenge is stored but the verifier is missing (with explicit assertion that the auth row is deleted); rejection when the verifier is submitted without a stored challenge; correct S256 and plain verifier acceptance; rejection of wrong verifiers for both methods; and rejection of verifiers outside the RFC unreserved set or length bounds.
- Documentation: updated `docs/indieauth.rst` (Security Considerations, consent-template override example, and the available-context-variables list) and `docs/api.rst` (authorization and token request parameters, IndieAuth flow diagram, and the error-response listings for `invalid_grant` and authorization-endpoint `invalid_request`).
- Changelog: updated `docs/changelog.rst`.
- Validation: `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, and `git diff --check` all passed.

### Validate IndieAuth `redirect_uri` Values

- Added module-level helpers `_validate_redirect_uri`, `_normalize_redirect_uri`, and `_append_redirect_params` in `src/indieweb/views.py`. Validation requires a syntactically valid URL (via Django's `URLValidator`) using a scheme from `ALLOWED_REDIRECT_URI_SCHEMES` (`http`, `https`), no fragment delimiter at all (so `https://x/cb#` is rejected, not just `https://x/cb#section`), and no userinfo component.
- Wired validation into `AuthView.get`, `AuthView.post` (consent approve/deny path), and `TokenView.post`. The authorization endpoint now returns HTTP 400 (`invalid redirect_uri`) before creating any `Auth` row when the value is malformed; the token endpoint returns HTTP 400 (`invalid_grant`) for a malformed submitted value.
- Replaced the previous string-equality redirect-URI check in `TokenView.post` with a normalized comparison: scheme and host are lowercased, path and query are preserved verbatim. Already-stored `Auth.redirect_uri` values are compared defensively without re-validation, so auth codes issued before this change continue to work.
- Replaced naive `f"{redirect_uri}?{urlencode(...)}"` concatenation in the consent approve/deny paths with `_append_redirect_params`, which parses the existing query and merges new pairs so a `redirect_uri` containing its own query (e.g. `?next=/x`) no longer collapses `code` into the trailing value.
- Reduced log verbosity to avoid leaking sensitive `code` query parameters at INFO level.
- Added regression tests covering: rejection of fragment, bare `#`, userinfo, disallowed scheme, and syntactically invalid `redirect_uri` at the authorization GET and the consent approval POST; query-merging on approve and deny; rejection at the token endpoint with `invalid_grant`; acceptance of a case-only difference in scheme/host at the token endpoint; and rejection of a path-only difference.
- Documentation: updated `docs/indieauth.rst` (Security Considerations) and `docs/api.rst` (token endpoint parameter notes and the error-response listing).
- Changelog: updated `docs/changelog.rst`.
- Validation: `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, and `git diff --check` all passed.

### Add Token Expiration Handling and Fix Auth-Code Timeout Calculation

- Added `Token.expires_at` (`DateTimeField(null=True, blank=True, db_index=True)`) plus migration `0010_token_expires_at` and a `Token.is_expired()` helper.
- Added the `INDIEWEB_TOKEN_EXPIRES_IN` setting (default 86400 seconds) and updated `TokenView.send_token()` to persist `expires_at` on create and reissue and to report the live remaining lifetime in `expires_in` instead of the previous hardcoded `10`.
- Updated `TokenAuthMixin.authenticated()` to reject tokens whose `expires_at` is in the past with HTTP 401. Legacy tokens with `expires_at=NULL` remain accepted for backwards compatibility until they are reissued.
- Replaced `(now - auth.created).seconds` with `total_seconds()` in `TokenView.post()` so auth codes older than one day are correctly rejected.
- Added regression tests covering: token response advertising the configured lifetime, persisted `expires_at`, reissue refresh, expired-token rejection on the Micropub endpoint, legacy null-expiry acceptance, and multi-day-old auth-code rejection.
- Documentation: updated `docs/api.rst`, `docs/configuration.rst`, and `docs/indieauth.rst` for the new setting and 24-hour default lifetime.
- Changelog: updated `docs/changelog.rst`.
- Validation: `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, and `git diff --check` all passed.

### Triage and Resolve Open Dependabot Alerts

- Raised the runtime Django dependency floor to `Django>=5.2.13,<6.0`.
- Raised direct development dependency floors for `pytest>=9.0.3` and `requests>=2.33.0`.
- Refreshed `uv.lock` so vulnerable locked packages resolve to patched versions: Django `5.2.13`, pytest `9.0.3`, requests `2.33.1`, urllib3 `2.6.3`, sqlparse `0.5.5`, Pygments `2.20.0`, filelock `3.29.0`, and virtualenv `21.2.4`.
- Updated `TokenView.send_token()` to query by `owner_id` for compatibility with newer `django-stubs` while keeping the public type generic for custom user models.
- Documentation: no usage docs changed; dependency/security status is recorded in the changelog.
- Changelog: updated `docs/changelog.rst`.
- Validation: `uv sync`, `uv run pytest`, `uv run mypy`, `uv run ruff check .`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv build`, and `git diff --check` passed.
- Dependabot verification: the GitHub API reports 0 open Dependabot alerts after GitHub rescanned the pushed `uv.lock`.

### Verify Micropub Create Flow End to End

- Confirmed Micropub create handles form-encoded and JSON bodies and returns `201 Created` with an absolute `Location` header.
- Coverage: `tests/test_micropub_create.py` and `tests/test_micropub_endpoint.py`.
- Implementation reference: `src/indieweb/views.py`, `src/indieweb/handlers.py`.
- Documentation: no changes needed; `docs/micropub.rst` already matches the current create behavior.
- Changelog: no entry needed; verification only, no behavior change.
- Validation: `uv run pytest tests/test_micropub_create.py tests/test_token_endpoint.py tests/test_auth_endpoint.py` and `uv run pytest tests/test_h_card.py tests/test_h_card_extra_classes.py tests/test_h_card_integration.py tests/test_h_card_templatetags.py --cov=indieweb.h_card --cov-report=term-missing` passed during the backlog audit.

### Add Backlog Page to Documentation Navigation

- Added `docs/backlog.rst` as a dedicated documentation page for the Markdown backlog workflow.
- Added the Backlog page to the Sphinx sidebar navigation.
- Documentation: updated `docs/index.rst` and `docs/development.rst`.
- Changelog: updated `docs/changelog.rst`.
- Validation: `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run prek run --all-files`, `uv run pytest`, and `git diff --check` all passed.

### Switch Hook Runner to prek and Fix pyupgrade on Python 3.14

- Upgraded hook revisions, including `pyupgrade` from `v3.21.0` to `v3.21.2`, which fixes the observed Python 3.14 crash.
- Replaced the development dependency `pre-commit` with `prek`.
- Updated tox, contributor docs, agent instructions, and README references to use `prek`.
- Added `specs/2026-04-26_pyupgrade_issue.md` with the investigation notes and reproduction commands.
- Documentation: updated `README.rst`, `CONTRIBUTING.rst`, `docs/development.rst`, `AGENTS.md`, and `CLAUDE.md`.
- Changelog: updated `docs/changelog.rst`.
- Validation: `uv run prek run --all-files`, `uv run tox -e hooks`, `uv run tox -e pre-commit`, `uvx --python 3.14 prek run pyupgrade --all-files`, `uv run ruff check .`, `uv run mypy`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run pytest`, `uv build`, and `git diff --check` all passed.

### Replace Beads with Markdown Backlog Workflow

- Removed Beads and Beadsflow as the project work-tracking system.
- Added `BACKLOG.md` for planned work and `DONE.md` for completed work.
- Linked the backlog from the project documentation.
- Updated agent instructions to use the Markdown workflow and to keep docs/changelog entries aligned with completed work.
- Documentation: updated `docs/development.rst` and `docs/index.rst`.
- Changelog: updated `docs/changelog.rst`.
- Validation: `uv run ruff check .`, `uv run mypy`, `uv run sphinx-build -W -b html docs docs/_build/html`, `uv run pytest`, `uv build`, `git diff --check`, and `uv run --python 3.13 pre-commit run --all-files` all passed.
