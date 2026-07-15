from rest_framework import serializers
from django.utils import timezone
from apps.authentication.models import User
from apps.streaming.models import View


class AppUserSerializer(serializers.ModelSerializer):
    """Serializer for mobile app users."""

    full_name = serializers.SerializerMethodField()
    plan = serializers.SerializerMethodField()
    last_active = serializers.SerializerMethodField()
    phone_number = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'full_name',
            'first_name',
            'last_name',
            'username',
            'email',
            'phone_number',
            'plan',
            'is_active',
            'is_suspended',
            'last_active',
            'last_login',
            'date_joined',
        ]

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_plan(self, obj):
        # Placeholder: derive from billing/subscription if available
        return 'Free'

    def get_last_active(self, obj):
        last_view = View.objects.filter(user=obj).order_by('-created_at').values_list('created_at', flat=True).first()
        if last_view and obj.last_login:
            return max(last_view, obj.last_login)
        return last_view or obj.last_login

    def get_phone_number(self, obj):
        if obj.profile and obj.profile.phone_number:
            return obj.profile.phone_number
        return None
