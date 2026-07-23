"""
Conversion job publisher for the C++ video conversion microservice.

Builds the job payload and publishes it to the conversion queue.
Django remains the source of truth — the microservice is a stateless worker.
"""
import json
import logging
import multiprocessing
import uuid

from django.conf import settings
from django.utils import timezone

from apps.streaming.models import Video
from apps.streaming.services.queue_backend import get_queue_backend
from apps.streaming.services.video_presets import get_enabled_hls_variants

logger = logging.getLogger(__name__)


def _is_local_path(path: str) -> bool:
    """Check if a path is a local filesystem path vs a remote R2/S3 key."""
    if not path:
        return False
    # Local paths start with / (unix) or a drive letter (Windows)
    return path.startswith('/') or (len(path) > 1 and path[1] == ':')

def build_conversion_job(video: Video, source_key: str | None = None) -> dict:
    source_key = source_key or (video.video.name if video.video else None)
    if not source_key:
        raise ValueError(f"No source video file for video {video.id}")

    is_local = _is_local_path(source_key)

    job_id = str(uuid.uuid4())

    source = {
        "key": source_key,
    }
    if is_local:
        source["type"] = "local"
    else:
        source["type"] = "r2"
        source["bucket"] = settings.AWS_STORAGE_BUCKET_NAME
        source["endpoint"] = settings.AWS_S3_ENDPOINT_URL

    return {
        "job_id": job_id,
        "video_id": video.id,
        "video_uid": str(video.uid),
        "source": source,
        "output": {
            "bucket": settings.AWS_STORAGE_BUCKET_NAME,
            "base_path": f"videos/hls/{video.slug or video.uid}",
            "endpoint": settings.AWS_S3_ENDPOINT_URL,
        },
        "variants": get_enabled_hls_variants(),
        "options": {
            "segment_duration": getattr(settings, 'HLS_SEGMENT_DURATION', 6),
            "encoder_preset": getattr(settings, 'HLS_ENCODER_PRESET', 'superfast'),
            "skip_upscaling": getattr(settings, 'HLS_SKIP_UPSCALING', True),
            "threads": getattr(settings, 'HLS_FFMPEG_THREADS', multiprocessing.cpu_count()),
            "prefer_hardware": True,
        },
        "checkpoint": video.processing_checkpoint or {},
    }


def publish_conversion_job(video: Video, source_key: str | None = None) -> str:
    job = build_conversion_job(video, source_key=source_key)

    queue = get_queue_backend()
    try:
        queue.publish("conversion_jobs", job)
    except Exception as e:
        logger.error(
            "conversion_job_publish_failed",
            extra={"video_id": video.id, "error": str(e)},
        )
        raise

    Video.objects.filter(id=video.id).update(
        conversion_job_id=job["job_id"],
        processing_backend="cpp",
        processing_status="processing",
        processing_stage="queued",
        processing_progress=0,
        processing_message="Queued for C++ conversion",
        queued_at=timezone.now(),
        last_event_received_at=timezone.now(),
    )

    logger.info(
        "conversion_job_published",
        extra={
            "video_id": video.id,
            "job_id": job["job_id"],
            "processing_backend": "cpp",
        },
    )
    return job["job_id"]


def trigger_video_processing(video: Video, source_key: str | None = None):
    """
    Single entry point for all ingestion paths to trigger video conversion.
    Routes to C++ microservice or legacy Python path based on feature flag.
    """
    if getattr(settings, 'USE_CPP_CONVERSION_SERVICE', False):
        return publish_conversion_job(video, source_key=source_key)

    from apps.streaming.tasks.tasks import convert_video_to_hls
    return convert_video_to_hls.delay(video.id, source_key)
