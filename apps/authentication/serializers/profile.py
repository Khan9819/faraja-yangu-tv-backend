from rest_framework import serializers

from apps.authentication.models import Profile

class ProfileSerializer(serializers.ModelSerializer):
    notification_count = serializers.SerializerMethodField()

    def get_notification_count(self, obj):
        """Return count of unread notifications for this profile's user."""
        if hasattr(obj, 'user') and obj.user:
            return obj.user.notifications.filter(is_read=False).count()
        return 0

    class Meta:
        model = Profile
        fields = '__all__'
