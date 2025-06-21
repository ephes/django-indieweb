from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseBase
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.utils.http import urlencode
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View

from .handlers import get_micropub_handler
from .models import Auth, Token

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
        auth_token = request.META.get("Authorization", request.POST.get("Authorization"))
        if auth_token is not None:
            key = auth_token.split()[-1]
        if key is not None:
            try:
                self.token = Token.objects.select_related("owner").get(key=key)
                if self.token.owner.is_active:
                    return True
                else:
                    return False
            except Token.DoesNotExist:
                return False
        else:
            return False

    def authorized(self, client_id: str, scope: str | None) -> bool:
        # TODO implement access control based on client_id
        return scope is not None and "post" in scope

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
    GET: Shows authorization prompt (or redirects with auth code if pre-authorized)
    POST: Verifies auth codes
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

        # FIXME scope is optional
        scope = request.GET.get("scope")
        # All required parameters are verified to be not None above
        assert client_id is not None
        assert redirect_uri is not None
        assert state is not None
        assert me is not None

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
        url_params = {"code": auth.key, "state": state, "me": me}
        target = f"{redirect_uri}?{urlencode(url_params)}"
        logger.info(f"auth view get complete: {target}")
        return redirect(target)

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        logger.info(f"auth view post: {request}, {args}, {kwargs}")
        auth_code = request.POST["code"]
        client_id = request.POST["client_id"]
        logger.info(f"auth view post: {client_id}, {auth_code}")
        auth = Auth.objects.get(key=auth_code, client_id=client_id)
        # if auth.key == key:
        response_values = {"me": auth.me}
        response = urlencode(response_values)
        status_code = 200
        return HttpResponse(response, status=status_code)


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
        return HttpResponse(response, status=status_code)

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        me = request.POST["me"]
        key = request.POST["code"]
        scope = request.POST["scope"]
        client_id = request.POST["client_id"]
        try:
            auth = Auth.objects.get(me=me, client_id=client_id, scope=scope)
            logger.info(f"token view post: {client_id}, {me}, {key} {scope}")
        except Auth.DoesNotExist:
            logger.info(f"auth does not exist: {client_id}, {me}, {scope}")
            return HttpResponse("authentication error", status=401)
        if auth.key == key:
            # auth code is correct
            timeout = getattr(settings, "INDIWEB_AUTH_CODE_TIMEOUT", 60)
            if (datetime.now(timezone.utc) - auth.created).seconds <= timeout:
                # auth code is still valid
                return self.send_token(me, client_id, scope, auth.owner)
        return HttpResponse("authentication error", status=401)


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
