from rest_framework import serializers
from apps.management.models import PlatformSettings


class PlatformSettingsSerializer(serializers.ModelSerializer):
    """Serializer for platform settings."""

    class Meta:
        model = PlatformSettings
        fields = [
            'platform_name',
            'language',
            'app_version',
            'minimum_version',
            'release_notes',
            'update_url',
            'is_force_update',
            'push_notifications_enabled',
            'email_notifications_enabled',
        ]
