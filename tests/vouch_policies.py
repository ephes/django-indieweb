"""Test-only Vouch trust policies."""

from indieweb.models import Webmention


def trust_submitted_and_final(
    *,
    webmention: Webmention,
    source_url: str,
    target_url: str,
    vouch_url: str,
    final_vouch_url: str | None = None,
) -> bool:
    """Trust the submitted test voucher and its redirected final URL."""
    return (
        webmention.source_url == source_url
        and webmention.target_url == target_url
        and target_url == "https://mysite.com/article"
        and source_url == "https://example.com/post"
        and vouch_url == "https://trusted.example/vouch-for-example"
        and final_vouch_url in {None, "https://trusted.example/final-vouch"}
    )


def reject_submitted(
    *,
    webmention: Webmention,
    source_url: str,
    target_url: str,
    vouch_url: str,
    final_vouch_url: str | None = None,
) -> bool:
    """Reject before voucher fetching."""
    return False


def reject_final(
    *,
    webmention: Webmention,
    source_url: str,
    target_url: str,
    vouch_url: str,
    final_vouch_url: str | None = None,
) -> bool:
    """Accept the submitted URL but reject the final redirected URL."""
    return final_vouch_url is None


def raises(
    *,
    webmention: Webmention,
    source_url: str,
    target_url: str,
    vouch_url: str,
    final_vouch_url: str | None = None,
) -> bool:
    """Raise to prove policy exceptions fail closed."""
    raise RuntimeError("policy failed")


non_callable = object()
