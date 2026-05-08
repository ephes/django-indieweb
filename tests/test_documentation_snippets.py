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
    # Note: INDIEWEB_LOG_REDACTION, INDIEWEB_WEBMENTION_STATUS_PUBLIC, and
    # INDIEWEB_MICROPUB_URL_POLICY are introduced in later tasks (P3/P4) of
    # the same plan and will be referenced from the same hardening section
    # then. They are intentionally omitted from this set until they exist.
}


def test_production_hardening_snippet_references_known_settings():
    text = Path("docs/configuration.rst").read_text()
    assert "Production hardening" in text, "configuration.rst missing 'Production hardening' section"
    for name in KNOWN_SETTINGS:
        assert name in text, f"{name} missing from configuration.rst hardening snippet"
