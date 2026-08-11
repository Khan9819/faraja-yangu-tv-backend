from django.db import models
from core.base_model import BaseModel


class WebsitePost(BaseModel):
    cover_image = models.ImageField(upload_to='website_posts', null=True, blank=True)
    title = models.CharField(max_length=255)
    description = models.TextField()
    date = models.DateField()

    class Meta:
        verbose_name = 'Website Post'
        verbose_name_plural = 'Website Posts'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return self.title


class PlatformSettings(BaseModel):
    """Singleton model for platform-level settings."""

    platform_name = models.CharField(max_length=255, default='FarajaYangu TV')
    language = models.CharField(max_length=50, default='English')
    # app_version = latest_version inayotumiwa na in-app update (management/app-version/)
    app_version = models.CharField(max_length=50, default='1.1.1')
    minimum_version = models.CharField(max_length=50, default='1.1.0')
    release_notes = models.JSONField(default=list, blank=True)
    update_url = models.CharField(
        max_length=500,
        default='https://play.google.com/store/apps/details?id=co.tz.farajayangutv.app',
    )
    is_force_update = models.BooleanField(default=False)
    push_notifications_enabled = models.BooleanField(default=True)
    email_notifications_enabled = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Platform Settings'
        verbose_name_plural = 'Platform Settings'

    def __str__(self):
        return self.platform_name

    def save(self, *args, **kwargs):
        """Ensure only one instance exists."""
        if not self.pk and PlatformSettings.objects.exists():
            existing = PlatformSettings.objects.first()
            self.pk = existing.pk
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        """Load or create the singleton settings instance."""
        # NOTE: usiweke app_version kwenye defaults hapa — inaweza kuwa ya kale.
        # Model field default (sasa '1.1.1') ndiyo inayotumika kwa singleton mpya.
        obj, _ = cls.objects.get_or_create(pk=1, defaults={
            'platform_name': 'FarajaYangu TV',
            'language': 'English',
        })
        return obj
