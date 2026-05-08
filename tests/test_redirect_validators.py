"""Validator callables imported by IndieAuth redirect_uri policy tests."""


def allow_all(client_id: str, redirect_uri: str) -> bool:
    return True


def broken_path() -> bool:
    raise RuntimeError("never called")
