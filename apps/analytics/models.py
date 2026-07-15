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
    target_video_slug = models.CharField(null=True, blank=True, max_length=255)
    target_url = models.URLField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} notification'