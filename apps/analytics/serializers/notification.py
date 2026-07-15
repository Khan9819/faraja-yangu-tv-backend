from rest_framework import serializers
from apps.analytics.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    body = serializers.CharField(source='message')

    class Meta:
        model = Notification
        fields = [
            'id',
            'title',
            'body',
            'type',
            'is_read',
            'created_at',
            'target_video_slug',
            'target_url',
        ]
