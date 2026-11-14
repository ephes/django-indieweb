"""Synthetic admin concurrency and JSON admission regressions."""

import json
from threading import Event, Thread
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import connections
from django.urls import reverse
from django.utils import timezone

from indieweb.models import Profile, WebSubSubscription
from indieweb.websub import confirm_websub_verification, record_websub_delivery


@pytest.fixture
def staff_client(client):
    client.force_login(get_user_model().objects.create_superuser(username="synthetic-admin", password="synthetic"))
    return client


def subscription_post(client, row):
    url = reverse("admin:indieweb_websubsubscription_change", args=[row.pk])
    form = client.get(url).context["adminform"].form
    data = {}
    for name in form.fields:
        value = form[name].value()
        if isinstance(value, bool):
            if value:
                data[name] = "on"
        elif name == "lease_expires_at":
            date, time = form.fields[name].widget.decompress(value)
            data[name + "_0"] = date.strftime("%Y-%m-%d") if date else ""
            data[name + "_1"] = time.strftime("%H:%M:%S") if time else ""
        else:
            data[name] = value if value is not None else ""
    return url, data


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("conflict", [False, True])
def test_admin_preserves_renewal_and_delivery_from_other_connection(staff_client, concurrent_database, conflict):
    row = WebSubSubscription.objects.create(
        hub_url="https://hub.example/",
        topic_url="https://topic.example/",
        state="active",
        pending_mode="subscribe",
        secret="synthetic-old-secret",
        pending_secret="synthetic-new-secret",
        pending_secret_set=True,
        confirmed_lease_seconds=300,
        lease_expires_at=timezone.now(),
    )
    url, data = subscription_post(staff_client, row)
    if conflict:
        data["state"] = "unsubscribed"
    else:
        data["requested_lease_seconds"] = "900"
    errors = []

    def renew():
        try:
            current = WebSubSubscription.objects.get(pk=row.pk)
            current.request_generation = uuid4()
            current.save(update_fields=["request_generation"])
            confirm_websub_verification(
                current, mode="subscribe", topic_url=current.topic_url, challenge="synthetic", lease_seconds=600
            )
            record_websub_delivery(current, body=b"synthetic", content_type="text/plain", status_code=204)
        except BaseException as exc:
            errors.append(exc)
        finally:
            connections.close_all()

    writer = Thread(target=renew)
    writer.start()
    writer.join(10)
    assert not writer.is_alive()
    assert not errors
    current = WebSubSubscription.objects.get(pk=row.pk)
    response = staff_client.post(url, data)
    row.refresh_from_db()
    if conflict:
        assert response.status_code == 200
        assert "changed" in str(response.context["adminform"].form.non_field_errors()).lower()
        assert row.state == "active"
    else:
        assert response.status_code == 302, response.context["adminform"].form.errors
        assert row.requested_lease_seconds == 900
    for field in (
        "secret",
        "pending_secret",
        "pending_secret_set",
        "request_generation",
        "last_verified_at",
        "last_delivery_digest",
        "last_delivery_at",
        "confirmed_lease_seconds",
        "lease_expires_at",
    ):
        assert getattr(row, field) == getattr(current, field), field


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        '{"name":' + "[" * 20000 + "0" + "]" * 20000 + "}",
        '{"name":[' + "9" * 5000 + "]}",
        json.dumps({"name": ["synthetic" * 120000]}),
        " " * 262145 + "{}",
        json.dumps({"note": ["é" * 132000]}, ensure_ascii=False),
    ],
    ids=["deep", "integer", "bytes", "padding", "utf8"],
)
def test_profile_admin_refuses_resource_inputs_without_saving(staff_client, payload):
    user = get_user_model().objects.create_user(username="synthetic-profile")
    profile = Profile.objects.create(user=user, h_card={"name": ["Before"]})
    response = staff_client.post(
        reverse("admin:indieweb_profile_change", args=[profile.pk]),
        {"user": user.pk, "h_card": payload, "name": "After"},
    )
    assert response.status_code == 200
    errors = str(response.context["adminform"].form.errors["h_card"])
    assert "Invalid JSON" in errors
    assert "synthetic" not in errors
    profile.refresh_from_db()
    assert profile.h_card == {"name": ["Before"]}


@pytest.mark.django_db(transaction=True)
def test_admin_holds_current_row_until_save(staff_client, concurrent_database):
    row = WebSubSubscription.objects.create(
        hub_url="https://hub.example/",
        topic_url="https://topic.example/",
        state="active",
        pending_mode="subscribe",
        secret="synthetic-old",
        pending_secret="synthetic-new",
        pending_secret_set=True,
    )
    url, data = subscription_post(staff_client, row)
    data["requested_lease_seconds"] = "900"
    started, finished = Event(), Event()
    errors = []

    def renew():
        try:
            # Use the previously loaded instance; confirmation must reload it.
            started.set()
            confirm_websub_verification(
                row, mode="subscribe", topic_url=row.topic_url, challenge="synthetic", lease_seconds=600
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            connections.close_all()
            finished.set()

    writer = Thread(target=renew)
    modeladmin = admin.site._registry[WebSubSubscription]
    original = modeladmin.get_form

    def pause(request, obj=None, **kwargs):
        if request.method == "POST" and not started.is_set():
            writer.start()
            assert started.wait(5)
            assert not finished.wait(0.1), "renewal committed while the admin owned the current row"
        return original(request, obj, **kwargs)

    try:
        with patch.object(modeladmin, "get_form", pause):
            response = staff_client.post(url, data)
    finally:
        writer.join(10)
    assert not writer.is_alive()
    assert not errors
    assert response.status_code == 302
    row.refresh_from_db()
    assert row.get_secret() == "synthetic-new"
    assert row.requested_lease_seconds == 900
    assert row.confirmed_lease_seconds == 600


@pytest.mark.django_db
@pytest.mark.parametrize("baseline", ["missing", "tampered", "foreign"])
def test_admin_invalid_baseline_is_a_form_error(staff_client, baseline):
    row = WebSubSubscription.objects.create(hub_url="https://hub.example/", topic_url="https://topic.example/")
    url, data = subscription_post(staff_client, row)
    if baseline == "missing":
        data.pop("edit_baseline")
    elif baseline == "tampered":
        data["edit_baseline"] += "changed"
    else:
        other = WebSubSubscription.objects.create(hub_url="https://hub.example/", topic_url="https://other.example/")
        data["edit_baseline"] = subscription_post(staff_client, other)[1]["edit_baseline"]
    data["requested_lease_seconds"] = "900"
    response = staff_client.post(url, data)
    assert response.status_code == 200
    assert response.context["adminform"].form.non_field_errors()
    row.refresh_from_db()
    assert row.requested_lease_seconds is None


@pytest.mark.django_db
def test_admin_new_subscription_and_profile_still_save(staff_client):
    response = staff_client.post(
        reverse("admin:indieweb_websubsubscription_add"),
        {
            "hub_url": "https://hub.example/",
            "topic_url": "https://topic.example/",
            "state": "active",
            "confirmed_lease_seconds": "600",
            "lease_expires_at_0": "2027-01-01",
            "lease_expires_at_1": "12:00:00",
        },
    )
    assert response.status_code == 302
    row = WebSubSubscription.objects.get()
    url, data = subscription_post(staff_client, row)
    data["state"] = "unsubscribed"
    response = staff_client.post(url, data)
    assert response.status_code == 302
    row.refresh_from_db()
    assert row.state == "unsubscribed"
    user = get_user_model().objects.create_user(username="synthetic-profile")
    response = staff_client.post(
        reverse("admin:indieweb_profile_add"),
        {
            "user": user.pk,
            "h_card": json.dumps({"name": ["Synthetic"]}),
        },
    )
    assert response.status_code == 302
    assert Profile.objects.get(user=user).name == "Synthetic"
