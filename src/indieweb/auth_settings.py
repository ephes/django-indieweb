"""Strict, shared lifetime admission for IndieAuth settings and requests."""

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

DEFAULT_TOKEN_EXPIRES_IN = 86400
MAX_AUTH_LIFETIME = 2**31 - 1


def auth_lifetime(name: str, default: int) -> int:
    """Read whole positive seconds, refusing unsafe arithmetic without coercion."""
    value = getattr(settings, name, default)
    if type(value) is not int or not 1 <= value <= MAX_AUTH_LIFETIME:
        raise ImproperlyConfigured(f"{name} must be an integer from 1 to {MAX_AUTH_LIFETIME} seconds")
    try:
        timezone.now() + timedelta(seconds=value)
    except OverflowError as exc:
        raise ImproperlyConfigured(f"{name} exceeds the supported datetime range") from exc
    return value


def auth_code_timeout_setting() -> str:
    """Prefer the correctly spelled setting while retaining the historical alias."""
    return (
        "INDIEWEB_AUTH_CODE_TIMEOUT"
        if hasattr(settings, "INDIEWEB_AUTH_CODE_TIMEOUT")
        else "INDIWEB_AUTH_CODE_TIMEOUT"
    )


def auth_lifetimes() -> tuple[int, int]:
    """Validate both settings before any authorization-code or token mutation."""
    # Check token arithmetic first so its error stays actionable near datetime.max.
    lifetime = auth_lifetime("INDIEWEB_TOKEN_EXPIRES_IN", DEFAULT_TOKEN_EXPIRES_IN)
    return auth_lifetime(auth_code_timeout_setting(), 60), lifetime
