"""
Signal handlers for cache invalidation in advertising app.
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from apps.advertising.models import Ad
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Ad)
def invalidate_carousel_ads_cache_on_save(sender, instance, created, **kwargs):
    """
    Invalidate carousel ads cache when an ad is created or updated.
    Clears cache for all ad_render_type variations.
    """
    try:
        # Clear cache for all possible ad_render_type values
        cache.delete("carousel_ads:")  # No filter
        cache.delete("carousel_ads:CUSTOM")
        cache.delete("carousel_ads:GOOGLE")
        
        logger.info(f"Invalidated carousel ads cache for ad {instance.id} (created={created})")
    except Exception as e:
        logger.error(f"Error invalidating carousel ads cache: {e}")


@receiver(post_delete, sender=Ad)
def invalidate_carousel_ads_cache_on_delete(sender, instance, **kwargs):
    """
    Invalidate carousel ads cache when an ad is deleted.
    """
    try:
        # Clear cache for all possible ad_render_type values
        cache.delete("carousel_ads:")
        cache.delete("carousel_ads:CUSTOM")
        cache.delete("carousel_ads:GOOGLE")
        
        logger.info(f"Invalidated carousel ads cache for deleted ad {instance.id}")
    except Exception as e:
        logger.error(f"Error invalidating carousel ads cache on delete: {e}")
