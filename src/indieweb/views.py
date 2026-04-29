from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import math
import re
import uuid
from datetime import timedelta
from pathlib import PurePath
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qsl, urlparse, urlunparse
from urllib.parse import urlencode as urllib_urlencode

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.validators import URLValidator
from django.http import HttpRequest, HttpResponse, HttpResponseBase
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import urlencode
from django.utils.module_loading import import_string
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View

from .handlers import get_micropub_handler
from .models import Auth, Token, Webmention
from .processors import WebmentionProcessor

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser
    from django.core.files.uploadedfile import UploadedFile

    from .handlers import MicropubEntry

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_EXPIRES_IN = 86400
ALLOWED_REDIRECT_URI_SCHEMES = ("http", "https")
ALLOWED_PKCE_METHODS = ("plain", "S256")
PKCE_UNRESERVED_RE = re.compile(r"^[A-Za-z0-9._~\-]+$")
PKCE_CHALLENGE_MIN = 43
PKCE_CHALLENGE_MAX = 128
PKCE_VERIFIER_MIN = 43
PKCE_VERIFIER_MAX = 128
MICROPUB_MEDIA_SCOPE = "media"
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


def _client_id_allowed(client_id: str) -> bool:
    """Return whether ``client_id`` passes the optional operator policy hook.

    When ``INDIEWEB_CLIENT_ID_VALIDATOR`` is unset, every ``client_id`` is
    permitted (preserving backwards compatibility for deployments that have
    not opted in to client allowlisting). When the setting is configured but
    the dotted path cannot be imported, or the callable raises, this fails
    closed and returns ``False`` so a misconfiguration cannot silently weaken
    access control.
    """
    validator_path = getattr(settings, "INDIEWEB_CLIENT_ID_VALIDATOR", None)
    if not validator_path:
        return True
    try:
        validator = import_string(validator_path)
    except Exception as exc:
        logger.error(f"Failed to load INDIEWEB_CLIENT_ID_VALIDATOR {validator_path}: {exc}")
        return False
    try:
        return bool(validator(client_id))
    except Exception as exc:
        logger.error(f"INDIEWEB_CLIENT_ID_VALIDATOR raised for client_id={client_id!r}: {exc}")
        return False


def _normalize_redirect_uri(value: str) -> str:
    """Return ``value`` with scheme and host lowercased.

    Path, query and fragment are preserved verbatim. Used for comparison only;
    the original value is what is sent to the client.
    """
    parsed = urlparse(value)
    netloc = parsed.netloc.lower()
    scheme = parsed.scheme.lower()
    return parsed._replace(scheme=scheme, netloc=netloc).geturl()


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


class CSRFExemptMixin(View):
    """Mixin to exempt views from CSRF protection."""

    @method_decorator(csrf_exempt)
    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponseBase:
        return super().dispatch(request, *args, **kwargs)


class TokenAuthMixin(View):
    """
    Mixin for views that require token-based authentication.

    Validates Bearer tokens from either the Authorization header or POST data
    and enforces scope-based authorization.
    """

    token: Token

    def authenticated(self, request: HttpRequest) -> bool:
        key = None
        # Check for Authorization header - Django prefixes HTTP headers with HTTP_
        auth_header = request.headers.get("authorization")
        # Also check without prefix for compatibility with some clients
        if not auth_header:
            auth_header = request.META.get("Authorization")
        # Finally check POST data as fallback
        auth_post = request.POST.get("Authorization")
        auth_token = auth_header or auth_post

        if auth_token is not None:
            key = auth_token.split()[-1]
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
            return HttpResponse("authentication error", status=401)

        if not _client_id_allowed(self.token.client_id):
            logger.warning(f"rejected disallowed client_id on resource server: {self.token.client_id!r}")
            return HttpResponse("invalid_client", status=403)

        return super().dispatch(request, *args, **kwargs)


class AuthView(CSRFExemptMixin, View):
    """
    IndieAuth authorization endpoint.

    Handles the authorization flow where users grant permission to client applications.
    GET: Shows authorization consent screen
    POST: Handles consent form submission or verifies auth codes
    """

    required_params: list[str] = ["client_id", "redirect_uri", "state", "me"]

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

        for name, val in zip(self.required_params, required):
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

        if _validate_redirect_uri(redirect_uri) is None:
            logger.info("rejected invalid redirect_uri on auth get")
            return HttpResponse("invalid redirect_uri", status=400)

        if _validate_client_id(client_id) is None:
            logger.info("rejected invalid client_id on auth get")
            return HttpResponse("invalid client_id", status=400)

        if not _client_id_allowed(client_id):
            logger.warning(f"rejected disallowed client_id on auth get: {client_id!r}")
            return HttpResponse("invalid_client", status=400)

        code_challenge = request.GET.get("code_challenge")
        code_challenge_method = request.GET.get("code_challenge_method")
        effective_method: str | None = None
        if code_challenge is not None or code_challenge_method is not None:
            pkce = _validate_pkce_request(code_challenge, code_challenge_method)
            if pkce is None:
                logger.info("rejected invalid PKCE parameters on auth get")
                return HttpResponse("invalid_request", status=400)
            code_challenge, effective_method = pkce

        # Parse scope into list for display
        scope_list = scope.split() if scope else []

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
        }
        return render(request, "indieweb/consent.html", context)

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

        if _validate_redirect_uri(redirect_uri) is None:
            logger.info("rejected invalid redirect_uri on auth consent")
            return HttpResponse("invalid redirect_uri", status=400)

        if _validate_client_id(client_id) is None:
            logger.info("rejected invalid client_id on auth consent")
            return HttpResponse("invalid client_id", status=400)

        if not _client_id_allowed(client_id):
            logger.warning(f"rejected disallowed client_id on auth consent: {client_id!r}")
            return HttpResponse("invalid_client", status=400)

        code_challenge = request.POST.get("code_challenge")
        code_challenge_method = request.POST.get("code_challenge_method")
        stored_challenge: str | None = None
        stored_method: str | None = None
        if code_challenge is not None or code_challenge_method is not None:
            pkce = _validate_pkce_request(code_challenge, code_challenge_method)
            if pkce is None:
                logger.info("rejected invalid PKCE parameters on auth consent")
                return HttpResponse("invalid_request", status=400)
            stored_challenge, stored_method = pkce

        if action == "deny":
            deny_params: dict[str, str] = {"error": "access_denied", "state": state}
            target = _append_redirect_params(redirect_uri, deny_params)
            logger.info("auth view consent denied")
            return redirect(target)

        if not request.user.is_authenticated:
            return HttpResponse("User not authenticated", status=401)

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
        url_params: dict[str, str] = {"code": auth.key, "state": state, "me": me}
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
        except Auth.DoesNotExist:
            return HttpResponse("Invalid authorization code", status=400)
        response_values = {"me": auth.me}
        return HttpResponse(urlencode(response_values), status=200)


class TokenView(CSRFExemptMixin, View):
    """
    IndieAuth token endpoint.

    Exchanges valid authorization codes for access tokens that can be used
    to authenticate API requests.
    """

    def send_token(self, me: str, client_id: str, scope: str | None, owner: AbstractBaseUser) -> HttpResponse:
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
            token.expires_at = expires_at
            token.save(update_fields=["expires_at", "modified"])
        remaining = max(0, math.floor((expires_at - timezone.now()).total_seconds()))
        response_values: dict[str, str | int] = {
            "access_token": token.key,
            "expires_in": remaining,
            "scope": token.scope or "",
            "me": token.me,
        }
        response = urlencode(response_values)
        status_code = 201 if created else 200
        return HttpResponse(response, status=status_code, content_type="application/x-www-form-urlencoded")

    def _check_pkce(self, auth: Auth, code_verifier: str | None) -> HttpResponse | None:
        """Verify PKCE for a token exchange. Deletes ``auth`` on failure to preserve one-time use."""
        if auth.code_challenge:
            if not code_verifier or not _verify_pkce(
                auth.code_challenge, auth.code_challenge_method or "plain", code_verifier
            ):
                logger.error("PKCE verification failed on token exchange")
                auth.delete()
                return HttpResponse("invalid_grant", status=400, content_type="application/x-www-form-urlencoded")
        elif code_verifier:
            logger.error("PKCE verifier submitted without stored challenge")
            auth.delete()
            return HttpResponse("invalid_grant", status=400, content_type="application/x-www-form-urlencoded")
        return None

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        # Get parameters from request
        code = request.POST.get("code")
        client_id = request.POST.get("client_id")
        redirect_uri = request.POST.get("redirect_uri")
        code_verifier = request.POST.get("code_verifier")

        # These are sometimes sent but not required by spec
        me = request.POST.get("me")
        requested_scope = request.POST.get("scope")

        # Validate required parameters
        if not code or not client_id:
            logger.error(f"Missing required parameters: code={code}, client_id={client_id}")
            return HttpResponse("invalid_request", status=400, content_type="application/x-www-form-urlencoded")

        client_id_error = _token_client_id_error(client_id)
        if client_id_error is not None:
            return client_id_error

        if redirect_uri and _validate_redirect_uri(redirect_uri) is None:
            logger.error("Rejected invalid redirect_uri on token exchange")
            return HttpResponse("invalid_grant", status=400, content_type="application/x-www-form-urlencoded")

        try:
            # Find auth by code and client_id
            auth = Auth.objects.get(key=code, client_id=client_id)

            # Verify redirect_uri if provided. Already-stored values are not re-validated;
            # they were validated when the auth code was issued (or pre-date validation).
            if redirect_uri and auth.redirect_uri:
                stored = _normalize_redirect_uri(auth.redirect_uri)
                submitted = _normalize_redirect_uri(redirect_uri)
                if stored != submitted:
                    logger.error("Redirect URI mismatch on token exchange")
                    return HttpResponse("invalid_grant", status=400, content_type="application/x-www-form-urlencoded")

            pkce_error = self._check_pkce(auth, code_verifier)
            if pkce_error is not None:
                return pkce_error

            stored_scope = _normalize_scope(auth.scope)
            normalized_request_scope = _normalize_scope(requested_scope)
            if requested_scope is not None and normalized_request_scope != stored_scope:
                logger.error(f"Scope mismatch on token exchange for client_id={client_id}")
                return HttpResponse("invalid_grant", status=400, content_type="application/x-www-form-urlencoded")

            # Use values from auth object if not provided in request
            me = me or auth.me
            scope = stored_scope

            logger.info(f"token view post: {client_id}, {me}, {code} {scope}")

            # Check if auth code is still valid
            timeout = getattr(settings, "INDIWEB_AUTH_CODE_TIMEOUT", 60)
            if (timezone.now() - auth.created).total_seconds() > timeout:
                logger.error(f"Auth code expired for client_id={client_id}")
                auth.delete()  # Clean up expired auth
                return HttpResponse("invalid_grant", status=400, content_type="application/x-www-form-urlencoded")

            # Delete auth code after use (one-time use)
            auth.delete()

            # Create and return token
            return self.send_token(me, client_id, scope, auth.owner)

        except Auth.DoesNotExist:
            logger.error(f"Auth not found for code={code}, client_id={client_id}")
            return HttpResponse("invalid_grant", status=400, content_type="application/x-www-form-urlencoded")


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


class MicropubView(CSRFExemptMixin, TokenAuthMixin, View):
    """
    Micropub endpoint for creating posts.

    Implements the Micropub protocol for creating content on the site.
    Requires valid access token with appropriate scope.
    GET: Returns configuration/verification info or handles queries
    POST: Creates new content
    """

    request: HttpRequest

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
        for prop in ["content", "name", "category", "location", "in-reply-to", "published", "photo"]:
            properties.update(self._parse_form_property(request, prop))

        # List properties (override if array format is used)
        for prop in ["content", "photo", "category"]:
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
        * ``GET ?q=config``, ``?q=syndicate-to``, ``GET`` (no ``q``) → ``None``
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

    def _handle_source_query(self, request: HttpRequest) -> HttpResponse:
        """Dispatch ``GET ?q=source`` using the handler's existing ``get_entry`` hook."""
        url = request.GET.get("url")
        if not url:
            return self._invalid_request()
        handler = get_micropub_handler()
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

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        """Handle POST requests to create or modify content."""
        self.request = request

        json_error = self._reject_invalid_json(request)
        if json_error is not None:
            return json_error

        if not self._scope_authorized(request):
            return HttpResponse("authorization error", status=403)

        action = self._post_action(request)
        if action == "update":
            return self._handle_update(request)
        if action == "delete":
            return self._handle_delete(request)
        if action == "undelete":
            return self._handle_undelete(request)

        # Parse properties from request
        try:
            properties = self.parse_request_data(request)
        except _MicropubMediaUploadError as exc:
            return _micropub_media_upload_error_response(exc)

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
            # Return configuration
            handler = get_micropub_handler()
            config = handler.get_config(self.token.owner)
            if not config.get("media-endpoint"):
                config["media-endpoint"] = request.build_absolute_uri(_reverse_request_namespace(request, "media"))
            return HttpResponse(json.dumps(config), content_type="application/json")
        elif q == "source":
            return self._handle_source_query(request)
        elif q == "syndicate-to":
            # Return empty syndication targets for now
            return HttpResponse(json.dumps({"syndicate-to": []}), content_type="application/json")
        else:
            # Default response with user's me URL
            params = {"me": self.token.me}
            return HttpResponse(urlencode(params), status=200)


class MicropubMediaView(CSRFExemptMixin, TokenAuthMixin, View):
    """
    Micropub media endpoint for direct file uploads.

    Accepts multipart/form-data uploads with a single ``file`` part, stores
    the file through Django's configured storage backend, and returns the
    stored media URL in the Location header.
    """

    def _scope_authorized(self) -> bool:
        """Require the conventional Micropub ``media`` scope for uploads."""
        return self.authorized(self.token.client_id, self.token.scope, MICROPUB_MEDIA_SCOPE)

    def _invalid_request(self) -> HttpResponse:
        return HttpResponse("invalid_request", status=400)

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if not self._scope_authorized():
            return HttpResponse("authorization error", status=403)

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


class WebmentionEndpoint(CSRFExemptMixin, View):
    """
    Webmention receiving endpoint.

    Implements the W3C Webmention protocol for receiving notifications
    when other sites mention content on this site.
    """

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        """Handle incoming webmentions."""
        source = request.POST.get("source")
        target = request.POST.get("target")

        # Basic validation
        if not source or not target:
            return HttpResponse(status=400)

        # Validate URLs
        validator = URLValidator()
        try:
            validator(source)
            validator(target)
        except ValidationError:
            return HttpResponse(status=400)

        # Check target is on our domain
        if not self.is_valid_target(target):
            return HttpResponse(status=400)

        # Process synchronously
        processor = WebmentionProcessor()
        try:
            webmention = processor.process_webmention(source, target)
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
            return parsed.netloc == current_site.domain
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


class WebmentionStatusView(View):
    """
    Webmention status endpoint.

    Returns the status of a specific webmention by ID.
    """

    def get(self, request: HttpRequest, pk: int, *args: object, **kwargs: object) -> HttpResponse:
        """Return status of a webmention."""
        webmention = get_object_or_404(Webmention, pk=pk)

        # Return JSON response with webmention status
        status_data = {
            "source": webmention.source_url,
            "target": webmention.target_url,
            "status": webmention.status,
        }

        if webmention.verified_at:
            status_data["verified_at"] = webmention.verified_at.isoformat()

        return HttpResponse(
            json.dumps(status_data),
            content_type="application/json",
        )
