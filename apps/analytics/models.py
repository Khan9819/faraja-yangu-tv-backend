from django.db import models
from apps.common.models import TimeStampedModel
from core.base_model import BaseModel

# Create your models here.

class Analytics(BaseModel):
    
    class ANALYTICS_TYPES(models.TextChoices):
        VIDEO = 'VIDEO'
        AD = 'AD'
        
    type = models.CharField(max_length=255, choices=ANALYTICS_TYPES.choices, default=ANALYTICS_TYPES.VIDEO)
    
    def __str__(self):
        return self.type


class WebsiteEvent(BaseModel):
    """Engagement event kutoka kwenye website (farajayangutv.co.tz) na web player.

    Events zinatumwa na JS ya website kwenye POST /api/analytics/website/events/:
      - pageview      (mtumiaji amefungua ukurasa)
      - video_play    (video imeanza kuchezwa)
      - video_pause   (video imesimamishwa)
      - video_end     (video imeisha)
      - watch_seconds (muda wa kutazama, hutumwa kila sekunde ~15)
      - scroll        (scroll depth: 25/50/75/100)
      - click         (kubofya video / kiungo)
      - heartbeat     (ishara ya "niko mtandaoni" — hutumika kuhesabu waliopo sasa)

    Session inahesabiwa kama "online" ikiwa ina heartbeat/pageview ndani ya
    dakika 5 zilizopita — hiyo ndiyo "real-time" ya dashboard.
    """

    class EVENT_TYPES(models.TextChoices):
        PAGEVIEW = 'pageview', 'Page View'
        VIDEO_PLAY = 'video_play', 'Video Play'
        VIDEO_PAUSE = 'video_pause', 'Video Pause'
        VIDEO_END = 'video_end', 'Video End'
        WATCH_SECONDS = 'watch_seconds', 'Watch Seconds'
        SCROLL = 'scroll', 'Scroll'
        CLICK = 'click', 'Click'
        HEARTBEAT = 'heartbeat', 'Heartbeat'

    session_id = models.CharField(max_length=64, db_index=True)
    event_type = models.CharField(max_length=32, choices=EVENT_TYPES.choices, db_index=True)
    page = models.CharField(max_length=255, blank=True, default='')
    video_uid = models.CharField(max_length=64, blank=True, default='', db_index=True)
    video_title = models.CharField(max_length=255, blank=True, default='')
    # value = sekunde za watch (watch_seconds) au scroll % (scroll)
    value = models.IntegerField(default=0)
    referrer = models.CharField(max_length=500, blank=True, default='')
    user_agent = models.CharField(max_length=500, blank=True, default='')
    ip = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['session_id', 'created_at']),
            models.Index(fields=['event_type', 'created_at']),
            models.Index(fields=['video_uid', 'event_type']),
        ]

    def __str__(self):
        return f'{self.event_type} {self.session_id[:8]} @ {self.created_at:%Y-%m-%d %H:%M}'

class Report(BaseModel):
    
    class REPORT_STATUS(models.TextChoices):
        PENDING = 'PENDING'
        APPROVED = 'APPROVED'
        REJECTED = 'REJECTED'
    
    analytics = models.ForeignKey('analytics.Analytics', related_name='reports', on_delete=models.CASCADE)
    user = models.ForeignKey('authentication.User', related_name='reports', on_delete=models.CASCADE)
    video = models.ForeignKey('streaming.Video', related_name='reports', on_delete=models.CASCADE)
    reason = models.TextField()
    details = models.TextField()
    status = models.CharField(max_length=255, choices=REPORT_STATUS.choices, default=REPORT_STATUS.PENDING)
    
    def __str__(self):
        return f'{self.user} report {self.analytics}'

class Notification(BaseModel):
    class NOTIFICATION_TYPES(models.TextChoices):
        VIDEO = 'VIDEO', 'VIDEO'
        VIDEO_PROCESSED = 'video_processed', 'Video Processed'
        VIDEO_FAILED = 'video_failed', 'Video Failed'
        NEW_USER = 'new_user', 'New User'
        COMMENT = 'comment', 'Comment'
        SYSTEM = 'SYSTEM', 'SYSTEM'
        PROMO = 'PROMO', 'PROMO'

    user = models.ForeignKey('authentication.User', related_name='notifications', on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    message = models.TextField()
    type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES.choices, default=NOTIFICATION_TYPES.SYSTEM)
    is_read = models.BooleanField(default=False)
    thumbnail_url = models.URLField(max_length=500, blank=True)
    target_video_slug = models.CharField(null=True, blank=True, max_length=255)
    target_url = models.URLField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
        ]

    def __str__(self):
        return f'{self.user} notification'