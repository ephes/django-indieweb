#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
test_django-indieweb
------------

Tests for `django-indieweb` micropub endpoint.
'''
from datetime import timedelta

from django.test import TestCase
from django.conf import settings
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse

from indieweb import models


class TestIndiewebMicropubEndpoint(TestCase):

    def setUp(self):
        self.username = 'foo'
        self.email = 'foo@example.org'
        self.password = 'password'
        self.auth_code = 'authkey'
        self.redirect_uri = 'https://webapp.example.org/auth/callback'
        self.state = 1234567890
        self.me = 'http://example.org'
        self.client_id = 'https://webapp.example.org'
        self.scope = 'post'
        self.user = User.objects.create_user(
            self.username, self.email, self.password)
        self.auth = models.Auth.objects.create(
            owner=self.user, key=self.auth_code, state=self.state, me=self.me,
            scope=self.scope)
        self.token = models.Token.objects.create(
            me=self.me, client_id=self.client_id, scope=self.scope,
            owner=self.user)
        self.endpoint_url = reverse('micropub')
        self.content = 'foobar'

    def test_no_token(self):
        '''Assert we can't post to the endpoint without token.'''
        payload = {'content': self.content, 'h': 'entry'}
        response = self.client.post(
            self.endpoint_url, data=payload)
        self.assertEqual(response.status_code, 401)
        self.assertTrue('error' in response.content.decode('utf-8'))
