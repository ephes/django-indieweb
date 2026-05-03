WebSub Publisher Support
========================

Overview
--------

django-indieweb provides publisher-side WebSub helpers for Django applications
that own their own feeds or topic resources. It does not run a WebSub hub and
does not provide subscriber callback persistence.

This shape fits reusable Django apps: your project decides which pages or feeds
are WebSub topics, renders those resources, and calls django-indieweb helpers to
advertise hub discovery links and notify hubs after content changes.

WebSub publisher flow
---------------------

1. Configure one or more hub URLs with ``INDIEWEB_WEBSUB_HUBS`` or pass hub URLs
   explicitly to the helper you call.
2. Add WebSub discovery links to each topic response:

   - one ``rel="hub"`` link for each hub
   - exactly one ``rel="self"`` link for the canonical topic URL

3. Notify each hub after the topic changes.

Discovery in Templates
----------------------

Load ``websub_tags`` and place the generated links in the HTML ``head`` of the
topic page or feed template:

.. code-block:: django

   {% load websub_tags %}
   {% websub_link_tags "https://example.com/feed/" %}

With ``INDIEWEB_WEBSUB_HUBS = ("https://hub.example/",)`` this renders:

.. code-block:: html

   <link rel="hub" href="https://hub.example/">
   <link rel="self" href="https://example.com/feed/">

You can also pass hubs explicitly:

.. code-block:: django

   {% load websub_tags %}
   {% websub_link_tags "https://example.com/feed/" "https://hub.example/" %}

If no hub is configured or passed, the tag raises ``ValueError``. That prevents
a template from silently rendering an invalid WebSub publisher advertisement.

Discovery in HTTP Headers
-------------------------

Use ``add_websub_link_header()`` when you control the view response:

.. code-block:: python

   from django.http import HttpResponse
   from indieweb.websub import add_websub_link_header

   def feed(request):
       topic_url = request.build_absolute_uri("/feed/")
       response = HttpResponse(render_feed(), content_type="application/atom+xml")
       add_websub_link_header(response, topic_url)
       return response

The helper appends to an existing ``Link`` header if one is already present.
Use ``websub_link_header(topic_url)`` if you need the combined header value
without mutating a response.

Notifying Hubs
--------------

Call ``notify_hubs(topic_url)`` after publishing, updating, or deleting content
that changes a topic:

.. code-block:: python

   from indieweb.websub import notify_hubs

   results = notify_hubs("https://example.com/feed/")
   for result in results:
       if not result.success:
           logger.warning("WebSub notification failed: %s", result)

The helper sends ``application/x-www-form-urlencoded`` POST requests with
``hub.mode=publish`` and ``hub.url=<topic_url>`` to each configured hub. This is
the publisher notification shape documented by the WebSub Recommendation for
existing public hubs.

``notify_hubs()`` returns one result per attempted hub. Network failures and
non-2xx hub responses are captured in the result instead of being raised, so
host applications can log, retry, or ignore individual failures without
crashing their publish workflow. Configuration and validation errors, such as
malformed topic or hub URLs, raise ``ValueError`` before any network request is
made.

When no hubs are configured or passed, ``notify_hubs()`` returns an empty list
without opening an HTTP client. If you inject a custom ``httpx.Client`` into
``notify_hubs()`` for testing or integration, that trusted client controls its
own redirect behavior; the package-created client uses ``follow_redirects=False``.

Management Command
------------------

You can notify hubs from a deployment hook, cron job, or manual operation:

.. code-block:: bash

   python manage.py notify_websub https://example.com/feed/

Pass hubs explicitly with repeated ``--hub`` options:

.. code-block:: bash

   python manage.py notify_websub https://example.com/feed/ \
       --hub https://hub.example/ \
       --hub https://backup.example/websub

The command exits with a Django ``CommandError`` for invalid URLs or when no
hub is configured. Individual hub failures are printed but do not abort
notification of later hubs.

Security and Compatibility Notes
--------------------------------

WebSub is server-to-server. Prefer HTTPS topic and hub URLs, and avoid leaking
private or draft topic URLs to public hubs. django-indieweb performs no network
calls unless your application explicitly calls ``notify_hubs()`` or you run the
``notify_websub`` command.

This publisher slice does not implement subscriber callback verification,
lease tracking, authenticated content-distribution signature validation, or a
hub service. Those roles require application-specific callback URLs,
persistence, worker, and content-distribution policies that django-indieweb
does not assume for host projects.
