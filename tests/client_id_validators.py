"""Validator callables used by INDIEWEB_CLIENT_ID_VALIDATOR tests."""

from __future__ import annotations

ALLOWED_CLIENT_ID = "https://allowed.example.org"


def allow_all(client_id: str) -> bool:
    return True


def deny_all(client_id: str) -> bool:
    return False


def allow_only_known(client_id: str) -> bool:
    return client_id == ALLOWED_CLIENT_ID
