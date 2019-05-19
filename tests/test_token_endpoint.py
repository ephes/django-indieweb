#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
test_django-indieweb
------------

Tests for `django-indieweb` auth endpoint.
"""
from datetime import timedelta

from urllib.parse import unquote
from urllib.parse import parse_qs

from django.test import TestCase
from django.conf import settings
from django.contrib.auth.models import User
from django.urls import reverse

from indieweb import models


class TestIndiewebTokenEndpoint(TestCase):
    def setUp(self):
        self.username = "foo"
        self.email = "foo@example.org"
        self.password = "password"
        self.auth_code = "authkey"
        self.redirect_uri = "https://webapp.example.org/auth/callback"
        self.state = 1234567890
        self.me = "http://example.org"
        self.client_id = "https://webapp.example.org"
        self.scope = "post"
        self.user = User.objects.create_user(self.username, self.email, self.password)
        self.auth = models.Auth.objects.create(
            owner=self.user,
            key=self.auth_code,
            state=self.state,
            me=self.me,
            scope=self.scope,
            client_id=self.client_id,
        )
        self.endpoint_url = reverse("indieweb:token")

    def test_wrong_auth_code(self):
        """Assert we can't get a token with the wrong auth code."""
        payload = {
            "redirect_uri": self.redirect_uri,
            "code": "wrong_key",
            "state": self.state,
            "me": self.me,
            "scope": self.scope,
            "client_id": self.client_id,
        }
        response = self.client.post(self.endpoint_url, data=payload)
        self.assertEqual(response.status_code, 401)
        self.assertTrue("error" in response.content.decode("utf-8"))

    def test_correct_auth_code(self):
        """Assert we get a token when the auth code is correct."""
        payload = {
            "redirect_uri": self.redirect_uri,
            "code": self.auth_code,
            "state": self.state,
            "me": self.me,
            "scope": self.scope,
            "client_id": self.client_id,
        }
        response = self.client.post(self.endpoint_url, data=payload)
        self.assertEqual(response.status_code, 201)
        data = parse_qs(unquote(response.content.decode("utf-8")))
        self.assertTrue("access_token" in data)

    def test_auth_code_timeout(self):
        """Assert we can't get a token when the auth code is outdated."""
        payload = {
            "redirect_uri": self.redirect_uri,
            "code": self.auth_code,
            "state": self.state,
            "me": self.me,
            "scope": self.scope,
            "client_id": self.client_id,
        }
        timeout = getattr(settings, "INDIWEB_AUTH_CODE_TIMEOUT", 60)
        to_old_delta = timedelta(seconds=(timeout + 1))
        self.auth.created = self.auth.created - to_old_delta
        self.auth.save()
        response = self.client.post(self.endpoint_url, data=payload)
        self.assertEqual(response.status_code, 401)
        self.assertTrue("error" in response.content.decode("utf-8"))
