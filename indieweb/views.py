from datetime import datetime

from django.conf import settings
from django.http import HttpResponse
from django.views.generic import View
from django.shortcuts import redirect
from django.utils.http import urlencode

from braces.views import LoginRequiredMixin

import pytz

from .models import Auth
from .models import Token


class AuthView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        client_id = request.GET['client_id']
        redirect_uri = request.GET['redirect_uri']
        state = request.GET['state']
        # FIXME scope is optional
        scope = request.GET['scope']
        me = request.GET['me']
        auth = Auth.objects.create(
            owner=request.user, client_id=client_id, redirect_uri=redirect_uri,
            state=state, scope=scope, me=me)
        url_params = {'code': auth.key, 'state': state, 'me': me}
        target = '{}?{}'.format(redirect_uri, urlencode(url_params))
        return redirect(target)


class TokenView(View):
    def send_token(self, me, client_id, scope, owner):
        token, created = Token.objects.get_or_create(
            me=me, client_id=client_id, scope=scope, owner=owner)
        response_values = {
            'access_token': token.key,
            'expires_in': 10,
            'scope': token.scope,
            'me': token.me,
        }
        response = urlencode(response_values)
        status_code = 201 if created else 200
        return HttpResponse(response, status=status_code)

    def post(self, request, *args, **kwargs):
        me = request.POST['me']
        key = request.POST['code']
        scope = request.POST['scope']
        client_id = request.POST['client_id']
        auth = Auth.objects.get(me=me)
        if auth.key == key:
            # auth code is correct
            timeout = getattr(settings, 'INDIWEB_AUTH_CODE_TIMEOUT', 60)
            if (datetime.now(pytz.utc) - auth.created).seconds <= timeout:
                # auth code is still valid
                return self.send_token(me, client_id, scope, auth.owner)
        return HttpResponse('authentication error', status=401)
