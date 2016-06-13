#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
test_django-indieweb
------------

Tests for `django-indieweb` auth endpoint.
'''

from django.test import TestCase
from django.utils.http import urlencode
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse


class TestIndiewebAuthEndpoint(TestCase):

    def setUp(self):
        self.username = 'foo'
        self.email = 'foo@example.org'
        self.password = 'password'
        self.user = User.objects.create_user(
            self.username, self.email, self.password)
        url = reverse('auth')
        url_params = {
            'me': 'http://example.org',
            'client_id': 'https://webapp.example.org',
            'redirect_uri': 'https://webapp.example.org/auth/callback',
            'state': 1234567890,
            'scope': 'post',
        }
        self.endpoint_url = '{}?{}'.format(url, urlencode(url_params))

    def test_not_authenticated(self):
        '''
        Assure we are redirected to login if we try to get an auth-code
        from the indieweb auth endpoint and are not yet logged in.
        '''
        response = self.client.get(self.endpoint_url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue('login' in response.url)

    def test_authenticated(self):
        '''Assure we get back an auth code if we are authenticated.'''
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(self.endpoint_url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue('code' in response.url)
