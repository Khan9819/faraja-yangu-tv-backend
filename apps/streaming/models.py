from django.db import models
from apps.common.models import TimeStampedModel
from core.base_model import BaseModel
from uuid import uuid4

# Create your models here.


def video_image_upload_path(instance, filename):
    """Return a unique storage key for a video cover image.

    Every video cover (thumbnail, tv_poster, tv_landscape, tv_square,
    portrait_cover) is saved under a random UUID filename, so two different
    videos can NEVER overwrite or share the same object-storage file — even
    when the CMS uploads two files with the same original name (cover.jpg).
    """
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    uid = getattr(instance, 'uid', None) or uuid4()
    return f'videos/{uid}/{uuid4().hex}.{ext}'

class Category(BaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField()
    slug = models.SlugField(unique=True)
    thumbnail = models.ImageField(upload_to='categories', null=True, blank=True)
    cover = models.ImageField(upload_to='categories', null=True, blank=True)
    parent = models.ForeignKey('self', related_name='subcategories', on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return self.name




class Video(BaseModel):
    PROCESSING_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('assembling', 'Assembling'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('killed', 'Killed'),
    ]
    
    PROCESSING_STAGE_CHOICES = [
        ('idle', 'Idle'),
        ('assembling', 'Assembling Chunks'),
        ('downloading', 'Downloading from Storage'),
        ('converting', 'Converting to HLS'),
        ('uploading', 'Uploading HLS Files'),
    ]
    
    title = models.CharField(max_length=255)
    description = models.TextField()
    slug = models.SlugField(unique=True, null=True, blank=True)
    thumbnail = models.ImageField(upload_to=video_image_upload_path, max_length=500, null=True, blank=True)
    category = models.ForeignKey(Category, related_name='videos', on_delete=models.CASCADE, null=True, blank=True )
    
    # Original uploaded video (will be deleted after HLS conversion)
    video = models.FileField(upload_to='videos/originals', max_length=500, null=True, blank=True)
    
    # Downloadable MP4 file (preserved for direct download)
    download_path = models.CharField(max_length=500, null=True, blank=True,
                                    help_text='Path to downloadable MP4 file in R2 storage (videos/downloads/)')
    
    # HLS streaming fields
    hls_master_playlist = models.CharField(max_length=500, null=True, blank=True, 
                                          help_text='Path to HLS master playlist (master.m3u8)')
    hls_path = models.CharField(max_length=500, null=True, blank=True,
                               help_text='Base directory path for HLS files')
    processing_status = models.CharField(max_length=20, choices=PROCESSING_STATUS_CHOICES, 
                                        default='pending')
    processing_error = models.TextField(null=True, blank=True)
    
    # Upload progress tracking (separate from processing)
    upload_progress = models.IntegerField(default=0, help_text='Upload progress percentage 0-100')
    upload_total_chunks = models.IntegerField(default=0, help_text='Total number of chunks for upload')
    upload_completed_chunks = models.IntegerField(default=0, help_text='Number of chunks uploaded')
    
    # Progress tracking for resume capability and WebSocket status
    processing_stage = models.CharField(max_length=20, choices=PROCESSING_STAGE_CHOICES,
                                        default='idle', help_text='Current processing stage')
    processing_progress = models.IntegerField(default=0, help_text='Progress percentage 0-100')
    processing_message = models.CharField(max_length=255, null=True, blank=True,
                                          help_text='Current progress message')
    # Checkpoint data for resume on retry (JSON)
    processing_checkpoint = models.JSONField(null=True, blank=True,
                                             help_text='Checkpoint data for resuming failed tasks')
    
    # C++ conversion microservice tracking fields
    conversion_job_id = models.UUIDField(null=True, blank=True, db_index=True,
                                         help_text='UUID of the conversion job in the C++ microservice')
    processing_backend = models.CharField(max_length=32, default='python',
                                          choices=[('python', 'Python'), ('cpp', 'C++')],
                                          help_text='Which backend processed/is processing this video')
    queued_at = models.DateTimeField(null=True, blank=True,
                                     help_text='When the conversion job was queued')
    processing_started_at = models.DateTimeField(null=True, blank=True,
                                                  help_text='When conversion actually started')
    processing_completed_at = models.DateTimeField(null=True, blank=True,
                                                    help_text='When conversion completed')
    processing_failed_at = models.DateTimeField(null=True, blank=True,
                                                 help_text='When conversion last failed')
    last_processing_heartbeat_at = models.DateTimeField(null=True, blank=True,
                                                         help_text='Last heartbeat from conversion worker')
    last_event_received_at = models.DateTimeField(null=True, blank=True,
                                                   help_text='Last event received from conversion worker')
    retry_count = models.PositiveIntegerField(default=0,
                                               help_text='Number of conversion retry attempts')
    
    duration = models.DurationField(null=True, blank=True)
    tv_poster = models.ImageField(upload_to=video_image_upload_path, max_length=500, null=True, blank=True,
                                  help_text='TV poster image (540x720 recommended)')
    tv_landscape = models.ImageField(upload_to=video_image_upload_path, max_length=500, null=True, blank=True,
                                     help_text='TV landscape/banner image (1280x720 recommended)')
    tv_square = models.ImageField(upload_to=video_image_upload_path, max_length=500, null=True, blank=True,
                                  help_text='TV square image (540x540 recommended)')
    portrait_cover = models.ImageField(upload_to=video_image_upload_path, max_length=500, null=True, blank=True,
                                       help_text='Portrait cover image for mobile app (1080x1350 recommended)')
    upload_token = models.CharField(max_length=255, null=True, blank=True, help_text='Long-lived upload session token')
    upload_token_expiry = models.DateTimeField(null=True, blank=True, help_text='Expiry of upload token')
    uploaded_by = models.ForeignKey('authentication.User', related_name='videos', on_delete=models.CASCADE)
    views_count = models.IntegerField(default=0)
    likes_count = models.IntegerField(default=0)
    dislikes_count = models.IntegerField(default=0)
    is_published = models.BooleanField(default=False)
    is_live = models.BooleanField(default=False)
    notification_sent = models.BooleanField(default=False, help_text='Whether push notification has been sent for this video')
    is_ad_media = models.BooleanField(default=False,
                                      help_text='True when this video record is media for an ad (interceptor etc). Excluded from content lists.')
    
    def __str__(self):
        return self.title
    
    @property
    def is_ready_for_streaming(self):
        """Check if video is ready for HLS streaming."""
        return self.processing_status == 'completed' and self.hls_master_playlist
    
    @property
    def streaming_url(self):
        """Get the streaming URL for the video."""
        if self.is_ready_for_streaming:
            return f"{self.hls_path}/master.m3u8"
        return None


from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=Video)
def trigger_mp4_reconstruction(sender, instance, created, **kwargs):
    """After HLS conversion completes, trigger MP4 reconstruction in background.
    
    This signal runs OUTSIDE the upload/conversion pipeline.
    It fires when processing_status transitions to 'completed'.
    """
    if not created and instance.processing_status == 'completed':
        update_fields = kwargs.get('update_fields')
        if update_fields and 'processing_status' not in update_fields:
            return
        if not instance.download_path:
            try:
                from apps.streaming.tasks.tasks import reconstruct_mp4_for_download_task
                reconstruct_mp4_for_download_task.delay(instance.id)
            except ImportError:
                pass
    

class Comment(BaseModel):
    video = models.ForeignKey(Video, related_name='comments', on_delete=models.CASCADE)
    user = models.ForeignKey('authentication.User', related_name='comments', on_delete=models.CASCADE)
    comment = models.TextField()
    reply_to = models.ForeignKey('self', related_name='replies', on_delete=models.CASCADE, null=True, blank=True)
    interaction_time = models.DurationField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'video'], name='comment_user_video_idx'),
            models.Index(fields=['reply_to'], name='comment_reply_to_idx'),
        ]

    def __str__(self):
        return self.comment
    

class Like(BaseModel):
    video = models.ForeignKey(Video, related_name='likes', on_delete=models.CASCADE)
    user = models.ForeignKey('authentication.User', related_name='likes', on_delete=models.CASCADE)
    interaction_time = models.DurationField(null=True, blank=True)
    
    def __str__(self):
        return f'{self.user} likes {self.video}'
    
class Dislike(BaseModel):
    video = models.ForeignKey(Video, related_name='dislikes', on_delete=models.CASCADE)
    user = models.ForeignKey('authentication.User', related_name='dislikes', on_delete=models.CASCADE)
    interaction_time = models.DurationField(null=True, blank=True)
    
    def __str__(self):
        return f'{self.user} dislikes {self.video}'


class View(BaseModel):
    video = models.ForeignKey(Video, related_name='views', on_delete=models.CASCADE)
    user = models.ForeignKey('authentication.User', related_name='views', on_delete=models.CASCADE)
    watch_time = models.DurationField(null=True, blank=True)

    class Meta:
        unique_together = ('video', 'user')
    
    def __str__(self):
        return f'{self.user} views {self.video}'

class VideoAdSlot(BaseModel):
    """Interceptor ad slot - defines when an ad break should occur during video playback."""
    
    class MediaType(models.TextChoices):
        IMAGE = 'image', 'Image'
        VIDEO = 'video', 'Video'
    
    video = models.ForeignKey(Video, related_name='ad_slots', on_delete=models.CASCADE, null=True, blank=True)
    
    # Optional link to existing Ad (for reusing ads from advertising system)
    ad = models.ForeignKey('advertising.Ad', related_name='ad_slots', on_delete=models.CASCADE, null=True, blank=True)
    
    # For video-type self-contained ads: reference a proper Video object that went through HLS conversion
    content_video = models.ForeignKey(
        'Video',
        related_name='interceptor_ad_content',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text='For video-type ads: the HLS-converted Video object containing the ad content'
    )
    
    is_active = models.BooleanField(default=True)
    
    # Category targeting: leave empty for ALL videos (global), otherwise
    # the ad only appears on videos belonging to (or nested under) these categories.
    categories = models.ManyToManyField(
        Category,
        related_name='ad_slots',
        blank=True,
    )
    
    # Self-contained interceptor ad fields
    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    media_type = models.CharField(max_length=10, choices=MediaType.choices, default=MediaType.IMAGE)
    media_file = models.FileField(upload_to='interceptor_ads/', null=True, blank=True,
                                  help_text='Image or video file for the interceptor ad')
    redirect_link = models.URLField(max_length=500, null=True, blank=True,
                                    help_text='URL to redirect when ad is clicked')
    display_duration = models.PositiveIntegerField(default=5,
                                                   help_text='Duration in seconds to display the ad (for images)')
    
    # Timing fields
    start_time = models.TimeField(help_text='When the ad should appear during video playback')
    end_time = models.TimeField(help_text='When the ad slot ends')
    
    class Meta:
        ordering = ['start_time']
    
    def __str__(self):
        return f'{self.video} ad slot ({self.start_time} - {self.end_time})'
    
    @property
    def is_self_contained(self):
        """Check if this ad slot uses its own media instead of linked Ad."""
        return (self.media_file or self.content_video) and not self.ad
    
    def clean(self):
        """Validate that either ad, media_file, or content_video is provided."""
        from django.core.exceptions import ValidationError
        if not self.ad and not self.media_file and not self.content_video:
            raise ValidationError('Either an Ad reference, media_file, or content_video must be provided.')


class Playlist(BaseModel):
    """User playlist model for grouping videos."""

    owner = models.ForeignKey('authentication.User', related_name='playlists', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    thumbnail = models.ImageField(upload_to='playlists', null=True, blank=True)

    def __str__(self):
        return f'{self.owner} - {self.name}'


class PlaylistVideo(BaseModel):
    """Through model for videos inside a playlist."""

    playlist = models.ForeignKey(Playlist, related_name='playlist_videos', on_delete=models.CASCADE)
    video = models.ForeignKey(Video, related_name='in_playlists', on_delete=models.CASCADE)

    class Meta:
        unique_together = ('playlist', 'video')

    def __str__(self):
        return f'{self.playlist} -> {self.video}'


class GoogleDriveImport(BaseModel):
    """Tracks the state of a Google Drive video import."""

    IMPORT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('downloading', 'Downloading'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    video = models.OneToOneField(Video, on_delete=models.CASCADE, related_name='gdrive_import')
    google_drive_url = models.URLField()
    google_drive_file_id = models.CharField(max_length=255)
    task_id = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=20, choices=IMPORT_STATUS_CHOICES, default='pending')
    progress = models.IntegerField(default=0)
    message = models.TextField(default='', blank=True)
    error = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'google_drive_imports'

    def __str__(self):
        return f'GDrive import for {self.video} ({self.status})'