.. :changelog:

Changelog
=========

Unreleased
----------
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
