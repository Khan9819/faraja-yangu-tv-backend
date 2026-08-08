"""
Event handler for conversion microservice events.
Receives progress/heartbeat/complete/error events from the C++ service
and updates the Video model + forwards WebSocket notifications.

All handlers are idempotent — duplicates and out-of-order events are safe.
"""
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.streaming.models import Video
from apps.streaming.socket.utils import send_video_progress, send_video_complete, send_video_error

logger = logging.getLogger(__name__)


EVENT_SERIALIZERS = {
    "heartbeat": "ConversionHeartbeatEventSerializer",
    "progress": "ConversionProgressEventSerializer",
    "complete": "ConversionCompleteEventSerializer",
    "error": "ConversionErrorEventSerializer",
}


def _validate_event(msg: dict) -> bool:
    from apps.streaming.serializers.conversion_messages import (
        ConversionHeartbeatEventSerializer,
        ConversionProgressEventSerializer,
        ConversionCompleteEventSerializer,
        ConversionErrorEventSerializer,
    )
    serializer_map = {
        "heartbeat": ConversionHeartbeatEventSerializer,
        "progress": ConversionProgressEventSerializer,
        "complete": ConversionCompleteEventSerializer,
        "error": ConversionErrorEventSerializer,
    }
    event_type = msg.get("type")
    serializer_cls = serializer_map.get(event_type)
    if not serializer_cls:
        logger.warning("conversion_event_unknown_type", extra={"type": event_type})
        return False

    serializer = serializer_cls(data=msg)
    if not serializer.is_valid():
        logger.warning(
            "conversion_event_validation_failed",
            extra={"type": event_type, "errors": serializer.errors},
        )
        return False
    return True


def handle_event(msg: dict) -> None:
    if not _validate_event(msg):
        return

    video_id = msg.get("video_id")
    job_id = msg.get("job_id")
    event_type = msg.get("type")

    video = Video.objects.filter(id=video_id).first()
    if not video:
        logger.warning("conversion_event_video_not_found", extra={"video_id": video_id, "job_id": job_id})
        return

    # Ignore stale events from old jobs
    if video.conversion_job_id and str(video.conversion_job_id) != str(job_id):
        logger.info(
            "conversion_event_stale_job_ignored",
            extra={"video_id": video_id, "job_id": job_id, "current_job_id": str(video.conversion_job_id)},
        )
        return

    # Ignore events for already completed videos (idempotency)
    if video.processing_status == "completed" and event_type != "complete":
        return

    if event_type == "heartbeat":
        _handle_heartbeat(video)
    elif event_type == "progress":
        _handle_progress(video, msg)
    elif event_type == "complete":
        _handle_complete(video, msg)
    elif event_type == "error":
        _handle_error(video, msg)


def _handle_heartbeat(video: Video) -> None:
    now = timezone.now()
    Video.objects.filter(id=video.id).update(
        last_processing_heartbeat_at=now,
        last_event_received_at=now,
    )


def _handle_progress(video: Video, msg: dict) -> None:
    now = timezone.now()
    # Monotonic floor — never let the C++ raw progress (0-100) move the
    # displayed percentage backwards within the same run (stage transitions
    # used to restart the number, e.g. 72% -> 33%). A new job resets the
    # floor when publish_conversion_job writes processing_progress=0.
    new_progress = msg.get("progress") or 0
    current_progress = video.processing_progress or 0
    if new_progress < current_progress:
        new_progress = current_progress
    update_fields = {
        "processing_status": "processing",
        "processing_stage": msg.get("stage") or "processing",
        "processing_progress": new_progress,
        "processing_message": msg.get("message") or "Processing",
        "last_event_received_at": now,
        "last_processing_heartbeat_at": now,
    }

    checkpoint = msg.get("checkpoint")
    if checkpoint:
        update_fields["processing_checkpoint"] = checkpoint

    # Set processing_started_at on first progress event
    if not video.processing_started_at:
        update_fields["processing_started_at"] = now

    Video.objects.filter(id=video.id).update(**update_fields)

    send_video_progress(
        video.id,
        msg.get("stage") or "processing",
        new_progress,
        msg.get("message") or "Processing",
        status="processing",
        variants_progress=msg.get("variants"),
        persist=False,  # Already persisted above
    )


def _handle_complete(video: Video, msg: dict) -> None:
    now = timezone.now()
    update_fields = {
        "processing_status": "completed",
        "processing_stage": "idle",
        "processing_progress": 100,
        "processing_message": "Processing complete",
        "processing_error": None,
        "processing_checkpoint": None,
        "hls_path": msg["hls_path"],
        "hls_master_playlist": msg["master_playlist"],
        "processing_completed_at": now,
        "last_event_received_at": now,
    }

    duration_seconds = msg.get("duration_seconds")
    if duration_seconds:
        update_fields["duration"] = timedelta(seconds=duration_seconds)

    Video.objects.filter(id=video.id).update(**update_fields)

    send_video_complete(video.id, "Video processing completed successfully", msg["hls_path"])

    logger.info(
        "conversion_event_complete",
        extra={"video_id": video.id, "job_id": msg.get("job_id"), "hls_path": msg["hls_path"]},
    )


def _handle_error(video: Video, msg: dict) -> None:
    now = timezone.now()
    Video.objects.filter(id=video.id).update(
        processing_status="failed",
        processing_stage="idle",
        processing_message=msg.get("message") or "Processing failed",
        processing_error=msg.get("error") or "Unknown error",
        processing_failed_at=now,
        last_event_received_at=now,
    )

    send_video_error(video.id, msg.get("message") or "Processing failed", msg.get("error"))

    logger.error(
        "conversion_event_error",
        extra={"video_id": video.id, "job_id": msg.get("job_id"), "error": msg.get("error")},
    )


def listen_forever() -> None:
    """
    Long-running loop that subscribes to conversion events via Redis PubSub.
    Intended to be run as a management command or standalone process.
    """
    from apps.streaming.services.queue_backend import get_queue_backend

    channel = getattr(settings, 'CONVERSION_EVENTS_CHANNEL', 'conversion_events')
    queue = get_queue_backend()
    pubsub = queue.subscribe(f"{channel}:*")

    logger.info(f"Listening for conversion events on {channel}:*")

    for message in pubsub.listen():
        if message["type"] not in ("pmessage",):
            continue
        try:
            data = json.loads(message["data"])
            handle_event(data)
        except json.JSONDecodeError:
            logger.warning("conversion_event_invalid_json", extra={"raw": message.get("data", "")[:200]})
        except Exception:
            logger.exception("conversion_event_handler_error")
