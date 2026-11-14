"""Finite settings, authoritative browser inventory and bounded profile fallback."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse

from indieweb.models import Profile, Token
from indieweb.processors import _canonical_profile_url, _lookup_profile_by_canonical_url
from indieweb.rate_limit import get_rate_limit_config


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["limit", "window"])
@pytest.mark.parametrize(
    "value", [float("inf"), float("-inf"), float("nan"), 1.9, True, 2**100, "999999999999999999999"]
)
def test_invalid_rate_config_is_ignored_by_real_endpoint(client, settings, field, value):
    cache.clear()
    config = {"limit": 1, "window": 60, field: value}
    settings.INDIEWEB_RATE_LIMITS = {"token": config}
    url = reverse("indieweb:token")
    for _ in range(2):
        response = client.post(url, {"code": "synthetic-invalid", "client_id": "https://client.example/"})
        assert response.status_code == 400
        assert "Retry-After" not in response
    assert get_rate_limit_config("token") is None


@pytest.mark.parametrize("value", [1, 1.0, "1", " 1 ", 2147483647])
def test_supported_exact_rate_config(settings, value):
    settings.INDIEWEB_RATE_LIMITS = {"token": {"limit": value, "window": value}}
    config = get_rate_limit_config("token")
    assert config.limit == config.window == int(value)


class TokenReplicaRouter:
    def db_for_read(self, model, **hints):
        return "default" if model is Token else None

    def db_for_write(self, model, **hints):
        return "other" if model is Token else None


@pytest.mark.django_db(databases=["default", "other"])
def test_browser_inventory_and_revoke_share_authority(client, settings):
    user = get_user_model().objects.create_user(username="synthetic-owner")
    get_user_model().objects.using("other").create(pk=user.pk, username="synthetic-authority-owner")
    foreign = get_user_model().objects.using("other").create(username="synthetic-foreign")
    replica = Token.objects.using("default").create(
        pk=1, owner_id=user.pk, client_id="https://replica.example/", me="https://owner.example/"
    )
    grants = [
        Token.objects.using("other").create(
            pk=index + 1, owner_id=user.pk, client_id=f"https://authority.example/{index}", me="https://owner.example/"
        )
        for index in range(53)
    ]
    unowned = Token.objects.using("other").create(
        owner_id=foreign.pk, client_id="https://foreign.example/", me="https://foreign.example/"
    )
    client.force_login(user)
    settings.DATABASE_ROUTERS = [TokenReplicaRouter()]
    url = reverse("indieweb:tokens")
    response = client.get(url)
    assert response.status_code == 200
    assert response.context["paginator"].count == 53
    assert len(response.context["tokens"]) == 50
    assert "replica.example" not in response.content.decode()
    assert all(row._state.db == "other" for row in response.context["tokens"])
    page2 = client.get(url, {"page": 2})
    assert len(page2.context["tokens"]) == 3
    assert client.post(reverse("indieweb:token-revoke", args=[grants[0].pk])).status_code == 302
    assert not Token.objects.using("other").filter(pk=grants[0].pk).exists()
    assert Token.objects.using("default").get(pk=replica.pk).client_id == "https://replica.example/"
    assert client.post(reverse("indieweb:token-revoke", args=[unowned.pk])).status_code == 404
    assert Token.objects.using("other").filter(pk=unowned.pk).exists()


@pytest.mark.django_db
def test_canonical_lookup_stops_at_second_match(caplog):
    for index in range(30):
        user = get_user_model().objects.create_user(username=f"synthetic-{index}")
        Profile.objects.create(user=user, url="https://EXAMPLE.com:443/author/")
    url = "https://example.com/author"
    with patch("indieweb.processors._canonical_profile_url", wraps=_canonical_profile_url) as canonical:
        assert _lookup_profile_by_canonical_url(url, url) is None
    assert canonical.call_count == 2
    assert "30" not in caplog.text
    assert "synthetic-" not in caplog.text
