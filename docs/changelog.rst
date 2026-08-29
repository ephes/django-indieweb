.. :changelog:

Changelog
=========

Unreleased
----------
* Added support for Django 6.1: the dependency cap is now ``Django<6.2`` and
  the tox matrix covers Django 6.1 on Python 3.12 through 3.14. Django 6.1
  itself treats a malformed ``Content-Length`` header as ``0`` (empty body),
  so the WebSub delivery size-limit fallback for malformed headers only
  applies on older Django versions.

0.6.1 (2026-05-11)
------------------
* Fixed migration ``0020`` on PostgreSQL by delaying the
  ``Webmention.status_token`` index creation until the final unique field
  definition. This avoids duplicate varchar pattern-index creation during
  upgrades from ``0.6.0``. Databases where ``0020`` already applied
  successfully need no operator action.

0.6.0 (2026-05-10)
------------------
* **Note:** PyPI users upgrading from ``0.5.2`` receive both the
  changes listed here and the ``0.5.3`` changes below; ``0.5.3`` existed
  in repository metadata but was not published to PyPI.
* **Security:** Webmention author attribution no longer rewrites a remote
  source page's claimed author URL to a local ``Profile``. Local profile
  metadata is used only when the source document itself is hosted on the
  current Django ``Site`` domain, preventing remote pages from rendering as a
  legitimate local author by declaring that author's ``u-url``.
* **Security:** Outbound Webmention sending and Salmention resend/preview
  workflows now cap fanout at 50 targets per source page and 5 targets per
  destination host by default
  (``INDIEWEB_WEBMENTION_MAX_TARGETS_PER_SOURCE`` /
  ``INDIEWEB_WEBMENTION_MAX_TARGETS_PER_HOST``), and ``HEAD`` endpoint
  discovery responses are decoded under a 64 KiB cap
  (``INDIEWEB_WEBMENTION_HEAD_MAX_BYTES``). Trusted-author deployments can set
  these caps to ``None`` when an external queue supplies equivalent limits.
* **Security:** WebSub delivery callbacks now require a ``Link`` header with
  ``rel="self"`` exactly matching the subscribed topic URL before hook or
  enqueue dispatch. ``INDIEWEB_WEBSUB_REQUIRE_TOPIC_LINK`` defaults to
  ``True`` and can be set to ``False`` only for trusted non-conforming hubs.
* **Security:** ``WebmentionNestedResponse`` now enforces the same
  ``http``/``https`` URL-scheme validation as parent ``Webmention`` rows
  on ``identity``, ``response_url``, ``author_url``, and
  ``author_photo``. Migration ``0028`` applies the model-layer
  validators so downstream templates and bulk write paths no longer have
  weaker URL-field guarantees for nested responses.
* **Security:** Micropub media deletion now requires submitted
  ``action=delete`` URLs to be relative/local or absolute URLs on the
  current request host, matching entry delete/update/undelete behavior.
  Cross-host media delete requests are rejected before
  ``INDIEWEB_MICROPUB_URL_POLICY`` or the host adapter can run.
* **Security:** ``TokenView.post`` no longer accepts a request-supplied
  ``me`` that differs from the consent-validated ``auth.me``. The issued
  bearer token is always bound to ``auth.me``; a mismatched submitted
  ``me`` is consumed and rejected with ``invalid_grant``. Introspection
  and the Micropub default config response now echo the bound identity
  rather than an attacker-supplied exchange parameter.
* **Security:** Webmention receive pairs are now keyed by a canonical
  ``(source_url, target_url)`` form (lowercased scheme, IDNA-encoded
  host, default port collapsed, empty path normalized to ``/``). Cosmetic
  URL variants of the same logical pair collapse onto a single stored
  row instead of sprawling new ``status_token`` URLs. A new
  ``INDIEWEB_WEBMENTION_PAIR_COOLDOWN_SECONDS`` setting (default ``0``,
  disabled) suppresses the synchronous fetch/parse/verify pipeline for
  repeat submissions of the same canonical pair within the cooldown
  window. Submitted ``source``/``target``/``vouch`` URLs that carry
  userinfo are rejected at the receive endpoint before canonicalization,
  and ``canonicalize_webmention_storage_url`` raises
  ``WebmentionCanonicalizationError`` on userinfo so direct callers of
  ``WebmentionProcessor.process_webmention`` cannot conflate two URLs
  differing only in userinfo either.
* **Security:** ``INDIEWEB_REDIRECT_URI_ALLOWLIST`` prefix entries
  reject candidates with literal or percent-encoded ``.``/``..`` path
  segments. ``_path_has_dot_segments`` iteratively decodes
  percent-encoded forms (bounded at 8 iterations) and fails closed if
  the decode has not stabilised within the bound, so multi-layer
  encodings such as ``%252e%252e`` and deeper cannot bypass the
  rejection. A trailing-slash prefix entry of
  ``https://client.example/oauth/`` no longer matches the traversal
  candidate ``https://client.example/oauth/../admin``.
* **Security:** ``Auth.get_for_raw_key`` and ``Token.get_for_raw_key``
  now hash submitted raw keys under every active Django secret key
  (primary plus ``SECRET_KEY_FALLBACKS``). Rotating ``SECRET_KEY``
  no longer invalidates active bearer tokens or outstanding
  authorization codes during the configured rotation window. New
  ``INDIEWEB_LEGACY_PLAINTEXT_KEY_LOOKUP`` setting (default ``True``)
  gates the legacy plaintext lookup fallback for rows persisted before
  at-rest hashing landed; set to ``False`` once the migration window has
  closed.
* **Security:** ``example_project.py`` now requires an explicit
  ``DJANGO_SECRET_KEY`` in the environment (or
  ``ALLOW_UNSAFE_DEV_SECRET=1`` to opt into the development sentinel),
  binds to ``localhost``/``127.0.0.1`` by default rather than ``["*"]``,
  and never auto-creates an ``admin/admin`` superuser. Use
  ``python example_project.py createsuperuser`` to make one.
  ``examples/custom_consent_template.html`` now carries the missing
  ``code_challenge`` / ``code_challenge_method`` hidden inputs so a
  copied custom consent template no longer silently strips PKCE
  bindings. ``handlers_example.py`` moved out of the installed
  ``indieweb`` package to ``examples/handlers_example.py`` so the
  example ``models.Model`` cannot accidentally attach to the
  ``indieweb`` migration graph.
* **Security:** ``WebmentionStatusView`` responses now emit
  ``Cache-Control: no-store`` and ``Vary: Cookie`` so a leaked status
  token cannot be replayed through a shared cache. ``TokenRevokeView``
  emits ``X-Frame-Options: DENY`` plus a ``frame-ancestors 'none'`` CSP
  header. ``MicropubView._valid_http_url`` rejects URL-typed Micropub
  create/update properties that carry userinfo. The
  ``webmention_endpoint_link`` template tag rejects non-HTTP(S),
  non-same-origin arguments and falls back to the configured indieweb
  webmention endpoint. ``Webmention.author_url`` and ``author_photo``
  enforce ``http``/``https`` schemes at the model layer.
* **Security:** ``http_client._blocked_ip_address`` rejects IPv6
  ``fec0::/10`` site-local addresses explicitly. ``_canonical_host``
  rejects URL hosts with empty labels. Default ``httpx.Client`` instances
  in ``processors.py``, ``senders.py``, and ``websub.py`` now configure
  bounded ``httpx.Limits``, drop ``Set-Cookie`` jar persistence via
  ``http_client.disable_client_cookies`` (because ``cookies=None``
  silently re-wraps to a real jar in ``httpx``), and emit a consistent
  operator-configurable ``User-Agent`` (set ``INDIEWEB_USER_AGENT`` to
  override the default ``django-indieweb/1.0``). The ``notify_websub``
  management command routes topic and hub URLs through ``redact_url``
  so deployments using ``INDIEWEB_LOG_REDACTION = "redact"`` extend the
  same privacy guarantee to its stdout. ``client.py`` no longer writes
  login response HTML to a fixed ``/tmp/blubber.html`` debug path.
* **Security:** WebSub renewal verification now applies a
  lease-shrink ratchet — an active confirmed lease cannot drop below
  half the prior value (or the configured floor, whichever is larger) —
  to defeat hub-driven renewal-traffic amplification. ``hub.challenge``
  is truncated to ``last_challenge``'s declared 200-character maximum
  before storage, preventing SQLite from silently growing the column.
  The vestigial ``WebSubSubscription.recent_accepted_delivery_digests``
  JSON column is removed via migration ``0026``;
  ``WebSubAcceptedDelivery`` rows are the authoritative replay gate.
  ``WebSubSubscription.callback_token`` preservation across successful
  resubscribes is documented as an intentional design choice.
* Documented Django's ``DATA_UPLOAD_MAX_NUMBER_FILES`` alongside the
  existing Micropub upload-size guidance in ``docs/micropub.rst``;
  Django parses multipart bodies before the view-level media-count cap
  runs, so a too-large ``DATA_UPLOAD_MAX_NUMBER_FILES`` lets a hostile
  sender exhaust memory before the view's per-request cap fires.
* Tightened Webmention URL parsing and display URL sanitization. Five
  defense-in-depth changes:
  ``WebmentionSender._parse_link_header`` now requires an exact
  ``webmention`` rel token (case-insensitive) instead of matching
  substrings like ``not-webmention``;
  ``_parse_html_for_endpoint`` applies the same exact-token rule to
  HTML ``<link>`` and ``<a>`` discovery via a new
  ``_rel_attribute_includes_webmention`` helper;
  ``sanitize_remote_webmention_url`` rejects URLs with userinfo
  (``user:pass@host``) — a phishing vector;
  ``WebmentionEndpoint.is_valid_target`` compares a normalized
  authority (lowercased scheme/host, IDNA-encoded host, default ports
  dropped) so URLs that differ only in case, explicit default port, or
  punycode form match the configured ``Site.domain`` consistently; and
  ``_prepare_nested_response_for_display`` now also routes
  ``identity`` / ``response_url`` through
  ``sanitize_remote_webmention_url`` so the bundled
  ``nested_response.html`` template never renders unsafe URLs from
  latent rows.
  ``tests/test_webmention_sender.py``, ``tests/test_webmention_endpoint.py``,
  ``tests/test_webmention_processor.py``, and
  ``tests/test_webmention_templatetags.py`` add focused regressions
  for each sub-task.
* Closed two log-redaction gaps under
  ``INDIEWEB_LOG_REDACTION="redact"``. Webmention outcome log strings
  in ``WebmentionProcessor._collect_webmention_outcome`` (410 Gone,
  fetch failure, target-not-in-source, vouch failure, spam, success,
  size-limit warning) now route ``source_url`` / ``target_url`` through
  ``redact_url``. Token-auth failure logs in ``TokenAuthMixin`` and
  ``TokenIntrospectionView`` route the submitted bearer key through a
  new ``redact_token`` helper (``src/indieweb/log_redaction.py``) that
  returns ``{value[:8]}...`` in passthrough mode and a stable 12-hex
  HMAC digest in redact mode, so even the leading bytes of the
  credential never appear in redacted logs. ERROR-level lines retain
  raw URLs intentionally for incident response.
  ``tests/test_log_redaction.py`` adds three pure-helper tests for
  ``redact_token``, two end-to-end token-auth tests, and two
  Webmention-outcome tests using an injected ``httpx.MockTransport``.
  ``docs/configuration.rst`` documents the expanded coverage.
* Added a WebSub secret encryption rotation path that honors Django's
  ``SECRET_KEY_FALLBACKS``. WebSub shared secrets are still encrypted
  at rest with key material derived from ``SECRET_KEY``, but
  decryption now tries the primary key first and then each entry in
  ``SECRET_KEY_FALLBACKS`` in declaration order. New encryption
  continues to use the primary key. Crucially, every save of a
  ``WebSubSubscription`` row also passively re-encrypts a
  fallback-bound ciphertext under the primary, so subscriptions
  migrate to the new key on the next save — including renewals that
  omit ``secret`` (where ``set_secret`` is never called). Operators
  can therefore rotate ``SECRET_KEY`` without re-subscribing every
  feed: keep the previous value in ``SECRET_KEY_FALLBACKS`` until every
  active subscription has been saved at least once under the new
  primary (any successful renewal, callback verification, or
  lease/state bookkeeping save triggers a save).
  ``src/indieweb/models.py`` introduces ``_websub_secret_keys`` and
  ``_websub_secret_multifernet`` helpers, plus a
  ``WebSubSubscription._maybe_reencrypt_under_primary`` classmethod
  invoked from ``save``. The save hook also adds the affected column(s)
  to ``update_fields`` when it mutated them, so partial-column saves
  (renewals, lease/state bookkeeping) actually persist the migrated
  ciphertext. ``tests/test_websub_subscriber.py`` adds seven focused
  regressions covering decrypt-with-fallback, fail-when-no-key,
  encrypt-uses-primary, ``set_secret``-after-rotation,
  save-without-``set_secret``-call-still-migrates,
  ``save(update_fields=...)``-still-persists-migration, and
  save-is-idempotent-for-already-migrated-rows.
  ``docs/websub.rst`` and ``docs/configuration.rst`` replace the
  "rotating ``SECRET_KEY`` requires re-subscribing" caveat with the
  fallbacks-based rotation guide.
* Enforced ``INDIWEB_AUTH_CODE_TIMEOUT`` on the legacy IndieAuth
  authorization-code verification POST. Token exchange has always
  rejected stale codes, but the verification POST returned ``me`` for
  any matching ``code`` / ``client_id`` pair regardless of age. The
  expiry check now lives in a small ``_auth_code_is_expired`` helper
  shared by ``TokenView.post`` and ``AuthView._verify_auth_code``, so
  both surfaces enforce the same window and delete the matched ``Auth``
  row on rejection. ``tests/test_auth_endpoint.py`` adds
  ``test_post_verify_auth_code_rejects_expired_code`` and
  ``test_post_verify_auth_code_accepts_fresh_code_within_window``.
  ``docs/indieauth.rst`` updates the auth-code-timeout
  security-considerations entry to describe the shared window.
* Hardened Micropub JSON parsing against extremely deeply nested request
  bodies. ``json.loads`` raises ``RecursionError`` when a JSON object or
  array exceeds the interpreter's recursion limit; the previous create,
  update/delete/undelete, and media JSON paths only caught
  ``json.JSONDecodeError`` / ``UnicodeDecodeError``, so a nested-bomb
  body bypassed validation and surfaced as an authenticated HTTP 500.
  A new module-level helper ``_load_micropub_json_object`` parses each
  ``application/json`` body once per request, caches the result on the
  request, and treats ``RecursionError`` (and non-object JSON roots) the
  same as a syntactically invalid body — returning
  ``400 invalid_request``. ``MicropubView`` (``_parse_json_request``,
  ``_post_action``, ``_reject_invalid_json``, ``_action_payload``) and
  ``MicropubMediaView._json_payload`` all consume the cached payload, so
  each authenticated body is parsed at most once.
  ``tests/test_micropub_actions.py`` adds two regressions covering the
  ``RecursionError`` catch path on the create and action POSTs;
  ``tests/test_micropub_media.py`` adds the same regression on the
  media POST. All three deterministically force ``json.loads`` in the
  views module to raise ``RecursionError`` via a thin ``_ProxyJson``
  shim — the C-accelerated parser's recursion limits vary across the
  supported Python matrix, so a fixed-depth payload is not a portable
  trigger (a 4_000-deep payload decoded fine on Python 3.13.12).
  Each test asserts ``400 invalid_request`` (or ``400`` on the media
  fallthrough) with no entries or hook side effects.
* Addressed three Warning-level findings from the security-residuals review:
  ``AuthView._handle_consent`` now applies the same ``_first_length_error``
  guard as ``AuthView.get`` and ``TokenView.post`` so overlong consent-POST
  fields are rejected before ``Auth.objects.create`` (closing a P4.2 gap);
  ``accept_websub_delivery`` short-circuits when
  ``INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS`` is ``0``/``None`` so
  duplicates are accepted unconditionally and no row is recorded in
  ``WebSubAcceptedDelivery``, restoring the documented "disable replay
  detection" semantics; and ``tests/test_documentation_snippets.py``
  ``KNOWN_SETTINGS`` now includes ``INDIEWEB_REDIRECT_URI_VALIDATOR`` so
  the documentation sanity-check covers all documented settings.
* Added length validation for inbound IndieAuth and Webmention protocol
  fields. ``WebmentionEndpoint.post`` now rejects ``source``, ``target``,
  and ``vouch`` URLs longer than the backing ``Webmention`` model
  ``max_length`` with ``400 invalid_request`` before
  ``_store_webmention_submission()`` so overlong but syntactically valid
  URLs cannot reach the storage layer.  ``AuthView.get`` and
  ``TokenView.post`` apply the same boundary check to ``client_id``,
  ``redirect_uri``, ``state``, ``me``, and ``scope`` against the ``Auth``
  model ``max_length`` values, returning ``400 invalid_request: <field>
  exceeds maximum length``. The maxima are derived from
  ``Auth._meta.get_field(...).max_length`` and
  ``Webmention._meta.get_field(...).max_length`` at import time so they
  stay in sync if the schema changes.  ``tests/test_webmention_endpoint.py``,
  ``tests/test_auth_endpoint.py``, and ``tests/test_token_endpoint.py``
  cover each rejected field and assert that no ``Webmention``/``Token``
  row is written.
* Added opt-in privacy-oriented log redaction for IndieAuth/Micropub/
  Webmention/WebSub INFO and WARNING log lines.
  ``INDIEWEB_LOG_REDACTION`` (default ``"passthrough"``) preserves the
  existing log shape; setting it to ``"redact"`` replaces ``client_id``,
  ``redirect_uri``, ``state``, ``me``, Webmention source/target URLs,
  and WebSub hub URLs with stable 12-character HMAC-SHA256 digests
  keyed with ``SECRET_KEY``. The ``me`` parameter uses an
  origin-only digest (scheme+host) so multiple paths under the same
  origin collapse to a shared digest, supporting correlation without
  disclosure. ERROR-level logs are not redacted so operators retain
  full URLs for incident response. New module
  ``src/indieweb/log_redaction.py`` exposes ``redact_url``,
  ``redact_url_origin``, and ``redact_state``. Wiring covers the auth
  GET log, consent verification, token exchange, resource-server
  client gating, Micropub entry/media URL rejections, the Webmention
  processing INFO line, stale-outcome and vouch-preservation logs, and
  WebSub subscription/notification failure warnings.
  ``docs/configuration.rst`` documents the setting (anchored at
  ``log-redaction``) and adds it to the ``Production hardening``
  snippet. ``tests/test_log_redaction.py`` covers both modes, stable
  digests, origin collapsing, mode resolution, and end-to-end log
  output via ``caplog``;  ``tests/test_documentation_snippets.py`` adds
  ``INDIEWEB_LOG_REDACTION`` to its known-settings sanity check.
* Added an optional public-safe Webmention status response mode.
  ``INDIEWEB_WEBMENTION_STATUS_PUBLIC`` (default ``False``) preserves the
  existing token-holder diagnostic shape that echoes ``source``, ``target``,
  ``status``, and (when verified) ``verified_at``. When set to ``True``,
  ``WebmentionStatusView`` returns only ``status`` and (when set)
  ``verified_at``, omitting ``source`` and ``target`` so a leaked status URL
  does not reveal the stored URL pair. Status URLs already use opaque
  high-entropy ``status_token`` values; this setting is the residual
  hardening for deployments where private or draft target URLs must not
  appear in a status response. ``src/indieweb/views.py``
  (``WebmentionStatusView``) reads the setting via ``getattr`` so existing
  ``settings.py`` files behave unchanged. ``docs/configuration.rst``
  documents the setting and adds it to the ``Production hardening`` snippet
  (anchored at ``production-hardening``); ``docs/webmention.rst`` and
  ``docs/api.rst`` describe the default response as token-holder diagnostics
  and cross-reference the setting. ``tests/test_webmention_endpoint.py``
  adds three regressions covering the public-safe shape (verified and
  pending) and the default diagnostic shape;
  ``tests/test_documentation_snippets.py`` adds
  ``INDIEWEB_WEBMENTION_STATUS_PUBLIC`` to its known-settings sanity check.
* Documented that injected ``httpx.Client`` arguments are a trusted
  test/integration escape hatch. ``docs/webmention.rst`` and
  ``docs/websub.rst`` now carry prominent ``.. warning::`` blocks (anchored
  at ``webmention-injected-client-warning`` and
  ``websub-injected-client-warning``) explaining that DNS-based SSRF blocking
  and IP pinning are not applied to caller-provided clients; the warnings
  cover ``WebmentionProcessor(client=...)``, ``process_queued_webmention``,
  ``WebmentionSender.discover_endpoint``,
  ``WebmentionSender.send_webmention``,
  ``WebmentionSender.fetch_content``, ``notify_hubs()``, and
  ``request_websub_subscription()``. ``docs/configuration.rst`` adds an
  ``Injected HTTP Clients`` subsection under ``Security Configuration`` and
  ``docs/api.rst`` cross-references the warnings near the WebSub publisher
  helpers. ``tests/test_documentation_snippets.py`` adds
  ``test_injected_client_warning_present`` so removing the warning text from
  either RST file fails CI. Doc-only change; no behavior, settings, or
  migrations changed.
* Added an optional view-level URL policy hook for Micropub source and media
  operations. ``INDIEWEB_MICROPUB_URL_POLICY`` is a dotted path to a callable
  ``(url, kind: Literal["entry", "media"], request) -> bool`` that gates the
  Micropub entry source query (``GET /indieweb/micropub/?q=source&url=...``),
  the media source-by-URL query (``GET /indieweb/media/?q=source&url=...``),
  and the media delete action (``POST /indieweb/media/`` with
  ``action=delete``) before the URL is forwarded to the configured
  ``INDIEWEB_MICROPUB_HANDLER``. Returning ``True`` permits the request; any
  other return value yields ``400 invalid_request``. Callable exceptions,
  import failures, and non-callable resolutions fail closed with ``500`` and
  are logged. The setting is unset by default; existing deployments behave
  unchanged. The hook intentionally avoids a hard same-host rule because
  media may legitimately live on storage or CDN hosts. ``src/indieweb/views.py``
  adds ``_resolve_micropub_url_policy`` and ``_enforce_micropub_url_policy``
  beside the other dotted-path resolvers; ``MicropubView._handle_source_query``,
  ``MicropubMediaView._handle_source_by_url_query``, and
  ``MicropubMediaView._handle_delete`` consult the gate immediately after
  URL extraction. ``docs/configuration.rst`` documents the setting and adds
  it to the ``Production hardening`` snippet; ``docs/micropub.rst`` adds an
  "Optional URL policy hook" subsection. ``tests/micropub_policies.py``
  provides fixture callables; ``tests/test_micropub_source.py`` and
  ``tests/test_micropub_media.py`` cover rejection, runtime errors, and
  import errors for all three surfaces.
  ``tests/test_documentation_snippets.py`` adds
  ``INDIEWEB_MICROPUB_URL_POLICY`` to its known-settings sanity check.
* Added an "unbounded by count" interpretation to
  ``INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX``. Setting the cap to ``0``
  now disables count-based eviction in
  ``indieweb.websub.accept_websub_delivery``; pruning happens purely by
  ``INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS`` so every accepted
  delivery body inside the window is retained against replay. The previous
  behavior raised on ``0`` and silently fell back to the default cap of 64,
  which re-enabled count-based eviction for operators who wanted unbounded
  retention. ``_delivery_replay_history_max`` recognizes an explicit ``0``
  before delegating to ``_positive_int`` and returns the same ``None``
  "disabled" sentinel that ``= None`` produces; empty or otherwise malformed
  values still fall back to the documented default cap and are logged.
  ``docs/websub.rst`` and ``docs/configuration.rst`` document the ``0`` opt-in
  alongside the high-volume eviction caveat for the default cap; signed
  deployments that retain every accepted body for the full window should set
  the cap to ``0``. ``tests/test_websub_subscriber.py`` adds
  ``test_replay_history_cap_zero_means_unbounded_by_count``. No migrations
  or other settings changes.
* Prevented unauthenticated Vouch metadata downgrade on repeat Webmention
  submissions. A repeat submission for an existing source/target row whose
  newly submitted ``vouch`` URL fails verification (or whose verification is
  skipped because the deployment does not verify Vouches) no longer replaces
  the row's previously verified ``vouch_url`` and no longer clears
  ``vouch_verified_at``. ``_store_webmention_submission`` now skips the
  ``vouch_url`` / ``vouch_verified_at`` write when the row already has a
  verified Vouch and stashes the submitted URL on a non-persisted attribute
  for any in-memory caller (the queued worker reloads the row by id and so
  silently discards the new URL when a prior verified Vouch is in place —
  preserving the verified state is the intended behavior). The synchronous
  ``WebmentionProcessor.process_webmention`` path records whether the row
  had a prior verified Vouch and, in the persistence phase, only commits the
  new ``vouch_url`` / ``vouch_verified_at`` when Phase 1 successfully
  verified the new URL; rows without a prior verified Vouch keep the existing
  behavior of accepting the submitted URL with a cleared timestamp.
  ``tests/test_webmention_endpoint.py`` adds
  ``test_async_repeat_submission_does_not_downgrade_verified_vouch`` and
  ``tests/test_webmention_processor.py`` adds
  ``test_repeat_submission_with_failing_vouch_keeps_previous_verified_metadata``
  and ``test_repeat_submission_with_succeeding_vouch_replaces_verified_metadata``.
  No migrations or settings changes.
* Preserved staged WebSub secret rotations across denied renewal callbacks.
  ``record_websub_denial`` previously cleared ``pending_secret`` and
  ``pending_secret_set`` on any valid denied callback, including denials
  that targeted a renewal of an already-active subscription; that
  discarded the staged rotation that operators had set up before the
  next subscribe attempt. The function now keeps the staged rotation
  intact when ``subscription.state == STATE_ACTIVE`` (the active secret
  continues to validate hub deliveries and the operator can retry the
  renewal without rebuilding the rotation) and only clears the pending
  secret state for non-active denials such as ``STATE_PENDING_SUBSCRIBE``.
  ``update_fields`` on the ``save()`` call is narrowed accordingly so we
  do not write the unchanged secret columns on the active-renewal path.
  ``tests/test_websub_subscriber.py`` adds
  ``test_denied_renewal_preserves_active_secret_and_staged_rotation`` and
  ``test_denied_initial_subscribe_clears_pending_secret_state`` and
  tightens
  ``test_callback_denial_for_active_renewal_preserves_current_subscription``
  to lock in the new behavior. No migrations or settings changes.
* Added a copyable production-hardening settings snippet to the
  configuration guide so internet-facing IndieAuth/Micropub deployments
  can opt in to strict defaults without deriving setting names by reading
  source. ``docs/configuration.rst`` gains a new ``Production hardening``
  section (with a ``production-hardening`` reST label) covering
  ``INDIEWEB_REQUIRE_PKCE``, ``INDIEWEB_REQUIRE_PKCE_S256``,
  ``INDIEWEB_BIND_ME_TO_USER``, ``INDIEWEB_ALLOWED_CLIENT_IDS``,
  ``INDIEWEB_REDIRECT_URI_ALLOWLIST``, and concrete
  ``INDIEWEB_RATE_LIMITS`` entries for the bundled ``auth``, ``token``,
  ``token_introspection``, ``micropub``, ``media``, ``webmention``,
  ``webmention_status``, and ``websub_callback`` keys. ``docs/indieauth.rst``,
  ``docs/api.rst``, and ``README.rst`` cross-reference the new section.
  ``tests/test_documentation_snippets.py`` asserts the section header and
  setting names exist in ``docs/configuration.rst`` so renaming or
  removing a setting in code without updating the snippet fails CI. No
  behaviour change.
* Aligned the Micropub create error path with the rest of the action handlers
  so unexpected exceptions no longer flow through to authenticated clients.
  ``MicropubView.post`` now catches ``ValueError`` from
  ``MicropubContentHandler.create_entry()`` and returns
  ``400 invalid_request`` (the rejection is logged at warning level; the
  exception message is no longer echoed in the response body). Any other
  handler exception is logged via ``logger.exception("Unexpected error in
  create_entry")`` and the response is ``500`` with an empty body, matching
  the existing update, delete, undelete, source, and media error semantics.
* Made WebSub delivery replay detection atomic against concurrent identical
  deliveries and tightened the at-most-once-per-digest hook contract. A new
  ``WebSubAcceptedDelivery`` model carries a unique constraint on
  ``(subscription, body_digest)``; ``WebSubCallbackView.post`` now opens
  ``transaction.atomic()``, prunes rows older than
  ``INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS`` inside the block, and
  inserts the new acceptance via an inner savepoint that surfaces a clean
  replay signal on ``IntegrityError``. Two concurrent identical deliveries
  cannot both record an acceptance, regardless of whether the database backend
  supports ``SELECT FOR UPDATE``; the losing delivery returns the existing
  HTTP ``409`` replay response. Hook dispatch happens after the gate commits,
  so a crash between commit and hook execution leaves an
  accepted-and-recorded delivery whose hook may not have run; on retry the
  unique-constraint conflict returns ``409`` and the hook is not re-invoked.
  ``INDIEWEB_WEBSUB_DELIVERY_HOOK`` and ``INDIEWEB_WEBSUB_DELIVERY_ENQUEUE``
  callables that advertise a ``body_digest`` parameter (or take ``**kwargs``)
  receive the SHA-256 hex digest of the delivery body as a stable idempotency
  key; legacy callables continue to receive the existing keyword set
  unchanged. The ``recent_accepted_delivery_digests`` JSON column on
  ``WebSubSubscription`` is no longer read or written and remains in place
  for migration compatibility; cleanup is planned for a follow-up. The
  legacy ``delivery_is_replay`` helper now consults the new table and emits
  a ``DeprecationWarning`` for callers that have not migrated. This change
  ships migration ``0025_websubaccepteddelivery``; deployments must run
  ``manage.py migrate`` before serving traffic on the upgraded code.
* Bound IndieAuth ``redirect_uri`` values to the submitted ``client_id`` so a
  trusted client identifier can no longer be paired with an attacker-controlled
  redirect target. ``AuthView.get`` and ``AuthView._handle_consent`` now run a
  layered policy after the existing ``client_id`` allowlist/validator: the
  built-in default requires the ``redirect_uri`` *origin* (scheme, host, port
  after IDNA encoding and default-port collapsing) to equal the ``client_id``
  origin; ``INDIEWEB_REDIRECT_URI_ALLOWLIST`` lets operators bind specific
  redirect URIs per ``client_id`` (trailing slash means prefix match, no
  trailing slash means exact origin+path+query match, fragments rejected); and
  ``INDIEWEB_REDIRECT_URI_VALIDATOR`` is a dotted-path
  ``(client_id, redirect_uri) -> bool`` policy hook that short-circuits both
  layers and fails closed on import error, callable exception, non-callable
  values, or non-bool returns. The bundled consent screen now displays the
  resolved redirect URI so a user can verify the destination before approving.
  This is a backwards-incompatible change for deployments that previously
  relied on cross-origin ``client_id``/``redirect_uri`` pairs without a custom
  validator; such deployments must configure
  ``INDIEWEB_REDIRECT_URI_ALLOWLIST`` or
  ``INDIEWEB_REDIRECT_URI_VALIDATOR`` before upgrading or the authorization
  endpoint returns HTTP 400 ``invalid redirect_uri for client_id``.
* Serialized the IndieAuth authorization-code consume-and-token-issue sequence
  under a database transaction so two concurrent token exchanges for the same
  code cannot both succeed. ``TokenView.post`` now opens
  ``transaction.atomic()`` once an ``Auth`` row matches, evaluates
  ``Auth.objects.select_for_update().filter(pk=auth.pk).first()`` for
  defense-in-depth on row-locking backends, and gates the consume on the
  delete count: ``Auth.objects.filter(pk=auth.pk).delete()`` returning ``0``
  means a competing exchange already consumed the code, in which case the view
  returns ``invalid_grant`` without issuing a token. ``send_token`` runs
  inside the same atomic block and the reissue branch now acquires
  ``Token.objects.select_for_update().filter(pk=token.pk).first()`` before
  rotating the bearer key, so a concurrent reissue cannot interleave another
  rotation on Postgres/MySQL. The delete-count gate is the authoritative
  enforcement on SQLite, where row locks are a no-op.
* Added a strict cross-origin redirect mode to the shared HTTP helper.
  ``request_with_safe_redirects`` and ``stream_with_safe_redirects`` now accept
  a ``cross_origin_strip`` keyword argument (default ``False``). When enabled,
  a redirect whose target origin (scheme/host/port) differs from the URL that
  produced the redirect raises ``WebmentionRedirectError`` before any network
  call to the new origin is made. WebSub subscribe (the new
  ``_post_subscription_request`` helper used by
  ``request_websub_subscription``) and publish (``notify_hubs``) opt into
  strict mode so a hub redirect cannot replay a ``hub.secret``-bearing or
  ``hub.url`` POST body to a different origin. Webmention sender redirect
  handling (``request_with_webmention_redirects``) deliberately keeps the
  permissive default because Webmention POST compatibility preserves the
  method/body across origins.
* Reject WebSub subscription requests that send ``hub.secret`` over plain HTTP.
  ``_post_subscription_request`` now validates the hub URL scheme before any
  network call and raises a typed ``WebSubSecretRequiresHTTPSError`` (a
  ``ValueError`` subclass) when ``hub.secret`` would be transmitted to an
  ``http://`` hub URL. ``request_websub_subscription`` records the rejection
  through its existing failure path so operators see a recognisable error
  without leaking the secret over the wire. Together with the strict
  redirect mode this completes the P1.2 outbound HTTP hardening work begun
  earlier in this Unreleased cycle.
* Tightened outbound SSRF blocklist in ``_blocked_ip_address`` so multicast,
  reserved, unspecified, loopback, link-local, and private destinations are
  rejected explicitly even when ``ipaddress.is_global`` would already cover
  them, and added recursion through NAT64 well-known (``64:ff9b::/96``) and
  local-use (``64:ff9b:1::/48``) prefixes so an IPv6 carrier of a blocked IPv4
  address (for example a NAT64-encoded ``127.0.0.1`` or
  ``169.254.169.254``) is rejected via the embedded v4 destination. Default
  ``httpx.Client`` instantiations in the Webmention, Webmention sender, and
  WebSub clients now pass ``trust_env=False`` so ambient
  ``HTTP(S)_PROXY``/``NO_PROXY``/``SSL_CERT_FILE`` environment variables
  cannot redirect or downgrade the screened connection path. Injected client
  branches are unchanged; callers that supply their own ``httpx.Client`` keep
  full control.
* Restricted Webmention and Vouch source proof to rendered ``<a href>``
  hyperlinks. Non-anchor href carriers such as ``<link rel="canonical">``,
  ``<base>``, and ``<area>`` no longer satisfy target or Vouch source-domain
  verification, and the non-rendered-ancestor guard (``<template>``,
  ``<script>``, ``<style>``, ``<noscript>``, ``<iframe>``, ``<svg>``, HTML
  comments) now applies consistently to Vouch domain checks as well.
* Tightened h-card URL handling as defense-in-depth. ``Profile`` validation now
  restricts ``h_card.url``/``h_card.photo``/``h_card.org.url`` and the synced
  ``Profile.url``/``Profile.photo_url`` fields to ``http``/``https``, rejecting
  ``ftp``, ``ftps``, ``javascript``, ``data``, ``file``, and ``mailto`` schemes
  via ``full_clean()``. The bundled ``h-card.html`` template now runs every
  interpolated ``href``/``src`` through a new ``h_card_safe_url`` filter
  (backed by ``sanitize_remote_webmention_url``) and skips emission when the
  result is empty, so bypass paths like ``QuerySet.update``, ``bulk_update``,
  raw SQL, and fixture loads cannot leak unsafe URLs into rendered pages.
  Outbound profile links now carry ``rel="me noopener"`` (first URL, for
  IndieAuth identity discovery) or ``rel="nofollow noopener"`` (subsequent
  URLs); every ``<a class="u-url">`` and ``<img class="u-photo">`` element sets
  ``referrerpolicy="no-referrer"``. ``mailto:`` ``href`` values now go through
  ``urlencode``.
* Added ``INDIEWEB_WEBSUB_DELIVERY_ENQUEUE`` so hosts can hand accepted WebSub
  deliveries off to a queue instead of running
  ``INDIEWEB_WEBSUB_DELIVERY_HOOK`` synchronously inside the callback request
  thread. The enqueue callable receives the same keyword arguments as the
  delivery hook (``subscription_id``, ``hub_url``, ``topic_url``, ``body``,
  ``headers``). When ``INDIEWEB_WEBSUB_DELIVERY_ENQUEUE`` is set, the callback
  view validates token, signature, size, content-type, and replay state, calls
  the enqueue, records HTTP ``204`` on success, and skips the inline delivery
  hook so the queued worker can run any host-side processing later. Import
  failures, non-callables, and exceptions from the enqueue callable are logged,
  recorded as ``delivery enqueue failed``, and returned as HTTP ``500`` so the
  hub retries. ``INDIEWEB_WEBSUB_DELIVERY_HOOK`` continues to drive synchronous
  deliveries when ``INDIEWEB_WEBSUB_DELIVERY_ENQUEUE`` is unset.
* Removed the ``unittest.mock`` module-name guards in
  ``request_with_safe_redirects`` and ``stream_with_safe_redirects``. Those
  guards silently disabled streaming size enforcement and IP pinning whenever
  the HTTP client's ``__class__.__module__`` was ``"unittest.mock"`` so legacy
  ``Mock`` clients in the sender/processor test suites kept working — but they
  also meant a future caller wrapping a real ``httpx.Client`` in a
  ``unittest.mock.Mock`` for tracing or instrumentation would have silently
  bypassed those SSRF protections in production. ``WebmentionSender``
  (``discover_endpoint``, ``send_webmention``, ``fetch_content``) and
  ``WebmentionProcessor`` (constructor) now accept an optional ``client``
  keyword argument; when provided, the SSRF resolver is skipped, mirroring the
  ``websub.request_websub_subscription`` injection pattern. ``process_queued_webmention``
  accepts and forwards the same kwarg. Production callers that pass no
  ``client`` (the default) retain the full DNS-blocking and IP-pinning
  pipeline. Sender and processor tests now inject ``httpx.MockTransport``-backed
  clients through this kwarg instead of patching ``httpx.Client`` with
  ``unittest.mock.Mock``.
* Replaced the package-local ``count-lines-of-code`` implementation with the
  shared ``slopscope`` line-count workflow. ``just loc`` now installs
  ``slopscope`` from PyPI by default with ``--prerelease allow`` and explicit
  ``rich`` support, while ``SLOPSCOPE_SPEC`` can point at a local checkout for
  ``slopscope`` development.
* Fixed Webmention ``dt-published`` parsing on Python 3.10 for microformats
  timestamps that serialize UTC offsets without a colon, such as
  ``2026-05-01T10:00:00+0000``. Nested Webmention responses now retain their
  published timestamp across all supported Python versions.
* Hardened the token management page against clickjacking. The
  ``TokenManagementView`` now emits ``X-Frame-Options: DENY`` (via
  ``@xframe_options_deny``) and ``Content-Security-Policy: frame-ancestors
  'none'``, matching the consent screen's posture rather than relying on
  ``XFrameOptionsMiddleware`` defaulting to ``SAMEORIGIN``. A regression test
  ``test_token_management_blocks_framing`` asserts both headers.
* Serialized concurrent Webmention receives for the same ``(source_url,
  target_url)`` pair. ``WebmentionProcessor.process_webmention`` now splits
  processing into a lock-free IO phase (source fetch, parsing, vouch and spam
  checks) and a short ``transaction.atomic`` block that acquires the row with
  ``select_for_update`` and applies the pre-computed outcome. The persistence
  phase reloads the row under the lock and writes onto that locked instance
  with scoped ``update_fields``, so a concurrent receive that committed
  changes between the initial ``get_or_create`` and the lock cannot have its
  unrelated field updates clobbered by a stale full save.
  ``_verify_vouch_for_webmention`` no longer persists ``vouch_verified_at``
  itself; it returns the verification timestamp so the caller can write it
  under the lock alongside any pending ``vouch_url`` change. The
  persistence phase records the URL Phase 1 actually verified
  (``verified_vouch_url``) and writes ``vouch_verified_at`` only when the
  locked row still holds that URL — so a concurrent receive that swaps
  ``vouch_url`` between Phase 1 and the lock cannot have a stale timestamp
  applied to its (unverified) URL. Spam outcomes also carry the verified
  timestamp, mirroring the previous mid-pipeline ``vouch_verified_at`` save
  so a successful Vouch verification followed by a spam classification still
  retains the verification timestamp.
  Each ``_WebmentionOutcome`` records the wall-clock time at which Phase 1
  *started* (``received_at``, captured before any outbound IO so that a
  slow older receive whose failure surfaces only after a timeout still
  carries an older watermark); a new ``Webmention.last_received_at`` column
  (migration ``0024_webmention_last_received_at``) tracks the latest
  ``received_at`` ever applied to a row. Phase 2 compares the locked row's
  ``last_received_at`` against the incoming outcome and skips writes whose
  start time is older than what has already been committed, so a slow
  older receive can no longer overwrite a newer outcome that has already
  landed — even when the older receive ultimately fails on a timeout.
  ``_store_source_snapshot_safely`` and ``_sync_nested_responses_safely`` run
  inside nested savepoints so a real database error in either cannot poison
  the parent transaction and roll back the verified save.
  ``webmention_received`` is dispatched via ``transaction.on_commit`` so
  receivers never observe rolled-back state. Regression tests assert that the
  source fetch happens before the row lock is acquired, that a concurrent
  ``vouch_url`` update committed between the two phases survives processing,
  that ``IntegrityError`` raised during snapshot writes still leaves
  ``status='verified'`` committed, and that the signal fires after commit
  (using ``django_capture_on_commit_callbacks``).
* Treated an empty ``INDIEWEB_WEBSUB_DELIVERY_MAX_BYTES`` as the documented
  default rather than a silent disable. ``_delivery_max_bytes()`` now mirrors
  the ``_hub_response_max_bytes()`` and ``_delivery_replay_history_max()``
  posture: ``None`` is the explicit "disable cap" sentinel, while malformed or
  empty values fall back to the 1 MiB default with a logged warning.
* Clamped ``INDIEWEB_WEBSUB_MIN_LEASE_SECONDS`` and
  ``INDIEWEB_WEBSUB_MAX_LEASE_SECONDS`` to a documented sane range of 60
  seconds to 90 days. Out-of-range configuration is logged and pulled to the
  nearest in-range value, so a misconfigured ``min=1`` no longer accepts
  one-second leases and a misconfigured ``max=10**12`` no longer accepts
  multi-thousand-year leases. If the configured pair would invert after
  parsing, the helper falls back to the defaults.
* Hashed IndieAuth authorization codes at rest. ``Auth.key`` is now stored as an
  HMAC-SHA256 digest of the issued raw code (using ``settings.SECRET_KEY``),
  mirroring the existing ``Token.key`` posture. The raw code is returned to the
  client only at issuance and surfaced through ``Auth.raw_key``; lookups go
  through ``Auth.get_for_raw_key()`` and at-rest digests are not accepted as the
  submitted code. The Django admin replaces the ``key`` field with a non-secret
  ``masked_key`` accessor (``hmac-sha256$...``). Migration ``0023`` widens the
  storage column and rehashes any in-flight rows. Hosts that previously ran raw
  database queries against ``Auth.key`` should switch to ``Auth.hash_key(raw)``.
* Capped the outbound Webmention sender's POST response body. The
  ``request_with_webmention_redirects`` helper now accepts a ``max_bytes``
  keyword that routes through the streaming path with the existing decoded-bytes
  budget, and ``WebmentionSender.send_webmention()`` threads the new
  ``INDIEWEB_WEBMENTION_RESPONSE_MAX_BYTES`` setting (default 1 MB; ``None``
  disables the cap, malformed values fall back to the default) through to that
  helper. Hostile Webmention endpoints returning oversized bodies surface as
  delivery failures with ``status_code=None`` and a ``response too large`` error
  rather than buffered into memory.
* Pinned SSRF-safe outbound HTTP connections to checked IP addresses. The
  shared ``request_with_safe_redirects`` and ``stream_with_safe_redirects``
  helpers now resolve the URL host once with the configured address resolver,
  validate every returned IP, and rewrite the request URL host to the chosen
  safe IP literal before handing it to ``httpx``. The original hostname is
  preserved as the ``Host`` header for HTTP correctness and forwarded as
  ``extensions["sni_hostname"]`` for HTTPS, so TLS SNI and certificate
  verification still target the original hostname. The pin is re-applied on
  every redirect hop, closing the DNS rebinding / TOCTOU window that
  previously existed between pre-flight validation and the actual ``httpx``
  connect. Callers that need the legacy hostname-on-the-wire behavior (for
  example, test code that asserts on the connected URL host) can pass
  ``pin_to_resolved_ip=False``. New helper ``resolve_safe_http_url(url, *,
  resolver) -> (host, port, ip)`` exposes the validate-and-resolve step for
  hosts that integrate the IndieWeb safe-HTTP layer with their own clients.
* Tightened token introspection per RFC 7662 §2.1 with a same-``client_id``
  rule. ``/indieweb/token/introspect/`` now requires the caller and target
  tokens to share a normalized ``client_id`` after scheme/host case and IDNA
  normalization; cross-client lookups for the same owner return
  ``{"active": false}`` without disclosing scope, ``me``, or expiry. The new
  ``INDIEWEB_TOKEN_INTROSPECTION_AUTHORIZER`` setting accepts a dotted path to
  a ``(caller_token, target_token) -> bool`` callable for hosts that need a
  broader policy (for example, a first-party resource-server credential that
  introspects every token). Import failures, callable exceptions, non-callable
  values, and non-bool return values fail closed.
* Capped Webmention parser fallback traversals. The fallback ``h-entry``,
  ``h-card``, ``h-card``-by-id, and page-level h-card walks in
  ``WebmentionProcessor`` are now iterative and share the existing
  ``INDIEWEB_WEBMENTION_NESTED_RESPONSE_MAX_DEPTH`` and
  ``INDIEWEB_WEBMENTION_SEARCH_MAX_ITEMS`` budgets with the primary scans.
  Maliciously deep ``children`` chains and oversized microformats trees no
  longer reach Python's recursion limit or starve the request worker; the
  walks return whatever they have found so far when the budget is exhausted
  and preserve existing authorship/source-selection behavior on normal pages.
* Tracked multiple recent WebSub delivery digests for replay protection.
  ``WebSubSubscription`` now stores a bounded list of recently accepted SHA-256
  delivery digests and ``delivery_is_replay()`` rejects any captured payload
  that matches a retained digest within the configured replay window, closing
  the A/B/A replay gap that the single-row ``last_accepted_delivery_digest``
  field could not detect. The history is bounded by the new
  ``INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX`` setting (default 64) so the
  cache cannot grow unbounded; an empty environment variable falls back to
  the default rather than disabling the cap. Migration ``0022`` adds the
  storage field with an empty default.
* Hardened Micropub action input validation and bounded outbound WebSub hub
  responses. ``action=update`` now rejects non-HTTP(S) values inside ``replace``
  and ``add`` operations for URL-typed properties (``photo``, ``audio``,
  ``video``, ``in-reply-to``, ``like-of``, ``repost-of``, ``bookmark-of``,
  ``syndication``) before ``update_entry()`` is called, mirroring the existing
  create-time URL validation. The server-managed Micropub property deny-list is
  now extendable through the ``INDIEWEB_MICROPUB_SERVER_MANAGED_PROPERTIES``
  setting and applied consistently to create and update operations so hosts
  with reserved internal property names (for example ``_owner``) reject
  client-supplied values on both paths. The shared
  ``request_with_safe_redirects`` HTTP helper now accepts a ``max_bytes``
  keyword that delegates to the streaming variant so non-streaming callers get
  decompression-bomb protection too; WebSub subscribe and publish requests now
  pass a configurable ``INDIEWEB_WEBSUB_HUB_RESPONSE_MAX_BYTES`` cap and
  surface oversized hub responses as request failures.
* Hardened WebSub subscriber delivery handling. ``hub.secret`` and staged
  renewal secrets are now encrypted at rest with key material derived from
  Django's ``SECRET_KEY`` using the new ``cryptography`` runtime dependency;
  new secrets must be non-empty, at least 20 bytes, and at most 200 bytes.
  Subscriber delivery signatures now prefer the strongest supplied
  algorithm, reject legacy ``sha1`` unless
  ``INDIEWEB_WEBSUB_ALLOW_SHA1_SIGNATURES`` is enabled, can require signed
  deliveries through ``INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES``, and reject
  duplicate accepted bodies within the configurable replay window. Subscribe
  verification now clamps confirmed lease durations to configurable minimum and
  maximum bounds, and Django admin masks callback tokens/secrets while keeping
  delivery-attempt audit rows non-deletable.
* Tightened test and release metadata. The test settings now load
  ``SECRET_KEY`` from ``DJANGO_INDIEWEB_TEST_SECRET_KEY`` with an explicit
  insecure sentinel default, runtime dependency floors are declared for
  ``httpx``, ``beautifulsoup4``, and ``mf2py``, tox includes a
  ``py313-django52-migrations`` environment that overrides the default
  ``--no-migrations`` pytest option, and release docs include a ``just sbom``
  CycloneDX runtime-dependency export from the tracked ``uv.lock``.
* Hardened optional endpoint rate limiting. Client identities in rate-limit
  cache keys are now HMAC-digested with Django's ``SECRET_KEY`` instead of
  bare SHA-256, exceeded limits now fall back to the configured window for
  ``Retry-After`` when the reset marker has been evicted, and the documentation
  now calls out recommended production endpoint budgets, proxy-aware
  ``REMOTE_ADDR`` configuration, and best-effort cache primitive semantics.
* Clarified Micropub adapter ownership requirements. The
  ``MicropubContentHandler`` base class now documents that host handlers must
  enforce user ownership for create/update/delete/undelete/source/media
  operations and raises ``NotImplementedError`` in abstract operation bodies;
  the bundled in-memory handler is documented as an unsafe development/testing
  example that performs no ownership checks.
* Hardened Micropub media and create/action input validation. Media uploads are now sniffed with ``filetype`` before storage, declared content type and filename suffix must match the sniffed media type, stored object suffixes are derived from the validated type, and upload count plus aggregate byte limits reject oversized multipart requests with ``413 invalid_request``. URL-valued create properties now require absolute HTTP(S) URLs before ``create_entry()`` dispatch, ``mp-slug`` values are sanitized before handler dispatch, update/delete/undelete action URLs must stay on the request host, and ``application/json`` requests with parameters such as ``charset=utf-8`` are parsed as JSON.
* Stored IndieAuth/Micropub bearer tokens as HMAC digests at rest. ``Token.key`` now contains a ``hmac-sha256$`` digest keyed by Django's ``SECRET_KEY`` instead of the raw bearer value; the raw token is returned only when issued or reissued, existing plaintext rows are hashed by migration, token authentication and introspection compare derived hashes with constant-time comparison, and token/admin-management surfaces do not expose raw token values.
* Made Webmention status URLs non-enumerable and reduced public status metadata. New and existing ``Webmention`` rows have opaque ``status_token`` values, receive responses now publish ``/indieweb/webmention/<status-token>/`` ``Location`` URLs instead of primary-key URLs, guessed sequential IDs return ``404``, and public status JSON no longer includes stored Vouch URLs or Vouch verification timestamps.
* Hardened built-in CORS handling for wildcard origins. ``INDIEWEB_CORS_ALLOWED_ORIGINS = "*"`` combined with ``INDIEWEB_CORS_ALLOW_CREDENTIALS = True`` now logs a warning, keeps non-credential wildcard CORS, and never emits ``Access-Control-Allow-Credentials: true``. Origin-dependent allowlist decisions now include ``Vary: Origin`` for disallowed-origin responses and preflight rejections, and django-indieweb no longer overwrites an existing downstream ``Access-Control-Allow-Origin`` header.
* Added opt-in IndieAuth production hardening settings. ``client_id`` policy checks now receive normalized scheme/host and IDNA host values while storing the original submitted URL; ``INDIEWEB_ALLOWED_CLIENT_IDS`` provides an exact normalized allowlist; ``INDIEWEB_REQUIRE_PKCE`` requires PKCE before issuing authorization codes; ``INDIEWEB_REQUIRE_PKCE_S256`` requires ``S256`` and updates metadata to advertise only ``S256``; and ``INDIEWEB_BIND_ME_TO_USER`` can bind requested ``me`` values to ``user.indieweb_profile.url``. The consent screen now shows the configured local profile URL when available and warns on ``me`` mismatches.
* Hardened the IndieAuth token introspection endpoint so callers must authenticate with a strict ``Authorization: Bearer <caller-token>`` header before any active token metadata can be returned. Valid caller tokens can introspect themselves or other active tokens owned by the same Django user; cross-owner, unknown, deleted, expired, inactive-owner, and disallowed-client target tokens return the stable inactive response to authenticated callers. Missing or malformed caller credentials now return HTTP 401 with ``Cache-Control: no-store`` and ``WWW-Authenticate: Bearer``.
* Rejected client-submitted Micropub server-managed properties before handler dispatch. Create requests in JSON or form encoding that submit ``uid`` or ``author`` now return ``400 invalid_request`` before ``create_entry()`` is called, and ``action=update`` rejects ``replace``, ``add``, and both ``delete`` forms for those properties before ``update_entry()`` is called. Command properties such as ``mp-slug``, ``mp-channel``, ``mp-photo-alt``, ``mp-syndicate-to``, and ``post-status`` remain allowed and handler-owned.
* Hardened Webmention source-link verification so links inside non-rendered ``<template>`` and ``<noscript>`` content, links hidden inside HTML comments, and plain-text URL tokens no longer verify a source link. Rendered ``href`` links and microformats URL properties keep the existing conservative canonical target matching behavior.
* Added Salmention historical resend policy state and settings. ``WebmentionOutboundTarget`` now tracks ``last_attempted_at`` and ``consecutive_failures``; ``WebmentionSender.resend_salmentions()`` applies ``INDIEWEB_SALMENTION_RESEND_COOLDOWN_SECONDS``, ``INDIEWEB_SALMENTION_SUCCESS_CUTOFF_SECONDS``, and ``INDIEWEB_SALMENTION_MAX_CONSECUTIVE_FAILURES`` to historical-only targets while current targets remain eligible. No-endpoint outcomes count as failures, successes reset the failure counter, exhausted historical-only rows are deleted, and ``send_webmentions --salmention-resend`` plus dry-run output report policy skips and drops without automatic receive-side resends.
* Restored CSRF enforcement for IndieAuth browser consent ``action=approve`` and ``action=deny`` POSTs while preserving the legacy authorization-code verification POST as a CSRF-exempt protocol request. Unauthenticated approve/deny submissions are now rejected before any client ``redirect_uri`` redirect is built, closing the unauthenticated denial open redirect. The bundled consent screen now sends ``X-Frame-Options: DENY`` and ``Content-Security-Policy: frame-ancestors 'none'``; bundled consent and token-management inline styles moved into the package static stylesheet.
* Hardened IndieAuth token exchange ``redirect_uri`` binding. When an authorization code was issued with a ``redirect_uri``, the token request must include a matching ``redirect_uri``; omitted or mismatched values now return the existing HTTP 400 ``invalid_grant`` form response and consume the matched code. Matching now normalizes scheme and host case, IDNA host forms, default ports, percent-encoded triplet case, and root empty-path/``/`` equivalence while preserving non-default ports, non-root paths, and query semantics. Malformed submitted ``redirect_uri`` values remain pre-lookup ``invalid_grant`` failures and do not delete unrelated auth-code rows.
* Tightened IndieAuth bearer-token handling. Token-protected resource views and token introspection now accept only strict two-part ``Authorization: Bearer <token>`` headers with a case-insensitive bearer scheme; malformed headers such as extra token fragments no longer authenticate or introspect as active. Micropub and other token-protected resource views no longer accept a POST-body ``Authorization`` fallback, and HTTP 401 authentication failures now include ``Cache-Control: no-store`` and ``WWW-Authenticate: Bearer`` while preserving the existing ``authentication error`` body.
* Added uniqueness hardening for IndieAuth authorization-code and bearer-token secrets. ``Auth.key`` and ``Token.key`` are now unique at the model and database level, with migration cleanup that rotates accidental duplicate historical keys before adding the constraints. Duplicate-key lookups are defensively rejected as authentication, introspection, or token-exchange failures instead of raising server errors. Reissuing an existing token row now refreshes ``expires_at`` and rotates ``Token.key``, so the previous bearer key stops authenticating immediately while the new key is returned to the client.
* Made IndieAuth authorization codes single-use across token-exchange grant-validation failures. After a submitted code resolves to an ``Auth`` row, PKCE failures, ``redirect_uri`` mismatches, scope mismatches, and expired-code failures now consume the code before returning the existing ``invalid_grant`` response, preventing replay attempts with corrected parameters. Unknown codes and pre-lookup malformed requests continue to leave unrelated authorization-code rows untouched. Token endpoint logs now redact authorization codes instead of writing full code values.
* Added shared SSRF-safe outbound HTTP handling for Webmention source/Vouch fetches, Webmention sender discovery/content/delivery, and WebSub subscribe/publish requests. Outbound protocol URLs now allow only absolute HTTP(S), reject userinfo and blocked IP destinations including loopback, private, link-local, reserved, multicast, and metadata-service addresses after DNS resolution, and re-check redirect targets. The Webmention receive endpoint now validates ``source``, ``target``, and ``vouch`` with HTTP(S)-only URL validators. Synchronous Webmention source/Vouch processing now enforces ``INDIEWEB_WEBMENTION_FETCH_MAX_BYTES`` during streamed decoded response reads plus nested response depth/candidate/search caps, and the WebSub callback rejects oversized ``Content-Length`` before reading the request body when possible. Documentation now recommends queued Webmention processing, queued WebSub delivery hooks, tight deployment body limits, and operator-controlled WebSub hub configuration.
* Hardened bundled Webmention display against stored XSS. Incoming processor-owned ``Webmention.content_html`` and ``WebmentionNestedResponse.content_html`` are now sanitized with a strict allowlist before persistence, unsafe remote author URL/photo fields are blanked unless they are absolute HTTP(S) URLs, and ``show_webmentions`` applies the same cleanup before rendering existing stored rows. Links and citation URLs inside sanitized remote HTML are kept only when they are absolute HTTP(S) URLs. Bundled Webmention author/source links now use ``rel="nofollow noopener ugc"`` with ``referrerpolicy="no-referrer"``, the h-card organization URL link gets the same outbound-link attributes, and ``webmention_endpoint_link`` now uses ``format_html`` for escaping interpolated endpoint URLs.
* Added ``AGENT_LEARNINGS.md`` as a small curated agent guidance file for repeated repo-specific workflow lessons, linked it from ``AGENTS.md``, and kept the existing privacy boundary that raw transcripts, prompts, command output, generated summaries, and local session material stay out of tracked files.
* Documented Webmention.io import/display guidance as an optional host-owned integration. The Webmention docs now explain that a host may advertise Webmention.io's external endpoint on selected pages or fetch Webmention.io JF2 for host-owned display/import alongside verified django-indieweb ``Webmention`` rows, while django-indieweb's built-in receive/send endpoints, processor verification, spam/Vouch checks, source snapshots, nested responses, status endpoint, sender workflows, models, settings, and templates remain unchanged. The guidance covers conservative ``wm-property`` mapping to the built-in ``mention``/``like``/``reply``/``repost`` vocabulary, calls out lossy or host-owned handling for ``bookmark-of`` and ``rsvp``, and requires host sanitization before rendering or storing external ``content.html`` in safe-rendered fields.
* Documented the Microsub and reader-side protocol boundary. django-indieweb preserves reader-oriented IndieAuth extension scopes such as ``read``, ``follow``, ``mute``, ``block``, and ``channels`` as opaque scope strings when requested, but the bundled resource servers attach no built-in behavior to them. The built-in IndieAuth metadata intentionally continues to advertise only ``create``, ``update``, ``delete``, ``undelete``, and ``media``; django-indieweb still does not add Microsub channels, feed fetching, following, muting, blocking, reader timelines, reader UI, a Microsub endpoint, or a Microsub setting.
* Added tested host-owned WebSub workflow examples in ``examples/websub_workflows.py``. The copy-and-adapt examples show how a Django project can wire ``INDIEWEB_WEBSUB_DELIVERY_HOOK`` to a queue-like adapter, process queued deliveries through host-owned feed parsing and persistence code, explicitly renew expiring leases with ``get_websub_renewal_candidates()`` and ``request_websub_subscription()``, and prune metadata-only ``WebSubDeliveryAttempt`` rows according to a host retention policy. This is documentation/example guidance only: django-indieweb still does not add a WebSub hub, automatic discovery, background scheduling, hidden renewal calls, queue dependency, feed parser, feed-entry model, retry policy, or automatic pruning.
* Added tested static-site and storage-boundary Micropub handler examples in ``examples/static_site_micropub.py``. The copy-and-adapt examples show how host projects can map Micropub properties to Markdown paths, public URLs, and front matter for Jekyll-, Hugo-, or Eleventy-style workflows; write files below an explicit local root while rejecting target collisions; write through an explicit Django storage; delegate Git-backed repository writes to a host adapter; and delegate media source/delete hooks to a host-owned media index. This is documentation/example guidance only: django-indieweb still does not add a content-store plugin architecture, static-site generator presets, repository credentials, Git commits or pushes, build/deploy automation, media indexing, media deletion policy, or endpoint behavior changes.
* Added conservative Micropub media source and delete extension points on ``/indieweb/media/``. ``GET /indieweb/media/?q=source`` now requires the exact ``media`` scope and can dispatch to optional ``MicropubContentHandler.list_media(user, limit=..., offset=..., filter=...)`` or ``get_media(url, user)`` hooks. List responses are JSON shaped as ``{"items": [{"properties": ...}], "paging": {"limit": ..., "offset": ..., "total": ...}}`` with ``total`` included only when known; by-URL responses are ``{"properties": ...}``, with a ``url`` property added from the media item URL when the hook omits one. ``POST /indieweb/media/`` with ``action=delete`` now dispatches to optional ``delete_media(url, user)`` and returns ``204 No Content`` on success. Missing hooks return ``501 not_implemented``; empty, unknown, or hook-rejected URLs and malformed media list ``limit``/``offset`` values return ``400 invalid_request``; unexpected hook exceptions return ``500`` and are logged. Existing direct multipart ``file`` uploads still return ``201 Created`` with ``Location`` and keep the existing Django-storage validation policy. django-indieweb still does not maintain a media index, infer storage paths from arbitrary URLs, delete ``default_storage`` objects without a host hook, add a media UI, transform media, or add a non-Django storage abstraction.
* Preserved common Micropub command properties for form-encoded creates. ``POST /indieweb/micropub/`` now forwards submitted ``mp-slug``, ``mp-channel``, ``mp-photo-alt``, ``mp-syndicate-to``, and ``post-status`` values to ``MicropubContentHandler.create_entry()`` as normalized property arrays; ``mp-channel[]``, ``mp-photo-alt[]``, and ``mp-syndicate-to[]`` array notation preserves all submitted values. JSON Microformats2 creates remain pass-through for the submitted ``properties`` object. django-indieweb still does not generate slugs, choose channels, attach alt text to stored files, cross-post, enqueue syndication, or implement draft storage. The extension ``draft`` scope remains host-owned and is not advertised in built-in IndieAuth metadata; ``post-status=draft`` create requests still require ``create`` or the legacy ``post`` scope, and update requests still require ``update``.
* Routed Micropub ``GET /indieweb/micropub/?q=syndicate-to`` through the configured ``MicropubContentHandler.get_config()`` value. The direct query now returns the handler's ``syndicate-to`` list under the ``syndicate-to`` JSON key instead of always returning an empty list; missing or non-list custom handler values return an empty list rather than raising. The bundled handler still advertises no targets by default, ``q=config`` preserves custom handler target data, and the query remains token-required only with no operation-scope gate. This change only advertises host-configured targets; django-indieweb still does not cross-post, call webhooks, choose targets, store syndicator credentials, or run syndicator plugins.
* Advertised built-in Micropub ``audio`` and ``video`` post types from the default handler config and direct ``q=post-types`` responses. The advertised shapes are ``audio``/``video`` plus optional ``content`` and ``category`` properties, matching the existing form parser behavior that forwards URL-valued ``audio`` and ``video`` fields as normalized arrays. Custom handler ``post-types`` config remains authoritative, and this change does not add transcoding, players, storage models, media processing, media source/delete behavior, or persistence semantics.
* Added direct Micropub configuration subqueries for ``q=media-endpoint`` and ``q=post-types``. ``GET /indieweb/micropub/?q=media-endpoint`` returns the same effective media endpoint value as ``q=config``, preserving a truthy custom handler value and otherwise injecting the bundled media endpoint as an absolute URL. ``GET /indieweb/micropub/?q=post-types`` returns the handler's supported vocabulary under ``post-types``; missing or non-list handler config values return an empty list. ``q=post-types`` supports ``post-type`` filtering plus the existing config-list ``filter``, ``limit``, and ``offset`` policy, with malformed ``limit``/``offset`` returning ``400 invalid_request``. ``q=config`` now advertises ``media-endpoint`` and ``post-types`` in its ``q`` array. These direct subqueries are token-required only and do not infer storage semantics from advertised post types. Standalone ``q=properties`` and unrelated extension query names such as ``q=contacts`` remain unsupported.
* Added Micropub ``GET /indieweb/micropub/?q=source`` list mode for editable/source post enumeration when no ``url`` parameter is supplied. The new optional ``MicropubContentHandler.list_entries(user, limit=..., offset=..., filter=...)`` hook returns a ``MicropubEntryList`` page; existing custom handlers are not forced to implement it because the default hook returns ``None``, which maps to ``501 not_implemented``. List responses are JSON shaped as ``{"items": [...], "paging": {"limit": ..., "offset": ..., "total": ...}}`` with Microformats-style item objects (``type`` and ``properties``), and list items include a ``url`` property derived from ``MicropubEntry.url`` when the handler properties omit one. ``limit``/``offset`` must be non-negative integers; omitted ``limit`` defaults to ``20`` and omitted ``offset`` defaults to ``0``; malformed values return ``400 invalid_request``. The bundled in-memory handler supports list mode, accurate ``total``, and case-insensitive substring ``filter`` matching against a stable JSON serialization of each source item. Existing ``GET ?q=source&url=...`` and ``properties[]`` behavior remains unchanged, including the ``update`` scope gate, ``400 invalid_request`` for empty or unknown submitted URLs, and ``500`` for unexpected handler exceptions. Cursor ``after``/``before`` paging, bundled post storage/search, media source/delete hooks, command properties, and syndication routing remain out of scope.
* Added Micropub ``q=category`` and ``q=channel`` queries plus query discovery in ``q=config``. ``GET /indieweb/micropub/?q=category`` returns the configured handler's ``categories`` config list under the JSON key ``categories``; ``GET /indieweb/micropub/?q=channel`` returns the configured handler's ``channels`` list under ``channels``. Both accept optional ``filter`` (case-insensitive substring against string items or a stable JSON serialization of dict items), ``limit``, and ``offset`` (non-negative integers; malformed values return ``400 invalid_request``); the order of operations is filter → offset → limit. Missing ``categories`` or ``channels`` keys in a custom handler config return an empty list instead of raising. ``q=config`` now advertises the supported query names through a ``q`` array and includes default empty ``categories`` and ``channels`` keys from the bundled handler. The new queries are token-required only (no specific operation scope), matching existing ``q=config`` and ``q=syndicate-to`` behavior. ``mp-channel`` command property handling and channel-aware publication routing remain out of scope and are owned by separate backlog items.
* Removed Beads and Beadsflow project-tracking files and instructions
* Added ``BACKLOG.md`` and ``DONE.md`` as the repository-local work tracking workflow
* Linked the backlog workflow from the project documentation
* Clarified that completed backlog items must keep docs and changelog entries aligned with implementation changes
* Switched hook execution from ``pre-commit`` to ``prek`` and updated hook revisions for Python 3.14 compatibility
* Added a dedicated backlog page to the documentation navigation
* Raised dependency floors and refreshed ``uv.lock`` to resolve open Dependabot alerts for Django, pytest, requests, urllib3, sqlparse, Pygments, filelock, and virtualenv
* Added ``Token.expires_at`` plus the ``INDIEWEB_TOKEN_EXPIRES_IN`` setting (default 86400 seconds); ``TokenView`` now persists the expiration and reports the live remaining lifetime in ``expires_in``
* ``TokenAuthMixin`` now rejects expired access tokens with HTTP 401; tokens issued before this change have ``expires_at=NULL`` and remain valid until reissued
* Fixed the IndieAuth auth-code timeout calculation to use ``timedelta.total_seconds()`` so codes older than one day are now correctly rejected
* Validated IndieAuth ``redirect_uri`` values: the authorization endpoint rejects malformed values (invalid URL, any ``#`` delimiter, userinfo, or a non-``http``/``https`` scheme) with HTTP 400 before issuing a code, and the token endpoint rejects malformed submissions with ``invalid_grant``; the comparison between the submitted and stored values now lowercases scheme and host while preserving path and query verbatim
* Fixed the consent approval and denial redirects to merge ``code``/``state``/``me`` (or ``error``/``state``) into an existing ``redirect_uri`` query string instead of breaking it with a duplicate ``?`` separator
* Added PKCE (RFC 7636) support to the IndieAuth authorization and token endpoints: the authorization endpoint accepts ``code_challenge`` and ``code_challenge_method`` (``S256`` and ``plain``, defaulting to ``plain`` when only the challenge is sent) and stores them on the ``Auth`` row; the token endpoint requires a matching ``code_verifier`` whenever a challenge was stored, comparing in constant time. Auth codes issued before this change continue to be redeemable without a ``code_verifier``, preserving backwards compatibility for legacy clients. Migration ``0011_auth_code_challenge`` adds the new nullable ``Auth.code_challenge`` and ``Auth.code_challenge_method`` columns.
* Added a public IndieAuth authorization-server metadata endpoint at ``/indieweb/auth/metadata/``. The JSON response advertises the issuer, authorization endpoint, token endpoint, ``code`` response type, ``authorization_code`` grant type, current PKCE challenge methods (``plain`` and ``S256``), built-in Micropub scopes (``create``, ``update``, ``delete``, ``undelete``, and ``media``), and service documentation. Host projects can route the reusable view at ``/.well-known/oauth-authorization-server`` for OAuth-compatible discovery. The metadata intentionally does not advertise protocol revocation, user-info, or refresh tokens until those capabilities are implemented.
* Tightened IndieAuth/OAuth wire compatibility while preserving legacy clients. Authorization requests now accept ``response_type=code`` and reject other present ``response_type`` values, while omitted ``response_type`` remains accepted. Token requests now accept ``grant_type=authorization_code`` and reject other present ``grant_type`` values, while omitted ``grant_type`` remains accepted. Successful authorization redirects include ``iss`` derived from the bundled metadata issuer, denial redirects omit ``iss`` per the IndieAuth error-response guidance, access-token responses include ``token_type=Bearer``, and profile/token success responses return JSON only when the client explicitly prefers ``Accept: application/json``. The public metadata endpoint now participates in configured read-only CORS for ``GET`` without adding rate limiting.
* Added the IndieAuth token introspection endpoint at ``/indieweb/token/introspect/``. ``POST`` requests can submit a form ``token`` value or use the bearer token from ``Authorization`` as the token being checked. Active JSON responses include ``active``, ``me``, ``client_id``, ``scope``, ``iat``, and ``exp`` when the token has an expiration; inactive responses are always ``{"active": false}`` for missing, unknown, deleted/revoked, expired, inactive-owner, and disallowed-client tokens. Server metadata now advertises ``introspection_endpoint``. The endpoint is CSRF-exempt, participates in configured CORS for ``POST``, and has an optional ``token_introspection`` rate-limit key. It does not mutate token rows and does not add protocol token revocation, refresh tokens, or user-info/profile claims.
* Added ``client_id`` access control. The authorization endpoint (GET, consent POST, code-verification POST) and the token endpoint now reject malformed ``client_id`` values (invalid URL, any ``#`` delimiter, userinfo, or a non-``http``/``https`` scheme) with HTTP 400 *before* creating any state. A new optional ``INDIEWEB_CLIENT_ID_VALIDATOR`` setting (dotted path to a ``(client_id: str) -> bool`` callable) runs on top of structural validation at all four authorization/token paths and again on the Micropub resource-server path, so revoking a client takes effect immediately for previously-issued tokens. A misconfigured validator fails closed: the authorization paths return plain-text HTTP 400 (``invalid client_id`` for structural failures, ``invalid_client`` for validator failures), the token endpoint returns HTTP 400 ``invalid_request`` with content type ``application/x-www-form-urlencoded``, and the Micropub resource server returns HTTP 403 ``invalid_client``. Stored ``client_id`` values are not re-validated structurally on use (matching the ``redirect_uri`` rule); the configured validator IS re-applied on use. Default behavior (setting unset) is unchanged: every structurally-valid ``client_id`` is permitted.
* Enforced per-operation scopes on the Micropub endpoint. ``POST`` entry create now requires ``create`` (the legacy alias ``post`` is still accepted); ``POST action=update`` requires ``update``; ``POST action=delete`` requires ``delete``; ``POST action=undelete`` requires ``undelete``; ``GET ?q=source`` requires ``update``. ``GET ?q=config``, ``GET ?q=syndicate-to``, and ``GET`` with no ``q`` only require an authenticated token (no scope gate). Stored ``scope`` is split on whitespace and compared as an exact token, so values like ``createXYZ`` no longer satisfy ``create`` (previously a substring match). Scope failures still return HTTP 403 with the plain-text body ``authorization error``. Closes the previously over-permissive scope check that allowed a ``create``-only token to reach update/delete/undelete code paths.
* Normalized IndieAuth scope strings before consent display and auth-code storage by splitting on whitespace, removing duplicate tokens while preserving first-seen order, and joining with single spaces. Unknown scopes are intentionally preserved. The token endpoint now issues the stored auth-code scope and rejects any submitted ``scope`` that normalizes differently with HTTP 400 ``invalid_grant`` and content type ``application/x-www-form-urlencoded``, without creating or reissuing a token.
* Implemented the Micropub source query on ``GET /indieweb/micropub/?q=source&url=...``. The query now uses the configured ``MicropubContentHandler.get_entry(url, user)`` method after the existing ``update`` scope check, returns full source content as ``{"type": [...], "properties": {...}}``, and supports the W3C ``properties[]=NAME`` filter form by returning only existing requested properties as ``{"properties": {...}}``. Missing or unknown ``url`` values return ``400 invalid_request``; unexpected handler exceptions return ``500`` and are logged via ``logger.exception``. This completes the source-query gap left by the partial editing-support slice.
* Implemented the Micropub ``update``, ``delete``, and ``undelete`` actions on ``POST /indieweb/micropub/`` by dispatching into the configured ``MicropubContentHandler``. ``POST action=update`` is JSON-only (per Micropub §3.7); the body must include at least one of ``replace``, ``add``, or ``delete`` and values inside each operation must be arrays per §3.4 — empty bodies, scalar operation values, and non-conformant ``delete`` shapes are rejected with ``400 invalid_request`` rather than papered over by the handler. ``POST action=delete`` and ``POST action=undelete`` accept either form-encoded or JSON bodies, both with a required ``url``. Successful updates and undeletes return ``204 No Content``, or ``201 Created`` with a ``Location`` header when the configured handler relocates the entry; successful deletes return ``204 No Content`` (delete cannot relocate because the handler interface returns ``None`` on delete). Unknown URLs (the handler raises ``ValueError``), missing ``url``, malformed JSON, non-object JSON bodies, and form-encoded ``action=update`` requests return ``400 invalid_request``; unexpected handler exceptions return ``500`` (logged via ``logger.exception``). Per-operation scope enforcement and the existing ``403 authorization error`` and ``403 invalid_client`` shapes are unchanged.
* Added a dedicated Micropub media endpoint at ``/indieweb/media/``. It accepts the same bearer tokens as the Micropub endpoint, requires the exact ``media`` scope, stores multipart ``file`` uploads through Django's configured storage backend under unguessable ``indieweb/media/`` keys, and returns ``201 Created`` with an absolute ``Location`` header. Uploads larger than ``INDIEWEB_MEDIA_MAX_UPLOAD_BYTES`` (default 10 MiB) return ``413 invalid_request``; uploads whose content type is not in ``INDIEWEB_MEDIA_ALLOWED_TYPES`` (default common image/audio/video MIME types) return ``415 invalid_request``. ``GET /indieweb/micropub/?q=config`` now advertises the media endpoint as an absolute ``media-endpoint`` URL unless a custom content handler already provides one.
* Multipart Micropub create requests sent to ``POST /indieweb/micropub/`` now process uploaded ``photo`` file parts instead of ignoring them. Uploaded photos use the same storage name generation, size limit, content-type allowlist, storage backend, and absolute URL building as the direct media endpoint; all submitted photos are validated before any are stored, and already-saved files are cleaned up if a later save in the same request fails. The resulting media URLs are appended to the created entry's ``photo`` property alongside any URL-valued ``photo`` form fields. This remains a create operation, so ``create`` or the legacy ``post`` scope is required; direct uploads to ``/indieweb/media/`` still require ``media``.
* Hardened the Micropub endpoint against malformed JSON bodies. A ``POST`` with ``Content-Type: application/json`` whose body fails to parse (including invalid UTF-8 bytes such as ``b"\xff"`` that surface as ``UnicodeDecodeError`` rather than ``json.JSONDecodeError``), or whose body parses to anything other than a JSON object, is now rejected with ``400 invalid_request`` *before* scope or action dispatch. Previously such requests fell through to the create path and could silently create an empty entry when the token had ``create`` scope, or escape as a ``500`` for invalid UTF-8.
* Webmention receive-side target verification now parses source-page ``href`` attributes and compares common canonical URL variants instead of relying on raw ``href`` string matching. Fragments are ignored; scheme/host case, a leading ``www.``, one non-root trailing slash, and query-parameter ordering are normalized for matching. Microformats2 target matching uses the same policy for reply/like/repost classification while stored ``Webmention.source_url`` and ``Webmention.target_url`` remain the submitted values.
* Webmention receive-side reprocessing now clears stale verification timestamps when a source can no longer be verified. Existing Webmentions whose source returns ``410 Gone`` or whose HTML no longer links to the submitted target are marked ``failed`` with ``verified_at=NULL`` while preserving submitted URLs and previously parsed author/content fields. Other processor failure paths also clear ``verified_at`` when they mark a row ``failed``, and spam reclassification clears ``verified_at`` when a row is marked ``spam``. A later valid source can be reprocessed back to ``verified`` with a fresh timestamp.
* Webmention receive and send HTTP requests now follow redirects explicitly with a limit of 5 redirects and only continue to ``http``/``https`` URLs. Receive-side source fetches parse the final response URL as the microformats2 base while preserving submitted source/target URLs; send-side endpoint discovery resolves relative endpoints against the final target page URL; source-content fetches follow the same policy; endpoint ``POST`` delivery preserves the Webmention form payload across followed redirects.
* Added optional asynchronous Webmention receiving through ``INDIEWEB_WEBMENTION_ENQUEUE``. When configured, ``POST /indieweb/webmention/`` validates the request, creates or reuses the ``Webmention`` row, calls the configured ``(webmention_id: int) -> None`` enqueue hook, and returns ``202 Accepted`` with a status ``Location`` without fetching the source URL in the request path. The new ``indieweb.processors.process_queued_webmention(webmention_id)`` helper lets queue workers run the existing processor. When the setting is unset, the existing synchronous ``201 Created`` behavior remains available.
* Added conservative Webmention Vouch support. The receive endpoint accepts an optional ``vouch`` HTTP(S) URL, rejects malformed values before processing or enqueueing, stores Vouch metadata on ``Webmention.vouch_url``, and includes it in the status response. Queue mode still does not fetch source or voucher URLs in the request path. Processor-owned Vouch verification can be enabled with ``INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS`` and required with ``INDIEWEB_WEBMENTION_VOUCH_REQUIRED``; failed Vouch checks mark the row ``failed`` without clearing parsed fields. Outgoing Webmentions can include Vouch with ``WebmentionSender.send_webmention(..., vouch=...)`` or ``send_webmentions --vouch``.
* Added ``INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY`` for receiver-side Vouch trust decisions. The callable is evaluated by ``WebmentionProcessor`` before voucher fetches and again after allowed redirects; import failures, non-callable values, and policy exceptions fail closed. Existing ``INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS`` behavior remains the default policy when no callable is configured. Required Vouch mode now fails closed when neither a policy nor trusted domains are configured instead of implicitly trusting only the local site domain.
* Documented the Salmention support status. Ordinary duplicate Webmention reprocessing remains supported, and outbound Salmention sending depends on outbound target tracking plus an explicit resend workflow.
* Documented the receive-side Salmention persistence design: submitted ``Webmention`` rows stay as top-level source/target notifications, related source snapshots store fetched HTML and normalized parsed state, related child rows store stable nested response identities, child displayability is gated on the parent remaining verified, duplicate inline children are suppressed when a direct top-level Webmention represents the same response, and fetch/parse/compare work stays in processor or worker paths rather than the queued receive endpoint.
* Added ``WebmentionSourceSnapshot`` persistence for verified incoming Webmentions. ``WebmentionProcessor`` now stores or updates the related one-to-one snapshot after the source fetch, target-link verification, microformats2 parsing, Vouch checks, and spam checks have passed. Snapshots include the raw source HTML, final fetched source URL, SHA-256 digest, fetch timestamp, normalized parent ``h-entry`` snapshot, and stable nested response identity set. Snapshot storage failures are logged without demoting the parent Webmention after otherwise successful verification. Queued receive requests still do not fetch, parse, verify, spam-check, or write snapshots; worker processing through ``process_queued_webmention()`` performs those writes.
* Added ``WebmentionNestedResponse`` persistence for stable nested ``h-entry`` responses discovered inside verified parent Webmention sources. Duplicate Webmention reprocessing compares current nested identities with the previous source snapshot before overwriting it, creates or updates child rows without duplicating the parent or child record, and marks disappeared children as ``missing`` without deleting historical fields. Failed fetches, non-HTML sources, missing target links, Vouch failures, and spam classifications do not create or update child rows from failed source content. Queued receive requests still do not fetch, parse, compare snapshots, or write child rows; worker processing through ``process_queued_webmention()`` performs those writes. Outbound Salmention sending was not changed by this receive-side storage slice.
* Exposed verified ``WebmentionNestedResponse`` child rows through ``show_webmentions``. Verified children are prefetched for verified top-level Webmentions and rendered inline under parent replies, ordered by child ``published`` with ``first_seen_at`` fallback. Inline children are suppressed when a verified direct top-level Webmention to the same target has the same child ``identity`` or ``response_url``, and duplicate child identities discovered under multiple displayed parents render only under the first parent in top-level ordering. ``webmention_count`` remains top-level-only.
* Documented the outbound Salmention target-tracking and resend-workflow design. The design called for a django-indieweb-managed outbound target-history model keyed by original ``source_url`` and ``target_url``, ordinary outbound-send recording, and an explicit ``resend_salmentions``/``send_webmentions --salmention-resend`` workflow that sends to the union of current links and prior targets for that source after the host application has incorporated a downstream response into the rendered permalink. No outbound sending code, model, command flag, or Salmention setting was added in that design slice.
* Added the ``WebmentionOutboundTarget`` model and migration as the outbound Webmention target-history storage foundation for Salmention resends. Rows store exact HTTP(S) ``source_url``/``target_url`` pairs with endpoint diagnostics, first/latest send timestamps, latest result fields, latest Vouch URL, and diagnostic current-content last-seen tracking.
* Ordinary ``WebmentionSender.send_webmentions()`` calls now record and refresh ``WebmentionOutboundTarget`` history by default for delivered current external targets while preserving current-link-only delivery and the existing per-target result shape. Callers can pass ``record_history=False`` to keep the earlier no-write behavior. Added ``WebmentionSender.resend_salmentions()`` to resend to the union of current external links and exact-source historical targets, rediscover endpoints, label results with ``provenance`` (``current``, ``history``, or ``both``), pass Vouch through, and refresh history for attempted targets.
* Added ``send_webmentions --salmention-resend`` as an explicit management-command workflow for outbound Salmention resends. Default command behavior remains the ordinary current-link-only send. Resend mode calls ``WebmentionSender.resend_salmentions()``, supports ``--content`` including ``--content -``, passes ``--vouch`` through, includes provenance labels in output, and keeps no-endpoint union targets visible as failures. ``--dry-run --salmention-resend`` previews the exact-source union of current and historical targets with endpoint rediscovery and provenance labels without sending or writing outbound target history.
* Webmention receive-side author extraction now completes the local/same-page authorship fallback chain. Explicit ``h-entry`` author data remains highest priority; URL-valued authors still resolve to matching same-page ``h-card`` items or fall back to URL-as-name when unmatched. Entries without explicit authors can now use ``rel=author`` links that point to an ``h-card`` already present in the fetched document, including same-page fragment references, and then a single unambiguous page-level ``h-card`` fallback. Relative author and photo URLs resolve against the final fetched source URL after redirects. Remote author-page fetching remains unsupported.
* Webmention receive-side author ``h-card`` lookup now uses the same conservative canonical URL matching policy already used for target verification. Explicit URL-valued ``p-author`` references and local ``rel=author`` links can now match same-page ``h-card`` ``u-url`` values across supported variants such as scheme/host case, a leading ``www.``, one non-root trailing slash, ignored fragments, and query-parameter ordering. Unmatched explicit author URLs still fall back to URL-as-name, and no remote author fetching was added.
* Audited and corrected current documentation for development commands, ``prek`` hook usage, ``just docs``/Sphinx validation, backlog workflow guidance, Micropub editing/source-query behavior, IndieAuth token fields, Webmention author h-card matching, and h-card support status.
* Added a browser token management UI at ``/indieweb/tokens/`` where authenticated users can view metadata for their own IndieAuth/Micropub access tokens and revoke an owned token through a CSRF-protected ``POST``. Revocation deletes the ``Token`` row, immediately invalidating the bearer credential for Micropub and other token-protected requests. The UI does not display full bearer token keys and does not change the token endpoint wire protocol.
* Tightened wording around still-unsupported media endpoint/uploads, WebSub, rate limiting, and CORS work so current docs match shipped IndieAuth, Micropub, Webmention, and token-management behavior; no functional change.
* Added optional cache-backed endpoint rate limiting through ``INDIEWEB_RATE_LIMITS``. The setting is disabled by default and supports per-endpoint ``limit``/``window`` entries for ``auth``, ``token``, ``micropub``, ``media``, ``webmention``, and ``webmention_status``. Counters are scoped by endpoint key, HTTP method, and ``REMOTE_ADDR``; exceeded limits return HTTP ``429`` with ``Retry-After`` when the window reset can be computed.
* Added optional built-in CORS support for public protocol endpoints through ``INDIEWEB_CORS_ALLOWED_ORIGINS`` and related settings. CORS remains disabled by default, supports explicit origin allowlists or an explicit ``"*"`` allow-all policy, adds headers only for allowed origins, and handles configured preflight ``OPTIONS`` requests before rate limiting, token authentication, Micropub handler work, media storage, Webmention processing, or async enqueue hooks. Browser token-management UI views remain excluded.
* Standardized developer test guidance around pytest function/fixture style for new tests, documented that pytest parametrization should not be mixed into legacy ``django.test.TestCase`` classes, and converted the h-card/profile-admin legacy tests to pytest style.
* Aligned Ruff's configured target version with the package's Python 3.10 minimum support floor so lint and formatting rewrites stay compatible with all supported Python versions.
* Added a local coverage gate to the default pytest workflow. ``uv run pytest`` now measures the ``indieweb`` package and enforces a conservative ``fail_under = 88`` threshold based on the current 89% baseline.
* Added a GitHub Actions CI workflow for pull requests and pushes to ``develop``. CI runs the existing tox Python matrix, mypy, Ruff lint and formatting checks, configured prek hooks, and Sphinx documentation with warnings treated as errors.
* Pinned Django support to the current stable supported range, ``Django>=5.2.13,<6.1``, and expanded tox/GitHub Actions to exercise Django 5.2 LTS on Python 3.10-3.14 plus Django 6.0 on Python 3.12-3.14.
* Removed ``django-model-utils`` from runtime dependencies after replacing the historical initial migration timestamp fields with Django-native fields, so fresh installs no longer need ``model_utils`` to apply migrations.
* Added ``just loc`` and the ``uv run count-lines-of-code`` console script for repository line-count summaries by language, area, and directory, with a ``cloc`` fast path and package-local Python fallback.
* Reserved gitignored local paths for private agent session summaries and documented that raw transcripts, prompts, and command output must stay out of tracked files by default.
* Added publisher-side WebSub support. Host applications can configure ``INDIEWEB_WEBSUB_HUBS``, render WebSub ``rel=hub``/``rel=self`` discovery with ``websub_link_tags`` or HTTP ``Link`` header helpers, and explicitly notify hubs with ``notify_hubs()`` or ``python manage.py notify_websub TOPIC``. Hub notifications use the WebSub publisher form ``hub.mode=publish`` and ``hub.url=<topic>`` and return per-hub results instead of raising on network or non-2xx hub failures. No WebSub hub service, subscriber callback endpoint, model, migration, or automatic network call was added.
* Expanded the default Micropub ``q=config`` ``post-types`` advertisement to include note, article, photo, reply, bookmark, like, and repost shapes. Form-encoded create parsing now forwards ``bookmark-of``, ``like-of``, ``repost-of``, URL-valued ``audio``, and URL-valued ``video`` properties to the configured handler while preserving existing JSON create, source query, update/delete/undelete, media endpoint, and multipart ``photo`` upload behavior.
* Refreshed the product backlog after the WebSub publisher and common Micropub post-type slices: future protocol work is now scoped to WebSub subscriber callback support and Micropub event/RSVP post types, and documentation no longer describes the completed common post-type work as future work.
* Added minimal WebSub subscriber callback support. ``WebSubSubscription`` stores host-level hub/topic state, unguessable callback tokens, pending verification mode, lease metadata, optional ``hub.secret`` values, latest request diagnostics, and latest delivery metadata. ``request_websub_subscription()`` sends explicit subscribe/unsubscribe requests to hubs, and ``/indieweb/websub/<token>/`` handles verification ``GET`` requests and content-distribution ``POST`` requests. Signed deliveries are validated with ``X-Hub-Signature-256`` or ``X-Hub-Signature`` when a secret is stored; accepted deliveries record metadata and optionally call ``INDIEWEB_WEBSUB_DELIVERY_HOOK`` without parsing or storing feed content. No WebSub hub service, automatic discovery, or background lease renewal was added.
* Added WebSub subscriber configuration for ``INDIEWEB_WEBSUB_CALLBACK_BASE_URL``, ``INDIEWEB_WEBSUB_DELIVERY_MAX_BYTES``, ``INDIEWEB_WEBSUB_DELIVERY_ALLOWED_TYPES``, and ``INDIEWEB_WEBSUB_DELIVERY_HOOK``. The subscriber callback is CSRF-exempt, excluded from built-in CORS handling, and covered by the optional ``websub_callback`` rate-limit key.
* Hardened WebSub subscriber operations. ``hub.mode=denied`` callback GET requests now validate the tokenized subscription and exact topic, record bounded denial diagnostics, clear pending state, mark denied initial subscribes as ``denied``, and keep existing active subscriptions active when a renewal or unsubscribe request is denied. Added metadata-only ``WebSubDeliveryAttempt`` history rows for recorded delivery attempts, plus read-only ``get_websub_expired_subscriptions()``, ``get_websub_renewal_candidates()``, ``summarize_websub_leases()``, and ``python manage.py websub_subscriptions`` lease-inspection workflows. These additions do not add a hub service, automatic discovery, background jobs, hidden renewal calls, feed parsing, or raw delivery body persistence.
* Expanded Micropub event/RSVP support. The default ``q=config`` ``post-types`` list now advertises ``event`` and ``rsvp`` shapes, and form-encoded creates forward ``summary``, ``description``, ``start``, ``end``, ``url``, and ``rsvp`` properties as normalized arrays alongside the existing common properties. JSON create pass-through remains unchanged, including ``type: ["h-event"]`` payloads and nested Microformats2 objects.

0.5.3 (2025-10-28)
------------------
* Fixed webmention author extraction when author is referenced as a URL string
* Implemented partial microformats2 authorship algorithm to resolve author URLs to h-cards on the same page
* Added recursive search for h-cards and h-entries in nested structures (e.g., h-feeds)
* Fixed regression where missing h-cards would result in empty author names
* Author URL now used as fallback name when matching h-card cannot be found
* Previously displayed the author URL as the name when parsing feed.city-style webmentions
* Now correctly extracts author name and photo from matching h-card on the page
* Note: Does not yet fetch remote author URLs or follow rel=author links (full authorship algorithm)
* Added a `justfile` with recipes for dependency install, testing, and type checking

0.5.2 (2025-07-27)
------------------
* Fixed JSON copy/paste issue in Django admin for h_card field
* Changed admin form to use CharField with custom widget instead of JSONField to prevent double-encoding
* Added proper JSON formatting and validation in Profile admin interface
* Added tests for admin JSON widget functionality

0.5.1 (2025-07-26)
------------------
* Fixed h-card template to properly handle photo data from mf2py parser
* Added automatic property name normalization (converts hyphens to underscores for Django template compatibility)
* Added webmention integration to use local Profile data when author is a local user
* Added automatic synchronization of Profile fields (name, photo_url, url) with h_card JSON data
* Added URL and email validation for h_card data to prevent invalid data storage
* Enhanced h_card normalization to properly handle nested objects
* Added h_card structure validation in admin interface
* Fixed all mypy type checking issues
* Updated tests for consistency with implementation

0.5.0 (2025-07-25)
------------------
* Added h-card support with Profile model for user profile data
* Added flexible JSON storage for all h-card properties
* Added h_card template tag for rendering h-card microformats
* Added Profile admin interface with JSON editing support
* Added h-card parsing and validation utilities
* Added comprehensive test suite for h-card functionality
* Updated documentation with h-card usage examples

0.4.3 (2025-07-11)
------------------
* Fixed ``webmention_count`` template tag to always return integers for consistent template comparisons
* Previously returned string when used directly but integer when used with ``as`` variable assignment
* Added comprehensive tests for the webmention_count fix

0.4.2 (2025-07-10)
------------------
* Added Django admin integration for Webmention, Token, and Auth models
* Added comprehensive admin test suite
* Webmention admin includes filters, search, and organized fieldsets for easy management
* Token and Auth admin are read-only for security purposes

0.4.1 (2025-07-10)
------------------
* Fixed Webmention endpoint to return Location header with HTTP 201 status per W3C specification
* Added WebmentionStatusView to provide webmention status information at the Location URL
* Fixed compatibility with webmention.rocks test suite

0.4.0 (2025-07-10)
------------------
* **MAJOR**: Added complete Webmention support (W3C Recommendation compliance)
* Added Webmention model for storing incoming and outgoing webmentions
* Added WebmentionEndpoint view for receiving webmentions
* Added WebmentionProcessor for validating and parsing webmentions with microformats2
* Added WebmentionSender for discovering endpoints and sending webmentions
* Added pluggable interfaces for URL resolution, spam checking, and comment integration
* Added Django template tags for displaying webmentions (``webmentions_for``, ``webmention_count``, ``webmention_endpoint_link``)
* Added management command ``send_webmentions`` for sending webmentions from the command line
* Added comprehensive test suite for Webmention functionality (35 new tests)
* Added detailed Webmention documentation with integration examples
* Added CSS styling and templates for different webmention types (likes, reposts, replies, mentions)
* Added Django signals for webmention processing (``webmention_received``)
* Replaced requests library with httpx for better async support and HTTP/2 features
* Updated dependencies to use httpx instead of requests

0.3.5 (2025-06-29)
------------------
* Fixed Authorization header handling to check for HTTP_AUTHORIZATION (Django's standard header format)
* Maintained backward compatibility with test client Authorization format
* Added tests to verify both Authorization header formats work correctly

0.3.4 (2025-06-29)
------------------
* Fixed Token model unique constraint that prevented multiple clients from obtaining tokens for the same user
* Removed incorrect unique=True from Token.me field (kept unique_together constraint)

0.3.3 (2025-06-29)
------------------
* Fixed micropub authorization to accept "create" scope (standard Micropub) in addition to legacy "post" scope
* Added debug logging for token authentication failures

0.3.2 (2025-06-29)
------------------
* Fixed KeyError in TokenView when 'me' parameter is missing - the token endpoint now correctly handles optional parameters according to IndieAuth spec
* Improved token endpoint error responses to use proper IndieAuth error codes (invalid_request, invalid_grant)
* Added redirect_uri verification for enhanced security
* Implemented one-time use of authorization codes to prevent replay attacks
* Added proper content-type headers to token endpoint responses

0.3.1 (2025-06-28)
------------------
* Added merge migration to resolve parallel migration branches

0.3.0 (2025-06-28)
------------------
* **MAJOR**: Implemented fully functional Micropub endpoint with content creation
* Added pluggable content handler system for Micropub integration
* Added ``MicropubContentHandler`` abstract base class for custom implementations
* Added ``InMemoryMicropubHandler`` for testing and development
* Added support for both form-encoded and JSON Micropub requests
* Implemented Micropub query endpoints (``?q=config``, ``?q=syndicate-to``)
* Added comprehensive test suite for Micropub functionality (19 new tests)
* Added detailed Micropub documentation with integration examples
* Added example content handlers demonstrating various integration patterns
* Updated type hints to use modern Python syntax (``list``, ``dict`` instead of ``List``, ``Dict``)
* **BREAKING**: Removed old Micropub property methods that were implementation details
* Added comprehensive documentation for IndieAuth implementation including consent screen
* Added test suite for IndieAuth consent screen functionality (14 new tests)
* Fixed MyPy type errors in AuthView for better type safety
* Updated development guidelines with "Definition of Done" criteria

0.2.0 (2025-06-16)
------------------
* Fixed Read the Docs build by adding missing dependencies to docs/requirements.txt
* Added coverage configuration to exclude migrations from coverage reports
* Cleaned up duplicate documentation files (removed outdated .txt versions)
* Added type annotations to models.py and views.py
* Added mypy configuration with django-stubs for static type checking
* Added documentation for running mypy in development.rst
* Added comprehensive API reference documentation with examples
* Added usage tutorial with client-side implementation examples
* Added configuration guide documenting all settings and options
* Added concepts documentation explaining IndieWeb protocols with Mermaid diagrams
* Updated CONTRIBUTING.rst to reflect current development workflow (uv, ruff, pytest)
* Documented Micropub handler architecture (in-memory default plus configurable handler via ``INDIEWEB_MICROPUB_HANDLER``)
* Converted all tests from unittest to pytest style
* Added __str__ method to Token model
* Added docstrings to all model and view classes
* **BREAKING**: Removed unnecessary dependencies:
  - Replaced django-model-utils TimeStampedModel with explicit timestamp fields
  - Replaced django-braces AccessMixin with direct login redirect
  - Removed setuptools (not needed at runtime with modern packaging)
  - Replaced pytz with Python's built-in datetime.timezone.utc
* Package now only depends on Django itself

0.1.0 (2025-06-13)
------------------
* Migrated from flit to uv build backend
* Moved package from top-level to src layout
* Replaced black, isort, and flake8 with ruff
* Added Python 3.13 support
* Dropped Python 3.9 support (minimum is now 3.10)
* Updated pre-commit hooks
* Consolidated dev dependencies into single group
* Added comprehensive documentation with Sphinx and Furo theme
* Updated documentation structure for Read the Docs
* Fixed Django settings configuration for tests

0.0.8 (unreleased)
------------------
* Development version (not released)

0.0.7 (2023-01-07)
------------------
* Added migration for auto field
* Updated pre-commit hooks

0.0.6 (2022-11-05)
------------------
* Use flit and pyproject.toml instead of setup.py
* Support recent Django versions
* Even better package infrastructure

0.0.5 (2019-05-19)
------------------
* Auth endpoint works with https://pin13.net/login/ \o/
* Use black for code formatting
* Better package infrastructure
* Require python >= 3.6

0.0.4 (2016-06-14)
------------------
* exempt csrf checking

0.0.3 (2016-06-13)
------------------
* added migrations

0.0.2 (2016-05-15)
------------------
* Auth and Token endpoints with some tests.

0.0.1 (2016-05-14)
------------------
* First release on PyPI.
