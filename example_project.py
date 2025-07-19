#!/usr/bin/env python
"""
Simple Django project to test webmentions.
Run with: python example_project.py
"""

import os
import sys
from pathlib import Path

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Django settings
from django.conf import settings

settings.configure(
    DEBUG=True,
    SECRET_KEY="test-secret-key-for-webmentions",
    ROOT_URLCONF=__name__,
    ALLOWED_HOSTS=["*"],
    INSTALLED_APPS=[
        "django.contrib.admin",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django.contrib.staticfiles",
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
    # IndieWeb settings
    INDIEWEB_SCHEME="http",
    INDIEWEB_DOMAIN="localhost:8000",
)

# URL configuration
from django.contrib import admin
from django.http import HttpResponse
from django.template import Context, Template
from django.urls import include, path


def test_page(request):
    """A test page that can receive webmentions."""
    template = Template("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Webmention Page</title>
        {% load webmentions %}
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
        {% webmentions_for request.build_absolute_uri %}

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

# Django setup and run
if __name__ == "__main__":
    import django
    from django.core.management import execute_from_command_line

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "__main__")
    django.setup()

    # Run migrations first if this is the first run
    if not os.path.exists("test_webmentions.db"):
        print("First run - creating database...")
        execute_from_command_line(["manage.py", "migrate"])

        # Create a superuser
        from django.contrib.auth import get_user_model

        User = get_user_model()
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@example.com", "admin")
            print("Created admin user (username: admin, password: admin)")

    print("\nStarting test server...")
    print("Visit http://localhost:8000/ to test webmentions")
    print("Admin interface: http://localhost:8000/admin/ (admin/admin)")

    execute_from_command_line(["manage.py", "runserver"])
