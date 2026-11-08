"""Accept quality admission through real profile and token code redemption."""

from urllib.parse import parse_qs

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from indieweb.models import Auth, Token

FORM = "application/x-www-form-urlencoded"
JSON = "application/json"

ACCEPT_CASES = [
    *[
        (f"{JSON};q={q}, {FORM};q=0.5", FORM)
        for q in ["NaN", "Infinity", "-Infinity", "2", "1.001", "-0.1", "1e0", "+1", ".5", "0.1234", '"1"', ""]
    ],
    (f"{JSON};Q=0, {FORM};q=0.5", FORM),
    (f"{JSON};Q=0.4, {FORM};q=0.5", FORM),
    (f"{JSON};Q=0.7, {FORM};q=0.5", JSON),
    (f"{JSON};q=0.5, {FORM};q=0.5", JSON),
    (f"{FORM};q=0.5, {JSON};q=0.5", FORM),
    (f"{JSON};q=0.000, */*;q=1", FORM),
    (f"{JSON};q=1.000, {FORM};q=0.999", JSON),
    (f"{JSON};q=0., {FORM};q=1.", FORM),
    ("*/*;q=1", FORM),
    (f"{JSON};q=0.1, */*;q=1", JSON),
    (f"{FORM};q=Infinity, {JSON};q=0.1", JSON),
]


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ["auth", "token"])
@pytest.mark.parametrize("accept,expected_type", ACCEPT_CASES)
def test_code_redemption_accept_quality_domain(client, endpoint, accept, expected_type):
    user = get_user_model().objects.create_user(username="synthetic")
    auth = Auth.objects.create(
        owner=user,
        client_id="https://client.example/",
        redirect_uri="https://client.example/cb",
        state="synthetic",
        me="https://profile.example/",
        scope="create",
    )
    response = client.post(
        reverse(f"indieweb:{endpoint}"),
        {"code": auth.key, "client_id": auth.client_id, "redirect_uri": auth.redirect_uri},
        HTTP_ACCEPT=accept,
    )
    assert response.status_code == (201 if endpoint == "token" else 200)
    assert response["Content-Type"] == expected_type
    data = (
        response.json()
        if expected_type == JSON
        else {key: values[0] for key, values in parse_qs(response.content.decode()).items()}
    )
    assert data["me"] == auth.me
    assert not Auth.objects.filter(pk=auth.pk).exists()
    if endpoint == "token":
        assert "no-store" in response["Cache-Control"]
        assert response["Pragma"] == "no-cache"
        assert data["token_type"] == "Bearer"
        assert data["scope"] == "create"
        assert Token.get_for_raw_key(data["access_token"]).owner_id == user.pk
    else:
        assert data == {"me": auth.me}
        assert not Token.objects.exists()
