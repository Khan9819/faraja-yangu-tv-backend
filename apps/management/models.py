from django.db import models
from core.base_model import BaseModel

# Create your models here.


class PlatformSettings(BaseModel):
    """Singleton model for platform-level settings."""

    platform_name = models.CharField(max_length=255, default='FarajaYangu TV')
    language = models.CharField(max_length=50, default='English')
    app_version = models.CharField(max_length=50, default='1.0.0')
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
        obj, _ = cls.objects.get_or_create(pk=1, defaults={
            'platform_name': 'FarajaYangu TV',
            'language': 'English',
            'app_version': '1.0.0',
        })
        return obj
