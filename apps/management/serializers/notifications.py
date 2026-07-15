from rest_framework import serializers
from apps.analytics.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """Serializer for admin notifications."""

    read = serializers.BooleanField(source='is_read', read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id',
            'type',
            'title',
            'message',
            'read',
            'is_read',
            'created_at',
        ]
