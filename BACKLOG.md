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

No current Micropub Enhancements and Extensions items.

### Syndication and Storage Examples

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
