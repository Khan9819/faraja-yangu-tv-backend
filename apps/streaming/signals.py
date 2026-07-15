"""
Signal handlers for cache invalidation in streaming app.
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from apps.streaming.models import Video
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Video)
def invalidate_feed_cache_on_video_save(sender, instance, created, **kwargs):
    """
    Invalidate feed cache when a video is created or updated by admin.
    Does NOT invalidate during automated processing (conversion, assembly, etc.).
    Only invalidates on admin-initiated changes or when video is published.
    """
    # Get update_fields from kwargs to check what was updated
    update_fields = kwargs.get('update_fields', None)
    
    # Define processing-related fields that should NOT trigger cache invalidation
    processing_fields = {
        'processing_status', 'processing_error', 'processing_stage',
        'processing_progress', 'processing_message', 'processing_checkpoint',
        'upload_progress', 'upload_total_chunks', 'upload_completed_chunks',
        'hls_master_playlist', 'hls_path', 'duration', 'video'
    }
    
    # Skip cache invalidation if:
    # 1. Only processing-related fields were updated (automated processing)
    # 2. Not a new creation
    if update_fields is not None and not created:
        # Check if only processing fields were updated
        updated_field_set = set(update_fields)
        if updated_field_set.issubset(processing_fields):
            logger.debug(f"Skipping cache invalidation for video {instance.id} - automated processing update")
            return
    
    # Invalidate cache for admin-initiated updates or new creations
    try:
        # Clear all feed cache pages since we can't know which pages are affected
        for page in range(1, 11):  # Clear first 10 pages
            for page_size in [10, 20, 30, 50]:
                cache_key = f"feed:page:{page}:size:{page_size}"
                cache.delete(cache_key)
        
        logger.info(f"Invalidated feed cache for video {instance.id} (created={created}, admin_update=True)")
    except Exception as e:
        logger.error(f"Error invalidating feed cache: {e}")


@receiver(post_delete, sender=Video)
def invalidate_feed_cache_on_video_delete(sender, instance, **kwargs):
    """
    Invalidate feed cache when a video is deleted.
    """
    try:
        # Clear all feed cache pages
        for page in range(1, 11):  # Clear first 10 pages
            for page_size in [10, 20, 30, 50]:
                cache_key = f"feed:page:{page}:size:{page_size}"
                cache.delete(cache_key)
        
        logger.info(f"Invalidated feed cache for deleted video {instance.id}")
    except Exception as e:
        logger.error(f"Error invalidating feed cache on delete: {e}")
