# Generated for django-indieweb on 2026-05-08
#
# Adds a bounded per-subscription history of recent accepted WebSub delivery digests.
# Forward-only: existing rows initialize to an empty list. The single-row
# ``last_accepted_delivery_*`` fields stay for backwards-compatible diagnostics.

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("indieweb", "0021_encrypt_websub_secrets"),
    ]

    operations = [
        migrations.AddField(
            model_name="websubsubscription",
            name="recent_accepted_delivery_digests",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
