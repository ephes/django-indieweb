import logging

from django.db import migrations
from django.db.models import Count, Q

logger = logging.getLogger(__name__)


def reconcile_no_scope_rows(model, using):
    """Leave one no-scope row per grant identity and store its scope as "".

    ``NULL`` scopes do not collide in a unique constraint, so an identity
    (``me``, ``client_id``, ``owner``) can hold several no-scope rows, as
    ``NULL`` or "". The most recently modified row (highest primary key on a
    tie) is kept exactly as stored: no key is rotated and no expiry is
    extended. Every other duplicate is deleted, which revokes it. Works on
    database ``using`` and returns the number of deleted rows.
    """
    rows = model.objects.using(using)
    no_scope = rows.filter(Q(scope__isnull=True) | Q(scope=""))
    duplicated = (
        no_scope.values("me", "client_id", "owner_id")
        .annotate(row_count=Count("pk"))
        .filter(row_count__gt=1)
        .order_by()
    )
    deleted = 0
    for identity in list(duplicated):
        group = no_scope.filter(
            me=identity["me"], client_id=identity["client_id"], owner_id=identity["owner_id"]
        ).order_by("-modified", "-pk")
        keep_pk = group.values_list("pk", flat=True).first()
        stale = group.exclude(pk=keep_pk)
        deleted += stale.count()
        stale.delete()
    rows.filter(scope__isnull=True).update(scope="")
    return deleted


def reconcile_no_scope_grants(apps, schema_editor):
    using = schema_editor.connection.alias
    for model_name in ("Auth", "Token"):
        deleted = reconcile_no_scope_rows(apps.get_model("indieweb", model_name), using)
        if deleted:
            logger.warning(
                "indieweb migration 0029 deleted %s duplicate no-scope %s row(s); "
                "the newest row per identity was kept",
                deleted,
                model_name,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("indieweb", "0028_alter_webmentionnestedresponse_url_validators"),
    ]

    operations = [
        # Data only. The schema change lives in 0030 so that PostgreSQL does
        # not alter a table with pending trigger events from these writes.
        migrations.RunPython(reconcile_no_scope_grants, migrations.RunPython.noop),
    ]
