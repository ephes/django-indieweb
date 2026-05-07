"""Validator callables used by INDIEWEB_CLIENT_ID_VALIDATOR tests."""

from __future__ import annotations

ALLOWED_CLIENT_ID = "https://allowed.example.org"
NORMALIZED_CLIENT_ID = "https://xn--bcher-kva.example/Client?A=1"
seen_client_ids: list[str] = []


def allow_all(client_id: str) -> bool:
    return True


def deny_all(client_id: str) -> bool:
    return False


def allow_only_known(client_id: str) -> bool:
    return client_id == ALLOWED_CLIENT_ID


def allow_only_normalized(client_id: str) -> bool:
    return client_id == NORMALIZED_CLIENT_ID


def capture_and_allow(client_id: str) -> bool:
    seen_client_ids.append(client_id)
    return True
