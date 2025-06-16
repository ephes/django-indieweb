#!/usr/bin/env python

"""
test_django-indieweb
------------

Tests for `django-indieweb` models module.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from indieweb.models import Token

User = get_user_model()


class TestIndieweb(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")

    def test_token_str_method(self):
        token = Token.objects.create(
            owner=self.user, client_id="https://example.com", me="https://user.example.com", scope="create update"
        )
        expected = "https://example.com https://user.example.com create update testuser"
        self.assertEqual(str(token), expected)

    def tearDown(self):
        pass
