from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import math
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import PurePath
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qsl, urlparse, urlunparse
from urllib.parse import urlencode as urllib_urlencode

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.files.storage import default_storage
from django.core.validators import URLValidator
from django.http import HttpRequest, HttpResponse, HttpResponseBase, JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import urlencode
from django.utils.module_loading import import_string
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View

from .cors import CorsMixin
from .handlers import MicropubContentHandler, get_micropub_handler
from .models import Auth, Token, Webmention, WebSubSubscription
from .processors import WebmentionProcessor
from .rate_limit import RateLimitMixin
from .websub import (
    WebSubDeliveryHookError,
    confirm_websub_verification,
    delivery_body_too_large,
    delivery_content_length_too_large,
    delivery_content_type_allowed,
    delivery_max_bytes,
    process_websub_delivery,
    record_websub_delivery,
    record_websub_denial,
    validate_websub_delivery_signature,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser
    from django.core.files.uploadedfile import UploadedFile

    from .handlers import MicropubEntry, MicropubMediaItem

logger = logging.getLogger(__name__)


def _read_request_body_with_invalid_content_length_fallback(request: HttpRequest) -> bytes:
    """Read a request body even when a malformed Content-Length would make Django raise."""
    try:
        return request.body
    except ValueError:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                int(content_length)
            except (TypeError, ValueError):
                stream = request.META.get("wsgi.input")
                max_bytes = delivery_max_bytes()
                read_size = max_bytes + 1 if max_bytes is not None else -1
                body = stream.read(read_size) if stream is not None else b""
                request._body = body
                return body
        raise


DEFAULT_TOKEN_EXPIRES_IN = 86400
ALLOWED_REDIRECT_URI_SCHEMES = ("http", "https")
ALLOWED_PKCE_METHODS = ("plain", "S256")
INDIEAUTH_METADATA_SCOPES_SUPPORTED = ("create", "update", "delete", "undelete", "media")
INDIEAUTH_SERVICE_DOCUMENTATION_URL = "https://django-indieweb.readthedocs.io/en/latest/indieauth.html"
INDIEAUTH_WELL_KNOWN_METADATA_PATH = "/.well-known/oauth-authorization-server"
PKCE_UNRESERVED_RE = re.compile(r"^[A-Za-z0-9._~\-]+$")
PKCE_CHALLENGE_MIN = 43
PKCE_CHALLENGE_MAX = 128
PKCE_VERIFIER_MIN = 43
PKCE_VERIFIER_MAX = 128
MICROPUB_MEDIA_SCOPE = "media"
SUPPORTED_MICROPUB_QUERIES = (
    "config",
    "source",
    "syndicate-to",
    "category",
    "channel",
    "media-endpoint",
    "post-types",
)
MICROPUB_FORM_CREATE_PROPERTIES = (
    "content",
    "name",
    "summary",
    "description",
    "category",
    "location",
    "start",
    "end",
    "in-reply-to",
    "bookmark-of",
    "like-of",
    "repost-of",
    "rsvp",
    "url",
    "published",
    "photo",
    "audio",
    "video",
    "mp-slug",
    "mp-channel",
    "mp-photo-alt",
    "mp-syndicate-to",
    "post-status",
)
MICROPUB_FORM_CREATE_LIST_PROPERTIES = (
    "content",
    "photo",
    "audio",
    "video",
    "category",
    "mp-channel",
    "mp-photo-alt",
    "mp-syndicate-to",
)
MICROPUB_SERVER_MANAGED_PROPERTIES = frozenset({"uid", "author"})
DEFAULT_MICROPUB_SOURCE_LIST_LIMIT = 20
MICROPUB_MEDIA_STORAGE_PREFIX = "indieweb/media"
DEFAULT_MICROPUB_MEDIA_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
DEFAULT_MICROPUB_MEDIA_ALLOWED_TYPES = (
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/heic",
    "image/heif",
    "audio/mpeg",
    "audio/mp4",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "video/mp4",
    "video/quicktime",
    "video/ogg",
    "video/webm",
)


class _MicropubMediaUploadError(Exception):
    """Internal exception carrying the HTTP status for upload validation/storage failures."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(status_code)


class _WebmentionEnqueueError(Exception):
    """Internal exception for configured Webmention enqueue failures."""


def _micropub_media_storage_name(original_name: str) -> str:
    """Return an unguessable storage key, preserving the lowercased final filename suffix."""
    suffix = PurePath(original_name).suffix.lower()
    return f"{MICROPUB_MEDIA_STORAGE_PREFIX}/{uuid.uuid4().hex}{suffix}"


def _absolute_storage_url(request: HttpRequest, stored_name: str) -> str:
    url = default_storage.url(stored_name)
    if url.startswith(("http://", "https://")):
        return url
    return request.build_absolute_uri(url)


def _upload_size_allowed(upload: UploadedFile) -> bool:
    max_bytes = getattr(settings, "INDIEWEB_MEDIA_MAX_UPLOAD_BYTES", DEFAULT_MICROPUB_MEDIA_MAX_UPLOAD_BYTES)
    if max_bytes is None:
        return True
    if upload.size is None:
        # Custom upload handler with unknown size; reject rather than storing an unbounded file.
        return False
    return upload.size <= int(max_bytes)


def _upload_type_allowed(upload: UploadedFile) -> bool:
    allowed_types = getattr(settings, "INDIEWEB_MEDIA_ALLOWED_TYPES", DEFAULT_MICROPUB_MEDIA_ALLOWED_TYPES)
    if allowed_types is None:
        return True
    return upload.content_type in allowed_types


def _validate_micropub_media_upload(upload: UploadedFile) -> None:
    """Validate a Micropub media upload before storage."""
    if not _upload_size_allowed(upload):
        raise _MicropubMediaUploadError(413)
    if not _upload_type_allowed(upload):
        raise _MicropubMediaUploadError(415)


def _save_micropub_media_upload(upload: UploadedFile) -> str:
    """Store a Micropub media upload and return the stored name."""
    try:
        return default_storage.save(_micropub_media_storage_name(upload.name or ""), upload)
    except OSError as exc:
        logger.exception("Unexpected error storing Micropub media upload")
        raise _MicropubMediaUploadError(500) from exc


def _store_micropub_media_upload(request: HttpRequest, upload: UploadedFile) -> str:
    """Validate and store a Micropub media upload, returning the absolute media URL."""
    _validate_micropub_media_upload(upload)
    return _absolute_storage_url(request, _save_micropub_media_upload(upload))


def _store_micropub_media_uploads(request: HttpRequest, uploads: list[UploadedFile]) -> list[str]:
    """Validate and store multiple uploads, cleaning up partial saves if storage fails."""
    for upload in uploads:
        _validate_micropub_media_upload(upload)

    stored_names: list[str] = []
    try:
        for upload in uploads:
            stored_names.append(_save_micropub_media_upload(upload))
    except _MicropubMediaUploadError:
        for stored_name in stored_names:
            try:
                default_storage.delete(stored_name)
            except OSError:
                logger.exception(f"Failed to clean up stored Micropub media upload {stored_name!r}")
        raise
    return [_absolute_storage_url(request, stored_name) for stored_name in stored_names]


def _micropub_media_upload_error_response(exc: _MicropubMediaUploadError) -> HttpResponse:
    if exc.status_code in {413, 415}:
        return HttpResponse("invalid_request", status=exc.status_code)
    return HttpResponse(status=exc.status_code)


def _validate_redirect_uri(value: str) -> str | None:
    """Validate a ``redirect_uri`` per IndieAuth.

    Returns the input unchanged when it is a syntactically valid URL with an
    allowed scheme, no fragment delimiter, and no userinfo component. Returns
    ``None`` otherwise. Userinfo is rejected because it is not a normal
    IndieAuth redirect target and would otherwise break case-insensitive
    host comparison at the token endpoint.
    """
    if not value:
        return None
    if "#" in value:
        return None
    try:
        URLValidator(schemes=list(ALLOWED_REDIRECT_URI_SCHEMES))(value)
    except ValidationError:
        return None
    parsed = urlparse(value)
    if parsed.scheme.lower() not in ALLOWED_REDIRECT_URI_SCHEMES:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    return value


def _validate_client_id(value: str | None) -> str | None:
    """Validate a ``client_id`` per IndieAuth.

    Returns the input unchanged when it is a syntactically valid URL with an
    allowed scheme, no fragment delimiter, and no userinfo component. Returns
    ``None`` otherwise. Stored ``client_id`` values are not re-validated
    structurally on use; this helper guards the issuance points only.
    """
    if not value:
        return None
    if "#" in value:
        return None
    try:
        URLValidator(schemes=list(ALLOWED_REDIRECT_URI_SCHEMES))(value)
    except ValidationError:
        return None
    parsed = urlparse(value)
    if parsed.scheme.lower() not in ALLOWED_REDIRECT_URI_SCHEMES:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    return value


def _normalize_client_id_for_policy(value: str) -> str:
    """Return the comparison form passed to client_id policy hooks.

    This lowercases scheme and host, IDNA-encodes domain hosts, and keeps path,
    params, query, fragment, and non-default ports unchanged. It is used for
    policy comparison only; stored request values remain the submitted strings.
    """
    try:
        parsed = urlparse(value)
    except ValueError:
        return value
    if parsed.username is not None or parsed.password is not None:
        return value

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname or ""
    try:
        ipaddress.ip_address(hostname)
        normalized_host = hostname.lower()
    except ValueError:
        try:
            normalized_host = hostname.encode("idna").decode("ascii").lower()
        except UnicodeError:
            return value
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"

    try:
        port = parsed.port
    except ValueError:
        return value
    netloc = normalized_host
    if port is not None:
        netloc = f"{netloc}:{port}"
    return parsed._replace(scheme=scheme, netloc=netloc).geturl()


def _configured_allowed_client_ids() -> frozenset[str] | None:
    """Return normalized ``INDIEWEB_ALLOWED_CLIENT_IDS`` values, or ``None`` when unset."""
    configured = getattr(settings, "INDIEWEB_ALLOWED_CLIENT_IDS", None)
    if not configured:
        return None
    values = (configured,) if isinstance(configured, str) else configured
    try:
        parsed_values = tuple(values)
    except TypeError:
        logger.error("Rejecting clients because INDIEWEB_ALLOWED_CLIENT_IDS is not a string or iterable of strings")
        return frozenset()

    normalized: set[str] = set()
    for client_id in parsed_values:
        if not isinstance(client_id, str) or _validate_client_id(client_id) is None:
            logger.error("Rejecting clients because INDIEWEB_ALLOWED_CLIENT_IDS contains an invalid client_id URL")
            return frozenset()
        normalized.add(_normalize_client_id_for_policy(client_id))
    return frozenset(normalized)


def _normalize_scope(value: str | None) -> str | None:
    """Normalize a scope string for display, storage, and token issuance.

    ``None``, empty, and whitespace-only values collapse to ``None``. Other
    values are split on whitespace, de-duplicated while preserving first-seen
    token order, and joined with single spaces. Unknown scope tokens are
    intentionally preserved because IndieAuth/Micropub scopes are
    extension-defined.
    """
    if value is None:
        return None
    scopes = list(dict.fromkeys(value.split()))
    if not scopes:
        return None
    return " ".join(scopes)


def _token_client_id_error(client_id: str) -> HttpResponse | None:
    """Return an ``invalid_request`` response if ``client_id`` cannot be used at the token endpoint.

    Combines structural validation and the optional configured policy hook. The
    response shape (``application/x-www-form-urlencoded`` body ``invalid_request``)
    matches the existing missing-``code`` case.
    """
    if _validate_client_id(client_id) is None:
        logger.info("rejected invalid client_id on token exchange")
        return HttpResponse("invalid_request", status=400, content_type="application/x-www-form-urlencoded")
    if not _client_id_allowed(client_id):
        logger.warning(f"rejected disallowed client_id on token exchange: {client_id!r}")
        return HttpResponse("invalid_request", status=400, content_type="application/x-www-form-urlencoded")
    return None


def _token_grant_type_error(grant_type: str | None) -> HttpResponse | None:
    """Return ``invalid_request`` when a present token grant type is unsupported."""
    if grant_type is None or grant_type == "authorization_code":
        return None
    logger.info(f"rejected invalid grant_type on token exchange: {grant_type!r}")
    return HttpResponse("invalid_request", status=400, content_type="application/x-www-form-urlencoded")


def _client_id_allowed(client_id: str) -> bool:
    """Return whether ``client_id`` passes optional operator client policy.

    When ``INDIEWEB_ALLOWED_CLIENT_IDS`` and ``INDIEWEB_CLIENT_ID_VALIDATOR``
    are unset, every ``client_id`` is permitted (preserving backwards
    compatibility for deployments that have not opted in to client
    allowlisting). Misconfigured allowlists, validator import failures, and
    callable exceptions fail closed so a misconfiguration cannot silently
    weaken access control.
    """
    normalized_client_id = _normalize_client_id_for_policy(client_id)
    allowed_client_ids = _configured_allowed_client_ids()
    if allowed_client_ids is not None and normalized_client_id not in allowed_client_ids:
        return False

    validator_path = getattr(settings, "INDIEWEB_CLIENT_ID_VALIDATOR", None)
    if not validator_path:
        return True
    try:
        validator = import_string(validator_path)
    except Exception as exc:
        logger.error(f"Failed to load INDIEWEB_CLIENT_ID_VALIDATOR {validator_path}: {exc}")
        return False
    try:
        return bool(validator(normalized_client_id))
    except Exception as exc:
        logger.error(f"INDIEWEB_CLIENT_ID_VALIDATOR raised for client_id={normalized_client_id!r}: {exc}")
        return False


def _get_webmention_enqueue() -> Callable[[int], None] | None:
    """Load the optional configured Webmention enqueue hook."""
    enqueue_path = getattr(settings, "INDIEWEB_WEBMENTION_ENQUEUE", None)
    if not enqueue_path:
        return None
    try:
        enqueue = import_string(enqueue_path)
    except Exception as exc:
        logger.exception(f"Failed to load INDIEWEB_WEBMENTION_ENQUEUE {enqueue_path!r}")
        raise _WebmentionEnqueueError from exc
    if not callable(enqueue):
        logger.error(f"INDIEWEB_WEBMENTION_ENQUEUE {enqueue_path!r} is not callable")
        raise _WebmentionEnqueueError
    return cast("Callable[[int], None]", enqueue)


def _store_webmention_submission(source: str, target: str, vouch: str | None) -> Webmention:
    """Create or reuse a submitted Webmention row, preserving existing state."""
    webmention, _created = Webmention.objects.get_or_create(
        source_url=source,
        target_url=target,
    )
    if vouch is not None and webmention.vouch_url != vouch:
        webmention.vouch_url = vouch
        webmention.vouch_verified_at = None
        webmention.save(update_fields=["vouch_url", "vouch_verified_at", "modified"])
    return webmention


def _normalize_redirect_uri(value: str) -> str:
    """Return ``value`` normalized for redirect_uri comparison.

    The comparison form lowercases scheme/host, IDNA-encodes host names,
    collapses default ports, lowercases percent-encoded triplets, and treats an
    empty root path as equivalent to ``/``. Other path and query semantics are
    preserved. Used for comparison only; the original value is what is sent to
    the client.
    """

    def normalize_percent_triplets(component: str) -> str:
        return re.sub(r"%[0-9A-Fa-f]{2}", lambda match: match.group(0).lower(), component)

    try:
        parsed = urlparse(value)
    except ValueError:
        return normalize_percent_triplets(value).lower()

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname or ""
    try:
        ipaddress.ip_address(hostname)
        normalized_host = hostname.lower()
    except ValueError:
        try:
            normalized_host = hostname.encode("idna").decode("ascii").lower()
        except UnicodeError:
            normalized_host = hostname.lower()
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"

    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = normalized_host
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{netloc}:{port}"

    path = normalize_percent_triplets(parsed.path)
    if path == "":
        path = "/"
    query = normalize_percent_triplets(parsed.query)
    params = normalize_percent_triplets(parsed.params)
    return parsed._replace(scheme=scheme, netloc=netloc, path=path, params=params, query=query).geturl()


def _validate_pkce_request(challenge: str | None, method: str | None) -> tuple[str, str] | None:
    """Validate PKCE inputs from an authorization request.

    Returns the normalized ``(challenge, method)`` pair on success, or ``None``
    if the inputs are malformed. ``method`` defaults to ``"plain"`` per
    RFC 7636 §4.3 when the caller sent a challenge without a method. A caller
    that sent neither parameter never reaches this function.
    """
    if not challenge:
        return None
    if not (PKCE_CHALLENGE_MIN <= len(challenge) <= PKCE_CHALLENGE_MAX):
        return None
    if not PKCE_UNRESERVED_RE.match(challenge):
        return None
    effective_method = method if method else "plain"
    if effective_method not in ALLOWED_PKCE_METHODS:
        return None
    return challenge, effective_method


def _pkce_methods_supported() -> tuple[str, ...]:
    """Return the PKCE methods accepted under the current deployment policy."""
    if bool(getattr(settings, "INDIEWEB_REQUIRE_PKCE_S256", False)):
        return ("S256",)
    return ALLOWED_PKCE_METHODS


def _validate_authorization_pkce(challenge: str | None, method: str | None) -> tuple[bool, str | None, str | None]:
    """Validate authorization-request PKCE under opt-in deployment policy."""
    require_s256 = bool(getattr(settings, "INDIEWEB_REQUIRE_PKCE_S256", False))
    require_pkce = require_s256 or bool(getattr(settings, "INDIEWEB_REQUIRE_PKCE", False))
    if challenge is None and method is None:
        return (not require_pkce, None, None)
    pkce = _validate_pkce_request(challenge, method)
    if pkce is None:
        return (False, None, None)
    normalized_challenge, normalized_method = pkce
    if require_s256 and normalized_method != "S256":
        return (False, None, None)
    return (True, normalized_challenge, normalized_method)


def _verify_pkce(stored_challenge: str, stored_method: str, submitted_verifier: str) -> bool:
    """Verify a submitted ``code_verifier`` against a stored challenge.

    Returns ``True`` only when the verifier is well-formed (RFC 7636 length and
    character set) and produces the stored challenge under ``stored_method``.
    """
    if not submitted_verifier:
        return False
    if not (PKCE_VERIFIER_MIN <= len(submitted_verifier) <= PKCE_VERIFIER_MAX):
        return False
    if not PKCE_UNRESERVED_RE.match(submitted_verifier):
        return False
    if stored_method == "plain":
        return hmac.compare_digest(stored_challenge, submitted_verifier)
    if stored_method == "S256":
        digest = hashlib.sha256(submitted_verifier.encode("ascii")).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return hmac.compare_digest(stored_challenge, computed)
    return False


def _expected_me_for_user(user: AbstractBaseUser) -> str | None:
    """Return the logged-in user's configured IndieWeb profile URL, if available."""
    try:
        profile = user.indieweb_profile  # type: ignore[attr-defined]
    except ObjectDoesNotExist:
        return None
    profile_url = getattr(profile, "url", "")
    return profile_url or None


def _me_matches_expected(submitted_me: str, expected_me: str) -> bool:
    """Return whether submitted ``me`` matches the configured profile URL."""
    return _normalize_redirect_uri(submitted_me) == _normalize_redirect_uri(expected_me)


def _me_binding_error(user: AbstractBaseUser, submitted_me: str) -> HttpResponse | None:
    """Return a strict me-binding error response when configured policy rejects the request."""
    if not bool(getattr(settings, "INDIEWEB_BIND_ME_TO_USER", False)):
        return None
    expected_me = _expected_me_for_user(user)
    if expected_me is None:
        logger.warning("rejected IndieAuth request because INDIEWEB_BIND_ME_TO_USER is enabled without profile URL")
        return HttpResponse("invalid me", status=400)
    if not _me_matches_expected(submitted_me, expected_me):
        logger.warning(f"rejected IndieAuth request with mismatched me={submitted_me!r}, expected={expected_me!r}")
        return HttpResponse("invalid me", status=400)
    return None


def _append_redirect_params(redirect_uri: str, params: dict[str, str]) -> str:
    """Append ``params`` to ``redirect_uri`` while preserving any existing query.

    Naive string concatenation with ``?`` corrupts URLs that already have a
    query (the new pairs collapse into the last existing value). This parses,
    merges, and re-encodes properly.
    """
    parsed = urlparse(redirect_uri)
    merged = parse_qsl(parsed.query, keep_blank_values=True) + list(params.items())
    return urlunparse(parsed._replace(query=urllib_urlencode(merged)))


def _reverse_request_namespace(request: HttpRequest, name: str) -> str:
    """Reverse ``name`` in the current URL namespace when one is active."""
    namespace = request.resolver_match.namespace if request.resolver_match else ""
    if namespace:
        try:
            return reverse(f"{namespace}:{name}")
        except NoReverseMatch:
            pass
    try:
        return reverse(name)
    except NoReverseMatch:
        # Useful in tests or direct view calls where resolver_match is absent,
        # but the bundled URLconf is still mounted with its default namespace.
        return reverse(f"indieweb:{name}")


def _common_path_prefix(*paths: str) -> str:
    """Return a slash-terminated path prefix common to all paths."""
    split_paths = [path.strip("/").split("/") for path in paths]
    common: list[str] = []
    for parts in zip(*split_paths, strict=False):
        if len(set(parts)) != 1:
            break
        common.append(parts[0])
    return f"/{'/'.join(common)}/" if common else "/"


def _indieauth_issuer(request: HttpRequest, authorization_path: str, token_path: str) -> str:
    """Build an issuer URL that is a prefix of the current metadata URL."""
    # The common-prefix branch handles script-prefix deployments such as /myapp/.well-known/...
    if request.path == INDIEAUTH_WELL_KNOWN_METADATA_PATH or request.path.startswith(
        f"{INDIEAUTH_WELL_KNOWN_METADATA_PATH}/"
    ):
        return request.build_absolute_uri("/")
    return request.build_absolute_uri(_common_path_prefix(request.path, authorization_path, token_path))


def _accept_media_ranges(request: HttpRequest) -> list[tuple[str, float, int]]:
    """Parse an Accept header into ``(media_range, q, order)`` tuples."""
    accept = request.headers.get("Accept", "")
    parsed: list[tuple[str, float, int]] = []
    for order, part in enumerate(accept.split(",")):
        item = part.strip()
        if not item:
            continue
        media_range, *parameters = (segment.strip() for segment in item.split(";"))
        q = 1.0
        for parameter in parameters:
            if parameter.startswith("q="):
                try:
                    q = float(parameter[2:])
                except ValueError:
                    q = 0.0
                break
        parsed.append((media_range.lower(), q, order))
    return parsed


def _best_explicit_accept(request: HttpRequest, media_type: str) -> tuple[float, int] | None:
    """Return the best explicit Accept quality/order for ``media_type``."""
    matches = [(q, order) for accepted, q, order in _accept_media_ranges(request) if accepted == media_type and q > 0]
    if not matches:
        return None
    return max(matches, key=lambda match: (match[0], -match[1]))


def _prefers_json_response(request: HttpRequest) -> bool:
    """Return True only when JSON is explicitly requested over form encoding."""
    json_accept = _best_explicit_accept(request, "application/json")
    if json_accept is None:
        return False
    form_accept = _best_explicit_accept(request, "application/x-www-form-urlencoded")
    if form_accept is None:
        return True
    json_q, json_order = json_accept
    form_q, form_order = form_accept
    return json_q > form_q or (json_q == form_q and json_order < form_order)


def _redact_auth_code(code: str | None) -> str:
    """Return a log-safe representation of an authorization code."""
    if not code:
        return "<empty>"
    if len(code) <= 6:
        return f"<redacted:{len(code)} chars>"
    return f"{code[:6]}..."


def _authorization_header(request: HttpRequest) -> str | None:
    """Return the Authorization header value across Django client/server spellings."""
    auth_header = request.headers.get("authorization")
    if not auth_header:
        auth_header = request.META.get("Authorization")
    return auth_header


def _parse_bearer_authorization_header(auth_header: str | None) -> str | None:
    """Return a bearer token only for a strict two-part Authorization header."""
    if not auth_header:
        return None
    parts = auth_header.strip().split()
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token


def _bearer_authentication_error_response() -> HttpResponse:
    """Return the shared response for token-protected resource authentication failures."""
    response = HttpResponse("authentication error", status=401)
    response["Cache-Control"] = "no-store"
    response["WWW-Authenticate"] = "Bearer"
    return response


class CSRFExemptMixin(View):
    """Mixin to exempt views from CSRF protection."""

    @method_decorator(csrf_exempt)
    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponseBase:
        return super().dispatch(request, *args, **kwargs)


class IndieAuthMetadataView(CorsMixin, View):
    """Public IndieAuth authorization server metadata endpoint."""

    cors_allowed_methods = ("GET",)

    def get(self, request: HttpRequest, *args: object, **kwargs: object) -> JsonResponse:
        authorization_path = _reverse_request_namespace(request, "auth")
        token_path = _reverse_request_namespace(request, "token")
        introspection_path = _reverse_request_namespace(request, "token-introspection")
        metadata = {
            "issuer": _indieauth_issuer(request, authorization_path, token_path),
            "authorization_endpoint": request.build_absolute_uri(authorization_path),
            "token_endpoint": request.build_absolute_uri(token_path),
            "introspection_endpoint": request.build_absolute_uri(introspection_path),
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": list(_pkce_methods_supported()),
            "scopes_supported": list(INDIEAUTH_METADATA_SCOPES_SUPPORTED),
            "service_documentation": INDIEAUTH_SERVICE_DOCUMENTATION_URL,
        }
        return JsonResponse(metadata)


class TokenAuthMixin(View):
    """
    Mixin for views that require token-based authentication.

    Validates Bearer tokens from the Authorization header and enforces
    scope-based authorization.
    """

    token: Token

    def authenticated(self, request: HttpRequest) -> bool:
        key = _parse_bearer_authorization_header(_authorization_header(request))
        if key is not None:
            try:
                self.token = Token.objects.select_related("owner").get(key=key)
                if not self.token.owner.is_active:
                    logger.warning(f"Token owner is not active: {self.token.owner}")
                    return False
                if self.token.is_expired():
                    logger.warning(f"Token expired: {key[:8]}...")
                    return False
                return True
            except Token.DoesNotExist:
                logger.warning(f"Token not found: {key[:8]}...")
                return False
            except Token.MultipleObjectsReturned:
                logger.warning(f"Multiple tokens found for bearer key: {key[:8]}...")
                return False
        else:
            logger.warning("No authorization token provided in request")
            return False

    def authorized(self, client_id: str, scope: str | None, required_scope: str | None = None) -> bool:
        """Return whether the token's ``scope`` satisfies ``required_scope``.

        ``required_scope`` of ``None`` means "any authenticated token is allowed"
        (the caller has no operation-specific scope requirement). Otherwise
        ``scope`` is split on whitespace and compared exactly to ``required_scope``;
        substring matches do not count.
        """
        if required_scope is None:
            return True
        if scope is None:
            return False
        return required_scope in scope.split()

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponseBase:
        if not self.authenticated(request):
            return _bearer_authentication_error_response()

        if not _client_id_allowed(self.token.client_id):
            logger.warning(f"rejected disallowed client_id on resource server: {self.token.client_id!r}")
            return HttpResponse("invalid_client", status=403)

        return super().dispatch(request, *args, **kwargs)


@method_decorator(csrf_exempt, name="dispatch")
class AuthView(CSRFExemptMixin, CorsMixin, RateLimitMixin, View):
    """
    IndieAuth authorization endpoint.

    Handles the authorization flow where users grant permission to client applications.
    GET: Shows authorization consent screen
    POST: Handles consent form submission or verifies auth codes
    """

    required_params: list[str] = ["client_id", "redirect_uri", "state", "me"]
    rate_limit_key = "auth"
    cors_allowed_methods = ("GET", "POST")

    def _csrf_failure_response(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponseBase | None:
        """Run Django's CSRF check for browser consent POSTs only."""
        action = request.POST.get("action")
        if request.method == "POST" and action in {"approve", "deny"}:
            return CsrfViewMiddleware(lambda csrf_request: HttpResponse()).process_view(
                request,
                self.post,
                args,
                kwargs,
            )
        return None

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponseBase:
        csrf_failure = self._csrf_failure_response(request, *args, **kwargs)
        if csrf_failure is not None:
            return csrf_failure
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponseBase:
        if not request.user.is_authenticated:
            login_url = getattr(settings, "LOGIN_URL", "/accounts/login/")
            return redirect(f"{login_url}?next={request.get_full_path()}")
        client_id = request.GET.get("client_id")
        redirect_uri = request.GET.get("redirect_uri")
        state = request.GET.get("state")
        me = request.GET.get("me")
        logger.info(f"auth view get: {client_id}, {redirect_uri}, {state}, {me}")
        required = [client_id, redirect_uri, state, me]

        for name, val in zip(self.required_params, required, strict=True):
            if val is None:
                err_msg = f"missing parameter {name}"
                logger.info(f"missing parameter: {name}")
                return HttpResponse(err_msg, status=404)

        # scope is optional; unknown scopes are intentionally preserved after normalization.
        scope = _normalize_scope(request.GET.get("scope"))
        # All required parameters are verified to be not None above
        assert client_id is not None
        assert redirect_uri is not None
        assert state is not None
        assert me is not None

        response_type = request.GET.get("response_type")
        if response_type is not None and response_type != "code":
            logger.info(f"rejected invalid response_type on auth get: {response_type!r}")
            return HttpResponse("invalid response_type", status=400)

        if _validate_redirect_uri(redirect_uri) is None:
            logger.info("rejected invalid redirect_uri on auth get")
            return HttpResponse("invalid redirect_uri", status=400)

        if _validate_client_id(client_id) is None:
            logger.info("rejected invalid client_id on auth get")
            return HttpResponse("invalid client_id", status=400)

        if not _client_id_allowed(client_id):
            logger.warning(f"rejected disallowed client_id on auth get: {client_id!r}")
            return HttpResponse("invalid_client", status=400)

        me_binding_error = _me_binding_error(request.user, me)
        if me_binding_error is not None:
            return me_binding_error

        code_challenge = request.GET.get("code_challenge")
        code_challenge_method = request.GET.get("code_challenge_method")
        pkce_valid, code_challenge, effective_method = _validate_authorization_pkce(
            code_challenge, code_challenge_method
        )
        if not pkce_valid:
            logger.info("rejected invalid PKCE parameters on auth get")
            return HttpResponse("invalid_request", status=400)

        # Parse scope into list for display
        scope_list = scope.split() if scope else []
        expected_me = _expected_me_for_user(request.user)
        me_mismatch = expected_me is not None and not _me_matches_expected(me, expected_me)

        # Render consent screen
        context = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "me": me,
            "scope": scope,
            "scope_list": scope_list,
            "code_challenge": code_challenge,
            "code_challenge_method": effective_method,
            "expected_me": expected_me,
            "me_mismatch": me_mismatch,
        }
        response = render(request, "indieweb/consent.html", context)
        response["X-Frame-Options"] = "DENY"
        response["Content-Security-Policy"] = "frame-ancestors 'none'"
        return response

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponseBase:
        logger.info(f"auth view post: {request}, {args}, {kwargs}")

        action = request.POST.get("action")
        if action in ["approve", "deny"]:
            return self._handle_consent(request, action)
        return self._verify_auth_code(request)

    def _handle_consent(self, request: HttpRequest, action: str) -> HttpResponseBase:
        client_id = request.POST.get("client_id")
        redirect_uri = request.POST.get("redirect_uri")
        state = request.POST.get("state")
        me = request.POST.get("me")
        scope = _normalize_scope(request.POST.get("scope"))

        if not all([client_id, redirect_uri, state, me]):
            return HttpResponse("Missing required parameters", status=400)

        assert client_id is not None
        assert redirect_uri is not None
        assert state is not None
        assert me is not None

        if not request.user.is_authenticated:
            return HttpResponse("User not authenticated", status=401)

        if _validate_redirect_uri(redirect_uri) is None:
            logger.info("rejected invalid redirect_uri on auth consent")
            return HttpResponse("invalid redirect_uri", status=400)

        if _validate_client_id(client_id) is None:
            logger.info("rejected invalid client_id on auth consent")
            return HttpResponse("invalid client_id", status=400)

        if not _client_id_allowed(client_id):
            logger.warning(f"rejected disallowed client_id on auth consent: {client_id!r}")
            return HttpResponse("invalid_client", status=400)

        me_binding_error = _me_binding_error(request.user, me)
        if me_binding_error is not None:
            return me_binding_error

        code_challenge = request.POST.get("code_challenge")
        code_challenge_method = request.POST.get("code_challenge_method")
        pkce_valid, stored_challenge, stored_method = _validate_authorization_pkce(
            code_challenge, code_challenge_method
        )
        if not pkce_valid:
            logger.info("rejected invalid PKCE parameters on auth consent")
            return HttpResponse("invalid_request", status=400)

        if action == "deny":
            deny_params: dict[str, str] = {"error": "access_denied", "state": state}
            target = _append_redirect_params(redirect_uri, deny_params)
            logger.info("auth view consent denied")
            return redirect(target)

        try:
            existing = Auth.objects.get(owner=request.user, client_id=client_id, scope=scope, me=me)
            existing.delete()
        except Auth.DoesNotExist:
            pass

        auth = Auth.objects.create(
            owner=request.user,
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            scope=scope,
            me=me,
            code_challenge=stored_challenge,
            code_challenge_method=stored_method,
        )
        authorization_path = _reverse_request_namespace(request, "auth")
        token_path = _reverse_request_namespace(request, "token")
        url_params: dict[str, str] = {
            "code": auth.key,
            "state": state,
            "me": me,
            "iss": _indieauth_issuer(request, authorization_path, token_path),
        }
        target = _append_redirect_params(redirect_uri, url_params)
        logger.info("auth view consent approved")
        return redirect(target)

    def _verify_auth_code(self, request: HttpRequest) -> HttpResponseBase:
        auth_code = request.POST.get("code")
        client_id = request.POST.get("client_id")

        if not auth_code or not client_id:
            return HttpResponse("Missing code or client_id", status=400)

        if _validate_client_id(client_id) is None:
            logger.info("rejected invalid client_id on code verification")
            return HttpResponse("invalid client_id", status=400)

        if not _client_id_allowed(client_id):
            logger.warning(f"rejected disallowed client_id on code verification: {client_id!r}")
            return HttpResponse("invalid_client", status=400)

        logger.info(f"auth view post verification: {client_id}")
        try:
            auth = Auth.objects.get(key=auth_code, client_id=client_id)
        except (Auth.DoesNotExist, Auth.MultipleObjectsReturned):
            return HttpResponse("Invalid authorization code", status=400)
        response_values = {"me": auth.me}
        if _prefers_json_response(request):
            return JsonResponse(response_values, status=200)
        return HttpResponse(urlencode(response_values), status=200, content_type="application/x-www-form-urlencoded")


class TokenView(CSRFExemptMixin, CorsMixin, RateLimitMixin, View):
    """
    IndieAuth token endpoint.

    Exchanges valid authorization codes for access tokens that can be used
    to authenticate API requests.
    """

    rate_limit_key = "token"
    cors_allowed_methods = ("POST",)

    def send_token(
        self,
        request: HttpRequest,
        me: str,
        client_id: str,
        scope: str | None,
        owner: AbstractBaseUser,
    ) -> HttpResponse:
        lifetime = int(getattr(settings, "INDIEWEB_TOKEN_EXPIRES_IN", DEFAULT_TOKEN_EXPIRES_IN))
        expires_at = timezone.now() + timedelta(seconds=lifetime)
        token, created = Token.objects.get_or_create(
            me=me,
            client_id=client_id,
            scope=scope,
            owner_id=owner.pk,
            defaults={"expires_at": expires_at},
        )
        if not created:
            token.key = ""
            token.expires_at = expires_at
            token.save(update_fields=["key", "expires_at", "modified"])
        remaining = max(0, math.floor((expires_at - timezone.now()).total_seconds()))
        response_values: dict[str, str | int] = {
            "access_token": token.key,
            "token_type": "Bearer",
            "expires_in": remaining,
            "scope": token.scope or "",
            "me": token.me,
        }
        status_code = 201 if created else 200
        if _prefers_json_response(request):
            return JsonResponse(response_values, status=status_code)
        response = urlencode(response_values)
        return HttpResponse(response, status=status_code, content_type="application/x-www-form-urlencoded")

    def _consume_invalid_grant(self, auth: Auth, message: str) -> HttpResponse:
        """Delete a matched auth code and return the token endpoint's invalid_grant response."""
        logger.error(message)
        auth.delete()
        return HttpResponse("invalid_grant", status=400, content_type="application/x-www-form-urlencoded")

    def _check_pkce(self, auth: Auth, code_verifier: str | None) -> HttpResponse | None:
        """Verify PKCE for a token exchange. Deletes ``auth`` on failure to preserve one-time use."""
        if auth.code_challenge:
            if not code_verifier or not _verify_pkce(
                auth.code_challenge, auth.code_challenge_method or "plain", code_verifier
            ):
                return self._consume_invalid_grant(auth, "PKCE verification failed on token exchange")
        elif code_verifier:
            return self._consume_invalid_grant(auth, "PKCE verifier submitted without stored challenge")
        return None

    def _get_auth_for_exchange(self, code: str, client_id: str) -> Auth | HttpResponse:
        """Return the matched auth code or the existing invalid_grant response."""
        try:
            return Auth.objects.get(key=code, client_id=client_id)
        except Auth.DoesNotExist:
            logger.error(f"Auth not found for code={_redact_auth_code(code)}, client_id={client_id}")
            return HttpResponse("invalid_grant", status=400, content_type="application/x-www-form-urlencoded")
        except Auth.MultipleObjectsReturned:
            logger.warning(
                f"Multiple auth codes found for code={_redact_auth_code(code)}, client_id={client_id}; rejecting"
            )
            Auth.objects.filter(key=code, client_id=client_id).delete()
            return HttpResponse("invalid_grant", status=400, content_type="application/x-www-form-urlencoded")

    def _check_redirect_uri(self, auth: Auth, redirect_uri: str | None) -> HttpResponse | None:
        """Verify redirect_uri binding for a matched authorization code."""
        if auth.redirect_uri and not redirect_uri:
            return self._consume_invalid_grant(auth, "Missing redirect_uri on token exchange")
        if redirect_uri and auth.redirect_uri:
            stored = _normalize_redirect_uri(auth.redirect_uri)
            submitted = _normalize_redirect_uri(redirect_uri)
            if stored != submitted:
                return self._consume_invalid_grant(auth, "Redirect URI mismatch on token exchange")
        return None

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        # Get parameters from request
        code = request.POST.get("code")
        client_id = request.POST.get("client_id")
        redirect_uri = request.POST.get("redirect_uri")
        code_verifier = request.POST.get("code_verifier")
        grant_type = request.POST.get("grant_type")

        # These are sometimes sent but not required by spec
        me = request.POST.get("me")
        requested_scope = request.POST.get("scope")

        # Validate required parameters
        if not code or not client_id:
            logger.error(f"Missing required parameters: code={_redact_auth_code(code)}, client_id={client_id}")
            return HttpResponse("invalid_request", status=400, content_type="application/x-www-form-urlencoded")

        parameter_error = _token_grant_type_error(grant_type) or _token_client_id_error(client_id)
        if parameter_error is not None:
            return parameter_error

        if redirect_uri and _validate_redirect_uri(redirect_uri) is None:
            logger.error("Rejected invalid redirect_uri on token exchange")
            return HttpResponse("invalid_grant", status=400, content_type="application/x-www-form-urlencoded")

        # Find auth by code and client_id
        auth = self._get_auth_for_exchange(code, client_id)
        if isinstance(auth, HttpResponse):
            return auth

        # Already-stored redirect_uri values are not re-validated structurally;
        # they were validated when the auth code was issued (or pre-date validation).
        redirect_uri_error = self._check_redirect_uri(auth, redirect_uri)
        if redirect_uri_error is not None:
            return redirect_uri_error

        pkce_error = self._check_pkce(auth, code_verifier)
        if pkce_error is not None:
            return pkce_error

        stored_scope = _normalize_scope(auth.scope)
        normalized_request_scope = _normalize_scope(requested_scope)
        if requested_scope is not None and normalized_request_scope != stored_scope:
            return self._consume_invalid_grant(auth, f"Scope mismatch on token exchange for client_id={client_id}")

        # Use values from auth object if not provided in request
        me = me or auth.me
        scope = stored_scope

        logger.info(f"token view post: {client_id}, {me}, {_redact_auth_code(code)} {scope}")

        # Check if auth code is still valid
        timeout = getattr(settings, "INDIWEB_AUTH_CODE_TIMEOUT", 60)
        if (timezone.now() - auth.created).total_seconds() > timeout:
            return self._consume_invalid_grant(auth, f"Auth code expired for client_id={client_id}")

        # Delete auth code after use (one-time use)
        auth.delete()

        # Create and return token
        return self.send_token(request, me, client_id, scope, auth.owner)


def _authorization_bearer_token(request: HttpRequest) -> str | None:
    """Return the bearer token from the Authorization header, if present."""
    return _parse_bearer_authorization_header(_authorization_header(request))


def _token_timestamp(value: datetime) -> int:
    """Return a whole-second Unix timestamp for a Django datetime value."""
    return math.floor(value.timestamp())


class TokenIntrospectionView(CSRFExemptMixin, CorsMixin, RateLimitMixin, View):
    """IndieAuth token introspection endpoint for verifying issued bearer tokens."""

    rate_limit_key = "token_introspection"
    cors_allowed_methods = ("POST",)

    def _inactive_response(self) -> JsonResponse:
        return JsonResponse({"active": False})

    def _submitted_token(self, request: HttpRequest, caller_token: Token) -> str:
        value = request.POST.get("token")
        if value:
            return value
        return caller_token.key

    def _token_for_key(self, key: str, *, log_prefix: str) -> Token | None:
        try:
            token = Token.objects.select_related("owner").get(key=key)
        except Token.DoesNotExist:
            logger.info(f"{log_prefix} token not found: {key[:8]}...")
            return None
        except Token.MultipleObjectsReturned:
            logger.warning(f"{log_prefix} found multiple tokens for submitted key: {key[:8]}...")
            return None
        if not token.owner.is_active:
            logger.info(f"{log_prefix} rejected inactive token owner: {token.owner}")
            return None
        if token.is_expired():
            logger.info(f"{log_prefix} rejected expired token: {key[:8]}...")
            return None
        if not _client_id_allowed(token.client_id):
            logger.warning(f"{log_prefix} rejected disallowed client_id: {token.client_id!r}")
            return None
        return token

    def _caller_token(self, request: HttpRequest) -> Token | HttpResponse:
        authorization = _authorization_header(request)
        key = _parse_bearer_authorization_header(authorization)
        if key is None:
            logger.warning("No valid introspection caller bearer token provided")
            return _bearer_authentication_error_response()
        token = self._token_for_key(key, log_prefix="introspection caller")
        if token is None:
            return _bearer_authentication_error_response()
        return token

    def _active_response(self, token: Token) -> JsonResponse:
        response_values: dict[str, bool | int | str] = {
            "active": True,
            "me": token.me,
            "client_id": token.client_id,
            "scope": token.scope or "",
            "iat": _token_timestamp(token.created),
        }
        if token.expires_at is not None:
            response_values["exp"] = _token_timestamp(token.expires_at)
        return JsonResponse(response_values)

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        caller_token = self._caller_token(request)
        if isinstance(caller_token, HttpResponse):
            return caller_token

        submitted_token = self._submitted_token(request, caller_token)
        token = self._token_for_key(submitted_token, log_prefix="introspection target")
        if token is None:
            return self._inactive_response()
        if token.owner_id != caller_token.owner_id:
            logger.info("introspection rejected target token owned by a different user")
            return self._inactive_response()
        return self._active_response(token)


class UserLoginRequiredMixin(View):
    """Mixin for browser views that require a logged-in Django user."""

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponseBase:
        if not request.user.is_authenticated:
            login_url = getattr(settings, "LOGIN_URL", "/accounts/login/")
            return redirect(f"{login_url}?next={request.get_full_path()}")
        return super().dispatch(request, *args, **kwargs)


class TokenManagementView(UserLoginRequiredMixin, View):
    """List access tokens owned by the authenticated user."""

    def get(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponseBase:
        tokens = Token.objects.filter(owner_id=request.user.pk).order_by("-created")
        return render(request, "indieweb/tokens.html", {"tokens": tokens})


class TokenRevokeView(UserLoginRequiredMixin, View):
    """Revoke an access token owned by the authenticated user."""

    def post(self, request: HttpRequest, pk: int, *args: object, **kwargs: object) -> HttpResponseBase:
        token = get_object_or_404(Token, pk=pk, owner_id=request.user.pk)
        token.delete()
        return redirect("indieweb:tokens")


class MicropubView(CSRFExemptMixin, CorsMixin, RateLimitMixin, TokenAuthMixin, View):
    """
    Micropub endpoint for creating posts.

    Implements the Micropub protocol for creating content on the site.
    Requires valid access token with appropriate scope.
    GET: Returns configuration/verification info or handles queries
    POST: Creates new content
    """

    request: HttpRequest
    rate_limit_key = "micropub"
    cors_allowed_methods = ("GET", "POST")

    @staticmethod
    def _normalized_property_name(name: str) -> str:
        """Return the Micropub property name represented by a submitted field name."""
        if name.endswith("[]"):
            return name[:-2]
        return name

    @classmethod
    def _has_server_managed_property(cls, property_names: object) -> bool:
        """Return whether submitted property names include view/server-owned properties."""
        if not isinstance(property_names, dict | list | tuple | set):
            return False
        return any(
            isinstance(name, str) and cls._normalized_property_name(name) in MICROPUB_SERVER_MANAGED_PROPERTIES
            for name in property_names
        )

    def _form_create_has_server_managed_property(self, request: HttpRequest) -> bool:
        """Return whether raw form fields include server-managed create properties."""
        return self._has_server_managed_property(request.POST)

    def _properties_have_server_managed_property(self, properties: dict[str, Any]) -> bool:
        """Return whether parsed create properties include server-managed properties."""
        return self._has_server_managed_property(properties)

    def _create_server_managed_property_error(self, request: HttpRequest) -> HttpResponse | None:
        """Reject raw form creates that submit server-managed properties before parsing side effects."""
        if request.content_type != "application/json" and self._form_create_has_server_managed_property(request):
            return self._invalid_request()
        return None

    def _parse_json_request(self, request: HttpRequest) -> dict[str, Any]:
        """Parse JSON formatted Micropub request."""
        try:
            data = json.loads(request.body)
            # Convert JSON format to normalized properties format
            if "type" in data and isinstance(data["type"], list):
                # Already in microformats2 JSON format
                properties: dict[str, Any] = data.get("properties", {})
                return properties
            else:
                # Convert simple JSON to properties format
                properties = {}
                for key, value in data.items():
                    if key not in ["access_token", "h", "action", "url"]:
                        properties[key] = [value] if not isinstance(value, list) else value
                return properties
        except json.JSONDecodeError:
            return {}

    def _parse_form_property(self, request: HttpRequest, property_name: str, is_list: bool = False) -> dict[str, Any]:
        """Parse a single property from form data."""
        properties = {}
        if is_list:
            if f"{property_name}[]" in request.POST:
                properties[property_name] = request.POST.getlist(f"{property_name}[]")
        else:
            if property_name in request.POST:
                value = request.POST.get(property_name, "")
                if property_name == "category" and "," in value:
                    # Handle comma-separated categories
                    properties[property_name] = [c.strip() for c in value.split(",") if c.strip()]
                elif value:  # Only add non-empty values
                    properties[property_name] = [value]
        return properties

    def _parse_form_request(self, request: HttpRequest) -> dict[str, Any]:
        """Parse form-encoded Micropub request."""
        properties = {}

        # Simple properties (including category which can be comma-separated)
        for prop in MICROPUB_FORM_CREATE_PROPERTIES:
            properties.update(self._parse_form_property(request, prop))

        # List properties (override if array format is used)
        for prop in MICROPUB_FORM_CREATE_LIST_PROPERTIES:
            list_props = self._parse_form_property(request, prop, is_list=True)
            if list_props:
                properties.update(list_props)

        photo_uploads = request.FILES.getlist("photo")
        for media_url in _store_micropub_media_uploads(request, photo_uploads):
            photo_values = properties.setdefault("photo", [])
            photo_values.append(media_url)

        return properties

    def parse_request_data(self, request: HttpRequest) -> dict[str, Any]:
        """Parse Micropub data from either form-encoded or JSON request."""
        if request.content_type == "application/json":
            return self._parse_json_request(request)
        else:
            return self._parse_form_request(request)

    def _post_action(self, request: HttpRequest) -> str | None:
        """Return the ``action`` value from a POST body, regardless of encoding."""
        action = request.POST.get("action")
        if action:
            return action
        if request.content_type == "application/json":
            try:
                payload = json.loads(request.body)
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                return None
            if isinstance(payload, dict):
                value = payload.get("action")
                if isinstance(value, str):
                    return value
        return None

    def _required_scope(self, request: HttpRequest) -> str | None:
        """Return the Micropub scope required for this request.

        The W3C Micropub Recommendation (§5 Scope) allows servers to define
        their own granular scopes. This is the project's chosen mapping;
        it follows the operation taxonomy that Micropub defines and uses
        the conventional scope names that reference clients (Quill, Indigenous,
        Micropublish) request:

        * ``POST`` (no action) → ``create`` (legacy alias ``post`` accepted)
        * ``POST action=update`` → ``update``
        * ``POST action=delete`` → ``delete``
        * ``POST action=undelete`` → ``undelete``
        * ``GET ?q=source`` → ``update`` (typical "read before update" use case;
          the spec does not define a separate read scope)
        * ``GET ?q=config``, ``?q=syndicate-to``, ``?q=category``, ``?q=channel``,
          ``?q=media-endpoint``, ``?q=post-types``, ``GET`` (no ``q``) → ``None``
          (token-required, no scope gate)
        """
        if request.method == "POST":
            action = self._post_action(request)
            if action == "update":
                return "update"
            if action == "delete":
                return "delete"
            if action == "undelete":
                return "undelete"
            return "create"
        if request.method == "GET" and request.GET.get("q") == "source":
            return "update"
        return None

    def _scope_authorized(self, request: HttpRequest) -> bool:
        """Apply the per-operation scope gate, accepting ``post`` as a ``create`` alias."""
        required = self._required_scope(request)
        if required is None:
            return True
        if self.authorized(self.token.client_id, self.token.scope, required):
            return True
        if required == "create" and self.authorized(self.token.client_id, self.token.scope, "post"):
            return True
        return False

    def _reject_invalid_json(self, request: HttpRequest) -> HttpResponse | None:
        """Reject a request with ``Content-Type: application/json`` whose body fails to parse.

        Returns a ``400 invalid_request`` response when the body cannot be decoded as JSON
        or does not decode to an object; otherwise ``None``. Called at the top of ``post()``
        so that malformed JSON cannot fall through to the create path or the action handlers
        and silently produce surprising behavior (e.g. an empty entry being created).

        Catches ``json.JSONDecodeError`` (syntax errors), ``UnicodeDecodeError`` (invalid
        UTF-8 in ``request.body``; ``json.loads`` decodes bytes as UTF-8 internally), and
        ``AttributeError`` (defensive — ``request.body`` should always be bytes, but a
        misbehaving middleware could substitute it). All three become ``400 invalid_request``
        rather than a ``500`` from the unhandled exception path.
        """
        if request.content_type != "application/json":
            return None
        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            return self._invalid_request()
        if not isinstance(payload, dict):
            return self._invalid_request()
        return None

    def _action_payload(self, request: HttpRequest) -> dict[str, Any] | None:
        """Return the parsed JSON body for an action POST, or ``None`` if it isn't JSON.

        Used by ``action=update`` (which is JSON-only per Micropub §3.7) and as a fallback
        for ``url`` extraction on JSON-bodied delete/undelete requests. By the time this
        runs in the action path the body has already been validated by ``_reject_invalid_json``,
        so the ``json.loads`` call is expected to succeed; the defensive ``except`` mirrors
        the guard's catch list so this helper is safe to call independently.
        """
        if request.content_type != "application/json":
            return None
        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _action_url(self, request: HttpRequest) -> str | None:
        """Return the target ``url`` for an action POST, accepting form-encoded and JSON bodies."""
        url = request.POST.get("url")
        if url:
            return url
        payload = self._action_payload(request)
        if payload is None:
            return None
        value = payload.get("url")
        if isinstance(value, str) and value:
            return value
        return None

    def _invalid_request(self) -> HttpResponse:
        """Return the standard 400 plain-text body the action handlers use for client errors."""
        return HttpResponse("invalid_request", status=400)

    def _action_response(self, request: HttpRequest, entry: MicropubEntry, submitted_url: str) -> HttpResponse:
        """Build a success response for ``update``/``undelete``: 204, or 201+Location if URL changed."""
        if entry.url == submitted_url:
            return HttpResponse(status=204)
        response = HttpResponse(status=201)
        if entry.url.startswith("http"):
            response["Location"] = entry.url
        else:
            response["Location"] = request.build_absolute_uri(entry.url)
        return response

    @staticmethod
    def _valid_property_map(value: Any) -> bool:
        """Return whether ``value`` is a dict mapping property names to arrays of values (§3.4)."""
        if not isinstance(value, dict):
            return False
        return all(isinstance(prop_values, list) for prop_values in value.values())

    @staticmethod
    def _valid_delete_value(value: Any) -> bool:
        """Return whether a Micropub ``delete`` value is well-formed (§3.4).

        A ``delete`` is either a list of property-name strings, or a dict mapping property
        names to arrays of values to remove from those properties.
        """
        if isinstance(value, list):
            return all(isinstance(name, str) for name in value)
        if isinstance(value, dict):
            return all(isinstance(prop_values, list) for prop_values in value.values())
        return False

    def _validate_update_operations(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Validate and extract update operations from a JSON update payload per Micropub §3.4.

        The spec requires that an update body include at least one of ``replace``, ``add``,
        or ``delete``; that ``replace`` and ``add`` map property names to *arrays* of values;
        and that ``delete`` is either a list of property names or a map of property names to
        arrays of values to remove. Scalar values inside operations and an empty update body
        are spec violations and must be rejected here rather than papered over by the
        handler's normalization. Returns the operations dict on success, or ``None`` on any
        validation failure.
        """
        updates: dict[str, Any] = {}
        for key in ("replace", "add"):
            if key not in payload:
                continue
            if not self._valid_property_map(payload[key]):
                return None
            updates[key] = payload[key]
        if "delete" in payload:
            if not self._valid_delete_value(payload["delete"]):
                return None
            updates["delete"] = payload["delete"]
        if not updates:
            return None
        return updates

    def _updates_have_server_managed_property(self, updates: dict[str, Any]) -> bool:
        """Return whether update operations attempt to mutate server-managed properties."""
        for key in ("replace", "add"):
            operation = updates.get(key)
            if isinstance(operation, dict) and self._has_server_managed_property(operation):
                return True
        delete = updates.get("delete")
        if isinstance(delete, dict | list) and self._has_server_managed_property(delete):
            return True
        return False

    def _handle_update(self, request: HttpRequest) -> HttpResponse:
        """Dispatch ``action=update``. JSON-only; validates the body shape before forwarding.

        Returns ``500`` (not ``400``) for handler exceptions other than ``ValueError`` so a
        database error or handler bug does not surface as a non-retryable client error.
        """
        url = self._action_url(request)
        if not url:
            return self._invalid_request()
        payload = self._action_payload(request)
        if payload is None:
            return self._invalid_request()
        updates = self._validate_update_operations(payload)
        if updates is None:
            return self._invalid_request()
        if self._updates_have_server_managed_property(updates):
            return self._invalid_request()
        handler = get_micropub_handler()
        try:
            entry = handler.update_entry(url, updates, self.token.owner)
        except ValueError as exc:
            logger.warning(f"update_entry rejected url={url!r}: {exc}")
            return self._invalid_request()
        except Exception:
            logger.exception(f"Unexpected error in update_entry for url={url!r}")
            return HttpResponse(status=500)
        return self._action_response(request, entry, url)

    def _handle_delete(self, request: HttpRequest) -> HttpResponse:
        """Dispatch ``action=delete``. Accepts form-encoded and JSON bodies; both need ``url``."""
        url = self._action_url(request)
        if not url:
            return self._invalid_request()
        handler = get_micropub_handler()
        try:
            handler.delete_entry(url, self.token.owner)
        except ValueError as exc:
            logger.warning(f"delete_entry rejected url={url!r}: {exc}")
            return self._invalid_request()
        except Exception:
            logger.exception(f"Unexpected error in delete_entry for url={url!r}")
            return HttpResponse(status=500)
        return HttpResponse(status=204)

    def _handle_undelete(self, request: HttpRequest) -> HttpResponse:
        """Dispatch ``action=undelete``. Accepts form-encoded and JSON bodies; both need ``url``."""
        url = self._action_url(request)
        if not url:
            return self._invalid_request()
        handler = get_micropub_handler()
        try:
            entry = handler.undelete_entry(url, self.token.owner)
        except ValueError as exc:
            logger.warning(f"undelete_entry rejected url={url!r}: {exc}")
            return self._invalid_request()
        except Exception:
            logger.exception(f"Unexpected error in undelete_entry for url={url!r}")
            return HttpResponse(status=500)
        return self._action_response(request, entry, url)

    def _post_action_response(self, request: HttpRequest) -> HttpResponse | None:
        """Dispatch a Micropub action POST, or return ``None`` for create requests."""
        action = self._post_action(request)
        if action == "update":
            return self._handle_update(request)
        if action == "delete":
            return self._handle_delete(request)
        if action == "undelete":
            return self._handle_undelete(request)
        return None

    @staticmethod
    def _parse_optional_non_negative_int(value: str | None) -> int | None:
        """Parse an optional non-negative ``int`` query value.

        Returns ``None`` when the parameter is omitted, the parsed value when it is a
        well-formed non-negative integer, and raises ``ValueError`` for malformed
        input that the caller should reject with ``400 invalid_request``. Floats like
        ``"1.5"`` and negative values like ``"-1"`` are treated as malformed protocol
        input rather than silently coerced to ``0``.
        """
        if value is None:
            return None
        parsed = int(value)
        if parsed < 0:
            raise ValueError
        return parsed

    @staticmethod
    def _query_filter_match(item: Any, needle: str) -> bool:
        """Return whether a list item matches a case-insensitive substring filter.

        Strings are matched directly; non-string items (typically dicts such as
        ``{"uid": ..., "name": ...}``) are matched against a stable JSON
        serialization so common fields are searchable without a per-shape policy.
        """
        if isinstance(item, str):
            return needle in item.lower()
        return needle in json.dumps(item, sort_keys=True).lower()

    def _filtered_query_items(self, items: list[Any], request: HttpRequest) -> list[Any] | None:
        """Apply ``filter``/``offset``/``limit`` to a list-valued query response.

        Returns the filtered list, or ``None`` when ``limit``/``offset`` are malformed
        so the caller can return ``400 invalid_request``. ``filter`` is a free-form
        string that is compared case-insensitively as a substring; an empty value
        matches every item. The order is filter → offset → limit, matching the
        Indiekit reference and avoiding surprising interactions with ``offset``.
        """
        try:
            limit = self._parse_optional_non_negative_int(request.GET.get("limit"))
            offset = self._parse_optional_non_negative_int(request.GET.get("offset"))
        except ValueError:
            return None

        filter_value = request.GET.get("filter")
        result = list(items)
        if filter_value:
            needle = filter_value.lower()
            result = [item for item in result if self._query_filter_match(item, needle)]
        if isinstance(offset, int):
            result = result[offset:]
        if isinstance(limit, int):
            result = result[:limit]
        return result

    def _micropub_config(self, request: HttpRequest) -> dict[str, Any]:
        """Return a copied handler config with view-owned defaults injected."""
        handler = get_micropub_handler()
        config = dict(handler.get_config(self.token.owner))
        if not config.get("media-endpoint"):
            config["media-endpoint"] = request.build_absolute_uri(_reverse_request_namespace(request, "media"))
        return config

    def _handle_config_query(self, request: HttpRequest) -> HttpResponse:
        """Return the aggregate ``q=config`` response with media-endpoint and ``q`` advertisement."""
        config = self._micropub_config(request)
        config["q"] = list(SUPPORTED_MICROPUB_QUERIES)
        return HttpResponse(json.dumps(config), content_type="application/json")

    def _handle_list_config_query(self, request: HttpRequest, config_key: str) -> HttpResponse:
        """Return a list-valued config property under ``config_key`` with filter/limit/offset.

        Used for ``q=category`` (``categories``) and ``q=channel`` (``channels``). When the
        configured handler omits the key or returns a non-list value, the response is an
        empty list rather than an error, matching the rest of the Micropub query surface.
        """
        config = self._micropub_config(request)
        raw = config.get(config_key, [])
        if not isinstance(raw, list):
            raw = []
        filtered = self._filtered_query_items(raw, request)
        if filtered is None:
            return self._invalid_request()
        return HttpResponse(json.dumps({config_key: filtered}), content_type="application/json")

    def _handle_post_types_query(self, request: HttpRequest) -> HttpResponse:
        """Return the handler's ``post-types`` config list, narrowing by ``post-type`` before list filters."""
        config = self._micropub_config(request)
        raw = config.get("post-types", [])
        if not isinstance(raw, list):
            raw = []

        post_type = request.GET.get("post-type")
        if post_type:
            raw = [item for item in raw if isinstance(item, dict) and item.get("type") == post_type]

        filtered = self._filtered_query_items(raw, request)
        if filtered is None:
            return self._invalid_request()
        return HttpResponse(json.dumps({"post-types": filtered}), content_type="application/json")

    def _handle_media_endpoint_query(self, request: HttpRequest) -> HttpResponse:
        """Return the effective media endpoint as a direct config subquery."""
        config = self._micropub_config(request)
        return HttpResponse(json.dumps({"media-endpoint": config["media-endpoint"]}), content_type="application/json")

    def _handle_syndicate_to_query(self, request: HttpRequest) -> HttpResponse:
        """Return configured Micropub syndication targets as a direct config query."""
        config = self._micropub_config(request)
        raw = config.get("syndicate-to", [])
        if not isinstance(raw, list):
            raw = []
        return HttpResponse(json.dumps({"syndicate-to": raw}), content_type="application/json")

    def _handle_source_query(self, request: HttpRequest) -> HttpResponse:
        """Dispatch ``GET ?q=source`` using the configured content handler."""
        handler = get_micropub_handler()
        if "url" not in request.GET:
            return self._handle_source_list_query(request, handler)

        url = request.GET.get("url")
        if not url:
            return self._invalid_request()

        try:
            entry = handler.get_entry(url, self.token.owner)
        except ValueError as exc:
            logger.warning(f"get_entry rejected url={url!r}: {exc}")
            return self._invalid_request()
        except Exception:
            logger.exception(f"Unexpected error in get_entry for url={url!r}")
            return HttpResponse(status=500)
        if entry is None:
            logger.warning(f"get_entry did not find url={url!r}")
            return self._invalid_request()

        requested_properties = request.GET.getlist("properties[]")
        if requested_properties:
            properties = {
                property_name: entry.properties[property_name]
                for property_name in requested_properties
                if property_name in entry.properties
            }
            # Micropub §3.7.2's selective-properties examples omit ``type``.
            body: dict[str, Any] = {"properties": properties}
        else:
            body = {"type": entry.type, "properties": entry.properties}
        return HttpResponse(json.dumps(body), content_type="application/json")

    @staticmethod
    def _source_list_item(entry: MicropubEntry) -> dict[str, Any]:
        """Return the Microformats-style source-list item for a handler entry."""
        properties = dict(entry.properties)
        properties.setdefault("url", [entry.url])
        return {"type": entry.type, "properties": properties}

    def _handle_source_list_query(self, request: HttpRequest, handler: MicropubContentHandler) -> HttpResponse:
        """Dispatch ``GET ?q=source`` without ``url`` into the optional list hook."""
        try:
            limit = self._parse_optional_non_negative_int(request.GET.get("limit"))
            offset = self._parse_optional_non_negative_int(request.GET.get("offset"))
        except ValueError:
            return self._invalid_request()

        effective_limit = DEFAULT_MICROPUB_SOURCE_LIST_LIMIT if limit is None else limit
        effective_offset = 0 if offset is None else offset

        try:
            result = handler.list_entries(
                self.token.owner,
                limit=effective_limit,
                offset=effective_offset,
                filter=request.GET.get("filter") or None,
            )
        except ValueError as exc:
            logger.warning(
                "list_entries rejected source list query "
                f"limit={effective_limit!r} offset={effective_offset!r} filter={request.GET.get('filter')!r}: {exc}"
            )
            return self._invalid_request()
        except Exception:
            logger.exception(
                "Unexpected error in list_entries for source list query "
                f"limit={effective_limit!r} offset={effective_offset!r} filter={request.GET.get('filter')!r}"
            )
            return HttpResponse(status=500)

        if result is None:
            return HttpResponse("not_implemented", status=501)

        body: dict[str, Any] = {
            "items": [self._source_list_item(entry) for entry in result.entries],
            "paging": {
                "limit": effective_limit,
                "offset": effective_offset,
            },
        }
        if result.total is not None:
            body["paging"]["total"] = result.total
        return HttpResponse(json.dumps(body), content_type="application/json")

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        """Handle POST requests to create or modify content."""
        self.request = request

        json_error = self._reject_invalid_json(request)
        if json_error is not None:
            return json_error

        if not self._scope_authorized(request):
            return HttpResponse("authorization error", status=403)

        action_response = self._post_action_response(request)
        if action_response is not None:
            return action_response

        create_property_error = self._create_server_managed_property_error(request)
        if create_property_error is not None:
            return create_property_error

        # Parse properties from request
        try:
            properties = self.parse_request_data(request)
        except _MicropubMediaUploadError as exc:
            return _micropub_media_upload_error_response(exc)
        if self._properties_have_server_managed_property(properties):
            return self._invalid_request()

        # Get the content handler and create entry
        handler = get_micropub_handler()

        try:
            entry = handler.create_entry(properties, self.token.owner)

            # Return 201 Created with Location header
            response = HttpResponse(status=201)
            # Build full URL - check if entry.url is already absolute
            if entry.url.startswith("http"):
                response["Location"] = entry.url
            else:
                # Build absolute URL from request
                response["Location"] = request.build_absolute_uri(entry.url)

            return response

        except Exception as e:
            logger.error(f"Error creating micropub entry: {e}")
            return HttpResponse(f"Error creating entry: {str(e)}", status=400)

    def get(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        """Handle GET requests for queries and configuration."""
        if not self._scope_authorized(request):
            return HttpResponse("authorization error", status=403)

        q = request.GET.get("q")

        if q == "config":
            return self._handle_config_query(request)
        elif q == "source":
            return self._handle_source_query(request)
        elif q == "syndicate-to":
            return self._handle_syndicate_to_query(request)
        elif q == "category":
            return self._handle_list_config_query(request, "categories")
        elif q == "channel":
            return self._handle_list_config_query(request, "channels")
        elif q == "media-endpoint":
            return self._handle_media_endpoint_query(request)
        elif q == "post-types":
            return self._handle_post_types_query(request)
        else:
            # Default response with user's me URL
            params = {"me": self.token.me}
            return HttpResponse(urlencode(params), status=200)


class MicropubMediaView(CSRFExemptMixin, CorsMixin, RateLimitMixin, TokenAuthMixin, View):
    """
    Micropub media endpoint for direct file uploads and host-owned media hooks.

    Accepts multipart/form-data uploads with a single ``file`` part, stores
    the file through Django's configured storage backend, and returns the
    stored media URL in the Location header. Optional source and delete hooks
    are delegated to the configured Micropub handler when the host implements
    them.
    """

    rate_limit_key = "media"
    cors_allowed_methods = ("GET", "POST")

    def _scope_authorized(self) -> bool:
        """Require the conventional Micropub ``media`` scope for all media operations."""
        return self.authorized(self.token.client_id, self.token.scope, MICROPUB_MEDIA_SCOPE)

    def _invalid_request(self) -> HttpResponse:
        return HttpResponse("invalid_request", status=400)

    def _not_implemented(self) -> HttpResponse:
        return HttpResponse("not_implemented", status=501)

    @staticmethod
    def _parse_optional_non_negative_int(value: str | None) -> int | None:
        if value is None:
            return None
        parsed = int(value)
        if parsed < 0:
            raise ValueError
        return parsed

    @staticmethod
    def _media_item_body(item: MicropubMediaItem) -> dict[str, Any]:
        properties = dict(item.properties)
        properties.setdefault("url", [item.url])
        return {"properties": properties}

    @staticmethod
    def _handler_overrides(handler: MicropubContentHandler, method_name: str) -> bool:
        return getattr(type(handler), method_name) is not getattr(MicropubContentHandler, method_name)

    def _delete_action(self, request: HttpRequest) -> str | None:
        action = request.POST.get("action")
        if action:
            return action
        if request.content_type == "application/json":
            payload = self._json_payload(request)
            if payload is None:
                return None
            value = payload.get("action")
            if isinstance(value, str):
                return value
        return None

    def _json_payload(self, request: HttpRequest) -> dict[str, Any] | None:
        if request.content_type != "application/json":
            return None
        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _delete_url(self, request: HttpRequest) -> str | None:
        url = request.POST.get("url")
        if url:
            return url
        payload = self._json_payload(request)
        if payload is None:
            return None
        value = payload.get("url")
        if isinstance(value, str) and value:
            return value
        return None

    def _handle_source_by_url_query(self, request: HttpRequest, handler: MicropubContentHandler) -> HttpResponse:
        url = request.GET.get("url")
        if not url:
            return self._invalid_request()
        if not self._handler_overrides(handler, "get_media"):
            return self._not_implemented()
        try:
            item = handler.get_media(url, self.token.owner)
        except ValueError as exc:
            logger.warning(f"get_media rejected url={url!r}: {exc}")
            return self._invalid_request()
        except Exception:
            logger.exception(f"Unexpected error in get_media for url={url!r}")
            return HttpResponse(status=500)
        if item is None:
            logger.warning(f"get_media did not find url={url!r}")
            return self._invalid_request()
        return HttpResponse(json.dumps(self._media_item_body(item)), content_type="application/json")

    def _handle_source_list_query(self, request: HttpRequest, handler: MicropubContentHandler) -> HttpResponse:
        if not self._handler_overrides(handler, "list_media"):
            return self._not_implemented()

        try:
            limit = self._parse_optional_non_negative_int(request.GET.get("limit"))
            offset = self._parse_optional_non_negative_int(request.GET.get("offset"))
        except ValueError:
            return self._invalid_request()

        effective_offset = 0 if offset is None else offset
        try:
            result = handler.list_media(
                self.token.owner,
                limit=limit,
                offset=effective_offset,
                filter=request.GET.get("filter") or None,
            )
        except ValueError as exc:
            logger.warning(
                "list_media rejected source query "
                f"limit={limit!r} offset={effective_offset!r} filter={request.GET.get('filter')!r}: {exc}"
            )
            return self._invalid_request()
        except Exception:
            logger.exception(
                "Unexpected error in list_media for source query "
                f"limit={limit!r} offset={effective_offset!r} filter={request.GET.get('filter')!r}"
            )
            return HttpResponse(status=500)

        if result is None:
            return self._not_implemented()

        body: dict[str, Any] = {
            "items": [self._media_item_body(item) for item in result.items],
            "paging": {
                "limit": limit,
                "offset": effective_offset,
            },
        }
        if result.total is not None:
            body["paging"]["total"] = result.total
        return HttpResponse(json.dumps(body), content_type="application/json")

    def _handle_source_query(self, request: HttpRequest) -> HttpResponse:
        handler = get_micropub_handler()
        if "url" in request.GET:
            return self._handle_source_by_url_query(request, handler)
        return self._handle_source_list_query(request, handler)

    def _handle_delete(self, request: HttpRequest) -> HttpResponse:
        url = self._delete_url(request)
        if not url:
            return self._invalid_request()

        handler = get_micropub_handler()
        if not self._handler_overrides(handler, "delete_media"):
            return self._not_implemented()
        try:
            deleted = handler.delete_media(url, self.token.owner)
        except ValueError as exc:
            logger.warning(f"delete_media rejected url={url!r}: {exc}")
            return self._invalid_request()
        except Exception:
            logger.exception(f"Unexpected error in delete_media for url={url!r}")
            return HttpResponse(status=500)

        if deleted is not True:
            logger.warning(f"delete_media did not delete url={url!r}")
            return self._invalid_request()
        return HttpResponse(status=204)

    def get(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if not self._scope_authorized():
            return HttpResponse("authorization error", status=403)

        q = request.GET.get("q")
        if not q:
            return self._invalid_request()
        if q != "source":
            return self._not_implemented()
        return self._handle_source_query(request)

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if not self._scope_authorized():
            return HttpResponse("authorization error", status=403)

        if self._delete_action(request) == "delete":
            return self._handle_delete(request)

        if request.content_type != "multipart/form-data" or "file" not in request.FILES:
            return self._invalid_request()

        upload = cast("UploadedFile", request.FILES["file"])
        try:
            location = _store_micropub_media_upload(request, upload)
        except _MicropubMediaUploadError as exc:
            return _micropub_media_upload_error_response(exc)

        response = HttpResponse(status=201)
        response["Location"] = location
        return response


class WebSubCallbackView(CSRFExemptMixin, RateLimitMixin, View):
    """WebSub subscriber callback for verification and content distribution."""

    rate_limit_key = "websub_callback"

    def _get_subscription(self, token: str) -> WebSubSubscription | None:
        try:
            return WebSubSubscription.objects.get(callback_token=token)
        except WebSubSubscription.DoesNotExist:
            return None

    def get(self, request: HttpRequest, token: str, *args: object, **kwargs: object) -> HttpResponse:
        """Handle WebSub subscribe/unsubscribe verification or denial callbacks."""
        subscription = self._get_subscription(token)
        if subscription is None:
            return HttpResponse(status=404)

        mode = request.GET.get("hub.mode")
        topic = request.GET.get("hub.topic")
        if not mode or not topic:
            return HttpResponse(status=400)

        if mode == "denied":
            try:
                record_websub_denial(
                    subscription,
                    topic_url=topic,
                    reason=request.GET.get("hub.reason", ""),
                )
            except ValueError as exc:
                logger.warning(f"Rejected WebSub denial for subscription {subscription.pk}: {exc}")
                return HttpResponse(status=400)
            return HttpResponse(status=204)

        challenge = request.GET.get("hub.challenge")
        if not challenge:
            return HttpResponse(status=400)

        try:
            confirm_websub_verification(
                subscription,
                mode=mode,
                topic_url=topic,
                challenge=challenge,
                lease_seconds=request.GET.get("hub.lease_seconds"),
            )
        except ValueError as exc:
            logger.warning(f"Rejected WebSub verification for subscription {subscription.pk}: {exc}")
            return HttpResponse(status=400)

        return HttpResponse(challenge, status=200, content_type="text/plain")

    def post(self, request: HttpRequest, token: str, *args: object, **kwargs: object) -> HttpResponse:
        """Acknowledge a content distribution POST and hand it to an optional host hook."""
        subscription = self._get_subscription(token)
        if subscription is None or subscription.state != WebSubSubscription.STATE_ACTIVE:
            return HttpResponse(status=404)

        content_type = request.headers.get("Content-Type", "")
        if delivery_content_length_too_large(request.headers.get("Content-Length")):
            record_websub_delivery(subscription, b"", content_type=content_type, status_code=413, error="too large")
            return HttpResponse(status=413)

        body = _read_request_body_with_invalid_content_length_fallback(request)
        if delivery_body_too_large(body):
            record_websub_delivery(subscription, body, content_type=content_type, status_code=413, error="too large")
            return HttpResponse(status=413)
        if not delivery_content_type_allowed(content_type):
            record_websub_delivery(
                subscription,
                body,
                content_type=content_type,
                status_code=415,
                error="unsupported content type",
            )
            return HttpResponse(status=415)

        try:
            signature_algorithm = validate_websub_delivery_signature(subscription, body, request.headers)
        except ValueError as exc:
            logger.warning(f"Rejected WebSub delivery for subscription {subscription.pk}: {exc}")
            record_websub_delivery(
                subscription,
                body,
                content_type=content_type,
                status_code=403,
                error="invalid signature",
            )
            return HttpResponse(status=403)

        try:
            process_websub_delivery(subscription, body, request.headers)
        except WebSubDeliveryHookError:
            record_websub_delivery(
                subscription,
                body,
                content_type=content_type,
                status_code=500,
                error="delivery hook failed",
                signature_algorithm=signature_algorithm,
            )
            return HttpResponse(status=500)

        record_websub_delivery(
            subscription,
            body,
            content_type=content_type,
            status_code=204,
            signature_algorithm=signature_algorithm,
        )
        return HttpResponse(status=204)


class WebmentionEndpoint(CSRFExemptMixin, CorsMixin, RateLimitMixin, View):
    """
    Webmention receiving endpoint.

    Implements the W3C Webmention protocol for receiving notifications
    when other sites mention content on this site.
    """

    rate_limit_key = "webmention"
    cors_allowed_methods = ("GET", "POST")

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        """Handle incoming webmentions."""
        source = request.POST.get("source")
        target = request.POST.get("target")
        vouch = request.POST.get("vouch") or None

        # Basic validation
        if not source or not target:
            return HttpResponse(status=400)

        # Validate URLs
        validator = URLValidator(schemes=["http", "https"])
        try:
            validator(source)
            validator(target)
            if vouch is not None:
                validator(vouch)
        except ValidationError:
            return HttpResponse(status=400)

        # Check target is on our domain
        if not self.is_valid_target(target):
            return HttpResponse(status=400)

        try:
            enqueue_webmention = _get_webmention_enqueue()
        except _WebmentionEnqueueError:
            return HttpResponse(status=500)

        if enqueue_webmention is not None:
            webmention = _store_webmention_submission(source, target, vouch)
            try:
                enqueue_webmention(webmention.pk)
            except Exception:
                logger.exception(f"Failed to enqueue webmention {webmention.pk}")
                return HttpResponse(status=500)

            response = HttpResponse(status=202)  # Accepted for queued processing
            response["Location"] = request.build_absolute_uri(
                reverse("indieweb:webmention-status", args=[webmention.pk])
            )
            return response

        # Process synchronously
        processor = WebmentionProcessor()
        try:
            webmention = processor.process_webmention(source, target, vouch_url=vouch)
            response = HttpResponse(status=201)  # Created
            response["Location"] = request.build_absolute_uri(
                reverse("indieweb:webmention-status", args=[webmention.pk])
            )
            return response
        except Exception as e:
            logger.error(f"Failed to process webmention: {e}")
            return HttpResponse(status=400)

    def is_valid_target(self, target_url: str) -> bool:
        """Check if target URL is on our domain."""
        try:
            current_site = Site.objects.get_current()
            parsed = urlparse(target_url)
            return parsed.netloc.lower() == current_site.domain.lower()
        except Exception:
            return False

    def get(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        """Return endpoint discovery info."""
        # Add Link header for discovery
        response = HttpResponse(
            "Webmention endpoint",
            content_type="text/plain",
        )
        endpoint_url = request.build_absolute_uri(request.path)
        response["Link"] = f'<{endpoint_url}>; rel="webmention"'
        return response


class WebmentionStatusView(CorsMixin, RateLimitMixin, View):
    """
    Webmention status endpoint.

    Returns the status of a specific webmention by ID.
    """

    rate_limit_key = "webmention_status"
    cors_allowed_methods = ("GET",)

    def get(self, request: HttpRequest, pk: int, *args: object, **kwargs: object) -> HttpResponse:
        """Return status of a webmention."""
        webmention = get_object_or_404(Webmention, pk=pk)

        # Return JSON response with webmention status
        status_data = {
            "source": webmention.source_url,
            "target": webmention.target_url,
            "status": webmention.status,
        }

        if webmention.vouch_url:
            status_data["vouch"] = webmention.vouch_url

        if webmention.verified_at:
            status_data["verified_at"] = webmention.verified_at.isoformat()

        if webmention.vouch_verified_at:
            status_data["vouch_verified_at"] = webmention.vouch_verified_at.isoformat()

        return HttpResponse(
            json.dumps(status_data),
            content_type="application/json",
        )
