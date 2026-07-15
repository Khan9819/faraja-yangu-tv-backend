"""
Signal handlers for cache invalidation in management app.
Invalidates dashboard cache when relevant data changes.
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from django.utils import timezone
from apps.streaming.models import View, Like, Comment
from apps.authentication.models import User, Devices
from apps.advertising.models import Ad
from apps.analytics.models import Report, Notification, Analytics
import logging

logger = logging.getLogger(__name__)


def invalidate_dashboard_cache():
    """
    Helper function to invalidate dashboard summary cache.
    Clears cache for current date.
    """
    try:
        today = timezone.localdate()
        cache_key = f"dashboard_summary:{today.isoformat()}"
        cache.delete(cache_key)
        logger.info(f"Invalidated dashboard cache for {today.isoformat()}")
    except Exception as e:
        logger.error(f"Error invalidating dashboard cache: {e}")


# User-related signals
@receiver(post_save, sender=User)
def invalidate_dashboard_on_user_change(sender, instance, created, **kwargs):
    """Invalidate dashboard when users are created or updated."""
    if created:  # Only invalidate on new user registration
        invalidate_dashboard_cache()


@receiver(post_delete, sender=User)
def invalidate_dashboard_on_user_delete(sender, instance, **kwargs):
    """Invalidate dashboard when users are deleted."""
    invalidate_dashboard_cache()


# View-related signals
@receiver(post_save, sender=View)
def invalidate_dashboard_on_view_create(sender, instance, created, **kwargs):
    """Invalidate dashboard when new views are recorded."""
    if created:
        invalidate_dashboard_cache()


@receiver(post_delete, sender=View)
def invalidate_dashboard_on_view_delete(sender, instance, **kwargs):
    """Invalidate dashboard when views are deleted."""
    invalidate_dashboard_cache()


# Like-related signals
@receiver(post_save, sender=Like)
def invalidate_dashboard_on_like_create(sender, instance, created, **kwargs):
    """Invalidate dashboard when likes are created."""
    if created:
        invalidate_dashboard_cache()


@receiver(post_delete, sender=Like)
def invalidate_dashboard_on_like_delete(sender, instance, **kwargs):
    """Invalidate dashboard when likes are deleted."""
    invalidate_dashboard_cache()


# Comment-related signals
@receiver(post_save, sender=Comment)
def invalidate_dashboard_on_comment_create(sender, instance, created, **kwargs):
    """Invalidate dashboard when comments are created."""
    if created:
        invalidate_dashboard_cache()


@receiver(post_delete, sender=Comment)
def invalidate_dashboard_on_comment_delete(sender, instance, **kwargs):
    """Invalidate dashboard when comments are deleted."""
    invalidate_dashboard_cache()


# Ad-related signals
@receiver(post_save, sender=Ad)
def invalidate_dashboard_on_ad_change(sender, instance, created, **kwargs):
    """Invalidate dashboard when ads are created or updated."""
    invalidate_dashboard_cache()


@receiver(post_delete, sender=Ad)
def invalidate_dashboard_on_ad_delete(sender, instance, **kwargs):
    """Invalidate dashboard when ads are deleted."""
    invalidate_dashboard_cache()


# Report-related signals
@receiver(post_save, sender=Report)
def invalidate_dashboard_on_report_change(sender, instance, created, **kwargs):
    """Invalidate dashboard when reports are created or updated."""
    invalidate_dashboard_cache()


@receiver(post_delete, sender=Report)
def invalidate_dashboard_on_report_delete(sender, instance, **kwargs):
    """Invalidate dashboard when reports are deleted."""
    invalidate_dashboard_cache()


# Notification-related signals
@receiver(post_save, sender=Notification)
def invalidate_dashboard_on_notification_create(sender, instance, created, **kwargs):
    """Invalidate dashboard when notifications are created."""
    if created:
        invalidate_dashboard_cache()


@receiver(post_delete, sender=Notification)
def invalidate_dashboard_on_notification_delete(sender, instance, **kwargs):
    """Invalidate dashboard when notifications are deleted."""
    invalidate_dashboard_cache()


# Device-related signals
@receiver(post_save, sender=Devices)
def invalidate_dashboard_on_device_change(sender, instance, created, **kwargs):
    """Invalidate dashboard when devices are created or updated."""
    invalidate_dashboard_cache()


@receiver(post_delete, sender=Devices)
def invalidate_dashboard_on_device_delete(sender, instance, **kwargs):
    """Invalidate dashboard when devices are deleted."""
    invalidate_dashboard_cache()
