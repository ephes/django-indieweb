# Security Analysis

Date: 2026-05-06 (initial); updated 2026-05-06 with second-pass deep review across the full codebase, then revised after independent claim-verification review; updated 2026-05-07 after implementation verification and residual-risk review; updated 2026-05-08 after an additional six-agent residual-risk review was verified against the current source; updated 2026-05-09 after a fresh six-agent parallel review pass surfaced new findings against the post-P1/P2/P3 codebase; updated 2026-05-09 (later) after the P1/P2/P3/P4 batch landed every 2026-05-09 finding; updated 2026-05-09 (later, third pass) after a six-agent parallel review against the post-P4 codebase surfaced no new Critical/High issues but identified two Medium residuals and a hardening backlog of 22 Lows (24 residual items total).

This document summarises a security review of `django-indieweb` as a third-party Django app. It focuses on risks when the app's public IndieWeb endpoints are installed on an internet-facing Django site.

The first pass identified five high-priority findings plus several supporting ones. The second pass dispatched six parallel reviewers (IndieAuth/token, Webmention receive, Webmention sender + Micropub, WebSub, cross-cutting infrastructure, templates/h-card/static assets). An independent third pass verified each new claim against the source and downgraded several findings whose evidence did not support a High severity for a third-party Django app. This revision reflects those corrections.

## Overall Risk

- **Low risk** if only h-card/template helpers are used and protocol endpoints are not exposed.
- **Medium risk** if IndieAuth/Micropub are exposed only with strict production configuration, trusted users, rate limits, and hardened media storage.
- **High risk** if Webmention processing and the bundled Webmention rendering templates are exposed publicly with defaults.

The most urgent remaining production blockers are:

1. ~~IndieAuth authorization requests do not bind ``redirect_uri`` to
   ``client_id``.~~ Resolved 2026-05-08 under P1.4: ``AuthView.get`` and
   ``AuthView._handle_consent`` now enforce a layered binding (built-in
   same-origin default; ``INDIEWEB_REDIRECT_URI_ALLOWLIST`` for per-client
   exact and prefix entries; ``INDIEWEB_REDIRECT_URI_VALIDATOR`` policy hook),
   the consent screen now displays the resolved ``redirect_uri``, and the
   change is documented as a backwards-incompatible default.

2. ~~``TokenView.post`` accepts a request-supplied ``me`` and prefers it
   over the consent-validated ``auth.me``.~~ Resolved 2026-05-09: a new
   ``TokenView._check_me_binding`` consumes the auth code and returns
   ``invalid_grant`` when a submitted ``me`` does not match ``auth.me``
   under the redirect-URI normalization policy. The issued token is
   always bound to ``auth.me``; introspection
   (``TokenIntrospectionView._active_response``) and the Micropub
   default config response (``MicropubView._handle_*``) echo the
   consent-bound identity. Regression coverage:
   ``tests/test_token_endpoint.py::test_token_exchange_rejects_me_substitution_attack``,
   ``test_token_exchange_introspection_echoes_consent_me_not_substituted``,
   and ``tests/test_micropub_endpoint.py::test_get_default_response_echoes_bound_me``.

There are no remaining open production blockers as of 2026-05-09.

The concurrent authorization-code exchange race called out in earlier passes
is fully resolved as of 2026-05-08; see Finding 5 below.

The outbound HTTP hardening blocker called out in earlier passes (incomplete
IP block table, ``trust_env=True`` defaults, secret-bearing cross-origin
redirects, and the missing HTTPS gate for ``hub.secret``) is fully resolved
as of 2026-05-08; see Finding 2 below.

Former production blockers that were verified fixed by 2026-05-07 include Webmention stored XSS/unsafe remote URL rendering, IndieAuth consent CSRF/open redirect, authorization-code validation-failure reuse, token exchange `redirect_uri` binding, token parsing/reissue hardening, Micropub media sniffing, introspection authentication, token hashing at rest, CORS wildcard credentials, and WebSub signature/lease/secret hardening. A separate concurrent authorization-code exchange race was identified on 2026-05-08 and resolved the same day; see Finding 5 below.

## Verification Status 2026-05-07

The 2026-05-07 verification pass reviewed `SECURITY_ANALYSIS.md` against the current source and ran focused security regression tests:

```bash
uv run pytest tests/test_http_client.py tests/test_webmention_endpoint.py tests/test_webmention_processor.py tests/test_webmention_templatetags.py tests/test_auth_endpoint.py tests/test_consent_screen.py tests/test_token_endpoint.py tests/test_micropub_endpoint.py tests/test_micropub_create.py tests/test_micropub_media.py tests/test_cors.py tests/test_rate_limiting.py tests/test_websub.py tests/test_websub_subscriber.py tests/test_admin.py -q --no-cov
```

Result: `792 passed in 41.31s`.

The pass found no new token, consent, Micropub media/property, CORS, admin-secret, or stored-XSS regressions beyond the three 2026-05-07 residual issues that were later resolved.

## Verification Status 2026-05-08

A follow-up residual-risk review checked new claims from six parallel reviewers
against the current source. The review did not run the full test suite; it
inspected the referenced implementation paths and empirically checked the
Python ``ipaddress`` classifications for multicast and NAT64 examples.

Validated high-priority residuals:

- ``processors.py`` previously used ``soup.find_all(href=True)`` in
  ``_html_links_to_target`` and ``_html_links_to_source_domain``, accepting
  metadata/navigation constructs as Webmention or Vouch proof rather than a
  rendered source-page anchor. **Resolved 2026-05-08:** both helpers now use
  ``soup.find_all("a", href=True)`` and ``_html_links_to_source_domain`` also
  applies the existing ``_has_non_rendered_ancestor`` guard, so non-anchor
  ``href`` carriers such as ``<link>``, ``<base>``, and ``<area>`` no longer
  satisfy source or Vouch proof. See ``DONE.md`` 2026-05-08 entry.
- ``http_client.py`` blocks only ``not ip.is_global`` after IPv4-mapped IPv6
  normalization. On Python 3.13, IPv4 multicast addresses such as
  ``239.255.255.250`` and reserved NAT64 well-known-prefix addresses such as
  ``64:ff9b::7f00:1`` report ``is_global=True`` and pass. The same outbound
  paths instantiate ``httpx.Client(..., verify=True)`` without
  ``trust_env=False``, so proxy and CA environment variables can alter the
  supposedly screened connection path. The redirect helper also intentionally
  preserves method, body, and headers for Webmention compatibility, which is
  unsafe for WebSub ``hub.secret`` and other secret-bearing POST callers when
  redirects cross origin.
- ``websub.py`` permits ``http://`` hub URLs even when sending ``hub.secret``.
  That is a confidentiality issue for deployments that configure WebSub
  secrets with plain-HTTP hubs.
- ``TokenView.post`` still obtains an ``Auth`` row through
  ``Auth.get_for_raw_key()``, validates it, deletes it, then issues/reissues a
  token without holding a row lock across the consume-and-issue sequence.

Validated medium-priority residuals:

- ~~WebSub delivery hooks are dispatched before successful deliveries are
  recorded in replay history.~~ Resolved 2026-05-08 under P2.1: the atomic
  ``WebSubAcceptedDelivery`` gate commits before hook dispatch, so a retry
  after a crash between the gate commit and the hook returns the replay
  response and does not re-invoke the hook. Hooks that opt in to the new
  ``body_digest`` keyword argument get a stable idempotency key for any
  remaining at-least-once host-side processing.
- ~~``record_websub_denial`` clears staged renewal secret state for any valid
  denied callback matching the subscription token and topic.~~ Resolved
  2026-05-08 under P2.4: ``record_websub_denial`` now only clears
  ``pending_secret`` / ``pending_secret_set`` when the subscription is not
  ``STATE_ACTIVE``. A denied callback for an active renewal leaves the
  active secret intact and the staged rotation available for an explicit
  operator retry; only fresh-subscribe denials (``STATE_PENDING_SUBSCRIBE``)
  transition to ``STATE_DENIED`` and clear pending secret state.
- ~~A new Webmention submission can replace ``vouch_url`` on an existing
  source/target row and clear a prior ``vouch_verified_at`` value if the new
  Vouch fails. That lets an unauthenticated repeat submission downgrade the
  row's Vouch metadata.~~ Resolved 2026-05-08 under P2.5:
  ``_store_webmention_submission`` no longer overwrites ``vouch_url`` /
  ``vouch_verified_at`` when the row already has a verified Vouch, and
  ``WebmentionProcessor.process_webmention`` preserves the prior verified
  metadata when a newly submitted Vouch fails verification. Verified Vouch
  state is replaced only when the new submission successfully verifies.

Claims reviewed but downgraded or rejected:

- The default ``InMemoryMicropubHandler`` is still an unsafe development
  example, but ``get_micropub_handler()`` returns a fresh instance when no
  handler is configured, so the claim that the default creates a process-global
  shared dictionary is not accurate for the current code.
- WebSub replay history is now a bounded multi-digest window. The default cap
  of 64 can evict older accepted digests during high-volume delivery windows,
  but exploiting that generally requires a malicious/compromised hub or another
  actor that can cause many valid signed deliveries. Track it as tuning and
  documentation work rather than a top production blocker.
- Bundled Webmention display through ``show_webmentions`` re-sanitizes author
  URLs/photos and HTML before rendering. The raw templates remain less safe if
  a host includes them directly with unsanitized model rows, but that is
  defense-in-depth/documentation work, not a bypass of the bundled tag.

## Verification Status 2026-05-08, IndieAuth and Adapter Boundaries

A second 2026-05-08 static review focused on IndieAuth bindings, race
conditions, deployment defaults, and host-adapter boundaries. The review did
not run tests; claims below were verified against the current implementation
and public documentation.

Validated high-priority residuals:

- ~~Authorization-code exchange atomicity remains open, as noted above.~~
  Resolved 2026-05-08 under P1.3; see Finding 5.
- ~~``AuthView.get`` and ``AuthView._handle_consent`` validate ``client_id``
  and ``redirect_uri`` independently.~~ Resolved 2026-05-08 under P1.4:
  ``AuthView.get`` and ``AuthView._handle_consent`` now run a layered binding
  policy after the existing client-policy checks. The default rule requires
  the ``redirect_uri`` origin (scheme, IDNA host, default-port-collapsed
  port) to equal the ``client_id`` origin; ``INDIEWEB_REDIRECT_URI_ALLOWLIST``
  enables per-client exact and prefix entries (fragments rejected); and
  ``INDIEWEB_REDIRECT_URI_VALIDATOR`` is a fail-closed policy hook that
  short-circuits both layers. The bundled consent screen now displays the
  resolved ``redirect_uri``.
- ~~WebSub replay detection is not atomic under concurrent identical deliveries.~~
  Resolved 2026-05-08 under P2.1: a new ``WebSubAcceptedDelivery`` table
  carries a unique constraint on ``(subscription, body_digest)``;
  ``WebSubCallbackView.post`` now wraps the prune-and-insert step in
  ``transaction.atomic()`` with an inner savepoint around ``create()`` so two
  concurrent identical deliveries cannot both record an acceptance, regardless
  of whether the database backend supports ``SELECT FOR UPDATE``. Hook
  dispatch happens after the gate commits, giving an at-most-once-per-digest
  hook contract within the configured replay window. The host hook and
  enqueue callables can opt in to a ``body_digest`` keyword argument as a
  stable idempotency key.

Validated medium-priority residuals:

- ~~Micropub create leaks unexpected handler exception text to authenticated
  clients. The create path catches every ``Exception`` from
  ``handler.create_entry(...)`` and returns ``400 Error creating entry:
  {str(exc)}``, unlike update/delete/source/media paths that keep unexpected
  exception details in logs and return a generic ``500``.~~ Resolved
  2026-05-08 (P2.2): ``MicropubView.post`` now catches ``ValueError``
  separately and returns ``400 invalid_request``; any other handler exception
  is logged via ``logger.exception`` and the response is ``500`` with an
  empty body, matching the rest of the action handlers.
- ~~Micropub entry source, media source-by-URL, and media delete operations
  pass submitted URLs unchanged to the configured handler. This matches the
  documented host-owned adapter boundary, but it remains an integration risk
  for handlers that key on URL substrings or fetch arbitrary submitted URLs.
  If django-indieweb wants stronger guardrails, it needs a configurable
  host-owned URL policy rather than a hard same-host rule, because media may
  legitimately live on storage/CDN hosts.~~ **Resolved 2026-05-08 under
  P3.1:** ``INDIEWEB_MICROPUB_URL_POLICY`` is an optional dotted-path setting
  resolving to a callable
  ``(url, kind: Literal["entry", "media"], request) -> bool``.
  ``MicropubView._handle_source_query``,
  ``MicropubMediaView._handle_source_by_url_query``, and
  ``MicropubMediaView._handle_delete`` consult the gate before forwarding
  the submitted URL to the handler; rejection yields
  ``400 invalid_request``, and callable exceptions / import failures /
  non-callable resolutions fail closed with ``500`` and are logged. The
  setting is unset by default to preserve compatibility, and avoids a hard
  same-host rule so media on storage or CDN hosts remains supported.
  Documented in ``docs/configuration.rst`` (with a slot in the Production
  hardening snippet) and ``docs/micropub.rst``. Tests:
  ``tests/test_micropub_source.py`` and ``tests/test_micropub_media.py``
  cover rejection, runtime errors, and import errors for all three
  surfaces.
- ~~Production IndieAuth and endpoint hardening remains opt-in:
  ``INDIEWEB_REQUIRE_PKCE``, ``INDIEWEB_REQUIRE_PKCE_S256``,
  ``INDIEWEB_ALLOWED_CLIENT_IDS``, ``INDIEWEB_BIND_ME_TO_USER``, and
  ``INDIEWEB_RATE_LIMITS`` default to compatibility-oriented values. This is
  documented, but a production hardening profile would make safe deployments
  easier to copy.~~ **Resolved 2026-05-08 under P2.3:**
  ``docs/configuration.rst`` now ships a copyable ``Production hardening``
  section enabling these settings together (with concrete
  ``INDIEWEB_RATE_LIMITS`` entries for ``auth``, ``token``,
  ``token_introspection``, ``micropub``, ``media``, ``webmention``,
  ``webmention_status``, and ``websub_callback``) and a
  ``production-hardening`` reST label that ``docs/indieauth.rst``,
  ``docs/api.rst``, and ``README.rst`` cross-reference. The compatibility
  defaults remain unchanged. ``tests/test_documentation_snippets.py``
  guards the snippet against setting-name drift.

Validated lower-priority hardening:

- Injected ``httpx.Client`` arguments intentionally bypass DNS-based SSRF
  blocking and IP pinning. The source docstrings warn that this is test/trusted
  integration behavior; public docs should carry the same warning.
  **Status:** Resolved 2026-05-08. ``docs/webmention.rst`` and
  ``docs/websub.rst`` now carry prominent ``.. warning::`` blocks that mirror
  the source docstrings; ``docs/configuration.rst`` adds an ``Injected HTTP
  Clients`` subsection and ``docs/api.rst`` cross-references the warnings.
  ``tests/test_documentation_snippets.py::test_injected_client_warning_present``
  guards the warning text against doc drift.
- The Webmention status endpoint uses high-entropy opaque status tokens, but a
  leaked status URL reveals source URL, target URL, status, and verification
  timestamp to the holder. This is likely intended protocol diagnostics, but
  privacy-sensitive deployments may want a minimal public-safe response mode.
  **Status:** Resolved 2026-05-08. ``WebmentionStatusView`` now honors
  ``INDIEWEB_WEBMENTION_STATUS_PUBLIC`` (default ``False`` preserves the
  diagnostic shape). When set to ``True``, the response body is restricted
  to ``status`` and (when set) ``verified_at``; ``source`` and ``target``
  are omitted. ``docs/configuration.rst``, ``docs/webmention.rst``, and
  ``docs/api.rst`` document the setting; ``docs/configuration.rst`` adds it
  to the ``Production hardening`` snippet.
- Logging now redacts authorization codes and bearer tokens, but INFO/WARNING
  logs still include client IDs, ``redirect_uri``, ``state``, ``me``, and
  Webmention source/target URLs. That can expose private or draft URLs through
  log aggregation; track a privacy logging mode or deployment guidance.
  **Status:** Resolved 2026-05-08. ``INDIEWEB_LOG_REDACTION`` (default
  ``"passthrough"``) opts INFO/WARNING log calls in ``views.py``,
  ``processors.py``, and ``websub.py`` into stable HMAC-SHA256 digests
  (12 hex chars, keyed with ``SECRET_KEY``) for ``client_id``,
  ``redirect_uri``, ``state``, ``me`` (origin-only), and Webmention/WebSub
  URLs. ERROR-level logs are left intact for incident response.
  ``docs/configuration.rst`` documents the setting (anchored at
  ``log-redaction``) and adds ``INDIEWEB_LOG_REDACTION = "redact"`` to
  the ``Production hardening`` snippet.

## Verification Status 2026-05-09

A six-agent parallel review pass examined the post-P1/P2/P3 codebase against
the resolved findings and looked for new vulnerabilities. The reviewers
covered IndieAuth/token endpoints, Webmention receive + processing, Webmention
sender + Micropub, WebSub subscriber, cross-cutting infrastructure
(``http_client``, ``rate_limit``, ``cors``, ``log_redaction``, sanitizers,
``h_card``, models, admin, migrations), and templates/URLs/management
commands/examples. The pass did not run the full test suite; claims below
were verified against the current source.

The pass confirmed that all 2026-05-07 and 2026-05-08 fixes hold up against
the current source. New findings:

Validated high-priority residual:

- ~~``TokenView.post`` overwrites the consent-validated ``auth.me`` with a
  request-supplied ``me``.~~ Resolved 2026-05-09 (P1): see blocker #2 above
  for the implementation summary and regression coverage.

Validated medium residuals:

- ~~``Webmention.objects.get_or_create`` runs against raw, un-canonicalized
  strings.~~ Resolved 2026-05-09 (P2):
  ``processors.canonicalize_webmention_storage_url`` lowercases scheme,
  IDNA-encodes the host, drops default ports, and maps an empty path to
  ``/`` before ``_store_webmention_submission`` and
  ``WebmentionProcessor.process_webmention`` call ``get_or_create``.
- ~~The synchronous Webmention receive path has no per-(source, target)
  cooldown.~~ Resolved 2026-05-09 (P2): new
  ``INDIEWEB_WEBMENTION_PAIR_COOLDOWN_SECONDS`` setting (default ``0``,
  disabled) gates the synchronous fetch/parse/verify pipeline for repeat
  submissions of the same canonical pair.
  ``WebmentionEndpoint._webmention_cooldown_short_circuit`` returns the
  existing status URL with ``HTTP 200`` when within the cooldown window.
- ~~``INDIEWEB_REDIRECT_URI_ALLOWLIST`` prefix entries permit ``..``
  traversal.~~ Resolved 2026-05-09 (P2):
  ``_redirect_uri_allowlist_match`` calls ``_path_has_dot_segments``
  on the candidate path (and the entry path) to reject literal or
  percent-encoded ``.``/``..`` segments before the existing
  origin/prefix check runs.
- ~~Top-level ``example_project.py`` is an unmarked production foot-gun.~~
  Resolved 2026-05-09 (P2): the script now requires ``DJANGO_SECRET_KEY``
  in the environment unless ``ALLOW_UNSAFE_DEV_SECRET=1`` opts into the
  development sentinel, defaults to ``ALLOWED_HOSTS=["localhost",
  "127.0.0.1"]``, and never auto-creates a superuser.
- ~~``examples/custom_consent_template.html`` omits the PKCE hidden
  inputs.~~ Resolved 2026-05-09 (P2): the template now mirrors the
  bundled ``consent.html`` with ``code_challenge`` /
  ``code_challenge_method`` hidden inputs (gated on the same context
  variable).
- ~~``src/indieweb/handlers_example.py`` declares a Django model inside
  the installable package.~~ Resolved 2026-05-09 (P2): the file moved to
  ``examples/handlers_example.py`` and now imports from
  ``indieweb.handlers``. The mypy override pinned to the old module path
  was removed.
- ~~``Token.hash_key()`` and ``Auth.hash_key()`` consult only
  ``settings.SECRET_KEY``.~~ Resolved 2026-05-09 (P2):
  ``Auth.get_for_raw_key`` and ``Token.get_for_raw_key`` now look up
  by ``key__in=_candidate_token_hashes(raw_key)``, which iterates
  ``[SECRET_KEY] + SECRET_KEY_FALLBACKS``. New issuance still hashes
  under the primary key only.
- ~~``Auth.get_for_raw_key`` / ``Token.get_for_raw_key`` keep a legacy
  plaintext fallback.~~ Resolved 2026-05-09 (P2): the fallback is now
  gated on ``INDIEWEB_LEGACY_PLAINTEXT_KEY_LOOKUP`` (default ``True``);
  set to ``False`` once the migration window has closed.

Validated lower-priority hardening (non-exhaustive):

- ~~``http_client._blocked_ip_address`` does not check
  ``is_site_local``.~~ Resolved 2026-05-09 (P3): IPv6 ``fec0::/10``
  site-local addresses are now rejected explicitly.
- ~~Default ``httpx.Client`` instances persist a cookie jar and do not
  configure ``httpx.Limits``.~~ Resolved 2026-05-09 (P3 + review
  follow-up): default clients in ``processors.py``, ``senders.py``, and
  ``websub.py`` set ``limits=SAFE_HTTP_DEFAULT_LIMITS`` and route the
  client through ``http_client.disable_client_cookies(...)`` after
  construction. The helper monkey-patches ``client.cookies.extract_cookies``
  to a no-op, because ``httpx.Client(cookies=None)`` still constructs a
  real jar and ``httpx.Client`` re-wraps any ``Cookies`` subclass passed
  in via the constructor (so a subclass override is silently dropped).
  Regression coverage:
  ``tests/test_http_client.py::test_disable_client_cookies_drops_set_cookie_responses``.
- ~~``Webmention.author_url`` and ``author_photo`` lack
  ``schemes=["http","https"]``.~~ Resolved 2026-05-09 (P3): both fields
  now carry an ``URLValidator(schemes=["http", "https"])`` at the model
  layer (migration ``0027``).
- ~~``MicropubView._valid_http_url`` does not reject userinfo on
  URL-typed Micropub create properties.~~ Resolved 2026-05-09 (P3): the
  helper now rejects userinfo before structural validation.
- ~~``WebmentionStatusView.get`` emits no ``Cache-Control: no-store`` /
  ``Vary: Cookie``.~~ Resolved 2026-05-09 (P3): both headers are now
  emitted on every response.
- ~~``confirm_websub_verification`` permits arbitrary lease shrinkage on
  active subscriptions.~~ Resolved 2026-05-09 (P3):
  ``_ratchet_renewal_lease`` floors renewals at ``max(floor, prior //
  2)``.
- ``WebSubSubscription.callback_token`` is intentionally preserved
  across successful resubscribes. Documented in ``models.py`` as a
  design choice: the hub keys subscriber identity by callback URL, so
  rotating mid-flight would invalidate the URL the hub still has cached
  and force a fresh handshake. New subscriptions always receive a fresh
  high-entropy token at row creation time.
- ~~``confirm_websub_verification`` writes hub-supplied ``hub.challenge``
  without truncation.~~ Resolved 2026-05-09 (P3): the value is truncated
  to ``last_challenge.max_length`` (200) before save.
- ~~Migration ``0022`` left a vestigial
  ``recent_accepted_delivery_digests`` JSON field.~~ Resolved 2026-05-09
  (P3): migration ``0026`` removes the column.
- ~~``commands/notify_websub.py`` echoes raw topic and hub URLs.~~
  Resolved 2026-05-09 (P3): topic and hub URLs are routed through
  ``redact_url`` so the management command honors the
  ``INDIEWEB_LOG_REDACTION`` setting.
- ~~Outbound ``User-Agent`` is hard-coded.~~ Resolved 2026-05-09 (P3):
  new ``outbound_user_agent`` helper backed by ``INDIEWEB_USER_AGENT``;
  default clients in all outbound modules set ``User-Agent`` from this
  helper.
- ~~``webmention_endpoint_link`` does not scheme-validate its
  argument.~~ Resolved 2026-05-09 (P3): unsafe scheme arguments fall
  back to the configured ``indieweb:webmention`` reverse URL.
- ~~``client.py`` writes login response HTML to ``/tmp/blubber.html``.~~
  Resolved 2026-05-09 (P3): the unsafe debug write removed.
- ~~``TokenRevokeView`` lacks ``xframe_options_deny``.~~ Resolved
  2026-05-09 (P3): ``TokenRevokeView`` now mirrors
  ``TokenManagementView`` with ``xframe_options_deny`` on dispatch and
  a ``frame-ancestors 'none'`` CSP header on the response.
- ~~``docs/micropub.rst`` does not mention
  ``DATA_UPLOAD_MAX_NUMBER_FILES``.~~ Resolved 2026-05-09 (P4): the
  setting is documented alongside the existing upload-size guidance,
  with a documentation snippet test guarding against drift.
- ~~``http_client._canonical_host`` accepts empty-label edge cases.~~
  Resolved 2026-05-09 (P3): empty-label hosts are rejected explicitly.

Claims reviewed but rejected:

- nh3 sanitizer allowlist drift (``frame``, ``frameset``, ``xmp``,
  ``plaintext``, ``marquee``, ``formaction``, ``srcset``): the allowlist
  is default-deny, and the carriers for each of these constructs
  (``<button>``, ``<input>``, ``<source>``, etc.) are not in the tag
  allowlist, so smuggling is not possible through ``content_html``.
- ``filetype.guess`` confusion via partial-buffer padding: Django buffers
  the upload before the view runs, so the 261-byte sniff cannot be
  evaded by post-sniff bytes.
- Storage filename traversal via UUID/suffix: server-derived, no client
  input enters the storage path.
- Concurrent reissue race for ``Token.key`` rotation: the auth-code
  delete-count gate already serializes the predecessor exchange, so
  ``send_token``'s ``select_for_update`` runs at most once per code.

## Verification Status 2026-05-09 (later, third pass)

A six-agent parallel review against the post-P4 codebase examined IndieAuth,
Token + Micropub, Webmention receive + processors, outbound HTTP + senders,
WebSub, and cross-cutting infrastructure + templates. Each reviewer was
briefed against the prior `SECURITY_ANALYSIS.md` so resolved findings were
not re-reported. The pass did not run the full test suite; claims below were
verified against the current source.

The pass confirmed that all 2026-05-07 / 2026-05-08 / 2026-05-09 (P1–P4)
fixes hold up against the current source. **No new Critical or High-severity
findings.** Two Medium residuals (one independently flagged by two
reviewers) and a hardening backlog of 22 Lows follow.

Validated medium residuals:

- ``WebmentionNestedResponse.author_url`` / ``author_photo`` /
  ``response_url`` / ``identity`` lack the model-layer
  ``URLValidator(schemes=["http","https"])`` that migration ``0027``
  applied to the parent ``Webmention`` model. Independently flagged by
  two reviewers (Webmention-receive M1 and cross-cutting M2).
  ``src/indieweb/models.py:466-471``. Bundled templates re-sanitize via
  ``_prepare_nested_response_for_display``
  (``templatetags/webmention_tags.py:55-79``), so the bundled render path
  remains safe; downstream templates that read these fields directly, or
  any write path that bypasses ingestion (``QuerySet.update``,
  ``bulk_update``, raw SQL, fixtures), get attacker-controlled values
  unfiltered. Sibling migration applying the same validators restores
  parity.
- ``MicropubMediaView._handle_delete`` skips the
  ``_action_url_is_same_host`` check that ``MicropubView._handle_delete``
  / ``_handle_update`` / ``_handle_undelete`` enforce.
  ``src/indieweb/views.py:2836-2860`` vs ``views.py:2367``. A
  ``media``-scoped token can submit
  ``action=delete url=https://attacker.example/...`` and the request
  reaches the host adapter relying entirely on its ownership check.
  Note that ``MicropubView._handle_source_query``
  (``views.py:2521-2533``) and ``MicropubMediaView._handle_source_by_url_query``
  (``views.py:2763-2783``) are at parity with each other — both rely on
  ``_enforce_micropub_url_policy`` plus the host adapter and neither
  applies the same-host gate. The asymmetry to fix is therefore
  delete-only, and the implementation should match the entry-side
  ``_handle_delete`` contract exactly — a structural same-host check
  with no ``INDIEWEB_MICROPUB_URL_POLICY`` override path on the delete
  surface. If the same-host invariant is also desirable for
  ``q=source&url=`` paths, both entry and media source handlers should
  be tightened together as a separate follow-up.

Validated lower-priority residuals (hardening / defense-in-depth):

- Token issuance and introspection success responses do not set
  ``Cache-Control: no-store``. ``views.py:1644-1655`` (``send_token``),
  ``views.py:1869-1879`` (``_active_response``), ``views.py:1829-1830``
  (``_inactive_response``). RFC 6749 §5.1 mandates ``no-store`` on
  token-endpoint responses; the 401 path already sets it
  (``views.py:1253-1256``).
- Consent GET response lacks ``Cache-Control: no-store`` and
  ``Referrer-Policy: no-referrer``. ``views.py:1473-1476``. The redirect
  response carrying ``code``/``state`` should also receive the same
  treatment.
- Legacy code-verification POST does not consume the auth code on
  success. ``views.py:1568-1599`` — ``_verify_auth_code`` returns
  ``{"me": auth.me}`` without ``auth.delete()``, leaving the row
  redeemable until expiry as a ``me``-validity oracle. The token
  endpoint's delete-count gate is symmetric (``views.py:1800-1810``);
  the legacy verification path should match.
- ``_handle_consent`` deletes the prior ``Auth`` row before the new row
  is created, outside ``transaction.atomic()``. ``views.py:1540-1555``.
  Reliability rather than privilege issue: two concurrent approves can
  race on ``IntegrityError``.
- Permissive cross-origin redirects on the outbound Webmention sender:
  ``send_webmention`` does not opt into ``cross_origin_strip``, so
  ``request_with_webmention_redirects`` replays the POST body up to five
  times across origins. ``senders.py:330-338``;
  ``http_client.py:300-326``. Each hop is still SSRF-screened. Consider
  an opt-in ``INDIEWEB_WEBMENTION_STRICT_REDIRECTS`` for operators who
  do not need bug-for-bug compatibility.
- ``WebmentionSender`` uses scalar ``httpx`` timeouts (10 s HEAD, 30 s
  POST), so worst-case wall-clock with the configured five redirects
  (initial request + 5 redirected hops = 6 requests) is ~180 s per
  POST delivery and ~60 s per HEAD discovery.
  ``senders.py:108-110, 167, 336``; ``http_client.py:16``. Replace
  with the layered ``SAFE_HTTP_DEFAULT_TIMEOUT`` and a per-call
  deadline.
- ``_extract_external_target_urls`` performs a case-sensitive netloc
  compare for the same-domain test. ``senders.py:567-583``. Lowercase
  both sides (or use ``_origin_for_url``) and strip default ports.
- ``send_webmention`` validates the ``vouch`` URL with ``resolver=None``
  (syntactic only). ``senders.py:326``. The URL is not fetched on this
  path, so this is future-proofing only — comment the intent or pass
  ``default_address_resolver``.
- Per-method rate-limit counter multiplies effective allowance and
  bloats key space. ``rate_limit.py:88-94, 110-127``. The counter key
  embeds ``:{method}:`` and increments before ``super().dispatch``, so
  unsupported-method requests still consume slots and the effective
  per-IP limit is ``limit × distinct-methods-tried``. Drop ``method``
  from the key.
- ``Token.objects.get_or_create`` with ``scope=None`` may proliferate
  rows on PostgreSQL/MySQL because ``unique_together = ("me",
  "client_id", "scope", "owner")`` does not collapse on NULL.
  ``views.py:1623-1629``; ``models.py:247, 251``. Coerce ``scope=None``
  to ``""`` for the storage key, or add a partial unique index.
- ``_check_redirect_uri`` lets a submitted ``redirect_uri`` pass when
  the stored ``auth.redirect_uri`` is empty. ``views.py:1692-1701``.
  Currently-issued codes always have a stored ``redirect_uri``
  (consent and ``required_params`` enforce it), so the gap is latent.
  Add the missing branch defensively.
- ``_redact_auth_code`` always discloses 6 leading characters
  regardless of ``INDIEWEB_LOG_REDACTION`` mode.
  ``views.py:1221-1227``. With a 32-char ``get_random_string`` (charset
  62), six chars is ~35 bits and is inconsistent with the redaction
  policy operators opted into. Replace call sites with
  ``log_redaction.redact_token`` or have the helper consult
  ``_resolve_mode``.
- Several logger sites still emit unredacted ``client_id`` /
  ``token.owner`` despite ``INDIEWEB_LOG_REDACTION=redact``.
  ``views.py:1306, 1682, 1686, 1742, 1804, 1848``. Sibling lines on the
  same view do redact (e.g. ``views.py:1341, 1399, 1583``); apply the
  same pattern.
- ``WebmentionNestedResponse``-related: ``_get_local_profile`` matches
  ``parsed.netloc`` against bare ``Site.domain`` without IDNA / case /
  default-port normalization. ``processors.py:1659-1662``. Defense-in-
  depth — ``sanitize_remote_webmention_url`` and the bundled
  re-sanitizer keep this from being exploitable for stored XSS, but the
  receive endpoint normalizes on both sides
  (``views.py:3231-3254``); the local-profile lookup should match.
- Source-link verification (``processors.py:244-254``) excludes only
  ``noscript`` and ``template`` ancestors. ``<a href>`` inside
  ``<head>``, foreign content, or CSS-hidden ancestors still satisfies
  the rendered-anchor invariant. Self-attestation by the source author
  bounds practical impact; tightening
  ``NON_RENDERED_LINK_ANCESTORS`` (or requiring the link inside an
  h-card / visible body region for Vouch proof) is the cheap
  hardening.
- ``WebmentionStatusView`` default response leaks ``source`` /
  ``target`` URLs to opaque-token holders.
  ``views.py:3314-3320``. Already toggleable via
  ``INDIEWEB_WEBMENTION_STATUS_PUBLIC=True``; consider flipping the
  default to public-safe or scoping diagnostics to staff.
- ``WebmentionSourceSnapshot.raw_source_html`` is unbounded ``TextField``
  capped only by the ingest fetch ceiling (default 1 MiB). Each
  accepted webmention persists up to ~1 MiB of attacker-controlled
  HTML. ``models.py:437``; ``processors.py:88-89``. Document a
  retention/compression policy or cap the stored snapshot size below
  the fetch size.
- ``delivery_content_length_too_large`` accepts negative
  ``Content-Length``. ``websub.py:977-986``. ``int("-1") > max_bytes``
  is False, so the early reject is skipped. The post-read length check
  still bounds the body; treat negative parsed values as malformed.
- WebSub migration ``0026`` drops
  ``recent_accepted_delivery_digests`` without backfilling. Brief
  replay-protection gap during deploy. Either backfill in a
  ``RunPython`` step, or note the deploy-window gap explicitly in the
  changelog so operators schedule during a quiet period.
- ``_signature_headers`` does not bind algorithm-name token to header-
  name suffix. ``websub.py:994-1003``. Currently safe because sha1 is
  off by default; add a regression test that locks in "trust the
  algorithm token only" so a future change cannot regress.
- ``commands/notify_websub.py`` echoes raw ``result.error`` content (up
  to 500 chars of the hub response body). ``notify_websub.py:60-62``.
  Pass through ``redact_url`` (or strip URL-shaped substrings) for
  parity with the redacted topic/hub URLs.
- CORS preflight 405 lacks ``Vary: Origin`` on the wildcard-origin
  branch. ``cors.py:142-145``. Upstream cache could pin a 405 across
  origins. Always emit ``Vary: Origin`` on preflight rejections.

Claims reviewed but rejected:

- ``WebSubAcceptedDelivery`` per-subscription scoping: the unique
  constraint ``(subscription, body_digest)`` is correct — a digest
  accepted for subscription A does not block subscription B.
  ``models.py:787-792``.
- WebSub HMAC body capture re-encoding: bytes are read once via
  ``request.body`` and forwarded unchanged to
  ``validate_websub_delivery_signature`` and the body-digest hash;
  no normalization. ``views.py:2960-2997``.
- DNS rebinding TOCTOU on outbound HTTP: closed by IP pinning + per-
  redirect re-validation in ``http_client.py``;
  ``tests/test_http_client.py:335-372`` proves the rebinding-resolver
  case is rejected on hop 2 before any second connection.
- Webmention sender / WebSub callback connection-pool reuse leaking
  ``Authorization`` across hosts: no default outbound client carries
  an ``Authorization`` header; secret-bearing WebSub callers route
  through ``cross_origin_strip=True``.
- nh3 sanitizer SVG/MathML smuggling via re-introduced carriers
  (``<button>``, ``<input>``, ``<source>``): the carriers themselves
  are not in the allowlist, so smuggling is not possible through
  ``content_html``.
- Connection-pool / cookie-jar leakage: ``disable_client_cookies`` is
  applied consistently on every default outbound client.

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

**Status:** Resolved 2026-05-08 after the four sub-tasks of the P1.2 outbound
HTTP hardening plan landed (see DONE.md "P1.2 — Complete outbound HTTP
hardening"). The shared outbound HTTP helper screens URL syntax,
private/loopback/link-local/reserved IP literals, DNS names that resolve to
blocked addresses, and unsafe redirects; direct receive, sender, WebSub
subscribe, and WebSub publish paths route through it with explicit TLS
verification and bounded redirects. As of 2026-05-07 the helper resolves the
URL host once, validates every returned IP, and connects to the resolved IP
literal while preserving the original ``Host`` header and forwarding the
original hostname as ``extensions["sni_hostname"]`` for HTTPS, closing the
DNS rebinding / TOCTOU window; the pin is re-applied on every redirect hop.
The remaining 2026-05-08 residuals — the multicast/reserved/NAT64 IP-block
gap, ``trust_env=True`` defaults on the protocol clients, the cross-origin
redirect behavior for secret-bearing callers, and the missing HTTPS gate for
``hub.secret`` — are all closed on the same day.

**References:**

- `src/indieweb/views.py` (`WebmentionEndpoint`)
- `src/indieweb/processors.py` (`_fetch_source` ~line 331, `_fetch_vouch` ~line 341)
- `src/indieweb/http_client.py:56` (redirect helper)
- `src/indieweb/senders.py` (`discover_endpoint` ~line 55, `fetch_content`, `send_webmention`, `extract_urls`)
- `src/indieweb/websub.py` (`_post_subscription_request` ~line 382, `notify_hubs` ~line 765)
- `src/indieweb/management/commands/notify_websub.py`

Historical finding, resolved in broad form on 2026-05-07: every outbound HTTP
path used `httpx` without filtering loopback, private, link-local, multicast,
reserved, or metadata IP ranges, and the redirect helper screened only
scheme/netloc syntactically. The affected SSRF surfaces were:

- **Webmention receive**: source and vouch fetches with attacker-controlled URLs.
- **Webmention sender**: endpoint discovery, content fetch, and POSTed delivery (note: practical risk depends on what content the sender operates on; see finding 7).
- **WebSub subscribe**: `_post_subscription_request` POSTs `hub.callback` and `hub.secret` to any operator-supplied (or templated) `hub_url`, including private/internal addresses.
- **WebSub publish**: `notify_hubs` POSTs to every URL in `INDIEWEB_WEBSUB_HUBS`.

Historical contributing issues, since resolved or narrowed:

- The Webmention receive endpoint accepted non-HTTP(S) `source` and `target`
  URLs at submission.
- Source/Vouch fetches did not use the shared safe redirect helper.
- DNS rebinding could split validation and connection across different lookups.

**Resolved sub-tasks (all four landed 2026-05-08):**

- (Resolved 2026-05-08, P1.2a) Extend `_blocked_ip_address` beyond
  `not ip.is_global` so multicast, reserved, and NAT64 well-known-prefix
  addresses that map to blocked IPv4 destinations are rejected. The current
  ``_blocked_ip_address`` now rejects multicast, reserved, unspecified,
  loopback, link-local, and private destinations explicitly and recurses
  through the embedded IPv4 destination for NAT64 well-known
  (``64:ff9b::/96``) and local-use (``64:ff9b:1::/48``) prefixes. Covered by
  ``test_blocked_ip_rejects_dangerous`` /
  ``test_blocked_ip_allows_public`` in ``tests/test_http_client.py``.
- (Resolved 2026-05-08, P1.2a) Instantiate default protocol clients
  with `trust_env=False`. Default ``httpx.Client(...)`` calls in
  ``processors.py``, ``senders.py``, and ``websub.py`` now pass
  ``trust_env=False`` so ambient proxy and CA bundle environment variables
  cannot redirect or downgrade the screened connection path. A static
  regression test
  (``test_default_clients_disable_trust_env``) prevents drift.
- (Resolved 2026-05-08, P1.2b) Split redirect behavior so Webmention
  compatibility can preserve POST bodies while WebSub subscription/publish
  and other secret-bearing callers reject cross-origin body/header replay.
  ``request_with_safe_redirects`` and ``stream_with_safe_redirects`` now
  accept ``cross_origin_strip``; WebSub subscribe (``_post_subscription_request``)
  and publish (``notify_hubs``) pass ``cross_origin_strip=True``. The
  Webmention sender path (``request_with_webmention_redirects``) keeps the
  permissive default. Covered by ``test_strict_redirect_rejects_cross_origin``
  and ``test_safe_redirect_allows_same_origin_when_strict`` in
  ``tests/test_http_client.py``.
- (Resolved 2026-05-08, P1.2b) Reject WebSub subscription requests that
  send `hub.secret` over plain HTTP. ``_post_subscription_request`` raises
  the typed ``WebSubSecretRequiresHTTPSError`` before any network call when
  the hub URL is not HTTPS, and ``request_websub_subscription`` records the
  failure through the existing
  ``_save_subscription_request_failure`` path. Covered by
  ``test_subscription_with_secret_rejects_http_hub`` in
  ``tests/test_websub_subscriber.py``.

### 3. Synchronous Webmention and WebSub Processing Cause DoS, Decompression Bombs, and Recursion DoS

**Severity:** High

**Status:** Mostly resolved and re-checked 2026-05-08. Webmention source/vouch
fetches and sender fetches now stream decoded content with a default 1 MiB cap
and tighter timeouts; Webmention nested-response extraction, primary
`_search_for_mentioning_entry` traversal, fallback h-entry lookup, h-card lookup,
h-card-id lookup, and page-level h-card collection all use iterative traversal
with depth/item limits; WebSub delivery checks `Content-Length` before reading
and enforces a configured body-size cap. The inline WebSub host hook remains a
deployment hardening consideration.

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

**Status:** Resolved 2026-05-06 for authorization-code validation-failure
reuse; the concurrent exchange race reopened on 2026-05-08 was resolved the
same day under P1.3.
`TokenView.post` now consumes a matched `Auth` row on PKCE failures,
`redirect_uri` mismatches, scope mismatches, and expired-code failures before
returning the existing `invalid_grant` response. Token endpoint logs now redact
authorization codes. Resolved 2026-05-06 for the adjacent bearer parsing,
key uniqueness, duplicate-lookup handling, and token reissue rotation slice:
bearer headers must now be strict two-part `Authorization: Bearer <token>`
values, POST-body `Authorization` fallback is removed, token-protected 401
responses include `Cache-Control: no-store` and `WWW-Authenticate: Bearer`,
`Auth.key` and `Token.key` are unique, duplicate-key lookups fail closed, and
token reissue rotates the existing row's bearer key. As of 2026-05-08 the
consume-and-issue sequence runs inside `transaction.atomic()`, evaluates
`Auth.objects.select_for_update().filter(pk=auth.pk).first()` for
defense-in-depth on row-locking backends, and gates single-use enforcement on
the delete count: `Auth.objects.filter(pk=auth.pk).delete()` returning ``0``
means a competing exchange already consumed the code and the view returns
`invalid_grant` without issuing a token. `send_token` now runs inside the
same atomic block and the reissue branch acquires
`Token.objects.select_for_update().filter(pk=token.pk).first()` before
rotating the bearer key. The delete-count gate is the authoritative
backend-agnostic enforcement (SQLite row locks are no-ops); the
`select_for_update` calls add real serialization on Postgres/MySQL.

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

**Status:** Resolved and verified 2026-05-07; further hardened 2026-05-08.
Status URLs now use opaque `status_token` values instead of sequential IDs,
and public status JSON no longer includes Vouch URLs or Vouch timestamps.
Deployments that must not echo the stored ``source``/``target`` URLs to a
holder of a leaked status URL can additionally set
``INDIEWEB_WEBMENTION_STATUS_PUBLIC = True`` to restrict the response body
to ``status`` and (when set) ``verified_at``.

`views.py:2025` — `WebmentionStatusView` is unauthenticated and its sequential `<int:pk>` URL exposes every Webmention's `source_url`, `target_url`, `vouch_url`, status, and verification timestamps. This leaks attacker-probe pending state, vouch URLs that may be private, and any private/draft post URL that happens to be a Webmention target.

**Recommendation:** Replace integer IDs with opaque tokens, gate access on ownership/staff, or restrict the response to public-safe states (verified only) and fields (no `vouch_url`).

### Webmention Source Verification Is Too Permissive

**Severity:** Medium

**Status:** Resolved 2026-05-08. HTML verification skips non-rendered
ancestors, plain-text URL tokens are not accepted as standalone source-link
proof, and both `_html_links_to_target` and `_html_links_to_source_domain`
now restrict source/Vouch proof to rendered `<a href>` anchors via
`soup.find_all("a", href=True)`. The non-rendered-ancestor guard now also
applies to Vouch source-domain checks. The separate residual parser recursion
issue is tracked under finding 3.

Historical finding, partly resolved on 2026-05-07 and fully resolved on
2026-05-08: `_html_links_to_target` matched links inside non-rendered
ancestors such as `<template>` and `<noscript>`, `_text_links_to_target`
accepted plain-text URL tokens that the source page never rendered as a link,
and both helpers used `soup.find_all(href=True)` so non-anchor carriers such
as `<link>`, `<base>`, and `<area>` could satisfy proof. All three bypasses
are closed.

### WebSub: No Replay Protection, No Lease Bounds, Algorithm Confusion

**Severity:** Medium

**Status:** Resolved 2026-05-08. WebSub signatures now prefer the strongest
accepted algorithm, `sha1` is disabled by default, leases are clamped, shared
secrets have byte-length bounds, secret headers are handled with
case-insensitive request headers, and a replay window now retains a bounded
history of accepted delivery digests. The default history cap of 64 still
applies to most subscriptions, but high-volume topics can opt into
"unbounded by count" semantics by setting
``INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX = 0``; pruning is then purely
time-based by ``INDIEWEB_WEBSUB_DELIVERY_REPLAY_WINDOW_SECONDS`` so no
accepted body is evicted while it remains inside the window. The high-volume
eviction caveat for the default cap is documented in ``docs/websub.rst`` and
``docs/configuration.rst``.

Historical finding, mostly resolved on 2026-05-07:

- Signed deliveries had no retained digest replay window.
- Confirmed lease durations were unbounded.
- Mixed SHA-1/SHA-256 signatures could validate via the weaker accepted header.
- Signature header handling was less robust for plain mappings.
- Empty/short `hub.secret` values were accepted as effectively no secret.

**Current residuals:** none. Replay protection retains a bounded digest
history with the default cap of 64; high-volume deployments can opt into
"unbounded by count" semantics by setting
``INDIEWEB_WEBSUB_DELIVERY_REPLAY_HISTORY_MAX = 0`` so pruning is purely
window-based, and replay-check/history-update is now atomic against parallel
identical valid deliveries via the ``WebSubAcceptedDelivery`` unique
constraint plus ``transaction.atomic()`` savepoint.

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

The 2026-05-09 (later, third pass) review surfaced two Medium residuals
and a hardening backlog of 22 Lows (24 residual items total). There are
no Critical / High items and no remaining production blockers. The
recommended fix order is:

1. Apply ``URLValidator(schemes=["http","https"])`` to
   ``WebmentionNestedResponse.author_url``, ``author_photo``,
   ``response_url``, and ``identity`` in a sibling migration that mirrors
   ``0027``. This restores the parent / nested-response invariant that
   bundled templates already rely on at render time.
2. Add ``_action_url_is_same_host`` to
   ``MicropubMediaView._handle_delete`` so the media-delete path matches
   ``MicropubView._handle_delete``'s hard-required same-host gate
   (``views.py:2367``). Tightening the source-by-URL paths is an
   optional follow-up that should be applied to ``MicropubView._handle_source_query``
   *and* ``MicropubMediaView._handle_source_by_url_query`` together,
   since both currently rely on ``_enforce_micropub_url_policy`` plus
   the host adapter and are at parity with each other.
3. Set ``Cache-Control: no-store`` on token-endpoint and introspection
   success responses; add ``Cache-Control: no-store`` and
   ``Referrer-Policy: no-referrer`` to the consent GET response and the
   redirect carrying ``code``/``state``/``iss``. RFC-compliance
   one-liners.
4. Logging-hygiene sweep: replace ``_redact_auth_code`` with
   ``log_redaction.redact_token``; route ``client_id`` through
   ``redact_url`` and ``token.owner`` through a hashed-id helper at
   ``views.py:1306, 1682, 1686, 1742, 1804, 1848``; pass
   ``notify_websub`` ``result.error`` through ``redact_url``.
5. Drop ``:{method}:`` from the rate-limit cache key (or normalize
   unsupported methods to one bucket) to prevent per-IP allowance
   multiplication.
6. Lower-priority hardening: opt-in
   ``INDIEWEB_WEBMENTION_STRICT_REDIRECTS``; layered
   ``httpx.Timeout`` for ``WebmentionSender``; consume the auth code
   on legacy verification success; coerce ``scope=None`` to ``""`` in
   ``Token`` get-or-create; reject negative ``Content-Length`` early;
   document the WebSub replay-window semantics and the
   ``0026``-deploy replay gap; add a regression test pinning
   ``X-Hub-Signature-256: sha1=…`` rejection; tighten
   ``NON_RENDERED_LINK_ANCESTORS`` (and Vouch proof location);
   normalize ``_get_local_profile`` netloc compare; flip
   ``WebmentionStatusView`` default to public-safe; document a
   ``WebmentionSourceSnapshot`` retention/compression policy; add
   ``Vary: Origin`` to the wildcard-branch CORS preflight rejection.

### Historical fix order (2026-05-09 batch, resolved)

1. ~~Drop request-supplied ``me`` in ``TokenView.post``.~~ Resolved
   2026-05-09 (P1): ``TokenView._check_me_binding`` rejects mismatched
   submitted ``me`` and consumes the auth code; the issued token is
   bound to ``auth.me``.
2. ~~Canonicalize Webmention ``source_url``/``target_url`` and add a
   per-canonical-pair cooldown.~~ Resolved 2026-05-09 (P2):
   ``processors.canonicalize_webmention_storage_url`` plus
   ``INDIEWEB_WEBMENTION_PAIR_COOLDOWN_SECONDS``. URLs with userinfo are
   rejected at the receive endpoint to prevent identity collapse.
3. ~~Reject ``..`` segments in ``INDIEWEB_REDIRECT_URI_ALLOWLIST``
   prefix matching.~~ Resolved 2026-05-09 (P2):
   ``_path_has_dot_segments`` iteratively decodes percent-encoded forms
   to defeat ``%252e%252e`` smuggling.
4. ~~Mark ``example_project.py`` development-only and move
   ``handlers_example.py`` out of the installable package.~~ Resolved
   2026-05-09 (P2).
5. ~~Iterate ``[SECRET_KEY] + SECRET_KEY_FALLBACKS`` in ``Auth``/``Token``
   key verification.~~ Resolved 2026-05-09 (P2):
   ``_candidate_token_hashes`` plus ``INDIEWEB_LEGACY_PLAINTEXT_KEY_LOOKUP``.
6. ~~Lower-priority hardening batch.~~ Resolved 2026-05-09 (P3):
   userinfo rejection in Micropub URL properties, ``Cache-Control:
   no-store`` and ``Vary: Cookie`` on status endpoint, lease-shrink
   ratchet, ``hub.challenge`` truncation, retired
   ``recent_accepted_delivery_digests`` removal, ``notify_websub`` URL
   redaction, ``TokenRevokeView`` xframe + frame-ancestors,
   ``DATA_UPLOAD_MAX_NUMBER_FILES`` documentation, empty-label
   ``_canonical_host`` rejection, IPv6 ``fec0::/10`` block, default
   ``httpx.Client`` cookie-jar disabling via
   ``http_client.disable_client_cookies``.

### Historical fix order (resolved)

The following items, listed in the 2026-05-08 fix order, are all
resolved:

1. ~~Restrict Webmention and Vouch source proof to rendered anchor links.~~
   Resolved 2026-05-08.
2. ~~Complete outbound HTTP hardening: deny multicast/reserved/NAT64 bypass
   addresses, disable environment trust on default protocol clients, protect
   secret-bearing WebSub subscription requests, and make redirect body/header
   replay opt-in for Webmention-only callers.~~ Resolved 2026-05-08 across
   the P1.2a (IP block table + ``trust_env=False``) and P1.2b (strict
   cross-origin redirect mode + ``hub.secret`` HTTPS gate) commits.
3. ~~Serialize authorization-code consume-and-token-issue under a database lock
   so the code remains single-use under concurrent exchanges.~~ Resolved
   2026-05-08 (P1.3): ``TokenView.post`` wraps the consume-and-issue sequence
   in ``transaction.atomic()`` with ``select_for_update`` on both ``Auth`` and
   reissued ``Token`` rows, and the authoritative single-use enforcement is
   the delete-count gate so SQLite deployments are protected too.
4. ~~Bind IndieAuth ``redirect_uri`` values to ``client_id`` through
   same-origin defaults, per-client redirect allowlists, or a configurable
   policy hook, and display the resolved redirect target on the consent
   screen.~~ Resolved 2026-05-08 (P1.4): ``AuthView.get`` and
   ``AuthView._handle_consent`` enforce the layered binding (built-in
   same-origin default, ``INDIEWEB_REDIRECT_URI_ALLOWLIST`` per-client
   exact/prefix entries, ``INDIEWEB_REDIRECT_URI_VALIDATOR`` fail-closed
   policy hook), and the consent screen now shows the resolved
   ``redirect_uri``.
5. Make WebSub replay detection and accepted-digest updates atomic for valid
   deliveries.
6. ~~Fix Micropub create exception disclosure.~~ Resolved 2026-05-08 (P2.2):
   the create branch now treats ``ValueError`` as ``400 invalid_request`` and
   any other exception as a generic ``500`` with an empty body, with the full
   exception logged via ``logger.exception``.
7. ~~Add the production hardening profile.~~ Resolved 2026-05-08 (P2.3):
   ``docs/configuration.rst`` ships a copyable ``Production hardening``
   section that enables ``INDIEWEB_REQUIRE_PKCE``,
   ``INDIEWEB_REQUIRE_PKCE_S256``, ``INDIEWEB_BIND_ME_TO_USER``,
   ``INDIEWEB_ALLOWED_CLIENT_IDS``, ``INDIEWEB_REDIRECT_URI_ALLOWLIST``,
   and concrete ``INDIEWEB_RATE_LIMITS`` entries for every bundled
   rate-limited endpoint, with cross-references from ``docs/indieauth.rst``,
   ``docs/api.rst``, and ``README.rst``.
   ``tests/test_documentation_snippets.py`` guards against setting-name
   drift.
8. ~~Follow with WebSub denial hardening and Vouch metadata downgrade
   protection.~~ Resolved 2026-05-08 (P2.4, P2.5).
9. ~~Then address Micropub source/media URL policy, injected HTTP-client
   safety docs, and status-token privacy controls.~~ Resolved 2026-05-08
   (P3.1) and concurrently for the docs/status items.
10. ~~Finish with privacy-oriented logging guidance or redaction mode.~~
    Resolved 2026-05-08 via ``INDIEWEB_LOG_REDACTION``.

## Documentation Impact

Documentation updates have landed alongside every historical fix. The
2026-05-09 (later, third pass) review introduced 24 new residuals (two
Mediums and 22 Lows); these are tracked in ``BACKLOG.md`` (2 Priority
2 + 13 Priority 3 + 9 Priority 4). Each will require corresponding
``docs/changelog.rst`` notes when fixed. The 2026-05-09 batch updated
``docs/changelog.rst``,
``docs/configuration.rst`` (new sections for
``INDIEWEB_WEBMENTION_PAIR_COOLDOWN_SECONDS``, ``INDIEWEB_USER_AGENT``,
and ``INDIEWEB_LEGACY_PLAINTEXT_KEY_LOOKUP``), ``docs/micropub.rst``
(``DATA_UPLOAD_MAX_NUMBER_FILES`` guidance), ``CONTRIBUTING.rst`` (new
``example_project.py runserver`` flow), ``DONE.md`` (consolidated entry),
and this analysis. ``AGENTS.md`` did not need a change.

## Current Backlog Coverage

As of 2026-05-09 (post-batch and post-third-pass), every previously
resolved item has a corresponding entry in ``DONE.md``. The 2026-05-09
(later, third pass) review introduced two Medium residuals and a Low
hardening backlog (24 residual items total); all 24 are recorded in
``BACKLOG.md`` (2 Priority 2 + 13 Priority 3 + 9 Priority 4) with
explicit references to affected files, docs, and this analysis.
