# Backlog

This project no longer uses Beads. Planned work lives here until it is completed, then the completed item is moved to `DONE.md`.

When adding or completing items, keep each entry specific enough for an agent or contributor to implement without needing an external issue database. Include references to affected files, docs, or upstream issues when useful.

## Priority 1

### Webmentions Reliability and Compliance

No current Priority 1 items.

## Priority 3

### API Hardening

No current API Hardening items.

### Tooling and Maintainability

No current Tooling and Maintainability items.

## Priority 4

### WebSub Enhancements

- [ ] Add WebSub subscriber callback support through a staged design and implementation slice.
  - Outcome: django-indieweb can act as a minimal WebSub subscriber for host applications that want to receive hub
    notifications for external topics, while keeping publisher helpers and host-owned feed rendering unchanged.
  - References: `docs/websub.rst`, `docs/api.rst`, `docs/configuration.rst`, `src/indieweb/websub.py`,
    `src/indieweb/views.py`, `src/indieweb/urls.py`, `src/indieweb/models.py`, `src/indieweb/migrations/`,
    `tests/`, and the WebSub Recommendation at <https://www.w3.org/TR/websub/>.
  - Scope:
    - Design the persistence model before adding code. At minimum, track hub URL, topic URL, callback URL or callback
      token, subscription state, requested and confirmed lease seconds, lease expiration, verification mode/challenge
      correlation, optional secret metadata, latest delivery diagnostics, created/modified timestamps, and user or
      host-application ownership if needed.
    - Add subscription initiation for `hub.mode=subscribe` and `hub.mode=unsubscribe` with form-encoded
      `hub.callback`, `hub.topic`, optional `hub.lease_seconds`, and optional `hub.secret`; handle hub response status,
      redirects according to the chosen HTTP policy, network errors, and re-requesting active subscriptions for renewal.
    - Add a callback endpoint that handles WebSub verification `GET` requests by matching pending subscription or
      unsubscription state, echoing `hub.challenge` on accepted `subscribe`/`unsubscribe` requests, recording
      hub-provided `hub.lease_seconds`, and rejecting mismatched topics or modes.
    - Add content distribution `POST` handling that acknowledges accepted deliveries with HTTP 2xx, records delivery
      metadata, exposes a clear hook or processing helper for host applications, and avoids doing expensive parsing or
      host-specific writes in the request path unless explicitly configured.
    - Support optional `hub.secret` signing as part of the first implementation only if the storage and callback design
      can validate `X-Hub-Signature`/algorithm variants safely; otherwise make unsigned delivery the minimal first
      slice and leave authenticated distribution as a follow-up tied to the same model.
    - Add settings for callback URL construction, subscription defaults, lease renewal margin, request timeout, delivery
      size/content-type limits, and host delivery hook/import path if those choices are needed after design.
    - Cover security interactions: unguessable callback URLs or tokens, HTTPS guidance, replay/duplicate delivery
      handling, SSRF-safe topic/hub URL validation, rate-limit key coverage for the callback endpoint, CORS policy
      exclusion by default, CSRF exemption only for the server-to-server callback, logging without leaking secrets, and
      cleanup for expired or denied subscriptions.
  - Non-goals: do not build a WebSub hub service, do not change the existing publisher helper API or `notify_websub`
    command semantics, do not auto-subscribe to arbitrary discovered feeds, and do not invent host content-storage
    semantics for delivered payloads.
  - Tests/docs expected: model migration checks; focused tests for subscription request forms, verification GET
    challenge echo and rejection cases, lease tracking, unsubscribe flow, delivery POST acknowledgment, optional
    signature validation if implemented, rate-limit/CORS behavior, management/helper error handling, and docs for
    configuration, API endpoints, security, and operator workflows. Update `docs/changelog.rst`, `BACKLOG.md`, and
    `DONE.md` when implemented.

### Micropub Enhancements and Extensions

- [ ] Support Micropub event and RSVP post types.
  - Outcome: `GET /indieweb/micropub/?q=config` advertises event/RSVP-capable post types and form-encoded create
    parsing forwards the relevant properties to the configured `MicropubContentHandler`, while host applications keep
    responsibility for deciding storage models, rendering, and publication semantics.
  - References: `docs/micropub.rst`, `docs/api.rst`, `docs/concepts.rst`, `src/indieweb/handlers.py`,
    `src/indieweb/views.py`, `tests/test_micropub_create.py`, `tests/test_micropub_endpoint.py`, and the Micropub
    Recommendation vocabulary section at <https://www.w3.org/TR/micropub/#vocabulary>.
  - Scope:
    - Add precise default `post-types` entries for events and RSVPs without re-opening the completed note/article/photo/
      reply/bookmark/like/repost slice.
    - For events, forward likely `h-event` properties such as `name`, `summary`, `description`, `start`, `end`,
      `location`, `category`, `url`, and `published` from form-encoded requests. Preserve JSON create behavior for
      clients that send `type: ["h-event"]` and nested Microformats2 objects. Clients that send h-entry-style
      `content` for event-like posts should continue to have that property forwarded as-is rather than remapped.
    - For RSVPs, forward `rsvp`, `in-reply-to`, `name`, `content`, `category`, and `published` for `h-entry` RSVP
      posts. Decide during implementation whether the default config advertises RSVP as a separate post type, a reply
      variant, or both, and document the choice.
    - Keep values normalized as property arrays before calling `create_entry()`. Do not make django-indieweb infer
      event dates, attendee state, calendar semantics, or persistence behavior.
  - Non-goals: do not add event/RSVP models, migrations, templates, calendar feeds, Webmention RSVP display changes,
    time-zone normalization policy, or host storage semantics.
  - Tests/docs expected: focused tests proving config advertisement, form parsing for event and RSVP properties, JSON
    create pass-through remains unchanged, existing common post-type parsing is preserved, and docs/API/changelog
    describe the new advertised shapes and handler responsibilities. Update `BACKLOG.md` and `DONE.md` when implemented.

## Agent Workflow Improvements

- [ ] Add a curated agent learnings file if repeated repo-specific mistakes emerge.
  - Outcome: future agents get concise, reviewed guidance rather than raw transcript dumps.
