import hashlib
import hmac

from django.conf import settings
from django.db import migrations, models
from django.utils.crypto import get_random_string

import indieweb.models

TOKEN_KEY_HASH_PREFIX = "hmac-sha256$"
WEBMENTION_STATUS_TOKEN_LENGTH = 48


def _hash_token_key(raw_key):
    digest = hmac.new(
        str(settings.SECRET_KEY).encode("utf-8"),
        raw_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{TOKEN_KEY_HASH_PREFIX}{digest}"


def hash_existing_token_keys(apps, schema_editor):
    Token = apps.get_model("indieweb", "Token")
    for token in Token.objects.all().only("pk", "key"):
        if token.key.startswith(TOKEN_KEY_HASH_PREFIX):
            continue
        token.key = _hash_token_key(token.key)
        token.save(update_fields=["key"])


def assign_webmention_status_tokens(apps, schema_editor):
    Webmention = apps.get_model("indieweb", "Webmention")
    used_tokens = set(Webmention.objects.exclude(status_token="").values_list("status_token", flat=True))
    for webmention in Webmention.objects.filter(status_token="").only("pk", "status_token"):
        while True:
            status_token = get_random_string(length=WEBMENTION_STATUS_TOKEN_LENGTH)
            if status_token not in used_tokens:
                used_tokens.add(status_token)
                break
        webmention.status_token = status_token
        webmention.save(update_fields=["status_token"])


class Migration(migrations.Migration):
    dependencies = [
        ("indieweb", "0019_webmentionoutboundtarget_consecutive_failures_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="token",
            name="key",
            field=models.CharField(max_length=80, unique=True),
        ),
        migrations.AddField(
            model_name="webmention",
            name="status_token",
            field=models.CharField(blank=True, db_index=True, default="", max_length=48),
            preserve_default=False,
        ),
        migrations.RunPython(hash_existing_token_keys, migrations.RunPython.noop),
        migrations.RunPython(assign_webmention_status_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="webmention",
            name="status_token",
            field=models.CharField(
                db_index=True,
                default=indieweb.models.generate_webmention_status_token,
                max_length=48,
                unique=True,
            ),
        ),
    ]
