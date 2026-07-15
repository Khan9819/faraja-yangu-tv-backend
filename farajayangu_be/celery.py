from __future__ import absolute_import, unicode_literals
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'farajayangu_be.settings.base')
app = Celery('farajayangu_be')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Define task routing - separate queues for video processing and general tasks
app.conf.task_routes = {
    'apps.streaming.tasks.tasks.assemble_chunks_task': {'queue': 'video_processing'},
    'apps.streaming.tasks.tasks.convert_video_to_hls': {'queue': 'video_processing'},
    'apps.streaming.tasks.tasks.import_video_from_google_drive': {'queue': 'video_processing'},
    'apps.streaming.tasks.tasks.cleanup_stale_chunks': {'queue': 'general'},
    'apps.streaming.tasks.conversion_monitor.mark_stale_conversions': {'queue': 'general'},
    'apps.authentication.tasks.main.*': {'queue': 'general'},
    'apps.authentication.tasks.main.sync_user_device': {'queue': 'general'},
    'apps.streaming.tasks.tasks.send_push_notification': {'queue': 'general'},
}

# Default queue for tasks not explicitly routed
app.conf.task_default_queue = 'general'

app.conf.beat_schedule = {
    'cleanup-stale-chunks-midnight': {
        'task': 'apps.streaming.tasks.tasks.cleanup_stale_chunks',
        'schedule': crontab(hour=0, minute=0),  # Run at midnight
    },
    'check-stale-conversions': {
        'task': 'apps.streaming.tasks.conversion_monitor.mark_stale_conversions',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
}
