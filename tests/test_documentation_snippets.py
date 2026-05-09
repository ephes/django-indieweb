"""Sanity-checks that copyable doc snippets reference current setting names.

If you rename or remove a setting, this test fails so the docs stay current.
"""

from pathlib import Path

KNOWN_SETTINGS = {
    "INDIEWEB_REQUIRE_PKCE",
    "INDIEWEB_REQUIRE_PKCE_S256",
    "INDIEWEB_BIND_ME_TO_USER",
    "INDIEWEB_ALLOWED_CLIENT_IDS",
    "INDIEWEB_RATE_LIMITS",
    "INDIEWEB_REDIRECT_URI_ALLOWLIST",
    "INDIEWEB_REDIRECT_URI_VALIDATOR",
    "INDIEWEB_MICROPUB_URL_POLICY",
    "INDIEWEB_WEBMENTION_STATUS_PUBLIC",
    "INDIEWEB_LOG_REDACTION",
}


def test_production_hardening_snippet_references_known_settings():
    text = Path("docs/configuration.rst").read_text()
    assert "Production hardening" in text, "configuration.rst missing 'Production hardening' section"
    for name in KNOWN_SETTINGS:
        assert name in text, f"{name} missing from configuration.rst"


def test_injected_client_warning_present():
    for path in ("docs/webmention.rst", "docs/websub.rst"):
        text = Path(path).read_text()
        assert "Leave ``client`` unset in production" in text, path
