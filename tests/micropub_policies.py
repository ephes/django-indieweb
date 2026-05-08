"""Test fixtures for INDIEWEB_MICROPUB_URL_POLICY."""

from django.http import HttpRequest


def reject_all(url: str, kind: str, request: HttpRequest) -> bool:
    return False


def allow_all(url: str, kind: str, request: HttpRequest) -> bool:
    return True


def allow_only_https(url: str, kind: str, request: HttpRequest) -> bool:
    return url.startswith("https://")


def raise_runtime(url: str, kind: str, request: HttpRequest) -> bool:
    raise RuntimeError("policy explosion")
