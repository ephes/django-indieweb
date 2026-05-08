=======
H-Cards
=======

H-card is a microformat for representing people and organizations on the web. Django-indieweb provides models, template tags, and utilities for managing and displaying h-card data.

Features
========

* **Profile model**: Store h-card data with flexible JSON storage
* **Template tags**: Render h-cards with proper microformat markup
* **Admin interface**: Edit h-card data with a user-friendly JSON editor
* **Parsing utilities**: Extract h-card data from HTML
* **Validation**: Ensure h-card data follows microformats2 specifications

Quick Start
===========

1. Create a profile for your users:

.. code-block:: python

    from django.contrib.auth import get_user_model
    from indieweb.models import Profile

    User = get_user_model()
    user = User.objects.get(username='alice')

    profile = Profile.objects.create(
        user=user,
        name="Alice Johnson",
        photo_url="https://example.com/alice.jpg",
        url="https://example.com",
        h_card={
            "name": ["Alice Johnson"],
            "photo": ["https://example.com/alice.jpg"],
            "url": ["https://example.com", "https://social.example/@alice"],
            "email": ["alice@example.com"],
            "note": ["Web developer and IndieWeb enthusiast"],
            "adr": [{
                "locality": "Portland",
                "region": "OR",
                "country-name": "USA"
            }]
        }
    )

2. Display the h-card in your templates:

.. code-block:: django

    {% load indieweb_tags %}

    <div class="author-info">
        {% h_card user %}
    </div>

This will render a properly formatted h-card with microformats2 markup.

Profile Model
=============

The ``Profile`` model stores h-card data for users:

.. code-block:: python

    class Profile(models.Model):
        user = models.OneToOneField(settings.AUTH_USER_MODEL, ...)
        h_card = models.JSONField(default=dict, blank=True)

        # Common fields for quick access
        name = models.CharField(max_length=200, blank=True)
        photo_url = models.URLField(blank=True)
        url = models.URLField(blank=True)

The ``h_card`` field stores all h-card properties as JSON, following the microformats2 structure where all values are arrays.

.. note::
   The common fields (``name``, ``photo_url``, ``url``) are automatically synchronized with the h_card data when saving. If you update the h_card JSON, these fields will be updated automatically.

Property Name Normalization
---------------------------

When h-card data is parsed or displayed in templates, property names containing hyphens are automatically converted to underscores for Django template compatibility:

* ``country-name`` → ``country_name``
* ``street-address`` → ``street_address``
* ``postal-code`` → ``postal_code``

This happens automatically in:

* The ``parse_h_card()`` function
* The ``{% h_card %}`` template tag
* The ``normalize_h_card()`` function

When storing h-card data in the database, you can use either format - both will work correctly.

H-Card Properties
-----------------

Common h-card properties you can store:

* ``name``: Full name (array of strings)
* ``photo``: Profile photo URLs (array of strings or objects with ``value`` and ``alt`` properties)

  .. code-block:: json

     {
         "photo": [
             "https://example.com/photo1.jpg",
             {"value": "https://example.com/photo2.jpg", "alt": "Profile photo"}
         ]
     }
* ``url``: Personal URLs (array of strings)
* ``email``: Email addresses (array of strings)
* ``tel``: Phone numbers (array of strings)
* ``note``: Biography or description (array of strings)
* ``nickname``: Nicknames or handles (array of strings)
* ``adr``: Addresses (array of address objects)
* ``org``: Organizations (array of organization objects)

Address Format
~~~~~~~~~~~~~~

.. code-block:: json

    {
        "adr": [{
            "street-address": "123 Main St",
            "locality": "Portland",
            "region": "OR",
            "postal-code": "97201",
            "country-name": "USA"
        }]
    }

Organization Format
~~~~~~~~~~~~~~~~~~~

.. code-block:: json

    {
        "org": [{
            "name": "IndieWeb Corp",
            "url": "https://indieweb.example"
        }]
    }

Template Tag
============

The ``h_card`` template tag renders h-card microformats:

.. code-block:: django

    {% load indieweb_tags %}

    {# Render h-card for a user #}
    {% h_card user %}

    {# Render h-card for a profile #}
    {% h_card profile %}

The tag accepts either a User object (which will look up the associated profile) or a Profile object directly.

Rendered HTML Example
---------------------

.. code-block:: html

    <div class="h-card">
        <img class="u-photo" src="https://example.com/alice.jpg" alt="Alice Johnson" referrerpolicy="no-referrer">
        <div class="p-name">Alice Johnson</div>
        <a class="u-url" href="https://example.com" rel="me noopener" referrerpolicy="no-referrer">Profile</a>
        <a class="u-url" href="https://social.example/@alice" rel="nofollow noopener" referrerpolicy="no-referrer">https://social.example/@alice</a>
        <a class="u-email" href="mailto:alice%40example.com">alice@example.com</a>
        <p class="p-note">Web developer and IndieWeb enthusiast</p>
        <div class="p-adr h-adr">
            <span class="p-locality">Portland</span>
            <span class="p-region">OR</span>
            <span class="p-country-name">USA</span>
        </div>
    </div>

The bundled template restricts every interpolated ``href``/``src`` to
``http``/``https`` URLs at render time via the ``h_card_safe_url`` filter.
Unsafe schemes (``javascript:``, ``data:``, ``ftp:``, ``file:``, ``mailto:``)
are dropped silently as a defense-in-depth layer over ``Profile.full_clean()``,
which catches the same cases when a profile is saved via ``Profile.save()`` but
not via bypass paths such as ``QuerySet.update``, ``bulk_update``, raw SQL, or
``loaddata`` fixtures.

Admin Interface
===============

The Profile model includes a Django admin interface with a pretty-printed JSON editor:

.. code-block:: python

    # In your admin.py
    from django.contrib import admin
    from indieweb.models import Profile

    # Profile admin is automatically registered

The admin interface provides:

* User-friendly JSON editing with syntax highlighting
* Quick access fields for common properties (name, photo_url, url)
* Search by username, email, name, and URL
* Filtering by creation and modification dates

Parsing H-Cards
===============

Use the h-card parsing utilities to extract h-card data from HTML:

.. code-block:: python

    from indieweb.h_card import parse_h_card, validate_h_card

    # Parse h-card from HTML
    html = '''
    <div class="h-card">
        <a class="p-name u-url" href="https://example.com">Jane Doe</a>
        <p class="p-note">Software engineer</p>
    </div>
    '''

    h_card_data = parse_h_card(html)
    # Returns: {"name": ["Jane Doe"], "url": ["https://example.com"], "note": ["Software engineer"]}

    # Validate h-card structure
    is_valid = validate_h_card(h_card_data)  # Returns True

Integration with IndieAuth
==========================

H-cards can be used as representative h-cards for IndieAuth:

.. code-block:: django

    {# In your homepage template #}
    <!DOCTYPE html>
    <html>
    <head>
        <link rel="me" href="https://github.com/username">
        <link rel="me" href="https://twitter.com/username">
    </head>
    <body>
        {% load indieweb_tags %}
        {% h_card request.user %}
    </body>
    </html>

The ``rel="me"`` links in the h-card help establish identity for IndieAuth authentication.

Best Practices
==============

1. **Always use arrays**: All h-card properties should be arrays, even for single values:

   .. code-block:: python

       # Correct
       h_card = {"name": ["Alice"]}

       # Incorrect
       h_card = {"name": "Alice"}

2. **Include rel="me"**: Add ``rel="me"`` to the first URL in your h-card for
   IndieAuth identity discovery. The bundled template emits ``rel="me
   noopener"`` on the first emitted safe profile URL and ``rel="nofollow
   noopener"`` on subsequent URLs, with ``referrerpolicy="no-referrer"`` on
   every outbound h-card link and photo:

   .. code-block:: html

       <a class="u-url" href="https://example.com" rel="me noopener" referrerpolicy="no-referrer">Profile</a>

3. **Use semantic markup**: The h-card template uses proper microformats2 classes (``p-name``, ``u-url``, ``u-photo``, etc.)

4. **Validate data**: Use ``validate_h_card()`` before saving h-card data to ensure it follows the correct structure

5. **URL and Email validation**: The Profile model automatically validates URLs
   and email addresses in h_card data when saving. URL fields
   (``h_card.url``, ``h_card.photo``, ``h_card.org.url``, ``Profile.url``,
   ``Profile.photo_url``) are restricted to ``http``/``https`` schemes;
   ``ftp``/``ftps``/``javascript``/``data``/``file``/``mailto`` schemes raise a
   ``ValidationError`` from ``Profile.full_clean()``. The bundled
   ``h-card.html`` template re-applies the same scheme restriction at render
   time so bypass paths (``QuerySet.update``, ``bulk_update``, raw SQL,
   fixtures) cannot leak unsafe URLs into rendered pages.

API Reference
=============

Models
------

.. autoclass:: indieweb.models.Profile
   :members:
   :undoc-members:
   :no-index:

Template Tags
-------------

.. autofunction:: indieweb.templatetags.indieweb_tags.h_card
   :no-index:

Utilities
---------

.. automodule:: indieweb.h_card
   :members:
   :undoc-members:
   :no-index:

Examples
========

Complete Profile Example
------------------------

.. code-block:: python

    from django.contrib.auth import get_user_model
    from indieweb.models import Profile

    User = get_user_model()
    user = User.objects.create_user(username='developer')

    profile = Profile.objects.create(
        user=user,
        name="Dev Person",
        photo_url="https://example.com/dev.jpg",
        url="https://dev.example",
        h_card={
            "name": ["Dev Person"],
            "photo": ["https://example.com/dev.jpg"],
            "url": ["https://dev.example", "https://github.com/devperson"],
            "email": ["dev@example.com", "developer@work.example"],
            "tel": ["+1-555-0123"],
            "note": ["Full-stack developer specializing in Django and IndieWeb protocols"],
            "nickname": ["dev", "developer"],
            "adr": [{
                "street-address": "123 Code Street",
                "locality": "San Francisco",
                "region": "CA",
                "postal-code": "94102",
                "country_name": "USA"
            }],
            "org": [{
                "name": "Tech Startup Inc",
                "url": "https://techstartup.example"
            }]
        }
    )

Custom H-Card Template
----------------------

You can create custom h-card templates by overriding ``indieweb/h-card.html``.
Always route ``href``/``src`` interpolations through the bundled
``h_card_safe_url`` filter (or ``h_card_safe_urls`` when iterating a list) and
keep ``rel`` / ``referrerpolicy`` defenses on outbound links — the bundled
template treats render-time sanitization as a defense-in-depth layer over
``Profile.full_clean()`` and overrides should preserve that:

.. code-block:: django

    {# templates/indieweb/h-card.html #}
    {% load indieweb_tags %}
    <div class="h-card custom-card">
        {% if profile and profile.photo_url %}
            {% with safe_photo=profile.photo_url|h_card_safe_url %}
                {% if safe_photo %}
                    <img class="u-photo avatar"
                         src="{{ safe_photo }}"
                         alt="{{ profile.name|default:user.username }}"
                         referrerpolicy="no-referrer">
                {% endif %}
            {% endwith %}
        {% endif %}

        <h3 class="p-name">{{ profile.name|default:user.username }}</h3>

        {% if h_card.note %}
            <div class="bio">
                {% for note in h_card.note %}
                    <p class="p-note">{{ note }}</p>
                {% endfor %}
            </div>
        {% endif %}

        <div class="links">
            {% for safe_url in h_card.url|h_card_safe_urls %}
                {% if forloop.first %}
                    <a class="u-url"
                       href="{{ safe_url }}"
                       rel="me noopener"
                       referrerpolicy="no-referrer">{{ safe_url }}</a>
                {% else %}
                    <a class="u-url"
                       href="{{ safe_url }}"
                       rel="nofollow noopener"
                       referrerpolicy="no-referrer">{{ safe_url }}</a>
                {% endif %}
            {% endfor %}
        </div>
    </div>

The ``h_card_safe_urls`` filter drops unsafe entries before iteration so
``forloop.first`` keys off the first *emitted* safe URL — preserving
``rel="me"`` for IndieAuth identity discovery even when an earlier raw entry
was filtered out by the sanitizer.
