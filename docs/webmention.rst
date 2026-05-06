===========
Webmentions
===========

Webmention is a W3C recommendation that enables cross-site conversations. When you link to someone else's content, you can send them a webmention to notify them. Similarly, when others link to your content, they can send you webmentions that you can display as comments, likes, or reposts.

Features
========

* **Receiving webmentions**: Accept and validate incoming webmentions
* **Sending webmentions**: Automatically discover and notify linked sites
* **Microformats2 parsing**: Extract semantic content from webmentions
* **Spam protection**: Pluggable spam checker interface
* **Display templates**: Show webmentions as comments, likes, and reposts
* **Management commands**: Send webmentions from the command line

Quick Start
===========

1. Add the webmention endpoint to your base template:

.. code-block:: django

    {% load webmention_tags %}
    <head>
        {% webmention_endpoint_link %}
    </head>

2. Display webmentions on your pages:

.. code-block:: django

    {% load webmention_tags %}

    {% show_webmentions request.build_absolute_uri %}

3. Send webmentions when you publish content:

.. code-block:: bash

    python manage.py send_webmentions https://mysite.com/new-post/

Configuration
=============

Add these settings to your Django settings:

.. code-block:: python

    # Required: URL resolver to map URLs to content objects
    INDIEWEB_URL_RESOLVER = 'myproject.webmention_config.MyURLResolver'

    # Required: Spam checker (use default or implement your own)
    INDIEWEB_SPAM_CHECKER = 'indieweb.interfaces.NoOpSpamChecker'

    # Optional: Queue incoming Webmention processing outside the request path
    INDIEWEB_WEBMENTION_ENQUEUE = 'myproject.webmention_config.enqueue_webmention'

    # Optional: Verify submitted Vouch URLs from approved voucher domains
    INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS = ('trusted.example',)

    # Optional: Use custom receiver-side Vouch trust logic
    INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY = 'myproject.webmention_config.trust_vouch'

    # Optional: Comment adapter to convert webmentions to comments
    INDIEWEB_COMMENT_ADAPTER = 'myproject.webmention_config.MyCommentAdapter'

Implementing URL Resolution
===========================

Create a URL resolver to map target URLs to your content objects:

.. code-block:: python

    # myproject/webmention_config.py
    from indieweb.interfaces import URLResolver
    from myapp.models import BlogPost
    from urllib.parse import urlparse

    class MyURLResolver(URLResolver):
        def resolve(self, target_url: str) -> Any | None:
            """Resolve a URL to a content object."""
            parsed = urlparse(target_url)
            path = parsed.path

            # Example: match /blog/post-slug/
            if path.startswith('/blog/'):
                slug = path.strip('/').split('/')[-1]
                try:
                    return BlogPost.objects.get(slug=slug)
                except BlogPost.DoesNotExist:
                    pass

            return None

        def get_absolute_url(self, content_object: Any) -> str:
            """Get the absolute URL for a content object."""
            if hasattr(content_object, 'get_absolute_url'):
                return content_object.get_absolute_url()
            return ''

Implementing Spam Protection
============================

Create a custom spam checker:

.. code-block:: python

    from indieweb.interfaces import SpamChecker
    from indieweb.models import Webmention

    class MySpamChecker(SpamChecker):
        def check(self, webmention: Webmention) -> dict[str, Any]:
            """Check if a webmention is spam."""
            # Implement your spam detection logic
            spam_keywords = ['casino', 'viagra', 'lottery']
            content_lower = webmention.content.lower()

            is_spam = any(kw in content_lower for kw in spam_keywords)

            return {
                'is_spam': is_spam,
                'confidence': 0.9 if is_spam else 0.1,
                'details': 'Keyword-based detection'
            }

Receiving and Queued Processing
===============================

By default, ``POST /indieweb/webmention/`` preserves the historical synchronous
behavior: after validating ``source`` and ``target``, it calls
``WebmentionProcessor.process_webmention()`` in the request path and returns
``201 Created`` with a ``Location`` header pointing to the status endpoint.

For production deployments that use a task queue, set
``INDIEWEB_WEBMENTION_ENQUEUE`` to a dotted path for a callable with this
contract:

.. code-block:: python

    def enqueue_webmention(webmention_id: int) -> None:
        ...

When this setting is configured, the receive endpoint still performs the
normal form validation, URL validation, and configured Django ``Site`` domain
check before any persistence or enqueueing happens. For a valid request, it
creates or reuses the ``Webmention`` row for the submitted ``source`` and
``target`` pair, calls the configured enqueue hook with that row's primary key,
and returns ``202 Accepted`` with a ``Location`` header pointing to
``/indieweb/webmention/<pk>/``. The request path does not fetch the source URL,
parse microformats2, run spam checks, or send ``webmention_received``; those
steps remain owned by ``WebmentionProcessor`` in the worker process.

Queue integrations should call ``process_queued_webmention()`` from the worker:

.. code-block:: python

    # myproject/webmention_config.py
    from myproject.tasks import process_webmention_task

    def enqueue_webmention(webmention_id: int) -> None:
        process_webmention_task.delay(webmention_id)

.. code-block:: python

    # myproject/tasks.py
    from indieweb.processors import process_queued_webmention

    def process_webmention_task(webmention_id: int) -> None:
        process_queued_webmention(webmention_id)

``process_queued_webmention(webmention_id)`` loads the existing row and calls
``WebmentionProcessor().process_webmention(webmention.source_url,
webmention.target_url)``. If the row no longer exists, Django raises
``Webmention.DoesNotExist`` so the queue's retry or failure policy can decide
what to do.

If ``INDIEWEB_WEBMENTION_ENQUEUE`` cannot be imported, is not callable, or the
callable raises, the receive endpoint returns HTTP ``500`` and does not fall
back to inline processing. This fail-closed behavior avoids claiming a
Webmention was queued when processing cannot be scheduled. Missing parameters,
malformed URLs, JSON bodies, and targets outside the configured ``Site`` domain
still return HTTP ``400`` before the enqueue hook is loaded or called.
Import and non-callable configuration failures happen before a row is persisted.
If the callable itself raises, the ``Webmention`` row has already been created
or reused and remains ``pending``; operators should rely on their queue retry
path or manual cleanup to reconcile those rows.

Vouch Support
=============

Vouch is a backwards-compatible Webmention extension for spam and moderation
signals. A sender may include an optional third form parameter, ``vouch``,
whose value is an ``http`` or ``https`` URL on a site the receiver trusts. The
voucher page should link to the source page's domain.

django-indieweb accepts ``vouch`` on incoming Webmention POSTs, validates it as
a URL when present, stores it on ``Webmention.vouch_url``, and exposes it from
the status endpoint. Missing ``vouch`` values do not affect ordinary
Webmentions unless ``INDIEWEB_WEBMENTION_VOUCH_REQUIRED`` is enabled.

Queued receiving preserves the async boundary: the request path validates and
stores the optional ``vouch`` URL, calls the configured enqueue hook, and
returns ``202`` without fetching the source or voucher URL. Voucher fetching
and verification happen only in ``WebmentionProcessor`` or the worker helper
that calls it.

By default, submitted Vouch URLs are stored but not enforced. To verify
submitted vouchers with the built-in domain allowlist policy, configure
``INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS``:

.. code-block:: python

    INDIEWEB_WEBMENTION_VOUCH_TRUSTED_DOMAINS = ("trusted.example", "events.example")

When verification is enabled and a Webmention includes ``vouch``,
django-indieweb checks that the submitted voucher URL is on the configured
Django ``Site`` domain or one of the trusted domains, fetches the voucher URL
with the same bounded redirect policy used for Webmention source fetches,
requires the final voucher URL to remain on a trusted domain, requires an HTTP
``200`` ``text/html`` response, and verifies that the voucher page contains an
HTTP(S) HTML ``href`` whose domain matches the source URL's domain. A failed
Vouch check marks the Webmention ``failed`` without clearing previously parsed
fields.

For deployments that need a richer receiver-side trust model, configure
``INDIEWEB_WEBMENTION_VOUCH_TRUST_POLICY`` with a dotted path to a callable:

.. code-block:: python

    def trust_vouch(
        *,
        webmention,
        source_url: str,
        target_url: str,
        vouch_url: str,
        final_vouch_url: str | None = None,
    ) -> bool:
        ...

When a policy is configured, it owns Vouch URL trust decisions and the domain
allowlist is not applied by django-indieweb. The processor calls the policy
before fetching the voucher with ``final_vouch_url=None`` and again after
allowed redirects with ``final_vouch_url`` set to the final URL; both calls
must return a truthy value. Import failures, non-callable policy values, and
policy exceptions fail closed. The policy is evaluated only in
``WebmentionProcessor`` or queued worker paths, never in the async receive
request path.

Set ``INDIEWEB_WEBMENTION_VOUCH_REQUIRED = True`` to require a verifiable
voucher for incoming Webmentions. When this is enabled, a Webmention with no
stored ``vouch`` is marked ``failed`` by the processor. The endpoint still
validates and queues quickly; required-mode failures happen in processor-owned
logic. If required mode is enabled without a trust policy or trusted domains,
submitted vouchers fail closed; most deployments should configure one of those
trust sources before requiring Vouch.

Outgoing Webmentions can include Vouch metadata explicitly:

.. code-block:: python

    from indieweb.senders import WebmentionSender

    sender = WebmentionSender()
    sender.send_webmention(
        "https://mysite.com/post",
        "https://example.com/article",
        "https://example.com/webmention",
        vouch="https://trusted.example/vouch-for-mysite",
    )

The ``send_webmentions`` management command also accepts ``--vouch`` to include
the same voucher URL with each delivered Webmention.

Salmention Support Status
=========================

Salmention is a Webmention extension for propagating downstream replies and
other interactions upstream. For example, if Bob replies to Alice and later
displays Carol's reply to Bob, Bob's site can resend a Webmention to Alice so
Alice can re-check Bob's page and display Carol's nested response.

django-indieweb now stores processor-owned source snapshots and stable nested
child response rows for successfully verified incoming ``Webmention`` sources,
and the bundled ``show_webmentions`` template tag renders verified children
inline under verified parent replies. Duplicate submissions for the same
``source``/``target`` pair still reprocess the existing ``Webmention`` row.
During that verified reprocessing, the processor compares the current nested
response identities with the previous stored source snapshot before overwriting
it, creates or updates child rows for stable nested ``h-entry`` responses, and
marks children that disappeared from the latest verified source as missing.

This does **not** mean fully automatic Salmention support is implemented.
django-indieweb does not automatically infer when a host application has
incorporated a downstream response into an original permalink. Host
applications and operators still trigger outbound Salmention resends
explicitly.

Outbound Salmention sender support now has package-managed outbound target
history and an explicit sender API. The protocol expects a site to resend
Webmentions to everything the original post previously sent Webmentions to
after a newly received response has been incorporated into that original post's
permalink. Ordinary ``WebmentionSender.send_webmentions()`` calls record
outbound target history by default while still sending only links found in the
current source page. Host applications can call
``WebmentionSender.resend_salmentions()`` after they update the rendered source
permalink to notify the union of current links and previously recorded targets.
Operators can trigger the same sender workflow with
``python manage.py send_webmentions SOURCE --salmention-resend``.

No Salmention setting is available. Source snapshots and child response storage
are always owned by verified processor/worker processing, bundled nested
rendering is part of the default ``show_webmentions`` template path, and
outbound target-history storage plus sender and management-command resend
support are package behavior rather than setting toggles. Host applications
and operators still own the explicit signal that a source permalink changed
and should use the sender API or the management command rather than a global
setting.

Outbound Target Tracking
------------------------

Outbound Salmention support uses a hybrid ownership model: django-indieweb owns
durable outbound Webmention target-history storage, while the host application
owns source rendering and the signal that an accepted downstream response has
actually changed an original permalink.

Target history lives in the django-indieweb-managed
``WebmentionOutboundTarget`` model. Each row represents one original source URL
and one target URL that django-indieweb can use as outbound delivery history
for that source. The row is history for resend decisions, not a received
Webmention and not a nested response. It is therefore separate from
``Webmention``, ``WebmentionSourceSnapshot``, and
``WebmentionNestedResponse``.

The persisted fields are:

* ``source_url``: the original post permalink whose outbound Webmentions were
  sent.
* ``target_url``: the exact target URL that was previously sent a Webmention.
  Rows should be unique by ``source_url`` and ``target_url`` so repeated sends
  update history instead of widening the resend set.
* ``endpoint_url`` and ``endpoint_discovered_at``: the last endpoint discovered
  for that target, retained for diagnostics only. Resend workflows must
  rediscover the endpoint before delivery because Webmention update sends need
  current endpoint discovery.
* ``first_sent_at`` and ``last_sent_at``: timestamps for the first and latest
  outbound attempt.
* ``last_status_code``, ``last_success``, and ``last_error``: the latest
  delivery outcome in the same spirit as ``WebmentionSender`` result
  dictionaries.
* ``last_vouch_url``: the voucher URL used on the latest attempt, blank when no
  Vouch URL was sent.
* ``last_seen_in_source_at``: the last time the target was discovered in the
  current source content. This is diagnostic and may support future retention
  or cleanup policy; resend workflows must still determine current versus
  historical provenance by extracting links from the latest source content at
  resend time.

The outbound history schema stores the exact absolute HTTP(S) ``source_url``
and ``target_url`` strings used for delivery and uniqueness. It does not
silently apply the receive-side target matching canonicalization policy to
those keys, because outgoing Webmention updates are sent with the specific
source and target URLs supplied by the host application. Host applications
should pass stable canonical public permalinks for source URLs so one post's
history is not fragmented across variants.

An implementation may later add detailed attempt rows, final redirected
endpoint URLs, or retry metadata, but those are not required for the first
resend-capable slice. The history set used for Salmention resends should be
bounded to rows for the same ``source_url`` plus current links extracted from
that source. It should not send to unrelated URLs from other posts or arbitrary
operator-provided historical lists. A future import or migration helper could
explicitly record older targets for a source, but no such backfill tool is
required for the first resend-capable implementation.

Ordinary sends populate and refresh target history by default. The default
behavior of ``WebmentionSender.send_webmentions(source_url, html_content=None,
vouch_url=None, record_history=True)`` still returns per-target delivery
dictionaries with the ordinary ``success``, ``status_code``, ``target``,
``endpoint``, and optional ``error`` keys, and it still sends only current
external absolute HTTP(S) links. Relative URLs, same-domain URLs, and targets
without a discovered endpoint do not produce ordinary send results or outbound
history rows. Recording target history is an additional durable side effect,
not a change to which ordinary targets are delivered.

Callers that need the earlier no-write behavior for tests or unusual
integrations can pass ``record_history=False``:

.. code-block:: python

    sender.send_webmentions(
        "https://mysite.example/post/",
        html_content=rendered_html,
        record_history=False,
    )

Outbound Resend Workflow
------------------------

Sender support exposes an explicit resend workflow instead of trying to infer
Salmention timing from incoming Webmention processing. A host application knows
whether a received response was accepted, moderated, rendered, and incorporated
into an original post permalink; django-indieweb does not.

Use ``WebmentionSender.resend_salmentions()`` after the source permalink has
been updated:

.. code-block:: python

    from indieweb.senders import WebmentionSender

    sender = WebmentionSender()
    results = sender.resend_salmentions(
        source_url,
        html_content=rendered_source_html,
        vouch_url=vouch_url,
    )

``resend_salmentions()`` requires the source URL and either caller-provided HTML
or fetchable source content, then:

1. Extract the source's current external links using the same rules as ordinary
   sending.
2. Load previously recorded target history for exactly that ``source_url``.
3. Attempts Webmentions for the union of current targets and historical
   targets.
4. Rediscover each target's endpoint before delivery.
5. Marks each result with ``provenance`` set to ``current``, ``history``, or
   ``both``.
6. Refresh outbound target history for each attempted target, including targets
   that are no longer linked from the current source.

Every resend result includes at least ``target``, ``endpoint``, ``success``,
``status_code``, and ``provenance``. When a union target has no discoverable
endpoint, the result reports ``success=False``, ``status_code=None``, and an
``error`` explaining that no endpoint was found so callers can see historical
targets that could not be delivered. No-endpoint resend results refresh the
latest outcome fields but do not overwrite previously discovered endpoint
diagnostics or advance sent timestamps because no Webmention POST was made.
Resend attempts refresh ``WebmentionOutboundTarget`` diagnostics for current
and historical targets. For historical-only targets, ``last_seen_in_source_at``
is not advanced because the target was not present in the latest source
content.

This helper is not called automatically by ``WebmentionProcessor``.
Receive-side verification, source snapshots, nested response storage, Vouch
verification, and async queue behavior must stay focused on receiving. A host
application should call the helper only after it has accepted a downstream
response and updated the rendered original permalink to include that response
as nested ``h-entry`` content or otherwise changed the permalink output. Queue-
based deployments can call the helper from an application task after the render
or publish step; synchronous deployments can call it directly after saving the
rendered page. Operators should also be able to trigger the same workflow
manually through a management command.

The management command keeps its current behavior by default:

.. code-block:: bash

    python manage.py send_webmentions https://mysite.example/post/

That default remains an ordinary current-link send. It extracts links from the
current source content, skips relative and same-domain URLs, discovers current
endpoints, and sends only ordinary current outbound Webmentions.

Use ``--salmention-resend`` to switch the command to the explicit resend
workflow:

.. code-block:: bash

    python manage.py send_webmentions https://mysite.example/post/ --salmention-resend

In resend mode, the command calls
``WebmentionSender.resend_salmentions(source_url, html_content,
vouch_url=vouch_url)``. Output includes each target, discovered endpoint when
available, success or error, and a provenance label:

* ``current`` means the target is linked from the latest source content only.
* ``history`` means the target is recorded in outbound history for exactly
  that source URL but is no longer linked from the latest source content.
* ``both`` means the target is both currently linked and present in outbound
  history.

No-endpoint union targets remain visible in resend output as failures with an
``Error: No endpoint found`` message.

In resend mode, ``--dry-run`` shows the union of current and historical targets
for exactly the provided source URL, labels each target with the same
``current``/``history``/``both`` provenance, and rediscovers endpoints for
display without sending Webmentions or writing outbound target history.
Without resend mode, ``--dry-run`` keeps showing only current targets and
preserves the ordinary same-domain skip and endpoint-discovery preview. The
existing ``--content`` option, including ``--content -`` for stdin, and
``--vouch`` work in both modes.

Examples:

.. code-block:: bash

    # Preview ordinary current-link sends only
    python manage.py send_webmentions https://mysite.example/post/ --dry-run

    # Preview a Salmention resend to current plus exact-source historical targets
    python manage.py send_webmentions https://mysite.example/post/ \
        --salmention-resend --dry-run

    # Pipe rendered source HTML after a publish task updates the permalink
    render-post https://mysite.example/post/ | \
        python manage.py send_webmentions https://mysite.example/post/ \
            --salmention-resend --content -

Deleted or removed links should follow ordinary Webmention update semantics.
When a target was previously sent from ``source_url`` but no longer appears in
the latest source HTML, it stays in outbound target history and is included in
resend mode so the receiver can update or remove its display. New current links
that are not in history are included and then recorded. The resend target set is
therefore ``current links for this source`` plus ``recorded historical targets
for this source``, not every URL that ever appeared in the database.

Receiving Persistence
---------------------

The receive-side design for Salmention support is intentionally separate
from the current flattened ``Webmention`` row. The ``Webmention`` model should
continue to represent a submitted Webmention from one ``source_url`` to one
``target_url``. Receiving Salmentions needs additional related state because a
nested response found inside a previously received source page is not itself a
submitted Webmention to the original target, and storing it as another
``Webmention`` row would misrepresent the protocol relationship.

Receive processing stores a ``WebmentionSourceSnapshot`` row related
one-to-one to each submitted ``Webmention`` after normal verified processor
processing succeeds. The snapshot stores the latest fetched source HTML, the
final URL after redirects, a SHA-256 content digest, the fetch time, a
normalized parsed representation of the mentioning parent ``h-entry``, and the
set of known nested response identities found inside that entry. Raw HTML is
stored so a Salmention receiver can compare a newly fetched source with
previously stored source contents; the normalized parsed snapshot is stored so
comparisons do not depend only on byte-for-byte HTML changes.

Snapshot writes are intentionally non-destructive. A later source failure,
``410 Gone`` response, non-HTML response, missing target link, Vouch failure, or
spam classification marks the parent ``Webmention`` failed or spam as before
but does not clear or replace the last successful source snapshot or create
child rows from the failed source. A later verified reprocessing updates the
same snapshot row rather than creating a second submitted ``Webmention`` row.
If a source snapshot cannot be stored after otherwise successful verification,
the processor logs the snapshot failure and leaves the parent Webmention
verified.

Because snapshots store the raw HTML from the last successful source fetch,
database storage grows with the size of those source documents. Operators that
receive large volumes of Webmentions should account for that table in normal
database retention and backup planning.

Verified processing also stores ``WebmentionNestedResponse`` rows for stable
nested ``h-entry`` descendants found inside the mentioning parent ``h-entry``.
The processor reads the previous snapshot's nested identity set before storing
the current snapshot, then creates or updates one child row per stable current
identity. Existing children for the same parent and identity are updated in
place rather than duplicated. Children that were previously stored but no
longer appear in the latest verified source are marked ``missing`` without
deleting historical author/content fields. Child synchronization happens only
after the parent ``Webmention`` has been saved as ``verified``.

Child writes follow the same non-destructive failure stance as source
snapshots. If child response synchronization fails after otherwise successful
parent verification, the processor logs the child sync failure and leaves the
parent Webmention verified. The failed child sync does not clear the previous
source snapshot or any previously stored child rows.

When a stable child is seen again, its stored display fields are refreshed from
the latest parsed nested ``h-entry``. If the latest verified parse omits
content, author, ``published``, or reply/like/repost properties, the stored
child fields are cleared or fall back to ``mention`` rather than preserving
older current values. Child rows therefore represent the latest verified nested
snapshot, not a historical maximum of every field ever seen.

Queued processing keeps the async receive boundary. When
``INDIEWEB_WEBMENTION_ENQUEUE`` is configured, the receive endpoint validates
the request, creates or reuses the submitted ``Webmention`` row, enqueues the
row ID, and returns without fetching the source, parsing microformats2, running
spam or Vouch checks, writing source snapshots, comparing nested identities, or
writing child response rows. Snapshot and child writes happen only when
``WebmentionProcessor`` runs synchronously or through worker paths such as
``process_queued_webmention()``.

Nested response identity extraction is conservative in this foundation slice.
Nested ``h-entry`` descendants inside the mentioning parent ``h-entry`` are
recorded only when a stable identity is available: URL-valued ``uid`` is
preferred, then URL-valued ``url``, then an HTML ``id`` resolved against the
final fetched source URL. Entries without a stable identity are not stored in
the identity set, and no child response rows are created for them.

Nested responses are stored in ``WebmentionNestedResponse``, a child model
related to the submitted parent ``Webmention``. Each child row captures the
stable identity key, a response URL when one can be extracted, author fields,
content fields, published date, mention type, first-seen/last-seen timestamps,
a ``verified_at``-equivalent timestamp, current status, a compact parsed
snapshot of the nested ``h-entry``, and a digest of that parsed snapshot for
change detection. Child mention types use the same ``mention``, ``like``,
``reply``, and ``repost`` vocabulary as top-level ``Webmention`` rows. Child
rows are unique per parent Webmention and stable response key. Reusing
``Webmention`` for these child responses is not appropriate because the nested
source normally links to the intermediate source, not necessarily to the
original target URL, and should not share the ``source_url``/``target_url``
uniqueness contract for submitted Webmentions.

Response identity should be derived conservatively. Prefer an explicit
microformats2 identity such as a URL-valued ``uid`` or ``url`` property, then an
HTML ``id`` resolved against the parent source's final fetched URL. A content
digest can be stored for change detection, but it should not be the primary
deduplication key because edits to a nested reply would otherwise create a new
child response. Entries without a stable identity should not be promoted to
durable child rows until the implementation defines an operator-visible policy
for unstable responses.

Status, spam, and moderation are stored independently for child responses, but
current displayability still depends on the parent ``Webmention`` remaining
verified. A child found inside a verified parent source starts as verified, but
if it later disappears from the parent source snapshot it stops being currently
verified without deleting historical author/content fields. If the parent later
becomes ``failed`` or ``spam`` because the source is gone, no longer links to
the target, fails Vouch, or is reclassified by the spam checker, child
``is_currently_displayable`` returns false until a later verified parent
reprocessing confirms the child again. Child rows are created or updated only
after the parent source has passed target-link verification, required Vouch
checks, and spam classification.

For bulk rendering or moderation queries, prefer filtering on both child and
parent state, for example ``WebmentionNestedResponse.objects.filter(status="verified",
webmention__status="verified").select_related("webmention")``. The bundled
``show_webmentions`` path prefetches verified child responses for rendering so
templates avoid checking parent status one child at a time.

Child spam classification does not call the configured parent
``SpamChecker.check(webmention)`` API in this slice. A future implementation
should either pass a temporary ``Webmention``-shaped value populated from the
child's parsed fields to that API, or introduce and document a child-aware spam
checker hook before using child rows for moderation. Vouch metadata remains
attached to the submitted parent Webmention only. A submitted ``vouch`` proves
trust for the Webmention source; it does not directly verify every nested
response embedded inside that source.

Display/query support exposes verified child responses as inline responses under
their parent reply Webmention. ``show_webmentions`` continues querying verified
top-level ``Webmention`` rows by ``target_url`` and prefetches verified children
for those rows. The default top-level ordering remains based on the parent
Webmention's ``published`` or ``created`` timestamp; child responses render
under their parent ordered by their own ``published`` timestamp, falling back to
``first_seen_at``. ``webmention_count`` keeps its current top-level counting
semantics for backwards compatibility. If nested-inclusive counts are needed,
they should be added through an explicit new API rather than changing this tag.

Rendering deduplicates a nested child that is also represented by a top-level
``Webmention`` to the same target. Storage may keep the child row as evidence of
the parent's nested source snapshot, but display prefers the direct top-level
Webmention row and suppresses the duplicate inline child when the child
``identity`` or ``response_url`` matches a verified top-level ``source_url`` for
the same target. This suppression is type-agnostic: a direct top-level response
can suppress a duplicate inline child even when ``show_webmentions`` is filtered
to a different mention type. When the same stable child identity is discovered
under more than one displayed parent for the same target, ``show_webmentions``
renders that child only under the first parent in the existing top-level
ordering and suppresses the later inline copies.

Queued processing must keep the existing async receive boundary. The endpoint
should continue to validate, create or reuse the submitted ``Webmention`` row,
enqueue the row ID, and return without fetching the source, parsing
microformats2, running spam or Vouch checks, or comparing Salmention snapshots.
Nested-response comparison lives in ``WebmentionProcessor`` and therefore in
``process_queued_webmention()``, management commands, or explicit worker helper
APIs that call the processor.

This design deliberately keeps outbound Salmention changes in focused
implementation slices so ordinary Webmention behavior, Vouch verification,
duplicate reprocessing semantics, and existing template output remain stable
unless those primitives are added together with tests and documentation.

Target URL Matching
===================

When receiving a Webmention, django-indieweb fetches the source page and
verifies that it links to the submitted ``target`` URL before marking the
Webmention as verified. Target verification parses HTML ``href`` attributes
from the source page and compares them with a conservative canonical URL
matching policy. The stored ``Webmention.source_url`` and
``Webmention.target_url`` remain the submitted values; canonicalization is
used only while matching.

The same matching policy is also used when parsing microformats2 target
properties such as ``u-in-reply-to``, ``u-like-of``, and ``u-repost-of``, so
reply/like/repost classification still works when the source page uses a
common URL variant.

Supported matching variants:

* URL fragments are ignored, so ``https://mysite.com/post#comments`` matches
  ``https://mysite.com/post``.
* URL scheme and host case are ignored, while path case remains significant.
* A leading ``www.`` hostname is treated as equivalent to the bare hostname.
* One trailing slash on non-root paths is treated as equivalent.
* Query parameters are compared independent of order. Duplicate query
  key/value pairs are preserved and must still match.

The receiver does not resolve relative source links during target verification,
does not follow redirects as part of this matching step, and does not broaden
endpoint domain validation. The submitted ``target`` must still pass the
Webmention endpoint's domain check before processing begins. Userinfo and
explicit ports, if present, must match exactly; default ports are not
normalized away.

HTTP Redirects
==============

django-indieweb follows HTTP redirects explicitly for Webmention network
requests. Redirect handling is bounded to 5 redirects per request and only
continues to ``http`` and ``https`` URLs. Redirect chains that exceed the
limit, redirect to another scheme, loop until the limit is reached, or raise a
network/client error are treated as request failures.

Receive-side source fetches follow redirects before validating the source
document. The submitted ``Webmention.source_url`` and ``Webmention.target_url``
are preserved exactly as submitted, but the final fetched source URL is used as
the microformats2 parsing base URL. This means relative author and photo URLs
from a redirected source page resolve against the page that actually returned
the HTML.

After redirects, the receive-side source response must still be HTTP ``200``
with a ``text/html`` content type and must link to the submitted target under
the target matching policy above. A final ``410 Gone``, non-``200`` response,
non-HTML response, missing target link, unsupported redirect, or excessive
redirect chain marks the Webmention ``failed`` through the same failed-state
path described below.

Send-side endpoint discovery follows redirects for both the initial ``HEAD``
request and the fallback ``GET`` request. Relative Webmention endpoints found
in ``Link`` headers or HTML ``<link rel="webmention">`` / ``<a
rel="webmention">`` elements are resolved against the final target page URL
after redirects, not the originally requested URL.

When sending outgoing Webmentions, source-content fetches also follow the same
bounded redirect policy. Endpoint delivery ``POST`` requests follow redirects
with the original ``POST`` method and ``source``/``target`` form payload
preserved for every followed redirect status (``301``, ``302``, ``303``,
``307``, and ``308``). The final endpoint response is considered successful
only when it returns HTTP ``200``, ``201``, or ``202``; redirect errors return
the existing ``{"success": False, ...}`` result shape.

Authorship Extraction
=====================

When a received Webmention source page contains microformats2, django-indieweb
extracts author details for the selected ``h-entry`` with a local/same-page
authorship fallback chain:

* Explicit ``author`` data on the ``h-entry`` has priority. Nested ``h-card``
  author data is used directly, and URL-valued ``author`` references are
  resolved to matching ``h-card`` items already present in the fetched source
  document. Same-page author ``h-card`` URL matching uses the same
  conservative URL policy described in `Target URL Matching`_, so common
  variants such as fragments, scheme/host case, a leading ``www.``, one
  non-root trailing slash, and query-parameter ordering do not prevent a local
  h-card match.
* If the ``h-entry`` has no explicit author, ``rel=author`` links are resolved
  against the final fetched source URL and matched to ``h-card`` items already
  present in the same parsed document using that same conservative URL policy.
  Same-page fragment links such as ``href="#author"`` can match an ``h-card``
  with the corresponding HTML ``id``.
* If neither explicit author data nor ``rel=author`` yields an author, a single
  unambiguous page-level ``h-card`` outside the ``h-entry`` is used as a
  fallback author. If multiple page-level ``h-card`` items are present, no
  fallback author is guessed.
* If an explicit URL-valued author reference has no matching ``h-card``, the
  resolved author URL is stored as both the author URL and display name for
  backwards compatibility.

Relative author URLs and photo URLs resolve against the final fetched source
URL, not the originally submitted source URL when redirects occurred. If the
resulting author URL matches a local ``Profile`` URL on the configured Django
``Site`` domain, the local profile's name, URL, and photo override the parsed
source-page author fields.

django-indieweb does not fetch remote author pages during Webmention receiving.
``rel=author`` support is limited to author ``h-card`` data already available in
the fetched source document.

Reprocessing and Source Removal
===============================

Incoming Webmentions are keyed by the submitted ``source`` and ``target`` URLs.
When the same pair is processed again, django-indieweb updates the existing
``Webmention`` row rather than creating a duplicate.

If a previously verified source returns ``410 Gone`` during reprocessing, the
row is marked ``failed`` and ``verified_at`` is cleared. The submitted
``source_url`` and ``target_url`` are preserved, and previously parsed fields
such as author, content, HTML content, mention type, and published date are
left intact so applications can keep historical display or moderation context.

The same failed-state update is used when a source fetch succeeds with
``text/html`` but the source page no longer links to the submitted target. This
represents a removed Webmention: it is no longer considered currently verified,
but the stored parsed fields are not destructively cleared.

Other processing failures, including non-``200`` responses, non-HTML responses,
and fetch errors, also mark the Webmention ``failed`` and clear ``verified_at``.
Those failures are not treated as explicit source-removal signals in the
documentation because they may be transient. If the source later returns valid
HTML that links to the target again, reprocessing can mark the existing row
``verified`` and assign a fresh ``verified_at`` timestamp.

Spam reclassification also clears ``verified_at``. The source may still link to
the target, but a ``spam`` row is not advertised as currently verified, and
previously parsed author, content, published, and mention-type fields are
preserved.

Using Webmention.io Alongside django-indieweb
=============================================

Webmention.io can be useful for host projects that want an external
collection/display service, but it is an optional host integration choice. It
is not a missing django-indieweb core endpoint and it does not replace the
built-in receive/send Webmention support described above.

If a site wants package-managed receiving, keep advertising django-indieweb's
``/indieweb/webmention/`` endpoint. That endpoint validates submitted
``source`` and ``target`` values, can process synchronously or enqueue via
``INDIEWEB_WEBMENTION_ENQUEUE``, fetches and verifies source pages in
``WebmentionProcessor``, parses Microformats2, classifies ``mention``,
``like``, ``reply``, and ``repost`` rows, runs configured spam/Vouch checks,
stores source snapshots and nested responses, and exposes status URLs. The
bundled sender workflows are unaffected.

A host project that wants Webmention.io collection instead can advertise
Webmention.io's endpoint on selected pages instead of rendering
``{% webmention_endpoint_link %}`` for those pages. That means incoming
Webmentions for those pages are collected by Webmention.io, not processed by
django-indieweb's receiver. The host owns any Webmention.io account setup,
token storage, API client, polling, caching, moderation, display templates, and
documentation. django-indieweb does not ship a Webmention.io endpoint, API
client, token setting, import command, dashboard, scheduled sync, model, parser,
queue integration, or display tag.

Hosts may also fetch Webmention.io JF2 data from their own code and display it
alongside verified django-indieweb ``Webmention`` rows. Keep that display layer
separate unless you deliberately choose an import policy. A common host-owned
shape is:

.. code-block:: python

    # myapp/webmention_io.py
    from indieweb.models import Webmention

    def webmention_io_items_for_target(target_url: str) -> list[dict]:
        """Fetch/cache Webmention.io JF2 in host code, then filter by target."""
        ...

    def responses_for_template(target_url: str) -> dict[str, list]:
        return {
            "django_indieweb": Webmention.objects.filter(
                target_url=target_url,
                status="verified",
            ),
            "webmention_io": webmention_io_items_for_target(target_url),
        }

If a host imports Webmention.io data into django-indieweb's built-in
``Webmention`` model, it owns deduplication against rows created by the
built-in endpoint, target ownership checks, moderation, status assignment,
source/author URL validation, sanitization, and reconciliation when Webmention.io
data changes. Imported rows should not be presented as verified by
django-indieweb's processor unless the host has a clear verification policy or
has reprocessed them through the built-in receive/processor flow. A separate
host-owned model is often cleaner when the site wants to preserve Webmention.io
metadata or distinguish service-originated display data from processor-verified
``Webmention`` rows.

JF2 Mapping Guidance
--------------------

Webmention.io JF2 fields are external display/import inputs, not a
django-indieweb storage contract. Hosts should tolerate missing fields and map
only the values their UI or import policy needs.

Common mappings:

* ``url`` is the canonical source URL; ``wm-source`` may also be present as a
  meta field.
* ``wm-target`` can be treated as the target URL concept.
* ``author.name``, ``author.url``, and ``author.photo`` can feed author display
  fields after validation and escaping.
* ``content.text`` can feed plain-text display.
* ``content.html`` can feed HTML display only after host sanitization.
* ``published`` and ``wm-received`` can feed display ordering, with a host-owned
  fallback policy when either value is missing or malformed.

For ``wm-property`` values, use django-indieweb's built-in vocabulary only when
it fits:

* ``in-reply-to`` -> ``reply``
* ``like-of`` -> ``like``
* ``repost-of`` -> ``repost``
* unknown values -> ``mention`` or a host-owned type

``bookmark-of`` and ``rsvp`` need explicit host-owned handling if the site
wants to preserve them distinctly. The built-in ``Webmention.mention_type`` and
``WebmentionNestedResponse.mention_type`` choices do not include ``bookmark`` or
``rsvp``. These values fall under the unknown bucket above; falling back to
``mention`` is lossy, while preserving them requires a separate host model,
separate display field, or another host-owned extension.

Safety and Trust
----------------

Treat Webmention.io JF2 as untrusted external content. In particular,
``content.html`` must be sanitized before rendering, and before storing it in
any field that a template later renders as trusted HTML. The bundled
django-indieweb processor sanitizes verified incoming Webmention
``content_html`` and nested-response ``content_html`` before storing it, and
the bundled ``show_webmentions`` tag sanitizes those fields again before
rendering so older stored rows cannot bypass the display policy. Hosts that
import external JF2 into built-in ``content_html`` fields directly should still
sanitize first so non-bundled queries, APIs, admin views, or custom rendering
paths do not encounter unsafe stored HTML. Links and citation URLs inside
sanitized remote HTML are kept only when they are absolute ``http://`` or
``https://`` URLs; relative URLs are dropped so remote content cannot render
same-origin-looking links.

Validate source URLs, author URLs, author photos, and target URLs before
storing or linking them. Processor-owned Webmention author URLs and author
photos are restricted to absolute ``http://`` and ``https://`` values; unsafe
or malformed remote values are stored and rendered as blank. The bundled
Webmention templates render external author/source links with
``rel="nofollow noopener ugc"`` and ``referrerpolicy="no-referrer"``. Keep
moderation decisions explicit. Webmention.io collection confirms that the
service collected a
mention for the domain; it does not mean django-indieweb fetched the source,
verified the target link, ran configured spam/Vouch checks, stored processor
snapshots, or synchronized nested response rows.

Template Usage
==============

Basic Usage
-----------

.. code-block:: django

    {% load webmention_tags %}

    {# Add endpoint discovery to your base template #}
    {% webmention_endpoint_link %}

    {# Show all webmentions for current page #}
    {% show_webmentions request.build_absolute_uri %}

    {# Verified nested child responses render inline under verified parent replies #}

    {# Show only replies #}
    {% show_webmentions request.build_absolute_uri mention_type="reply" %}

    {# Get top-level webmention count #}
    {% webmention_count request.build_absolute_uri as count %}
    <p>This post has {{ count }} responses.</p>

Custom Templates
----------------

You can override the default templates by creating your own:

* ``indieweb/webmentions.html`` - Main container
* ``indieweb/webmention_types/like.html`` - Like template
* ``indieweb/webmention_types/reply.html`` - Reply template
* ``indieweb/webmention_types/nested_response.html`` - Nested child response template
* ``indieweb/webmention_types/repost.html`` - Repost template
* ``indieweb/webmention_types/mention.html`` - Generic mention template

Custom templates that render built-in ``Webmention.content_html`` or
``WebmentionNestedResponse.content_html`` should use rows prepared by
``show_webmentions`` or apply the same sanitizer before marking HTML safe.
Custom outbound links to Webmention authors, source pages, and nested response
URLs should preserve the bundled ``rel="nofollow noopener ugc"`` and
``referrerpolicy="no-referrer"`` attributes unless the host has a stricter
site policy.

Management Commands
===================

send_webmentions
----------------

Send webmentions for all links in a post:

.. code-block:: bash

    # Send webmentions for a URL
    python manage.py send_webmentions https://mysite.com/new-post/

    # Provide content directly
    python manage.py send_webmentions https://mysite.com/new-post/ \
        --content '<p>Check out <a href="https://example.com">this site</a>!</p>'

    # Include a Vouch URL
    python manage.py send_webmentions https://mysite.com/new-post/ \
        --vouch https://trusted.example/vouch-for-mysite

    # Dry run to see what would be sent
    python manage.py send_webmentions https://mysite.com/new-post/ --dry-run

    # Resend Salmentions to current and exact-source historical targets
    python manage.py send_webmentions https://mysite.com/new-post/ \
        --salmention-resend

    # Preview the Salmention resend target union with provenance labels
    python manage.py send_webmentions https://mysite.com/new-post/ \
        --salmention-resend --dry-run

Signals
=======

The ``webmention_received`` signal is sent when a webmention is processed:

.. code-block:: python

    from django.dispatch import receiver
    from indieweb.signals import webmention_received

    @receiver(webmention_received)
    def handle_webmention(sender, webmention, created, **kwargs):
        if created and webmention.status == 'verified':
            # Send notification, update cache, etc.
            print(f"New webmention from {webmention.source_url}")

Models
======

The ``Webmention`` model stores all webmention data:

.. code-block:: python

    from indieweb.models import Webmention

    # Get all verified webmentions for a URL
    webmentions = Webmention.objects.filter(
        target_url='https://mysite.com/post/',
        status='verified'
    )

    # Get webmentions by type
    likes = webmentions.filter(mention_type='like')
    replies = webmentions.filter(mention_type='reply')

Fields:

* ``source_url`` - The URL that links to your content
* ``target_url`` - Your URL that was linked to
* ``vouch_url`` - Optional Vouch URL submitted with the Webmention
* ``status`` - pending, verified, failed, or spam
* ``mention_type`` - mention, like, reply, or repost
* ``author_name``, ``author_url``, ``author_photo`` - Author info. Processor-owned
  remote author URLs/photos are stored only when they are absolute HTTP(S) URLs.
* ``content``, ``content_html`` - The mention content. Processor-owned rich HTML
  is stored as an allowlist-sanitized fragment.
* ``published`` - When the mention was published
* ``created``, ``modified`` - Timestamps
* ``verified_at`` - When the mention was verified
* ``vouch_verified_at`` - When the configured Vouch check succeeded
* ``spam_check_result`` - JSON field with spam check details

``WebmentionNestedResponse`` stores stable nested ``h-entry`` responses found
inside a verified parent ``Webmention`` source. Rows are unique per parent
``Webmention`` and stable identity key, store extracted author/content/type
fields plus parsed child snapshots and digests, and use ``status`` plus the
parent ``Webmention.status`` to decide current displayability. The bundled
``show_webmentions`` tag renders verified child rows inline under verified
parent replies, while ``webmention_count`` remains top-level-only.

Testing Webmentions
===================

You can test your webmention implementation using webmention.rocks:

1. Visit https://webmention.rocks/
2. Follow the test suite to verify your implementation
3. Use the discovery tests to check endpoint detection
4. Use the receiving tests to verify your endpoint

Troubleshooting
===============

Common issues and solutions:

**Webmentions not being received**
  - Check that your webmention endpoint is discoverable
  - Verify the endpoint URL is correct in your Link header/tag
  - Check Django logs for any errors

**Target URL validation failing**
  - Ensure ``django.contrib.sites`` is configured correctly
  - Check that the Site domain matches your production domain

**Microformats not being parsed**
  - Verify the source page has proper microformats2 markup
  - Use a validator like https://indiewebify.me/

**Author name shows as URL or profile picture is missing**
  - The source page may use URL references for author data (e.g., ``<data class="p-author" value="https://example.com/author"></data>``)
  - This is valid microformats2 markup following the authorship algorithm
  - Django-indieweb automatically looks for a matching h-card **on the same page** with the referenced URL
  - If the entry has no explicit author, same-page ``rel=author`` links and one unambiguous page-level h-card can also provide author data
  - Ensure the source page includes a same-page h-card whose ``u-url`` matches
    the referenced URL under the canonical matching policy above; name and
    photo properties are used when present
  - The h-card may be nested in structures like h-feeds - the parser searches recursively
  - Example services using this pattern: feed.city, some Mastodon webmention bridges
  - If no matching h-card is found, the URL will be displayed as the name (fallback behavior)
  - **Limitation**: Django-indieweb does not currently fetch remote author URLs; author data must be present in the fetched source document

**Spam checker rejecting valid webmentions**
  - Review your spam checker implementation
  - Check the ``spam_check_result`` field for details

API Reference
=============

See :doc:`api` for detailed API documentation of all webmention-related classes and functions.
