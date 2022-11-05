#!/usr/bin/env python

"""
test_django-indieweb
------------

Tests for `django-indieweb` micropub endpoint.
"""
from urllib.parse import unquote

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from indieweb import models
from indieweb.views import MicropubView


class DummyRequest:
    GET = {}
    POST = {}
    META = {}


class TestIndiewebMicropubEndpoint(TestCase):
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
        )
        self.token = models.Token.objects.create(
            me=self.me, client_id=self.client_id, scope=self.scope, owner=self.user
        )
        self.endpoint_url = reverse("indieweb:micropub")
        self.content = "foobar"

    def test_no_token(self):
        """Assert we can't post to the endpoint without token."""
        payload = {"content": self.content, "h": "entry"}
        response = self.client.post(self.endpoint_url, data=payload)
        self.assertEqual(response.status_code, 401)
        self.assertTrue("error" in response.content.decode("utf-8"))

    def test_wrong_token(self):
        """Assert we can't post to the endpoint without the right token."""
        payload = {"content": self.content, "h": "entry"}
        auth_header = "Bearer {}".format("wrongtoken")
        response = self.client.post(self.endpoint_url, data=payload, Authorization=auth_header)
        self.assertEqual(response.status_code, 401)
        self.assertTrue("error" in response.content.decode("utf-8"))

    def test_correct_token_header(self):
        """
        Assert we can post to the endpoint with the right token
        submitted in the requests header.
        """
        payload = {"content": self.content, "h": "entry"}
        auth_header = f"Bearer {self.token.key}"
        response = self.client.post(self.endpoint_url, data=payload, Authorization=auth_header)
        self.assertEqual(response.status_code, 201)
        self.assertTrue("created" in response.content.decode("utf-8"))

    def test_correct_token_body(self):
        """
        Assert we can post to the endpoint with the right token
        submitted in the requests body.
        """
        auth_body = f"Bearer {self.token.key}"
        payload = {"content": self.content, "h": "entry", "Authorization": auth_body}
        response = self.client.post(self.endpoint_url, data=payload)
        self.assertEqual(response.status_code, 201)
        self.assertTrue("created" in response.content.decode("utf-8"))

    def test_not_authorized(self):
        """Assure we cant post if we don't have the right scope."""
        auth_body = f"Bearer {self.token.key}"
        old_scope = self.token.scope
        self.token.scope = "foo"
        self.token.save()
        payload = {"content": self.content, "h": "entry", "Authorization": auth_body}
        response = self.client.post(self.endpoint_url, data=payload)
        self.assertEqual(response.status_code, 403)
        self.assertTrue("error" in response.content.decode("utf-8"))
        self.token.scope = old_scope
        self.token.save()

    def test_content(self):
        """Test post with content."""
        mv = MicropubView()
        mv.request = DummyRequest()
        self.assertEqual(mv.content, None)
        mv.request.POST["content"] = None
        self.assertEqual(mv.content, None)
        content = "foobar"
        mv.request.POST["content"] = "foobar"
        self.assertEqual(mv.content, content)

    def test_categories(self):
        """Test post with categories."""
        mv = MicropubView()
        mv.request = DummyRequest()
        self.assertEqual(mv.categories, [])

        mv.request.POST["category"] = "foo,bar,baz"
        self.assertEqual(len(mv.categories), 3)

        mv.request.POST["category"] = "foo"
        self.assertEqual(mv.categories, ["foo"])

        mv.request.POST["category"] = ""
        self.assertEqual(mv.categories, [])

    def test_location(self):
        """Test post with location."""
        mv = MicropubView()
        mv.request = DummyRequest()
        self.assertEqual(mv.location, {})

        mv.request.POST["location"] = "foo,bar,baz"
        self.assertEqual(mv.location, {})

        lat, lng = 37.786971, -122.399677
        mv.request.POST["location"] = f"geo:{lat},{lng}"
        self.assertEqual(mv.location, {"latitude": lat, "longitude": lng})

        uncertainty = 35
        result = {"latitude": lat, "longitude": lng, "uncertainty": uncertainty}
        mv.request.POST["location"] = f"geo:{lat},{lng};crs=Moon-2011;u={uncertainty}"
        self.assertEqual(mv.location, result)

    def test_token_verification_on_get(self):
        """
        Test authentication tokens via get request to micropub endpoint.
        """
        auth_header = f"Bearer {self.token.key}"
        response = self.client.get(self.endpoint_url, Authorization=auth_header)
        response_text = unquote(response.content.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.me in response_text)

    def test_token_verification_on_get_wrong(self):
        """
        Test wrong authentication tokens via get request to micropub endpoint.
        """
        auth_header = "Bearer {}".format("wrong_token")
        response = self.client.get(self.endpoint_url, Authorization=auth_header)
        self.assertEqual(response.status_code, 401)
