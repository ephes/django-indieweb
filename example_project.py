#!/usr/bin/env python
"""
Development-only Django smoke-test project for django-indieweb.

WARNING: THIS FILE IS A DEVELOPMENT/SMOKE-TEST HARNESS. DO NOT COPY THIS
SETTINGS FILE INTO A PRODUCTION DEPLOYMENT.

It binds to ``localhost``, requires an explicit ``DJANGO_SECRET_KEY``
environment variable (refusing to start with the unsafe development
sentinel unless ``ALLOW_UNSAFE_DEV_SECRET=1`` is set), and never
auto-creates a superuser. Create one explicitly with
``python example_project.py createsuperuser``.

Run with: ``python example_project.py runserver``
"""

import os
import sys
from pathlib import Path

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Django settings
from django.conf import settings  # noqa: E402

UNSAFE_DEV_SECRET = "unsafe-development-secret-do-not-use"  # noqa: S105

_secret_key_from_env = os.environ.get("DJANGO_SECRET_KEY")
if _secret_key_from_env:
    SECRET_KEY = _secret_key_from_env
else:
    if os.environ.get("ALLOW_UNSAFE_DEV_SECRET") != "1":
        sys.stderr.write(
            "example_project.py refuses to start without DJANGO_SECRET_KEY.\n"
            "Set DJANGO_SECRET_KEY in the environment, or set\n"
            "ALLOW_UNSAFE_DEV_SECRET=1 to opt into the unsafe development\n"
            "sentinel for local smoke-testing only.\n"
        )
        raise SystemExit(2)
    sys.stderr.write(
        "WARNING: example_project.py is using the UNSAFE development SECRET_KEY.\n"
        "Never run this configuration on a public host.\n"
    )
    SECRET_KEY = UNSAFE_DEV_SECRET

_allowed_hosts_env = os.environ.get("DJANGO_ALLOWED_HOSTS")
if _allowed_hosts_env:
    ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_env.split(",") if h.strip()]
else:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

settings.configure(
    DEBUG=True,
    SECRET_KEY=SECRET_KEY,
    ROOT_URLCONF=__name__,
    ALLOWED_HOSTS=ALLOWED_HOSTS,
    INSTALLED_APPS=[
        "django.contrib.admin",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django.contrib.staticfiles",
        "django.contrib.sites",
        "indieweb",
    ],
    MIDDLEWARE=[
        "django.middleware.security.SecurityMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ],
    DATABASES={
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": "test_webmentions.db",
        }
    },
    TEMPLATES=[
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [],
            "APP_DIRS": True,
            "OPTIONS": {
                "context_processors": [
                    "django.template.context_processors.debug",
                    "django.template.context_processors.request",
                    "django.contrib.auth.context_processors.auth",
                    "django.contrib.messages.context_processors.messages",
                ],
            },
        },
    ],
    STATIC_URL="/static/",
    USE_TZ=True,
    SITE_ID=1,
    DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
    # IndieWeb settings
    INDIEWEB_SCHEME="http",
    INDIEWEB_DOMAIN="localhost:8000",
)

# Initialize Django before importing app registries/URLs
import django  # noqa: E402

django.setup()

# URL configuration
from django.contrib import admin  # noqa: E402
from django.http import HttpResponse  # noqa: E402
from django.template import Context, Template  # noqa: E402
from django.urls import include, path  # noqa: E402


def test_page(request):
    """A test page that can receive webmentions."""
    template = Template("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Webmention Page</title>
        {% load webmention_tags %}
        {% webmention_endpoint_link %}
    </head>
    <body>
        <h1>Test Webmention Page</h1>
        <p>This page can receive webmentions! The endpoint is at /webmention/</p>

        <h2>Send a test webmention:</h2>
        <pre>
curl -X POST http://{{ request.get_host }}/webmention/ \\
  -d "source=https://example.com/your-post" \\
  -d "target=http://{{ request.get_host }}/"
        </pre>

        <h2>Webmentions for this page:</h2>
        <p>Count: {% webmention_count request.build_absolute_uri %}</p>
        {% show_webmentions request.build_absolute_uri %}

        <hr>
        <p><a href="/admin/">Django Admin</a> | <a href="/webmention/">Webmention Endpoint</a></p>
    </body>
    </html>
    """)
    return HttpResponse(template.render(Context({"request": request})))


urlpatterns = [
    path("", test_page, name="home"),
    path("admin/", admin.site.urls),
    path("", include("indieweb.urls")),
]


def migrate_if_needed() -> None:
    """Apply pending migrations if any."""
    from django.core.management import execute_from_command_line
    from django.db import connections
    from django.db.migrations.executor import MigrationExecutor

    connection = connections["default"]
    try:
        executor = MigrationExecutor(connection)
    except Exception:
        execute_from_command_line(["manage.py", "migrate"])
        return

    targets = executor.loader.graph.leaf_nodes()
    plan = executor.migration_plan(targets)
    if plan:
        print("Applying pending migrations...")
        execute_from_command_line(["manage.py", "migrate"])


# Django setup and run
if __name__ == "__main__":
    from django.core.management import execute_from_command_line

    # Run migrations if needed
    migrate_if_needed()

    print("\n*** DEVELOPMENT-ONLY CONFIGURATION ***")
    print("This example_project.py is for local smoke-testing only.")
    print("Create an admin user manually with:\n  python example_project.py createsuperuser")
    print("Visit http://localhost:8000/ to test webmentions")
    print("Admin interface: http://localhost:8000/admin/\n")

    execute_from_command_line(sys.argv if len(sys.argv) > 1 else ["manage.py", "runserver"])
