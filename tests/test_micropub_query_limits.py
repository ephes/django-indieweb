"""Synthetic adapter probes for source/media query pagination boundaries."""

from unittest.mock import Mock

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

from indieweb.handlers import (
    InMemoryMicropubHandler,
    MicropubEntry,
    MicropubEntryList,
    MicropubMediaItem,
    MicropubMediaList,
)
from indieweb.models import Token


@pytest.fixture(params=["micropub", "media"])
def query_adapter(request, client, db, monkeypatch):
    user = User.objects.create_user(username="paging-user")
    access_grant = Token.objects.create(
        owner=user, me="https://example.org/", client_id="https://client.example.org/", scope="update media"
    )
    entries = [MicropubEntry(url=f"/posts/{index}/", properties={}) for index in range(5)]
    media = [MicropubMediaItem(url=f"/media/{index}.jpg", properties={}) for index in range(5)]

    class SpyHandler(InMemoryMicropubHandler):
        def list_media(self, user, *, limit=None, offset=0, filter=None):
            return MicropubMediaList(items=media, total=50)

    handler = SpyHandler()
    method = "list_entries" if request.param == "micropub" else "list_media"
    result = MicropubEntryList(entries=entries, total=50) if method == "list_entries" else handler.list_media(user)
    spy = Mock(return_value=result)
    monkeypatch.setattr(handler, method, spy)
    monkeypatch.setattr("indieweb.views.get_micropub_handler", lambda: handler)

    def query(params):
        return client.get(
            reverse(f"indieweb:{request.param}"),
            data={"q": "source", **params},
            Authorization=f"Bearer {access_grant.key}",
        )

    return query, spy, user


@pytest.mark.django_db
@pytest.mark.parametrize(
    "params,limit,offset", [({}, 20, 0), ({"limit": "100", "offset": "2147483647"}, 100, 2147483647)]
)
def test_query_default_and_boundary_limits(query_adapter, params, limit, offset):
    query, spy, user = query_adapter
    response = query({**params, "filter": "synthetic"})
    assert response.status_code == 200
    spy.assert_called_once_with(user, limit=limit, offset=offset, filter="synthetic")
    assert response.json()["paging"] == {"limit": limit, "offset": offset, "total": 50}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "params",
    [
        {"limit": "0"},
        {"limit": "101"},
        {"limit": "9" * 100},
        {"offset": "2147483648"},
        {"offset": "9" * 100},
        {"limit": "-1"},
        {"offset": "-1"},
        {"limit": "invalid"},
        {"offset": "1.5"},
    ],
)
def test_query_rejects_unsupported_paging_before_adapter(query_adapter, params):
    query, spy, _ = query_adapter
    response = query(params)
    assert response.status_code == 400
    assert response.content == b"invalid_request"
    spy.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("params,limit", [({}, 2), ({"limit": "3"}, 3)])
def test_query_configured_limits_and_response_ceiling(query_adapter, settings, params, limit):
    settings.INDIEWEB_MICROPUB_QUERY_DEFAULT_LIMIT = 2
    settings.INDIEWEB_MICROPUB_QUERY_MAX_LIMIT = 3
    query, spy, user = query_adapter
    response = query({**params, "offset": "1", "filter": "synthetic"})
    assert response.status_code == 200
    spy.assert_called_once_with(user, limit=limit, offset=1, filter="synthetic")
    # Even a nonconforming adapter cannot enlarge the serialized page.
    assert len(response.json()["items"]) == limit
    assert response.json()["paging"] == {"limit": limit, "offset": 1, "total": 50}


@pytest.mark.django_db
def test_query_configured_maximum_is_enforced(query_adapter, settings):
    settings.INDIEWEB_MICROPUB_QUERY_DEFAULT_LIMIT = 2
    settings.INDIEWEB_MICROPUB_QUERY_MAX_LIMIT = 3
    query, spy, _ = query_adapter
    assert query({"limit": "4"}).status_code == 400
    spy.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "default,maximum", [(0, 100), (20, None), (20, True), (20, "100"), (21, 20), (20, 2147483648)]
)
def test_query_invalid_configuration_fails_before_adapter(query_adapter, settings, default, maximum):
    settings.INDIEWEB_MICROPUB_QUERY_DEFAULT_LIMIT = default
    settings.INDIEWEB_MICROPUB_QUERY_MAX_LIMIT = maximum
    query, spy, _ = query_adapter
    with pytest.raises(ImproperlyConfigured):
        query({})
    spy.assert_not_called()
