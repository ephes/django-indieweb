"""Authorization redirect confinement: complete path identity and reserved response keys."""

from urllib.parse import parse_qs, parse_qsl, urlsplit

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from indieweb.models import Auth

CLIENT_ID = "https://client.example/"
EXACT_CALLBACK = "https://callback.example/oauth/cb"
PREFIX_CALLBACK = "https://callback.example/oauth/"


@pytest.fixture
def user(db):
    return User.objects.create_user(username="confinement", email="confinement@example.com", password="password")


def _auth_params(redirect_uri: str) -> dict[str, str]:
    return {
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "state": "state-123",
        "me": "https://me.example/",
        "response_type": "code",
    }


def _consent(client, redirect_uri: str, action: str = "approve"):
    data = _auth_params(redirect_uri)
    data.pop("response_type")
    data["action"] = action
    data["scope"] = "create"
    return client.post(reverse("indieweb:auth"), data=data)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "candidate",
    [
        "https://callback.example/oauth/cb;other",
        "https://callback.example/oauth/cb;",
        "https://callback.example/oauth/cb;jsessionid=abc",
    ],
)
def test_exact_allowlist_entry_rejects_semicolon_path_variants(client, settings, user, candidate):
    """An exact entry is the complete path: a ``;`` suffix names a different resource."""
    settings.INDIEWEB_REDIRECT_URI_ALLOWLIST = {CLIENT_ID: [EXACT_CALLBACK]}
    client.force_login(user)

    assert client.get(reverse("indieweb:auth"), _auth_params(candidate)).status_code == 400
    consent = _consent(client, candidate)
    assert consent.status_code == 400
    assert "Location" not in consent
    assert not Auth.objects.filter(client_id=CLIENT_ID).exists()


@pytest.mark.django_db
def test_exact_allowlist_entry_with_semicolon_matches_only_itself(client, settings, user):
    entry = "https://callback.example/oauth/cb;v=1"
    settings.INDIEWEB_REDIRECT_URI_ALLOWLIST = {CLIENT_ID: [entry]}
    client.force_login(user)

    assert client.get(reverse("indieweb:auth"), _auth_params(entry)).status_code == 200
    assert client.get(reverse("indieweb:auth"), _auth_params(EXACT_CALLBACK)).status_code == 400
    assert client.get(reverse("indieweb:auth"), _auth_params(entry + "x")).status_code == 400

    approved = _consent(client, entry)
    assert approved.status_code == 302
    location = urlsplit(approved["Location"])
    assert location.path == "/oauth/cb;v=1"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("entry", "candidate"),
    [
        ("https://callback.example/oauth/cb;", "https://callback.example/oauth/cb;"),
        (PREFIX_CALLBACK, "https://callback.example/oauth/cb;"),
    ],
)
@pytest.mark.parametrize("action", ["approve", "deny"])
def test_redirect_delivers_the_validated_path_byte_for_byte(client, settings, user, entry, candidate, action):
    """An empty trailing ``;`` is part of the validated path and must reach the client unchanged."""
    settings.INDIEWEB_REDIRECT_URI_ALLOWLIST = {CLIENT_ID: [entry]}
    client.force_login(user)

    response = _consent(client, candidate, action=action)

    assert response.status_code == 302
    assert urlsplit(response["Location"]).path == "/oauth/cb;"
    assert response["Location"].startswith(candidate + "?")


@pytest.mark.django_db
def test_exact_allowlist_entry_still_accepts_identical_callback(client, settings, user):
    settings.INDIEWEB_REDIRECT_URI_ALLOWLIST = {CLIENT_ID: [EXACT_CALLBACK]}
    client.force_login(user)

    assert client.get(reverse("indieweb:auth"), _auth_params(EXACT_CALLBACK)).status_code == 200
    approved = _consent(client, EXACT_CALLBACK)
    assert approved.status_code == 302
    assert urlsplit(approved["Location"]).path == "/oauth/cb"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "candidate",
    [
        "https://callback.example/oauth/..;/admin",
        "https://callback.example/oauth/.;/admin",
        "https://callback.example/oauth/%2e%2e;x/admin",
        "https://callback.example/oauth/cb/..;",
    ],
)
def test_prefix_allowlist_entry_rejects_dot_segments_with_parameters(client, settings, user, candidate):
    """``..;`` is treated as ``..`` by servers that strip path parameters before routing."""
    settings.INDIEWEB_REDIRECT_URI_ALLOWLIST = {CLIENT_ID: [PREFIX_CALLBACK]}
    client.force_login(user)

    assert client.get(reverse("indieweb:auth"), _auth_params(candidate)).status_code == 400
    assert _consent(client, candidate).status_code == 400
    assert not Auth.objects.filter(client_id=CLIENT_ID).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "candidate",
    [
        "https://callback.example/oauth/cb;session=1",
        "https://callback.example/oauth/a;b/cb",
    ],
)
def test_prefix_allowlist_entry_accepts_parameters_inside_the_prefix(client, settings, user, candidate):
    settings.INDIEWEB_REDIRECT_URI_ALLOWLIST = {CLIENT_ID: [PREFIX_CALLBACK]}
    client.force_login(user)

    assert client.get(reverse("indieweb:auth"), _auth_params(candidate)).status_code == 200
    approved = _consent(client, candidate)
    assert approved.status_code == 302
    assert urlsplit(approved["Location"]).path == urlsplit(candidate).path


@pytest.mark.django_db
def test_prefix_allowlist_entry_rejects_semicolon_before_the_prefix_boundary(client, settings, user):
    settings.INDIEWEB_REDIRECT_URI_ALLOWLIST = {CLIENT_ID: [PREFIX_CALLBACK]}
    client.force_login(user)

    candidate = "https://callback.example/oauth;x/cb"
    assert client.get(reverse("indieweb:auth"), _auth_params(candidate)).status_code == 400


@pytest.mark.django_db
def test_approval_replaces_reserved_response_keys_in_redirect_uri(client, user):
    """Each protocol key reaches the client exactly once, with the server's value."""
    client.force_login(user)
    redirect_uri = (
        "https://client.example/cb?code=old&state=old&me=old&iss=old&error=old&error_description=old"
        "&error_uri=old&keep=1&keep=2&blank="
    )

    response = _consent(client, redirect_uri)

    assert response.status_code == 302
    pairs = parse_qsl(urlsplit(response["Location"]).query, keep_blank_values=True)
    keys = [key for key, _ in pairs]
    for reserved in ("code", "state", "me", "iss"):
        assert keys.count(reserved) == 1, reserved
    for absent in ("error", "error_description", "error_uri"):
        assert absent not in keys
    query = parse_qs(urlsplit(response["Location"]).query, keep_blank_values=True)
    assert query["code"] != ["old"]
    assert query["state"] == ["state-123"]
    assert query["me"] == ["https://me.example/"]
    assert query["iss"] == ["http://testserver/indieweb/"]
    assert query["keep"] == ["1", "2"]
    assert query["blank"] == [""]
    issued = query["code"][0]
    assert Auth.get_for_raw_key(issued, client_id=CLIENT_ID).redirect_uri == redirect_uri


@pytest.mark.django_db
def test_denial_replaces_reserved_response_keys_in_redirect_uri(client, user):
    client.force_login(user)
    redirect_uri = "https://client.example/cb?code=old&state=old&iss=old&error=old&error_description=x&keep=1"

    response = _consent(client, redirect_uri, action="deny")

    assert response.status_code == 302
    pairs = parse_qsl(urlsplit(response["Location"]).query, keep_blank_values=True)
    assert [key for key, _ in pairs].count("error") == 1
    assert [key for key, _ in pairs].count("state") == 1
    query = parse_qs(urlsplit(response["Location"]).query, keep_blank_values=True)
    assert query["error"] == ["access_denied"]
    assert query["state"] == ["state-123"]
    assert query["keep"] == ["1"]
    for absent in ("code", "iss", "error_description", "me"):
        assert absent not in query
    assert not Auth.objects.filter(client_id=CLIENT_ID).exists()


@pytest.mark.django_db
def test_reserved_key_removal_matches_percent_encoded_key_names(client, user):
    """``co%64e`` decodes to ``code``; clients read the decoded name, so it is reserved too."""
    client.force_login(user)
    redirect_uri = "https://client.example/cb?co%64e=old&st%61te=old&keep=1"

    response = _consent(client, redirect_uri)

    query = parse_qs(urlsplit(response["Location"]).query, keep_blank_values=True)
    assert len(query["code"]) == 1
    assert query["code"] != ["old"]
    assert query["state"] == ["state-123"]
    assert query["keep"] == ["1"]
