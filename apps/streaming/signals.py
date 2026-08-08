"""
Signal handlers for cache invalidation in streaming app.
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from apps.streaming.models import Video, Category
import logging

logger = logging.getLogger(__name__)

WEBSITE_VIDEOS_CACHE_KEY = 'videos_by_category:website'


def _invalidate_website_videos_cache():
    """Invalidate the public website videos-by-category cache.

    Called whenever video/category state changes that affect what the
    website should show (new upload, publish/unpublish, HLS completion,
    delete, category rename/reorder).
    """
    try:
        cache.delete(WEBSITE_VIDEOS_CACHE_KEY)
    except Exception:
        logger.exception('Failed to invalidate website videos cache')


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
            # New content becomes watchable the moment HLS conversion completes
            # (that's when it actually exists on R2) — the website list MUST
            # refresh so fresh uploads appear without a manual cache flush.
            # New content becomes watchable the moment HLS conversion completes
            # (that's when it actually exists on R2). Invalidate on either the
            # processing_status transition OR the hls_master_playlist save, so
            # fresh uploads appear without a manual cache flush.
            is_completed = instance.processing_status == 'completed'
            has_hls = bool(instance.hls_master_playlist)
            if (('processing_status' in updated_field_set and is_completed) or
                    ('hls_master_playlist' in updated_field_set and has_hls)):
                _invalidate_website_videos_cache()
                logger.info(f"Invalidated website videos cache for completed video {instance.id}")
            return
    
    # Invalidate cache for admin-initiated updates or new creations
    try:
        # Clear all feed cache pages since we can't know which pages are affected
        for page in range(1, 11):  # Clear first 10 pages
            for page_size in [10, 20, 30, 50]:
                cache_key = f"feed:page:{page}:size:{page_size}"
                cache.delete(cache_key)
        
        # The website list also depends on publish state and video metadata.
        _invalidate_website_videos_cache()
        
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
        
        _invalidate_website_videos_cache()
        
        logger.info(f"Invalidated feed cache for deleted video {instance.id}")
    except Exception as e:
        logger.error(f"Error invalidating feed cache on delete: {e}")


@receiver(post_save, sender=Category)
def invalidate_website_cache_on_category_save(sender, instance, **kwargs):
    """Category rename/reorder changes how the website groups videos."""
    _invalidate_website_videos_cache()


@receiver(post_delete, sender=Category)
def invalidate_website_cache_on_category_delete(sender, instance, **kwargs):
    """Deleting a category removes its video group from the website."""
    _invalidate_website_videos_cache()
