from rest_framework import serializers
from django.utils import timezone
from apps.authentication.models import User
from apps.streaming.models import View


class ClientSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    is_registered_today = serializers.SerializerMethodField()
    provider = serializers.CharField(source="auth_provider")
    watched_video_count_today = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "full_name",
            "email",
            "is_registered_today",
            "provider",
            "watched_video_count_today",
            "date_joined",
            "last_login",
        ]

    def get_full_name(self, obj: User) -> str:
        return obj.get_full_name() or obj.username

    def get_is_registered_today(self, obj: User) -> bool:
        if not obj.date_joined:
            return False
        local_today = timezone.localdate()
        return timezone.localtime(obj.date_joined).date() == local_today

    def get_watched_video_count_today(self, obj: User) -> int:
        today = timezone.localdate()
        # View inherits from BaseModel, which likely has a created_at field
        return View.objects.filter(user=obj, created_at__date=today).count()