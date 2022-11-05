#!/usr/bin/env python

"""
test_django-indieweb
------------

Tests for `django-indieweb` auth endpoint.
"""
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytz
from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils.http import urlencode

from indieweb.models import Auth


class TestIndiewebAuthEndpoint(TestCase):
    def setUp(self):
        self.username = "foo"
        self.email = "foo@example.org"
        self.password = "password"
        self.user = User.objects.create_user(self.username, self.email, self.password)
        self.base_url = reverse("indieweb:auth")
        url_params = {
            "me": "http://example.org",
            "client_id": "https://webapp.example.org",
            "redirect_uri": "https://webapp.example.org/auth/callback",
            "state": 1234567890,
            "scope": "post",
        }
        self.endpoint_url = f"{self.base_url}?{urlencode(url_params)}"

    def test_not_authenticated(self):
        """
        Assure we are redirected to login if we try to get an auth-code
        from the indieweb auth endpoint and are not yet logged in.
        """
        response = self.client.get(self.endpoint_url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue("login" in response.url)

    def test_authenticated_without_params(self):
        """Assure get without proper parameters raises an error."""
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, 404)
        self.assertTrue("missing" in response.content.decode("utf-8"))

    def test_authenticated(self):
        """Assure we get back an auth code if we are authenticated."""
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(self.endpoint_url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue("code" in response.url)

    def test_get_or_create(self):
        """Test get or create logic for Auth object."""
        self.client.login(username=self.username, password=self.password)
        for i in range(2):
            response = self.client.get(self.endpoint_url)
            self.assertEqual(response.status_code, 302)
            self.assertTrue("code" in response.url)

    def test_auth_timeout_reset(self):
        """Test timeout is resetted on new authentication."""
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(self.endpoint_url)
        data = parse_qs(urlparse(response.url).query)
        auth = Auth.objects.get(owner=self.user, me=data["me"][0])
        timeout = getattr(settings, "INDIWEB_AUTH_CODE_TIMEOUT", 60)
        auth.created = auth.created - timedelta(seconds=timeout + 10)
        auth.save()
        response = self.client.get(self.endpoint_url)
        auth = Auth.objects.get(owner=self.user, me=data["me"][0])
        self.assertTrue((datetime.now(pytz.utc) - auth.created).seconds <= timeout)
