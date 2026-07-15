from rest_framework import serializers

from apps.authentication.models import User, Profile, Role


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = (
            "id",
            "name",
            "description",
        )


class ProfileDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = (
            "id",
            "bio",
            "location",
            "is_phone_verified",
            "phone_number",
            "phone_number_country_code",
            "country_short_code",
            "birth_date",
            "preferences",
            "credit_accumulation",
            "avatar",
        )


class UserProfileSerializer(serializers.ModelSerializer):
    profile = ProfileDetailSerializer()
    roles = RoleSerializer(many=True)
    favorite_videos_count = serializers.IntegerField(source="profile.favorite_videos_count", read_only=True)
    videos_watched_count = serializers.IntegerField(source="profile.videos_watched_count", read_only=True)
    notification_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "is_verified",
            "is_active",
            "date_joined",
            "last_login",
            "auth_provider",
            "roles",
            "profile",
            "favorite_videos_count",
            "videos_watched_count",
            "notification_count",
        )

    def get_notification_count(self, obj):
        return obj.notifications.filter(is_read=False).count()