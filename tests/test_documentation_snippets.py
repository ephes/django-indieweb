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
    "INDIEWEB_MICROPUB_URL_POLICY",
    "INDIEWEB_WEBMENTION_STATUS_PUBLIC",
    # Note: INDIEWEB_LOG_REDACTION is introduced in a later task (P4) of the
    # same plan and will be referenced from the same hardening section then.
    # It is intentionally omitted from this set until it exists.
}


def test_production_hardening_snippet_references_known_settings():
    text = Path("docs/configuration.rst").read_text()
    assert "Production hardening" in text, "configuration.rst missing 'Production hardening' section"
    for name in KNOWN_SETTINGS:
        assert name in text, f"{name} missing from configuration.rst hardening snippet"


def test_injected_client_warning_present():
    for path in ("docs/webmention.rst", "docs/websub.rst"):
        text = Path(path).read_text()
        assert "Leave ``client`` unset in production" in text, path
