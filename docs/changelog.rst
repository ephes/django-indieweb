.. :changelog:

Changelog
=========

Unreleased
----------
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
