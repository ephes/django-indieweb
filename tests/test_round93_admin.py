"""Current-state admin boundaries, using synthetic grants and content."""

import json
from unittest.mock import patch

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from indieweb.models import Auth, Profile, Token, Webmention
from indieweb.processors import WebmentionProcessor

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(client):
    client.force_login(get_user_model().objects.create_superuser(username="synthetic-admin", password="synthetic"))
    return client


def edit_post(client, model, row):
    url = reverse(f"admin:indieweb_{model}_change", args=[row.pk])
    form = client.get(url).context["adminform"].form
    data = {}
    for name in form.fields:
        value = form[name].value()
        if name == "published":
            date, time = form.fields[name].widget.decompress(value)
            data[name + "_0"] = date.strftime("%Y-%m-%d") if date else ""
            data[name + "_1"] = time.strftime("%H:%M:%S") if time else ""
        else:
            data[name] = value if value is not None else ""
    return url, data


@pytest.mark.parametrize("model", [Auth, Token])
@pytest.mark.parametrize("mutation", ["delete", "rotate"])
def test_credential_inspection_cannot_save_stale_grant(staff_client, model, mutation):
    owner = get_user_model().objects.get(username="synthetic-admin")
    row = model.objects.create(owner=owner, client_id="https://client.example/", me="https://owner.example/")
    url = reverse(f"admin:indieweb_{model._meta.model_name}_change", args=[row.pk])
    assert staff_client.get(url).status_code == 200
    modeladmin = admin.site._registry[model]
    # Return the pre-mutation instance as if it had been loaded before revocation.
    if mutation == "delete":
        model.objects.filter(pk=row.pk).delete()
    else:
        model.objects.filter(pk=row.pk).update(key="synthetic-rotated")
    with (
        patch.object(modeladmin, "get_object", return_value=row),
        patch.object(model, "save", autospec=True, side_effect=AssertionError("inspection called save")),
    ):
        response = staff_client.post(url, {"_save": "Save"})
    assert response.status_code == 403
    if mutation == "delete":
        assert not model.objects.filter(pk=row.pk).exists()
    else:
        assert model.objects.get(pk=row.pk).key == "synthetic-rotated"


@pytest.mark.parametrize("model", [Auth, Token])
def test_credential_view_and_delete_permissions_are_separate(client, model):
    staff = get_user_model().objects.create_user(username="synthetic-viewer", is_staff=True)
    staff.user_permissions.add(Permission.objects.get(codename=f"view_{model._meta.model_name}"))
    row = model.objects.create(owner=staff, client_id="https://client.example/", me="https://owner.example/")
    client.force_login(staff)
    url = reverse(f"admin:indieweb_{model._meta.model_name}_change", args=[row.pk])
    response = client.get(url)
    assert response.status_code == 200
    assert 'name="_save"' not in response.content.decode()
    delete = reverse(f"admin:indieweb_{model._meta.model_name}_delete", args=[row.pk])
    assert client.post(delete, {"post": "yes"}).status_code == 403
    staff.user_permissions.add(Permission.objects.get(codename=f"delete_{model._meta.model_name}"))
    assert client.post(delete, {"post": "yes"}).status_code == 302
    assert not model.objects.filter(pk=row.pk).exists()


@pytest.mark.parametrize("change", [False, True])
def test_webmention_editor_preserves_current_processor_outcome(staff_client, change):
    row = Webmention.objects.create(source_url="https://source.example/post", target_url="https://target.example/post")
    url, data = edit_post(staff_client, "webmention", row)
    if change:
        data["content"] = "editorial"
    modeladmin = admin.site._registry[Webmention]
    original = modeladmin.get_object

    def receive(*args, **kwargs):
        # A real processing failure changes only status/verification/receive state.
        WebmentionProcessor()._mark_webmention_failed(Webmention.objects.get(pk=row.pk), timezone.now())
        Webmention.objects.filter(pk=row.pk).update(spam_check_result={"synthetic": True})
        return original(*args, **kwargs)

    with patch.object(modeladmin, "get_object", side_effect=receive):
        response = staff_client.post(url, data)
    row.refresh_from_db()
    assert row.status == "failed"
    assert row.last_received_at is not None
    assert row.spam_check_result == {"synthetic": True}
    assert row.content == ""
    assert response.status_code == (200 if change else 302)
    if change:
        assert response.context["adminform"].form.non_field_errors()


@pytest.mark.parametrize("changed_field", ["name", "h_card"])
def test_profile_two_clients_refuse_stale_card_and_allow_fresh_resubmit(staff_client, changed_field):
    user = get_user_model().objects.create_user(username="synthetic-profile")
    row = Profile.objects.create(user=user, h_card={"name": ["Before"]})
    second = Client()
    second.force_login(get_user_model().objects.get(username="synthetic-admin"))
    url, old = edit_post(second, "profile", row)
    _, current = edit_post(staff_client, "profile", row)
    current["h_card"] = json.dumps({"name": ["Current"], "url": ["https://current.example/"]})
    assert staff_client.post(url, current).status_code == 302
    old[changed_field] = "Stale" if changed_field == "name" else json.dumps({"name": ["Stale"]})
    response = second.post(url, old)
    assert response.status_code == 200
    conflict_form = response.context["adminform"].form
    assert conflict_form.non_field_errors()
    assert json.loads(conflict_form["h_card"].value())["name"] == ["Current"]
    assert conflict_form["name"].value() == "Current"
    row.refresh_from_db()
    assert row.name == "Current"
    assert row.url == "https://current.example/"
    _, fresh = edit_post(second, "profile", row)
    fresh["h_card"] = json.dumps({"name": ["Resubmitted"], "url": ["https://fresh.example/"]})
    assert second.post(url, fresh).status_code == 302
    row.refresh_from_db()
    assert row.name == row.h_card["name"][0] == "Resubmitted"
    assert row.url == row.h_card["url"][0] == "https://fresh.example/"


@pytest.mark.parametrize("model_name", ["profile", "webmention"])
@pytest.mark.parametrize("revision", ["missing", "tampered", "foreign"])
def test_admin_requires_matching_signed_revision(staff_client, model_name, revision):
    if model_name == "profile":
        row = Profile.objects.create(user=get_user_model().objects.create_user(username="synthetic-one"))
        other = Profile.objects.create(user=get_user_model().objects.create_user(username="synthetic-two"))
        field, new_value, token = "h_card", json.dumps({"name": ["Refused"]}), "edit_revision"
    else:
        row = Webmention.objects.create(source_url="https://one.example/", target_url="https://target.example/")
        other = Webmention.objects.create(source_url="https://two.example/", target_url="https://target.example/")
        field, new_value, token = "content", "Refused", "edit_baseline"
    url, data = edit_post(staff_client, model_name, row)
    if revision == "missing":
        data.pop(token)
    elif revision == "tampered":
        data[token] += "tampered"
    else:
        data[token] = edit_post(staff_client, model_name, other)[1][token]
    data[field] = new_value
    response = staff_client.post(url, data)
    assert response.status_code == 200
    assert response.context["adminform"].form.non_field_errors()
    row.refresh_from_db()
    assert getattr(row, field) == ({} if model_name == "profile" else "")


def test_deliberate_webmention_identity_edit_retains_current_diagnostics(staff_client):
    row = Webmention.objects.create(source_url="https://source.example/", target_url="https://target.example/")
    url, data = edit_post(staff_client, "webmention", row)
    verified = timezone.now()
    Webmention.objects.filter(pk=row.pk).update(verified_at=verified, spam_check_result={"synthetic": "current"})
    data["source_url"] = "https://changed.example/"
    data["content"] = "Deliberate editorial decision"
    response = staff_client.post(url, data)
    assert response.status_code == 302
    row.refresh_from_db()
    assert row.source_url == "https://changed.example/"
    assert row.content == "Deliberate editorial decision"
    assert row.verified_at == verified
    assert row.spam_check_result == {"synthetic": "current"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("model_name", ["profile", "webmention"])
def test_admin_lock_serializes_other_connection_until_save(staff_client, concurrent_database, model_name):
    from threading import Event, Thread

    from django.db import connections

    if model_name == "profile":
        row = Profile.objects.create(user=get_user_model().objects.create_user(username="synthetic-profile"))
        field, value = "h_card", json.dumps({"name": ["Admin"]})
    else:
        row = Webmention.objects.create(source_url="https://source.example/", target_url="https://target.example/")
        field, value = "content", "Admin"
    url, data = edit_post(staff_client, model_name, row)
    data[field] = value
    started, finished = Event(), Event()
    errors = []

    def update():
        try:
            current = type(row).objects.get(pk=row.pk)
            started.set()
            if model_name == "profile":
                current.h_card = {"name": ["Worker"]}
                current.save(update_fields=["h_card"])
            else:
                WebmentionProcessor()._mark_webmention_failed(current, timezone.now())
        except BaseException as exc:
            errors.append(exc)
        finally:
            connections.close_all()
            finished.set()

    worker = Thread(target=update)
    modeladmin = admin.site._registry[type(row)]
    original = modeladmin.get_form

    def pause(request, obj=None, **kwargs):
        if request.method == "POST" and not started.is_set():
            worker.start()
            assert started.wait(5)
            assert not finished.wait(0.1), "concurrent writer committed before admin saved"
        return original(request, obj, **kwargs)

    try:
        with patch.object(modeladmin, "get_form", pause):
            response = staff_client.post(url, data)
    finally:
        worker.join(10)
    assert not worker.is_alive()
    assert not errors
    assert response.status_code == 302
    row.refresh_from_db()
    if model_name == "profile":
        assert row.h_card == {"name": ["Worker"]}
        assert row.name == "Worker"
    else:
        assert row.content == "Admin"
        assert row.status == "failed"
        assert row.last_received_at is not None
