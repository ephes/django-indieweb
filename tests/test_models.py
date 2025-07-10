#!/usr/bin/env python

"""
test_django-indieweb
------------

Tests for `django-indieweb` models module.
"""

import pytest
from django.contrib.auth import get_user_model

from indieweb.models import Token

User = get_user_model()


@pytest.mark.django_db
def test_token_str_method():
    user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
    token = Token.objects.create(
        owner=user, client_id="https://example.com", me="https://user.example.com", scope="create update"
    )
    expected = "https://example.com https://user.example.com create update testuser"
    assert str(token) == expected
