"""Exchange must use current account eligibility rather than consent-time state."""

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from indieweb import views
from indieweb.models import Auth, Token


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ["token", "auth"])
@pytest.mark.parametrize("change", ["disable", "delete"])
def test_owner_changed_after_code_lookup(monkeypatch, endpoint, change):
    owner = get_user_model().objects.create_user(username="synthetic-owner")
    identity = dict(owner=owner, client_id="https://client.example/", me="https://owner.example/", scope="create")
    auth = Auth.objects.create(**identity, state="state")
    Token.objects.create(**identity)
    lookup = Auth.get_for_raw_key
    prior = list(Token.objects.values())

    def changed_owner(*args, **kwargs):
        matched = lookup(*args, **kwargs)
        assert matched.owner.is_active  # Deliberately populate the related-object cache.
        if change == "disable":
            get_user_model().objects.filter(pk=owner.pk).update(is_active=False)
        else:
            get_user_model().objects.filter(pk=owner.pk).delete()
        return matched

    monkeypatch.setattr(Auth, "get_for_raw_key", changed_owner)
    request = RequestFactory().post(f"/{endpoint}/", {"code": auth.raw_key, "client_id": auth.client_id})
    response = (views.TokenView if endpoint == "token" else views.AuthView).as_view()(request)
    assert response.status_code == 400
    assert list(Token.objects.values()) == (prior if change == "disable" else [])
    assert not Auth.objects.exists()
