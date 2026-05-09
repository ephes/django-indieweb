# Generated for django-indieweb on 2026-05-09
#
# Drops the now-vestigial ``WebSubSubscription.recent_accepted_delivery_digests``
# JSON field. Replay detection is authoritative through
# ``WebSubAcceptedDelivery`` rows written atomically by
# :func:`accept_websub_delivery`; the JSON column is no longer read or
# written.

from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("indieweb", "0025_websubaccepteddelivery"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="websubsubscription",
            name="recent_accepted_delivery_digests",
        ),
    ]
