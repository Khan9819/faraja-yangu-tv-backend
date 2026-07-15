from django.db import models
from core.base_model import BaseModel

# Create your models here.

class Ad(BaseModel):
    
    class AD_TYPES(models.TextChoices):
        BANNER = 'BANNER'
        VIDEO = 'VIDEO'
        CAROUSEL = 'CAROUSEL'
    
    class AD_RENDER_TYPES(models.TextChoices):
        CUSTOM = 'CUSTOM'
        GOOGLE = 'GOOGLE'
    
    name = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    slug = models.SlugField(unique=True, null=True, blank=True)
    type = models.CharField(max_length=255, choices=AD_TYPES.choices, default=AD_TYPES.BANNER)
    ad_render_type = models.CharField(max_length=255, choices=AD_RENDER_TYPES.choices, default=AD_RENDER_TYPES.CUSTOM)
    ad_unit_id = models.CharField(max_length=255, null=True, blank=True, help_text='Google AdMob ad unit ID (only for GOOGLE render type)')
    ad_format = models.CharField(max_length=50, null=True, blank=True, choices=[('banner', 'Banner'), ('native', 'Native'), ('interstitial', 'Interstitial')], default='banner', help_text='Ad format for GOOGLE render type')
    thumbnail = models.ImageField(upload_to='ads', null=True, blank=True)
    video = models.FileField(upload_to='ads', null=True, blank=True)
    redirect_link = models.URLField(max_length=500, null=True, blank=True, help_text='URL to redirect when ad is clicked')
    duration = models.DurationField(null=True, blank=True)
    uploaded_by = models.ForeignKey('authentication.User', related_name='ads', on_delete=models.CASCADE)
    views_count = models.IntegerField(default=0)
    likes_count = models.IntegerField(default=0)
    dislikes_count = models.IntegerField(default=0)
    is_published = models.BooleanField(default=False)
    
    
    def __str__(self):
        return self.name