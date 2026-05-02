from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseBase
from django.utils.cache import patch_vary_headers
from django.views.generic import View

logger = logging.getLogger(__name__)

DEFAULT_CORS_ALLOWED_HEADERS = ("Authorization", "Content-Type", "Accept")
DEFAULT_CORS_MAX_AGE = 86400


@dataclass(frozen=True)
class CorsConfig:
    """Validated CORS configuration for IndieWeb protocol endpoints."""

    allowed_origins: frozenset[str]
    allow_all_origins: bool
    allow_credentials: bool
    allowed_headers: tuple[str, ...]
    max_age: int | None


def _string_tuple(value: Any, *, setting_name: str) -> tuple[str, ...] | None:
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Iterable):
        logger.warning(f"Ignoring invalid {setting_name} value; expected a string or iterable of strings")
        return None
    parsed: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            logger.warning(f"Ignoring invalid {setting_name} entry; expected non-empty strings")
            return None
        parsed.append(item)
    return tuple(parsed)


def _max_age(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        logger.warning("Ignoring invalid INDIEWEB_CORS_MAX_AGE value; expected a non-negative integer")
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid INDIEWEB_CORS_MAX_AGE value; expected a non-negative integer")
        return None
    if parsed < 0:
        logger.warning("Ignoring invalid INDIEWEB_CORS_MAX_AGE value; expected a non-negative integer")
        return None
    return parsed


def get_cors_config() -> CorsConfig | None:
    """Return validated built-in CORS settings, or ``None`` when disabled."""
    configured_origins = getattr(settings, "INDIEWEB_CORS_ALLOWED_ORIGINS", None)
    if not configured_origins:
        return None

    origins = _string_tuple(configured_origins, setting_name="INDIEWEB_CORS_ALLOWED_ORIGINS")
    if origins is None:
        return None

    allowed_origins = frozenset(origins)
    allow_all_origins = "*" in allowed_origins
    if not allow_all_origins and not allowed_origins:
        return None

    configured_headers = getattr(settings, "INDIEWEB_CORS_ALLOWED_HEADERS", DEFAULT_CORS_ALLOWED_HEADERS)
    allowed_headers = _string_tuple(configured_headers, setting_name="INDIEWEB_CORS_ALLOWED_HEADERS")
    if allowed_headers is None:
        allowed_headers = DEFAULT_CORS_ALLOWED_HEADERS

    return CorsConfig(
        allowed_origins=allowed_origins,
        allow_all_origins=allow_all_origins,
        allow_credentials=bool(getattr(settings, "INDIEWEB_CORS_ALLOW_CREDENTIALS", False)),
        allowed_headers=allowed_headers,
        max_age=_max_age(getattr(settings, "INDIEWEB_CORS_MAX_AGE", DEFAULT_CORS_MAX_AGE)),
    )


def _origin_allowed(config: CorsConfig, origin: str | None) -> bool:
    if not origin:
        return False
    return config.allow_all_origins or origin in config.allowed_origins


def _allow_origin_value(config: CorsConfig, origin: str) -> str:
    if config.allow_all_origins and not config.allow_credentials:
        return "*"
    return origin


def _add_cors_headers(response: HttpResponseBase, config: CorsConfig, origin: str) -> HttpResponseBase:
    response["Access-Control-Allow-Origin"] = _allow_origin_value(config, origin)
    if config.allow_credentials:
        response["Access-Control-Allow-Credentials"] = "true"
    if response["Access-Control-Allow-Origin"] != "*":
        patch_vary_headers(response, ("Origin",))
    return response


class CorsMixin(View):
    """Apply configured endpoint-scoped CORS behavior to public protocol views."""

    cors_allowed_methods: tuple[str, ...] = ()

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponseBase:
        config = get_cors_config()
        if config is None:
            return super().dispatch(request, *args, **kwargs)

        origin = request.headers.get("Origin")
        if request.method == "OPTIONS":
            preflight_response = self._cors_preflight_response(request, config, origin)
            if preflight_response is not None:
                return preflight_response
            if origin and not _origin_allowed(config, origin):
                return HttpResponse(status=405)

        response = super().dispatch(request, *args, **kwargs)
        if _origin_allowed(config, origin):
            return _add_cors_headers(response, config, origin or "")
        return response

    def _cors_preflight_response(
        self,
        request: HttpRequest,
        config: CorsConfig,
        origin: str | None,
    ) -> HttpResponse | None:
        requested_method = request.headers.get("Access-Control-Request-Method")
        if not requested_method or not _origin_allowed(config, origin):
            return None

        allowed_methods = {method.upper() for method in self.cors_allowed_methods}
        if requested_method.upper() not in allowed_methods:
            return HttpResponse(status=405)

        response = HttpResponse(status=204)
        response["Allow"] = ", ".join((*self.cors_allowed_methods, "OPTIONS"))
        response["Access-Control-Allow-Methods"] = ", ".join(self.cors_allowed_methods)
        if config.allowed_headers:
            response["Access-Control-Allow-Headers"] = ", ".join(config.allowed_headers)
        if config.max_age is not None:
            response["Access-Control-Max-Age"] = str(config.max_age)
        _add_cors_headers(response, config, origin or "")
        return response
