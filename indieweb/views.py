from django.views.generic import View
from django.shortcuts import redirect
from django.utils.http import urlencode
from django.utils.crypto import get_random_string

from braces.views import LoginRequiredMixin

from .models import Auth


class AuthView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        client_id = request.GET['client_id']
        redirect_uri = request.GET['redirect_uri']
        state = request.GET['state']
        scope = request.GET['scope']
        me = request.GET['me']
        key = get_random_string(length=32)
        auth = Auth.objects.create(
            owner=request.user, client_id=client_id, redirect_uri=redirect_uri,
            state=state, scope=scope, me=me, key=key)
        url_params = {'code': key, 'state': state, 'me': me}
        target = '{}?{}'.format(redirect_uri, urlencode(url_params))
        return redirect(target)
