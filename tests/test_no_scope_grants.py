"""No-scope grants are stored as "" so the unique grant identity covers them."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import textwrap
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, models, transaction
from django.db.models import QuerySet
from django.urls import reverse
from django.utils import timezone

from indieweb.models import Auth, Token
from indieweb.views import AuthView

CLIENT_ID = "https://webapp.example.org"
ME = "https://example.org/"
REDIRECT_URI = "https://webapp.example.org/callback"


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="foo", email="foo@example.org", password="password")


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(username="bar", email="bar@example.org", password="password")


def _auth(owner, **overrides) -> Auth:
    values = {
        "owner": owner,
        "state": "state",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "me": ME,
    }
    values.update(overrides)
    return Auth.objects.create(**values)


def _token(owner, **overrides) -> Token:
    values = {"owner": owner, "client_id": CLIENT_ID, "me": ME}
    values.update(overrides)
    return Token.objects.create(**values)


def _exchange(client, code: str):
    return client.post(
        reverse("indieweb:token"),
        data={"code": code, "client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI},
    )


@pytest.mark.parametrize("factory", [_auth, _token])
def test_none_scope_is_stored_as_empty_string(user, factory):
    row = factory(user, scope=None)

    assert row.scope == ""
    assert type(row).objects.get(pk=row.pk).scope == ""
    assert not type(row).objects.filter(scope__isnull=True).exists()


@pytest.mark.parametrize("factory", [_auth, _token])
def test_scope_defaults_to_empty_string(user, factory):
    assert factory(user).scope == ""


@pytest.mark.parametrize("factory", [_auth, _token])
@pytest.mark.parametrize("second_scope", [None, ""])
def test_second_no_scope_row_for_the_same_identity_is_rejected(user, factory, second_scope):
    """The insert that loses a first-issuance race now hits the unique constraint."""
    factory(user, scope=None)

    with pytest.raises(IntegrityError), transaction.atomic():
        factory(user, scope=second_scope)

    assert type(factory(user, scope="create")).objects.filter(owner=user).count() == 2


@pytest.mark.parametrize("factory", [_auth, _token])
def test_no_scope_rows_for_independent_identities_coexist(user, other_user, factory):
    factory(user, scope=None)
    factory(other_user, scope=None)
    factory(user, scope=None, client_id="https://other-client.example/")
    factory(user, scope=None, me="https://other.example/")

    assert type(factory(user, scope="create")).objects.count() == 5


def test_consent_replaces_the_pending_no_scope_code(user):
    first = AuthView._replace_auth_code(
        owner=user,
        client_id=CLIENT_ID,
        redirect_uri=REDIRECT_URI,
        state="one",
        scope=None,
        me=ME,
        code_challenge=None,
        code_challenge_method=None,
    )
    second = AuthView._replace_auth_code(
        owner=user,
        client_id=CLIENT_ID,
        redirect_uri=REDIRECT_URI,
        state="two",
        scope=None,
        me=ME,
        code_challenge=None,
        code_challenge_method=None,
    )

    assert first.scope == "" and second.scope == ""
    assert list(Auth.objects.values_list("pk", "state")) == [(second.pk, "two")]


def test_consent_retries_when_a_concurrent_no_scope_approval_wins_the_insert(user, monkeypatch):
    """The loser of the insert race retries and replaces the winner's code: one row remains."""
    original_create = Auth.objects.create
    raced = False

    def create_after_concurrent_winner(**fields):
        nonlocal raced
        if not raced:
            raced = True
            original_create(**{**fields, "state": "winner"})
        return original_create(**fields)

    monkeypatch.setattr(Auth.objects, "create", create_after_concurrent_winner)

    auth = AuthView._replace_auth_code(
        owner=user,
        client_id=CLIENT_ID,
        redirect_uri=REDIRECT_URI,
        state="loser",
        scope=None,
        me=ME,
        code_challenge=None,
        code_challenge_method=None,
    )

    assert raced
    assert list(Auth.objects.values_list("pk", "state", "scope")) == [(auth.pk, "loser", "")]


def test_sequential_no_scope_exchanges_reuse_one_token_row(client, user):
    first = _exchange(client, _auth(user, key="firstnoscopecode").key)
    second = _exchange(client, _auth(user, key="secondnoscopecode").key)

    assert (first.status_code, second.status_code) == (201, 200)
    token = Token.objects.get()
    assert token.scope == ""
    second_key = parse_qs(second.content.decode("utf-8"), keep_blank_values=True)["access_token"][0]
    assert Token.get_for_raw_key(second_key).pk == token.pk
    assert parse_qs(second.content.decode("utf-8"), keep_blank_values=True)["scope"] == [""]


def test_exchange_reuses_the_token_a_concurrent_first_issuance_created(client, user, monkeypatch):
    """A first issuance that loses the insert race gets the winner's row, not a second one."""
    auth = _auth(user, key="racingnoscopecode")
    original_get = QuerySet.get
    raced = False

    def get_then_concurrent_winner_inserts(queryset, *args, **kwargs):
        nonlocal raced
        if queryset.model is not Token or raced:
            return original_get(queryset, *args, **kwargs)
        raced = True
        try:
            return original_get(queryset, *args, **kwargs)
        finally:
            # The other request commits its row after our lookup found nothing.
            _token(user, scope=None, expires_at=timezone.now() + timedelta(hours=1))

    monkeypatch.setattr(QuerySet, "get", get_then_concurrent_winner_inserts)

    response = _exchange(client, auth.key)

    assert raced
    assert response.status_code == 200
    token = Token.objects.get()
    assert token.scope == ""
    key = parse_qs(response.content.decode("utf-8"), keep_blank_values=True)["access_token"][0]
    assert Token.get_for_raw_key(key).pk == token.pk


def test_no_scope_token_still_fails_scope_checks(client, user):
    token = _token(user, key="noscopebearertoken", scope=None, expires_at=timezone.now() + timedelta(hours=1))

    response = client.post(
        reverse("indieweb:micropub"), data={"h": "entry", "content": "x"}, HTTP_AUTHORIZATION=f"Bearer {token.key}"
    )

    assert response.status_code == 403


# ----------------------------------------------------------------------------
# Migration 0029: duplicate reconciliation on legacy-shaped tables.
# ----------------------------------------------------------------------------


class LegacyGrant(models.Model):
    """The pre-migration shape: nullable scope and no usable uniqueness for NULL."""

    modified = models.DateTimeField()
    owner = models.ForeignKey("auth.User", on_delete=models.CASCADE, related_name="+")
    client_id = models.CharField(max_length=512)
    me = models.CharField(max_length=512)
    scope = models.CharField(max_length=256, null=True, blank=True)  # noqa: DJ001
    key = models.CharField(max_length=80)

    class Meta:
        app_label = "tests"
        db_table = "tests_legacy_grant"

    def __str__(self) -> str:
        return self.key


@pytest.fixture
def legacy_grants(transactional_db):
    with connection.schema_editor() as editor:
        editor.create_model(LegacyGrant)
    try:
        yield LegacyGrant
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(LegacyGrant)


@pytest.fixture
def reconcile_no_scope_rows():
    return importlib.import_module("indieweb.migrations.0029_reconcile_no_scope_grants").reconcile_no_scope_rows


def _legacy(owner, key: str, scope: str | None, *, age_hours: int, **overrides):
    values = {
        "owner": owner,
        "client_id": CLIENT_ID,
        "me": ME,
        "scope": scope,
        "key": key,
        "modified": timezone.now() - timedelta(hours=age_hours),
    }
    values.update(overrides)
    return LegacyGrant.objects.create(**values)


def test_reconcile_keeps_only_the_newest_no_scope_row_per_identity(legacy_grants, reconcile_no_scope_rows):
    owner = get_user_model().objects.create_user(username="legacy")
    other = get_user_model().objects.create_user(username="legacy-other")
    _legacy(owner, "old-null", None, age_hours=30)
    _legacy(owner, "newest-null", None, age_hours=1)
    _legacy(owner, "older-empty", "", age_hours=10)
    _legacy(owner, "scoped", "create", age_hours=50)
    _legacy(other, "other-owner", None, age_hours=40)
    _legacy(owner, "other-client", None, age_hours=40, client_id="https://other-client.example/")

    deleted = reconcile_no_scope_rows(legacy_grants, "default")

    assert deleted == 2
    assert dict(legacy_grants.objects.values_list("key", "scope")) == {
        "newest-null": "",
        "scoped": "create",
        "other-owner": "",
        "other-client": "",
    }


def test_reconcile_keeps_the_kept_row_unchanged_and_is_idempotent(legacy_grants, reconcile_no_scope_rows):
    owner = get_user_model().objects.create_user(username="legacy")
    kept = _legacy(owner, "kept", "", age_hours=1)
    _legacy(owner, "dropped", None, age_hours=2)

    assert reconcile_no_scope_rows(legacy_grants, "default") == 1
    assert reconcile_no_scope_rows(legacy_grants, "default") == 0

    stored = legacy_grants.objects.get()
    assert (stored.pk, stored.key, stored.scope, stored.modified) == (kept.pk, "kept", "", kept.modified)


def test_reconcile_breaks_modified_ties_by_highest_primary_key(legacy_grants, reconcile_no_scope_rows):
    owner = get_user_model().objects.create_user(username="legacy")
    moment = timezone.now()
    _legacy(owner, "first", None, age_hours=0, modified=moment)
    _legacy(owner, "second", None, age_hours=0, modified=moment)

    assert reconcile_no_scope_rows(legacy_grants, "default") == 1
    assert legacy_grants.objects.get().key == "second"


MIGRATION_PROBE = textwrap.dedent(
    """
    import django
    django.setup()
    from django.db import IntegrityError, connection, transaction
    from django.db.migrations.executor import MigrationExecutor

    BEFORE = [("indieweb", "0028_alter_webmentionnestedresponse_url_validators")]
    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE)
    apps = executor.loader.project_state(BEFORE).apps
    User = apps.get_model("auth", "User")
    owner = User.objects.create(username="legacy")
    for name in ("Auth", "Token"):
        model = apps.get_model("indieweb", name)
        extra = {"state": "s", "redirect_uri": "https://c.example/cb"} if name == "Auth" else {}
        for index, scope in enumerate([None, None, "", "create"]):
            model.objects.create(
                owner=owner, key=f"{name}-{index}", client_id="https://c.example/", me="https://me.example/",
                scope=scope, **extra,
            )

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    apps = executor.loader.project_state(executor.loader.graph.leaf_nodes()).apps
    for name in ("Auth", "Token"):
        model = apps.get_model("indieweb", name)
        assert sorted(model.objects.values_list("scope", flat=True)) == ["", "create"], name
        assert not model.objects.filter(scope__isnull=True).exists(), name
        extra = {"state": "s", "redirect_uri": "https://c.example/cb"} if name == "Auth" else {}
        try:
            with transaction.atomic():
                model.objects.create(
                    owner_id=owner.pk, key=f"{name}-dup", client_id="https://c.example/", me="https://me.example/",
                    scope="", **extra,
                )
        except IntegrityError:
            pass
        else:
            raise AssertionError(f"{name}: duplicate no-scope row was accepted")
    print("MIGRATION-PROBE-OK")
    """
)


def test_migrations_normalize_null_scopes_and_enforce_uniqueness():
    """Run the real 0028 -> latest migration path in a fresh process (the suite disables migrations)."""
    repo_root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "tests.settings", "PYTHONPATH": str(repo_root)}

    result = subprocess.run(
        [sys.executable, "-c", MIGRATION_PROBE], cwd=repo_root, env=env, capture_output=True, text=True, timeout=120
    )

    assert result.returncode == 0, result.stderr
    assert "MIGRATION-PROBE-OK" in result.stdout
