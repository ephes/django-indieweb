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

- [ ] Document host-owned WebSub workflow examples for delivery processing and lease renewal.
  - Outcome: add examples and docs showing how a Django project can wire ``INDIEWEB_WEBSUB_DELIVERY_HOOK`` to a task queue, parse delivered feeds in host code, renew expiring subscriptions with ``get_websub_renewal_candidates()`` and ``request_websub_subscription()``, and prune old ``WebSubDeliveryAttempt`` rows. Include tests for any example helpers that live in the package.
  - References: local ``src/indieweb/websub.py``, ``src/indieweb/models.py``, ``docs/websub.rst``, ``docs/concepts.rst``, ``docs/configuration.rst``, ``tests/test_websub_subscriber.py``, and ``tests/test_notify_websub_command.py``; Indiekit comparison reference ``/Users/jochen/src/getindiekit-indiekit/docs/specifications.md`` at ``1ee20d06``; WebSub Recommendation ``https://www.w3.org/TR/websub/``.
  - Scope exclusions: do not add a WebSub hub service, automatic topic discovery, hidden network calls, feed persistence, or a background scheduler owned by django-indieweb.

### Micropub Enhancements and Extensions

- [ ] Add Micropub supported-vocabulary and direct config subqueries.
  - Outcome: support direct configuration subqueries such as ``q=media-endpoint``, ``q=post-types``, and any documented supported-property/supported-vocabulary response the project chooses to implement, while keeping ``q=config`` as the aggregate response. Ensure custom handler config values remain authoritative and add docs for which Micropub extension query names are intentionally unsupported.
  - References: local ``src/indieweb/views.py``, ``src/indieweb/handlers.py``, ``tests/test_micropub_endpoint.py``, ``tests/test_micropub_media.py``, ``docs/micropub.rst``, and ``docs/api.rst``; Indiekit ``/Users/jochen/src/getindiekit-indiekit/packages/endpoint-micropub/lib/config.js``, ``lib/controllers/query.js``, and ``packages/endpoint-micropub/README.md`` at ``1ee20d06``; Micropub extension issues ``https://github.com/indieweb/micropub-extensions/issues/1`` and ``https://github.com/indieweb/micropub-extensions/issues/33``.
  - Scope exclusions: do not infer storage semantics from advertised post types; host handlers continue to decide how properties map to models.
- [ ] Preserve Micropub ``mp-*`` command properties and define draft-scope semantics.
  - Outcome: forward common command properties such as ``mp-slug``, ``mp-channel``, ``mp-photo-alt``, and ``mp-syndicate-to`` to the handler for form-encoded creates, and document JSON behavior for the same properties. Decide and implement django-indieweb's policy for ``draft`` scope and ``post-status=draft``: either allow ``draft`` to satisfy create/update only when the request is draft-bound, or explicitly keep ``draft`` host-owned and document the required custom scope handling. Include tests showing that command properties are preserved without django-indieweb generating slugs, choosing channels, writing alt text into files, or syndicating.
  - References: local ``src/indieweb/views.py``, ``src/indieweb/handlers.py``, ``src/indieweb/handlers_example.py``, ``tests/test_micropub_create.py``, ``tests/test_micropub_actions.py``, ``docs/micropub.rst``, and ``docs/indieauth.rst``; Indiekit ``/Users/jochen/src/getindiekit-indiekit/packages/endpoint-micropub/lib/jf2.js``, ``lib/scope.js``, ``lib/controllers/action.js``, ``lib/post-data.js``, and ``docs/specifications.md`` at ``1ee20d06``; Micropub server-command extensions ``https://github.com/indieweb/micropub-extensions/issues/40`` and ``https://github.com/indieweb/micropub-extensions/issues/39`` where applicable.
  - Scope exclusions: do not add an Indiekit-style post-template renderer, static-site path generator, or syndicator plugin in this slice.
- [ ] Add Micropub media source and delete extension points.
  - Outcome: add optional media handler/storage hooks so ``GET /indieweb/media/?q=source`` can list uploaded media or return metadata for a submitted ``url``, and ``POST /indieweb/media/`` with ``action=delete`` can delete host-owned media when supported. Preserve current direct upload behavior and return clear ``not implemented`` or ``invalid_request`` responses when no media listing/deletion hook is configured.
  - References: local ``src/indieweb/views.py``, ``tests/test_micropub_media.py``, ``docs/micropub.rst``, ``docs/api.rst``, and ``docs/configuration.rst``; Indiekit ``/Users/jochen/src/getindiekit-indiekit/packages/endpoint-media/lib/controllers/query.js``, ``lib/controllers/action.js``, ``lib/media-data.js``, ``lib/media-content.js``, and ``packages/endpoint-media/README.md`` at ``1ee20d06``; Micropub media extensions ``https://github.com/indieweb/micropub-extensions/issues/13``, ``https://github.com/indieweb/micropub-extensions/issues/14``, ``https://github.com/indieweb/micropub-extensions/issues/30``, and ``https://github.com/indieweb/micropub-extensions/issues/37``.
  - Scope exclusions: do not add a media management UI, Sharp-style image transforms, MongoDB-like media index, or non-Django storage backend abstraction unless a later design item calls for it.
- [ ] Advertise and document audio/video Micropub post types.
  - Outcome: after direct ``q=post-types`` behavior is settled, decide whether the built-in handler config should advertise ``audio`` and ``video`` post types now that form parsing forwards URL-valued ``audio`` and ``video`` properties, and add tests/docs for the chosen shape. If advertised, keep behavior limited to forwarding normalized properties to the handler; if not advertised, document why these remain custom handler config examples.
  - References: local ``src/indieweb/handlers.py``, ``src/indieweb/views.py``, ``tests/test_micropub_create.py``, ``docs/micropub.rst``, and ``docs/api.rst``; Indiekit ``/Users/jochen/src/getindiekit-indiekit/docs/plugins/post-types/audio.md``, ``docs/plugins/post-types/video.md``, ``packages/post-type-audio/README.md``, and ``packages/post-type-video/README.md`` at ``1ee20d06``; IndieWeb post type background ``https://indieweb.org/Category:PostType``.
  - Scope exclusions: do not add transcoding, players, storage models, or media processing in this advertisement slice.

### Syndication and Storage Examples

- [ ] Route Micropub syndication targets through handler configuration and document host-owned syndication.
  - Outcome: make ``GET ?q=syndicate-to`` return the configured handler's ``syndicate-to`` data instead of an unconditional empty list, document the expected target shape including ``uid``, ``name``, optional ``service`` metadata, and checked/default behavior if supported, and add an example showing how a host application can consume forwarded ``mp-syndicate-to`` values after publishing. Keep actual cross-posting and webhook-triggered syndication in host code.
  - References: local ``src/indieweb/views.py``, ``src/indieweb/handlers.py``, ``tests/test_micropub_endpoint.py``, ``docs/micropub.rst``, and ``docs/api.rst``; Indiekit ``/Users/jochen/src/getindiekit-indiekit/packages/endpoint-micropub/lib/config.js``, ``packages/endpoint-syndicate/README.md``, ``docs/concepts.md``, ``docs/plugins/syndicators/index.md``, and ``/Users/jochen/src/getindiekit-example-config/indiekit.config.js`` at ``b11b749``.
  - Scope exclusions: do not add Mastodon, Bluesky, Internet Archive, Bridgy, or deployment-webhook syndicator plugins to django-indieweb.
- [ ] Add static-site and storage-boundary Micropub handler examples.
  - Outcome: add examples that show how a host project can implement ``MicropubContentHandler`` for file/static-site workflows inspired by Jekyll, Hugo, Eleventy, Git-backed storage, and Django storage, including how to map post properties to paths/URLs and how to keep host rendering ownership. The examples should be executable or tested where practical and should call out when a full host model is required.
  - References: local ``src/indieweb/handlers.py``, ``src/indieweb/handlers_example.py``, ``examples/``, ``docs/concepts.rst``, and ``docs/micropub.rst``; Indiekit ``/Users/jochen/src/getindiekit-indiekit/docs/concepts.md``, ``docs/configuration/post-template.md``, ``docs/plugins/stores/index.md``, ``docs/plugins/presets/index.md``, ``packages/preset-jekyll/README.md``, ``packages/preset-hugo/README.md``, ``packages/store-github/README.md``, and ``/Users/jochen/src/getindiekit-example-config/indiekit.config.js`` at ``b11b749``.
  - Scope exclusions: do not introduce a django-indieweb content-store plugin architecture, repository credentials, file commit/push behavior, or static-site generator presets as core runtime features.

### Webmention and Reader Boundaries

- [ ] Add Webmention.io import/display guidance without replacing built-in Webmention processing.
  - Outcome: document how a host project could outsource collection to Webmention.io or import/display Webmention.io JF2 data alongside django-indieweb's built-in ``Webmention`` model, including sanitization expectations and mention type mapping. Make clear when using Webmention.io is an alternative integration choice rather than a missing core protocol endpoint.
  - References: local ``src/indieweb/models.py``, ``src/indieweb/processors.py``, ``src/indieweb/templatetags/webmention_tags.py``, ``docs/webmention.rst``, and ``tests/test_webmention_*.py``; Indiekit ``/Users/jochen/src/getindiekit-indiekit/packages/endpoint-webmention-io/README.md``, ``lib/controllers/webmentions.js``, ``lib/utils.js``, and ``docs/plugins/endpoints/webmention-io.md`` at ``1ee20d06``; Webmention.io API docs ``https://webmention.io/``.
  - Scope exclusions: do not replace django-indieweb's receive/send Webmention endpoints, add a Webmention.io API token setting to core, or add a bundled Webmention management dashboard in this item.
- [ ] Document Microsub and reader-side protocol non-goals.
  - Outcome: add concise docs that distinguish django-indieweb's publishing/notification scope from reader-side protocols such as Microsub. Explain that reader scopes like ``read``, ``follow``, ``mute``, ``block``, and ``channels`` are accepted as opaque IndieAuth scope strings today but have no built-in resource-server behavior unless a host application adds it; ensure future metadata work does not accidentally advertise unsupported reader capabilities.
  - References: local ``src/indieweb/views.py``, ``docs/concepts.rst``, ``docs/indieauth.rst``, ``docs/api.rst``, and ``docs/configuration.rst``; Indiekit ``/Users/jochen/src/getindiekit-indiekit/docs/specifications.md`` and ``/Users/jochen/src/getindiekit-indiekit/packages/endpoint-auth/lib/scope.js`` at ``1ee20d06``; Microsub background ``https://indieweb.org/Microsub-spec``.
  - Scope exclusions: do not implement Microsub channels, feed fetching, following, muting, blocking, or a reader UI in this documentation slice.

## Agent Workflow Improvements

- [ ] Add a curated agent learnings file if repeated repo-specific mistakes emerge.
  - Outcome: future agents get concise, reviewed guidance rather than raw transcript dumps.
