# Done

Completed backlog items move here from `BACKLOG.md`. Keep entries concise, but include validation and documentation/changelog notes so future contributors can understand what changed.

## 2026-04-26

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
