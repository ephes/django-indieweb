import hashlib
import hmac

from django.conf import settings
from django.db import migrations, models

TOKEN_KEY_HASH_PREFIX = "hmac-sha256$"


def _hash_auth_key(raw_key):
    digest = hmac.new(
        str(settings.SECRET_KEY).encode("utf-8"),
        raw_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{TOKEN_KEY_HASH_PREFIX}{digest}"


def hash_existing_auth_keys(apps, schema_editor):
    Auth = apps.get_model("indieweb", "Auth")
    for auth in Auth.objects.all().only("pk", "key"):
        if auth.key.startswith(TOKEN_KEY_HASH_PREFIX):
            continue
        auth.key = _hash_auth_key(auth.key)
        auth.save(update_fields=["key"])


class Migration(migrations.Migration):
    dependencies = [
        ("indieweb", "0022_websubsubscription_recent_accepted_delivery_digests"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auth",
            name="key",
            field=models.CharField(max_length=80, unique=True),
        ),
        migrations.RunPython(hash_existing_auth_keys, migrations.RunPython.noop),
    ]
