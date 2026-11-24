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
from .rate_limit import RATE_LIMITS_SETTING, parse_rate_limit_config, rate_limit_settings
from .websub import (
    WEBSUB_DELIVERY_ALLOWED_TYPES_SETTING,
    WEBSUB_SIGNED_DELIVERIES_SETTING,
    validate_websub_delivery_allowed_types,
    websub_signature_policy,
)

RATE_LIMIT_ENDPOINTS = frozenset(
    {"auth", "token", "token_introspection", "micropub", "media", "websub_callback", "webmention", "webmention_status"}
)


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
                hint='Use bare http(s) origins, for example "https://example.com".',
                obj=CANONICAL_ORIGINS_SETTING,
                id="indieweb.E001",
            )
        ]
    return []


@register(Tags.security)
def check_websub_unsigned_deliveries(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    """Validate the WebSub signature policy and warn about unsigned hook or queue delivery."""
    policy = websub_signature_policy()
    if policy is None:
        return [
            Error(
                f"{WEBSUB_SIGNED_DELIVERIES_SETTING} must be True or False.",
                obj=WEBSUB_SIGNED_DELIVERIES_SETTING,
                id="indieweb.E005",
            )
        ]
    if policy:
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
            obj=WEBSUB_SIGNED_DELIVERIES_SETTING,
            id="indieweb.W001",
        )
    ]


@register(Tags.security)
def check_websub_delivery_allowed_types(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    """Report malformed media type allowlists without exposing configured values."""
    try:
        validate_websub_delivery_allowed_types()
    except ValueError:
        return [
            Error(
                f"{WEBSUB_DELIVERY_ALLOWED_TYPES_SETTING} must contain bare media types.",
                hint='Use a string or a reusable iterable such as ("application/atom+xml",), or set it to None.',
                obj=WEBSUB_DELIVERY_ALLOWED_TYPES_SETTING,
                id="indieweb.E006",
            )
        ]
    return []


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


@register(Tags.security)
def check_endpoint_rate_limits(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    """Report malformed rate limits and unknown built-in endpoint keys."""
    try:
        configured = rate_limit_settings()
    except ValueError as exc:
        return [Error(str(exc), obj=RATE_LIMITS_SETTING, id="indieweb.E004")]

    errors: list[CheckMessage] = []
    for key, config in configured.items():
        if not isinstance(key, str):
            errors.append(Error("Endpoint keys must be strings.", obj=RATE_LIMITS_SETTING, id="indieweb.E004"))
            continue
        if key not in RATE_LIMIT_ENDPOINTS:
            errors.append(Error(f"Unknown endpoint {key!r}.", obj=RATE_LIMITS_SETTING, id="indieweb.E004"))
            continue
        try:
            parse_rate_limit_config(config)
        except ValueError as exc:
            errors.append(Error(f"Invalid limit for {key!r}: {exc}.", obj=RATE_LIMITS_SETTING, id="indieweb.E004"))
    return errors
