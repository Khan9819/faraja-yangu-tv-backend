"""
One-off cleanup for accumulated/stale device rows.

Every time a Firebase FCM token rotates (periodic refresh, app re-install,
factory reset) the old Devices row was left active, so a user could receive
several push notifications for a single video (one per row).

This command deactivates all but the single most recent Devices row per
fcm_token AND per device_id, mirroring the dedup that sync_user_device now
enforces going forward. It is idempotent and safe to run multiple times.

Run on the server:
    python3.12 manage.py cleanup_devices
"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.authentication.models import Devices


class Command(BaseCommand):
    help = "Deactivate duplicate/stale device rows (one active row per device_id and per fcm_token)."

    def handle(self, *args, **options):
        total = Devices.objects.count()
        deactivated = 0

        # 1) Keep only the most recent row per fcm_token.
        seen_tokens = set()
        for device in Devices.objects.order_by('-updated_at').only('id', 'fcm_token'):
            token = (device.fcm_token or '').strip()
            if token in seen_tokens:
                Devices.objects.filter(id=device.id).update(is_active=False)
                deactivated += 1
            elif token:
                seen_tokens.add(token)

        # 2) Keep only the most recent row per device_id.
        seen_ids = set()
        for device in Devices.objects.order_by('-updated_at').only('id', 'device_id'):
            did = (device.device_id or '').strip()
            if did and did in seen_ids:
                Devices.objects.filter(id=device.id).update(is_active=False)
                deactivated += 1
            elif did:
                seen_ids.add(did)

        self.stdout.write(
            self.style.SUCCESS(
                f"cleanup_devices: checked {total} rows, deactivated {deactivated} duplicates. "
                f"Active rows now: {Devices.objects.filter(is_active=True).count()}."
            )
        )
