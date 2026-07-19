"""
Utility functions for sending WebSocket progress updates from Celery tasks.
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
import logging

logger = logging.getLogger(__name__)


def update_video_progress_db(video_id: int, stage: str, progress: int, message: str, 
                              status: str = None, checkpoint: dict = None):
    """
    Persist progress state to database for resume capability and late-joining clients.
    
    Args:
        video_id: The video ID
        stage: Current processing stage
        progress: Progress percentage (0-100)
        message: Human-readable progress message
        status: Optional status update (processing, completed, failed)
        checkpoint: Optional checkpoint data for resume
    """
    try:
        from apps.streaming.models import Video
        
        update_fields = ['processing_stage', 'processing_progress', 'processing_message']
        video = Video.objects.get(id=video_id)
        video.processing_stage = stage
        video.processing_progress = progress
        video.processing_message = message
        
        if status:
            video.processing_status = status
            update_fields.append('processing_status')
        
        if checkpoint is not None:
            video.processing_checkpoint = checkpoint
            update_fields.append('processing_checkpoint')
        
        video.save(update_fields=update_fields)
        logger.debug(f"Updated DB progress for video {video_id}: {stage} - {progress}%")
    except Exception as e:
        logger.warning(f"Could not update DB progress for video {video_id}: {str(e)}")


def get_video_progress(video_id: int) -> dict:
    """
    Get current progress state from database.
    
    Args:
        video_id: The video ID
        
    Returns:
        Dictionary with current progress state
    """
    try:
        from apps.streaming.models import Video
        video = Video.objects.get(id=video_id)
        return {
            'video_id': video_id,
            'stage': video.processing_stage,
            'progress': video.processing_progress,
            'message': video.processing_message or '',
            'status': video.processing_status,
            'hls_path': video.hls_path,
        }
    except Exception as e:
        logger.warning(f"Could not get progress for video {video_id}: {str(e)}")
        return None


def send_video_progress(
    video_id: int, 
    stage: str, 
    progress: int, 
    message: str, 
    status: str = "processing", 
    checkpoint: dict = None, 
    persist: bool = True,
    variants_progress: dict = None
):
    """
    Send a progress update to all WebSocket clients listening for this video.
    Also persists to database for late-joining clients and resume capability.
    
    Args:
        video_id: The video ID
        stage: Current processing stage (e.g., 'assembling', 'converting', 'uploading')
        progress: Progress percentage (0-100)
        message: Human-readable progress message
        status: Status string (processing, completed, failed)
        checkpoint: Optional checkpoint data for resume on retry
        persist: Whether to persist progress to database (default True)
        variants_progress: Optional dict of per-variant progress for HLS conversion
                          Format: {'1080p': {'status': 'processing', 'progress': 45, 'message': '...'}, ...}
    """
    # Persist to database for late-joining clients and resume
    if persist:
        update_video_progress_db(video_id, stage, progress, message, status, checkpoint)
    
    try:
        channel_layer = get_channel_layer()
        group_name = f"video_progress_{video_id}"
        
        payload = {
            "type": "video_progress",
            "video_id": video_id,
            "stage": stage,
            "progress": progress,
            "message": message,
            "status": status
        }
        
        # Include per-variant progress if provided
        if variants_progress:
            payload["variants"] = _serialize_variants_progress(variants_progress)
        
        async_to_sync(channel_layer.group_send)(group_name, payload)
        logger.debug(f"Sent progress update for video {video_id}: {stage} - {progress}%")
    except Exception as e:
        logger.warning(f"Could not send progress update for video {video_id}: {str(e)}")


def _serialize_variants_progress(variants_progress: dict) -> dict:
    """
    Serialize variant progress objects to JSON-compatible dict.
    
    Args:
        variants_progress: Dict of variant name to VariantProgress dataclass or dict
        
    Returns:
        JSON-serializable dict
    """
    result = {}
    for name, vp in variants_progress.items():
        if hasattr(vp, '__dict__'):
            # It's a dataclass or object
            result[name] = {
                'name': getattr(vp, 'name', name),
                'status': getattr(vp, 'status', 'pending'),
                'progress': getattr(vp, 'progress', 0),
                'message': getattr(vp, 'message', '')
            }
        elif isinstance(vp, dict):
            result[name] = vp
        else:
            result[name] = {'name': name, 'status': 'unknown', 'progress': 0, 'message': ''}
    return result


def send_video_complete(video_id: int, message: str = "Video processing completed", hls_path: str = None):
    """
    Send a completion notification to all WebSocket clients listening for this video.
    
    Args:
        video_id: The video ID
        message: Completion message
        hls_path: Path to the HLS files
    """
    try:
        channel_layer = get_channel_layer()
        group_name = f"video_progress_{video_id}"
        
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "video_complete",
                "video_id": video_id,
                "message": message,
                "hls_path": hls_path
            }
        )
        logger.info(f"Sent completion notification for video {video_id}")
    except Exception as e:
        logger.warning(f"Could not send completion notification for video {video_id}: {str(e)}")


def send_video_error(video_id: int, message: str, error: str = None):
    """
    Send an error notification to all WebSocket clients listening for this video.
    
    Args:
        video_id: The video ID
        message: Error message
        error: Detailed error string
    """
    try:
        channel_layer = get_channel_layer()
        group_name = f"video_progress_{video_id}"
        
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "video_error",
                "video_id": video_id,
                "message": message,
                "error": error
            }
        )
        logger.info(f"Sent error notification for video {video_id}: {message}")
    except Exception as e:
        logger.warning(f"Could not send error notification for video {video_id}: {str(e)}")


def send_upload_progress(video_id: int, completed_chunks: int, total_chunks: int, message: str = None):
    """
    Send upload progress update to all WebSocket clients listening for this video.
    Also updates database for persistence.
    
    Args:
        video_id: The video ID
        completed_chunks: Number of chunks uploaded so far
        total_chunks: Total number of chunks
        message: Optional custom message
    """
    try:
        # Calculate progress percentage
        upload_progress = int((completed_chunks / total_chunks) * 100) if total_chunks > 0 else 0
        
        # Update database
        from apps.streaming.models import Video
        video = Video.objects.get(id=video_id)
        video.upload_completed_chunks = completed_chunks
        video.upload_total_chunks = total_chunks
        video.upload_progress = upload_progress
        video.save(update_fields=['upload_completed_chunks', 'upload_total_chunks', 'upload_progress'])
        
        # Send WebSocket update
        channel_layer = get_channel_layer()
        group_name = f"video_progress_{video_id}"
        
        default_message = f"Uploading: {completed_chunks}/{total_chunks} chunks"
        
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "upload_progress",
                "video_id": video_id,
                "upload_progress": upload_progress,
                "completed_chunks": completed_chunks,
                "total_chunks": total_chunks,
                "message": message or default_message,
                "is_complete": completed_chunks >= total_chunks
            }
        )
        logger.debug(f"Sent upload progress for video {video_id}: {completed_chunks}/{total_chunks} ({upload_progress}%)")
    except Exception as e:
        logger.warning(f"Could not send upload progress for video {video_id}: {str(e)}")
