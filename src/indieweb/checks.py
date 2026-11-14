"""Django system checks for django-indieweb security settings.

The checks only read settings; they never query the database.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Error, Tags, Warning, register
from django.core.exceptions import ImproperlyConfigured

from .auth_settings import DEFAULT_TOKEN_EXPIRES_IN, auth_code_timeout_setting, auth_lifetime
from .micropub_urls import CANONICAL_ORIGINS_SETTING, parse_canonical_origins


@register(Tags.security)
def check_micropub_canonical_origins(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    """Report an invalid ``INDIEWEB_MICROPUB_CANONICAL_ORIGINS`` value (it fails closed at runtime)."""
    value = getattr(settings, CANONICAL_ORIGINS_SETTING, None)
    if value is None:
        return []
    try:
        parse_canonical_origins(value)
    except ValueError as exc:
        return [
            Error(
                f"{CANONICAL_ORIGINS_SETTING} is invalid: {exc}.",
                hint='Use http(s) origins without path, query or userinfo, for example "https://example.com".',
                obj=CANONICAL_ORIGINS_SETTING,
                id="indieweb.E001",
            )
        ]
    return []


@register(Tags.security)
def check_websub_unsigned_deliveries(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    """Warn when unsigned WebSub deliveries may reach a configured delivery hook or queue."""
    if bool(getattr(settings, "INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES", True)):
        return []
    hook = getattr(settings, "INDIEWEB_WEBSUB_DELIVERY_HOOK", None)
    enqueue = getattr(settings, "INDIEWEB_WEBSUB_DELIVERY_ENQUEUE", None)
    if not hook and not enqueue:
        return []
    return [
        Warning(
            "INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES is False while a WebSub delivery hook or queue is "
            "configured: deliveries for subscriptions without a secret are accepted unsigned.",
            hint=(
                "Subscribe with a hub.secret and remove the opt-out, or silence indieweb.W001 if "
                "unauthenticated content is acceptable for your delivery hook."
            ),
            obj="INDIEWEB_WEBSUB_REQUIRE_SIGNED_DELIVERIES",
            id="indieweb.W001",
        )
    ]


@register(Tags.security)
def check_auth_lifetimes(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    """Reject invalid lifetimes at configuration admission without database IO."""
    errors: list[CheckMessage] = []
    for name, default, error_id in (
        (auth_code_timeout_setting(), 60, "indieweb.E002"),
        ("INDIEWEB_TOKEN_EXPIRES_IN", DEFAULT_TOKEN_EXPIRES_IN, "indieweb.E003"),
    ):
        try:
            auth_lifetime(name, default)
        except ImproperlyConfigured as exc:
            errors.append(Error(str(exc), obj=name, id=error_id))
    return errors
