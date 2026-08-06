"""Detect videos whose cover images are shared with OTHER videos.

When the CMS uploaded two different videos using files with the same original
name (e.g. cover.jpg), the old storage config could overwrite the shared
object-storage key — leaving both Video rows pointing at the SAME file.
Editing one video's cover then visibly changes the other video's cover too.

This command lists those videos (grouped by shared key) so covers can be
re-uploaded, and with --clear it nulls the duplicated cover fields on the
"extra" videos (keeping the first video that references each key).

Usage:
    python manage.py detect_duplicate_covers            # report only
    python manage.py detect_duplicate_covers --clear    # also null the extras
"""

from django.core.management.base import BaseCommand
from apps.streaming.models import Video

COVER_FIELDS = [
    "thumbnail",
    "tv_poster",
    "tv_landscape",
    "tv_square",
    "portrait_cover",
]


class Command(BaseCommand):
    help = "Find videos that share the same cover storage key with another video."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Null out the duplicated cover field on the non-first video rows.",
        )

    def handle(self, *args, **options):
        clear = options["clear"]
        total_dupes = 0
        total_cleared = 0

        # Only inspect fields that exist on the current schema (dev DBs may be
        # older than production and lack e.g. portrait_cover).
        existing_fields = {f.name for f in Video._meta.fields}

        for field in COVER_FIELDS:
            if field not in existing_fields:
                self.stdout.write(f"[{field}] column not present, skipping.")
                continue

            # Videos that have this cover set, oldest first. Wrap in try/except
            # so a dev DB missing a column (e.g. no portrait_cover) is skipped
            # instead of crashing the whole command.
            try:
                rows = list(
                    Video.objects.exclude(**{f"{field}__isnull": True})
                    .exclude(**{f"{field}": ""})
                    .order_by("id")
                    .values_list("id", "title", field)
                )
            except Exception as exc:  # noqa: BLE001 - column may not exist
                self.stdout.write(f"[{field}] query failed ({exc}), skipping.")
                continue

            # Group by storage key (field value).
            by_key = {}
            for vid, title, key in rows:
                by_key.setdefault(key, []).append((vid, title))

            for key, videos in by_key.items():
                if len(videos) < 2:
                    continue
                total_dupes += len(videos) - 1
                keeper, *extras = videos
                self.stdout.write(
                    self.style.WARNING(
                        f"\n[{field}] key='{key}' shared by {len(videos)} videos:"
                    )
                )
                self.stdout.write(f"  keep : id={keeper[0]} '{keeper[1]}'")
                for vid, title in extras:
                    self.stdout.write(f"  dupe : id={vid} '{title}'")
                    if clear:
                        Video.objects.filter(id=vid).update(**{field: None})
                        total_cleared += 1
                        self.stdout.write(f"         -> {field} cleared on id={vid}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Duplicate cover references: {total_dupes} "
                f"(cleared: {total_cleared})."
            )
        )
