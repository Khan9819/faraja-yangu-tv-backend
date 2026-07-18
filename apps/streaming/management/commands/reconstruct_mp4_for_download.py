import os
import subprocess
import tempfile

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from apps.streaming.models import Video


class Command(BaseCommand):
    help = 'Reconstruct MP4 from existing HLS segments for direct download support'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Limit number of videos to process (0 = all)',
        )
        parser.add_argument(
            '--uid',
            type=str,
            default=None,
            help='Process a specific video by UID',
        )
        parser.add_argument(
            '--timeout',
            type=int,
            default=3600,
            help='FFmpeg timeout in seconds per video (default: 3600)',
        )

    def handle(self, *args, **kwargs):
        limit = kwargs['limit']
        specific_uid = kwargs['uid']
        ffmpeg_timeout = kwargs['timeout']

        if specific_uid:
            videos = Video.objects.filter(uid=specific_uid, processing_status='completed')
        else:
            videos = Video.objects.filter(
                processing_status='completed',
                download_path__isnull=True,
                hls_path__isnull=False,
            )

        if limit > 0:
            videos = videos[:limit]

        total = videos.count() if hasattr(videos, 'count') else len(videos)
        if total == 0:
            self.stdout.write(self.style.WARNING('No videos found needing MP4 reconstruction.'))
            return

        self.stdout.write(f'Found {total} videos to reconstruct.')

        success_count = 0
        fail_count = 0

        for video in videos:
            self.stdout.write(f'Processing: {video.uid} - {video.title}')

            backend_url = getattr(settings, 'BACKEND_URL', 'https://backend.farajayangutv.co.tz')
            playlist_url = f'{backend_url}/streaming/hls/{video.uid}/master.m3u8'

            output_path = None
            try:
                fd, output_path = tempfile.mkstemp(suffix='.mp4')
                os.close(fd)

                cmd = [
                    'ffmpeg', '-y',
                    '-i', playlist_url,
                    '-c', 'copy',
                    '-bsf:a', 'aac_adtstoasc',
                    '-movflags', '+faststart',
                    '-reconnect', '1',
                    '-reconnect_at_eof', '1',
                    '-reconnect_streamed', '1',
                    '-reconnect_delay_max', '30',
                    '-timeout', '0',
                    output_path,
                ]

                self.stdout.write(f'  Running: ffmpeg -i {playlist_url} ...')
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=ffmpeg_timeout,
                )

                if result.returncode != 0:
                    self.stdout.write(self.style.ERROR(
                        f'  FFmpeg failed for {video.uid}:\n{result.stderr[-500:]}'
                    ))
                    fail_count += 1
                    continue

                if not os.path.exists(output_path) or os.path.getsize(output_path) < 10000:
                    self.stdout.write(self.style.ERROR(f'  Output file missing or too small for {video.uid}'))
                    fail_count += 1
                    continue

                r2_path = f'videos/downloads/{video.uid}/original.mp4'
                with open(output_path, 'rb') as mp4_file:
                    default_storage.save(r2_path, mp4_file)

                video.download_path = r2_path
                video.save(update_fields=['download_path'])

                file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                self.stdout.write(self.style.SUCCESS(
                    f'  Done: {video.uid} → {r2_path} ({file_size_mb:.1f} MB)'
                ))
                success_count += 1

            except subprocess.TimeoutExpired:
                self.stdout.write(self.style.ERROR(f'  Timeout: {video.uid}'))
                fail_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  Error: {video.uid} - {e}'))
                fail_count += 1
            finally:
                if output_path and os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except OSError:
                        pass

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Complete: {success_count} succeeded, {fail_count} failed, {total} total'
        ))
