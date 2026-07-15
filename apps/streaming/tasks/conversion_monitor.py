"""
Periodic task to detect stale/stuck C++ conversion jobs and handle retries.
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.streaming.models import Video
from apps.streaming.socket.utils import send_video_error

logger = logging.getLogger(__name__)


@shared_task(queue='general')
def mark_stale_conversions():
    """
    Find C++ conversion jobs that have stopped sending heartbeats and mark them failed.
    Optionally requeue if retry_count < max retries.
    """
    timeout_seconds = getattr(settings, 'CONVERSION_HEARTBEAT_TIMEOUT_SECONDS', 300)
    max_retries = getattr(settings, 'CONVERSION_MAX_RETRIES', 2)
    cutoff = timezone.now() - timedelta(seconds=timeout_seconds)

    stale_qs = Video.objects.filter(
        processing_status='processing',
        processing_backend='cpp',
        last_processing_heartbeat_at__lt=cutoff,
    )

    for video in stale_qs:
        if video.retry_count < max_retries:
            # Requeue
            video.retry_count += 1
            video.processing_status = 'processing'
            video.processing_stage = 'queued'
            video.processing_message = f'Retrying (attempt {video.retry_count + 1})'
            video.save(update_fields=[
                'retry_count', 'processing_status', 'processing_stage', 'processing_message',
            ])

            try:
                from apps.streaming.services.conversion_client import publish_conversion_job
                publish_conversion_job(video)
                logger.info(
                    "conversion_stale_requeued",
                    extra={"video_id": video.id, "retry_count": video.retry_count},
                )
            except Exception as e:
                logger.error(
                    "conversion_stale_requeue_failed",
                    extra={"video_id": video.id, "error": str(e)},
                )
                video.processing_status = 'failed'
                video.processing_error = f'Requeue failed: {e}'
                video.processing_failed_at = timezone.now()
                video.save(update_fields=['processing_status', 'processing_error', 'processing_failed_at'])
                send_video_error(video.id, "Conversion failed after retry", str(e))
        else:
            # Exhausted retries
            video.processing_status = 'failed'
            video.processing_stage = 'idle'
            video.processing_message = 'Conversion worker heartbeat timed out'
            video.processing_error = 'No heartbeat received from conversion service (retries exhausted)'
            video.processing_failed_at = timezone.now()
            video.save(update_fields=[
                'processing_status', 'processing_stage', 'processing_message',
                'processing_error', 'processing_failed_at',
            ])
            send_video_error(video.id, "Conversion timed out", video.processing_error)

            logger.error(
                "conversion_stale_failed",
                extra={"video_id": video.id, "retry_count": video.retry_count},
            )
