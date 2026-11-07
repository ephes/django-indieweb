"""Disposable PostgreSQL settings for synthetic state-transition CI tests."""

import os

from tests.settings import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "indieweb_synthetic",
        "USER": "synthetic",
        "PASSWORD": "synthetic",
        "HOST": "127.0.0.1",
        "PORT": os.environ.get("INDIEWEB_TEST_POSTGRES_PORT", "5432"),
    },
}

# Separate synthetic database for routed diagnostic rollback tests.
DATABASES["other"] = {**DATABASES["default"], "NAME": "indieweb_synthetic_other"}
