import logging

from datetime import datetime

from django.conf import settings
from django.http import HttpResponse
from django.views.generic import View
from django.shortcuts import redirect
from django.utils.http import urlencode
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from braces.views._access import AccessMixin

import pytz

from .models import Auth
from .models import Token

logger = logging.getLogger(__name__)


class CSRFExemptMixin:
    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)


class TokenAuthMixin:
    def authenticated(self, request):
        key = None
        auth_token = request.META.get(
            "Authorization", request.POST.get("Authorization")
        )
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

    def authorized(self, client_id, scope):
        # TODO implement access control based on client_id
        return "post" in scope

    def dispatch(self, request, *args, **kwargs):
        if not self.authenticated(request):
            return HttpResponse("authentication error", status=401)

        if not self.authorized(self.token.client_id, self.token.scope):
            return HttpResponse("authorization error", status=403)

        return super().dispatch(request, *args, **kwargs)


class AuthView(CSRFExemptMixin, AccessMixin, View):
    required_params = ["client_id", "redirect_uri", "state", "me"]

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission(request)
        client_id = request.GET.get("client_id")
        redirect_uri = request.GET.get("redirect_uri")
        state = request.GET.get("state")
        me = request.GET.get("me")
        logger.info(f"auth view get: {client_id}, {redirect_uri}, {state}, {me}")
        required = [client_id, redirect_uri, state, me]

        for name, val in zip(self.required_params, required):
            if val is None:
                err_msg = "missing parameter {}".format(name)
                logger.info(f"missing parameter: {name}")
                return HttpResponse(err_msg, status=404)

        # FIXME scope is optional
        scope = request.GET.get("scope")
        try:
            auth = Auth.objects.get(
                owner=request.user, client_id=client_id, scope=scope, me=me
            )
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
        target = "{}?{}".format(redirect_uri, urlencode(url_params))
        logger.info(f"auth view get complete: {target}")
        return redirect(target)

    def post(self, request, *args, **kwargs):
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
    def send_token(self, me, client_id, scope, owner):
        token, created = Token.objects.get_or_create(
            me=me, client_id=client_id, scope=scope, owner=owner
        )
        response_values = {
            "access_token": token.key,
            "expires_in": 10,
            "scope": token.scope,
            "me": token.me,
        }
        response = urlencode(response_values)
        status_code = 201 if created else 200
        return HttpResponse(response, status=status_code)

    def post(self, request, *args, **kwargs):
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
            if (datetime.now(pytz.utc) - auth.created).seconds <= timeout:
                # auth code is still valid
                return self.send_token(me, client_id, scope, auth.owner)
        return HttpResponse("authentication error", status=401)


class MicropubView(CSRFExemptMixin, TokenAuthMixin, View):
    @property
    def content(self):
        return self.request.POST.get("content")

    @property
    def categories(self):
        category_str = self.request.POST.get("category", "")
        return [c for c in category_str.split(",") if len(c) > 0]

    @property
    def location(self):
        location = {}
        location_str = self.request.POST.get("location", "")
        if len(location_str) > 0:
            if ";" in location_str:
                location["uncertainty"] = int(
                    location_str.split(";")[-1].split("=")[-1]
                )
            if location_str.startswith("geo:"):
                lat, lng = location_str.split(";")[0].split(":")[-1].split(",")
                location["latitude"] = float(lat)
                location["longitude"] = float(lng)
        return location

    @property
    def in_reply_to(self):
        url = self.request.POST.get("in-reply-to", "")
        return url

    def post(self, request, *args, **kwargs):
        # print('request: {}'.format(request))
        # print('post: {}'.format(request.POST))
        # print('files: {}'.format(request.FILES))
        # print('meta: {}'.format(request.META))
        self.request = request
        # location = self.get_location()
        # print(self.categories)
        return HttpResponse("created", status=201)

    def get(self, request, *args, **kwargs):
        params = {"me": self.token.me}
        return HttpResponse(urlencode(params), status=200)
