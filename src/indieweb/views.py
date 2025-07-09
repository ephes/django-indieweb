from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import HttpRequest, HttpResponse, HttpResponseBase
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.utils.http import urlencode
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View

from .handlers import get_micropub_handler
from .models import Auth, Token
from .processors import WebmentionProcessor

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser

logger = logging.getLogger(__name__)


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
                if self.token.owner.is_active:
                    return True
                else:
                    logger.warning(f"Token owner is not active: {self.token.owner}")
                    return False
            except Token.DoesNotExist:
                logger.warning(f"Token not found: {key[:8]}...")
                return False
        else:
            logger.warning("No authorization token provided in request")
            return False

    def authorized(self, client_id: str, scope: str | None) -> bool:
        # TODO implement access control based on client_id
        # Check for either "create" (standard Micropub) or "post" (legacy)
        return scope is not None and ("create" in scope or "post" in scope)

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponseBase:
        if not self.authenticated(request):
            return HttpResponse("authentication error", status=401)

        if not self.authorized(self.token.client_id, self.token.scope):
            return HttpResponse("authorization error", status=403)

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

        # scope is optional
        scope = request.GET.get("scope")
        # All required parameters are verified to be not None above
        assert client_id is not None
        assert redirect_uri is not None
        assert state is not None
        assert me is not None

        # Parse scope into list for display
        scope_list = []
        if scope:
            scope_list = scope.split()

        # Render consent screen
        context = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "me": me,
            "scope": scope,
            "scope_list": scope_list,
        }
        return render(request, "indieweb/consent.html", context)

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponseBase:
        logger.info(f"auth view post: {request}, {args}, {kwargs}")

        # Check if this is a consent form submission
        action = request.POST.get("action")
        if action in ["approve", "deny"]:
            # Handle consent form submission
            client_id = request.POST.get("client_id")
            redirect_uri = request.POST.get("redirect_uri")
            state = request.POST.get("state")
            me = request.POST.get("me")
            scope = request.POST.get("scope")

            # Validate required parameters
            if not all([client_id, redirect_uri, state, me]):
                return HttpResponse("Missing required parameters", status=400)

            # These are verified to be not None above
            assert client_id is not None
            assert redirect_uri is not None
            assert state is not None
            assert me is not None

            if action == "approve":
                # User approved - create auth code and redirect
                if not request.user.is_authenticated:
                    return HttpResponse("User not authenticated", status=401)

                try:
                    auth = Auth.objects.get(owner=request.user, client_id=client_id, scope=scope, me=me)
                    auth.delete()
                except Auth.DoesNotExist:
                    pass

                auth = Auth.objects.create(
                    owner=request.user,
                    client_id=client_id,
                    redirect_uri=redirect_uri,
                    state=state,
                    scope=scope,
                    me=me,
                )
                url_params: dict[str, str] = {"code": auth.key, "state": state, "me": me}
                target = f"{redirect_uri}?{urlencode(url_params)}"
                logger.info(f"auth view consent approved: {target}")
                return redirect(target)
            else:
                # User denied - redirect with error
                deny_params: dict[str, str] = {"error": "access_denied", "state": state}
                target = f"{redirect_uri}?{urlencode(deny_params)}"
                logger.info(f"auth view consent denied: {target}")
                return redirect(target)
        else:
            # Original auth code verification flow
            auth_code = request.POST.get("code")
            client_id = request.POST.get("client_id")

            if not auth_code or not client_id:
                return HttpResponse("Missing code or client_id", status=400)

            logger.info(f"auth view post verification: {client_id}, {auth_code}")
            try:
                auth = Auth.objects.get(key=auth_code, client_id=client_id)
                response_values = {"me": auth.me}
                response = urlencode(response_values)
                return HttpResponse(response, status=200)
            except Auth.DoesNotExist:
                return HttpResponse("Invalid authorization code", status=400)


class TokenView(CSRFExemptMixin, View):
    """
    IndieAuth token endpoint.

    Exchanges valid authorization codes for access tokens that can be used
    to authenticate API requests.
    """

    def send_token(self, me: str, client_id: str, scope: str | None, owner: AbstractBaseUser) -> HttpResponse:
        token, created = Token.objects.get_or_create(me=me, client_id=client_id, scope=scope, owner=owner)
        response_values: dict[str, str | int] = {
            "access_token": token.key,
            "expires_in": 10,
            "scope": token.scope or "",
            "me": token.me,
        }
        response = urlencode(response_values)
        status_code = 201 if created else 200
        return HttpResponse(response, status=status_code, content_type="application/x-www-form-urlencoded")

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        # Get parameters from request
        code = request.POST.get("code")
        client_id = request.POST.get("client_id")
        redirect_uri = request.POST.get("redirect_uri")

        # These are sometimes sent but not required by spec
        me = request.POST.get("me")
        scope = request.POST.get("scope")

        # Validate required parameters
        if not code or not client_id:
            logger.error(f"Missing required parameters: code={code}, client_id={client_id}")
            return HttpResponse("invalid_request", status=400, content_type="application/x-www-form-urlencoded")

        try:
            # Find auth by code and client_id
            auth = Auth.objects.get(key=code, client_id=client_id)

            # Verify redirect_uri if provided
            if redirect_uri and auth.redirect_uri and auth.redirect_uri != redirect_uri:
                logger.error(f"Redirect URI mismatch: expected {auth.redirect_uri}, got {redirect_uri}")
                return HttpResponse("invalid_grant", status=400, content_type="application/x-www-form-urlencoded")

            # Use values from auth object if not provided in request
            me = me or auth.me
            scope = scope or auth.scope

            logger.info(f"token view post: {client_id}, {me}, {code} {scope}")

            # Check if auth code is still valid
            timeout = getattr(settings, "INDIWEB_AUTH_CODE_TIMEOUT", 60)
            if (datetime.now(timezone.utc) - auth.created).seconds > timeout:
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

        # Handle file uploads
        if "photo" in request.FILES:
            # TODO: Handle file uploads
            pass

        return properties

    def parse_request_data(self, request: HttpRequest) -> dict[str, Any]:
        """Parse Micropub data from either form-encoded or JSON request."""
        if request.content_type == "application/json":
            return self._parse_json_request(request)
        else:
            return self._parse_form_request(request)

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        """Handle POST requests to create or modify content."""
        self.request = request

        # Check for action parameter (for updates/deletes)
        action = request.POST.get("action") or (
            json.loads(request.body).get("action") if request.content_type == "application/json" else None
        )

        if action in ["update", "delete", "undelete"]:
            # TODO: Implement update/delete/undelete actions
            return HttpResponse("Not implemented", status=501)

        # Parse properties from request
        properties = self.parse_request_data(request)

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
        q = request.GET.get("q")

        if q == "config":
            # Return configuration
            handler = get_micropub_handler()
            config = handler.get_config(self.token.owner)
            return HttpResponse(json.dumps(config), content_type="application/json")
        elif q == "source":
            # TODO: Implement source query
            return HttpResponse("Not implemented", status=501)
        elif q == "syndicate-to":
            # Return empty syndication targets for now
            return HttpResponse(json.dumps({"syndicate-to": []}), content_type="application/json")
        else:
            # Default response with user's me URL
            params = {"me": self.token.me}
            return HttpResponse(urlencode(params), status=200)


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
            processor.process_webmention(source, target)
            return HttpResponse(status=201)  # Created
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
