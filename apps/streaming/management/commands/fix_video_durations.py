"""
Management command to fix video durations that are 0 or None.
Run on production after deploying the duration extraction fix.

Usage:
    python manage.py fix_video_durations
    python manage.py fix_video_durations --dry-run
"""
from django.core.management.base import BaseCommand
from apps.streaming.tasks.tasks import fix_video_durations


class Command(BaseCommand):
    help = 'Fix videos with duration=0 or None by extracting from ffprobe/HLS'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only show what would be fixed without making changes',
        )

    def handle(self, *args, **options):
        if options['dry_run']:
            from apps.streaming.models import Video
            from datetime import timedelta
            videos = Video.objects.filter(
                processing_status='completed',
                hls_master_playlist__isnull=False,
            ).filter(
                duration__isnull=True,
            ) | Video.objects.filter(
                processing_status='completed',
                hls_master_playlist__isnull=False,
                duration=timedelta(0),
            )
            video_ids = set(v.id for v in videos)
            self.stdout.write(
                self.style.WARNING(
                    f'DRY RUN: {len(video_ids)} videos would be fixed'
                )
            )
            for vid in Video.objects.filter(id__in=video_ids):
                self.stdout.write(f'  - {vid.uid} | {vid.title} | duration={vid.duration}')
            return

        self.stdout.write('Running fix_video_durations...')
        result = fix_video_durations()
        self.stdout.write(
            self.style.SUCCESS(
                f'Done! Fixed {result["fixed"]}/{result["total"]} videos'
            )
        )
