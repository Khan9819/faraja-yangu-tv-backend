from rest_framework import serializers

from apps.streaming.models import Comment


class CommentSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    author_avatar = serializers.SerializerMethodField()
    likes_count = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    replies_count = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = (
            "id",
            "uid",
            "author_name",
            "author_avatar",
            "comment",
            "created_at",
            "likes_count",
            "is_liked",
            "replies_count",
        )

    def get_author_name(self, obj):
        user = getattr(obj, "user", None)
        if not user:
            return None
        full_name = f"{user.first_name} {user.last_name}".strip()
        return full_name or user.username

    def get_author_avatar(self, obj):
        user = getattr(obj, "user", None)
        profile = getattr(user, "profile", None) if user else None
        avatar = getattr(profile, "avatar", None) if profile else None
        try:
            return avatar.url if avatar else None
        except ValueError:
            return None

    def get_likes_count(self, obj):  # placeholder, no comment-like model yet
        return 0

    def get_is_liked(self, obj):  # placeholder, frontend can treat as false
        return False

    def get_replies_count(self, obj):
        return obj.replies.count()


class ReplySerializer(CommentSerializer):
    class Meta(CommentSerializer.Meta):
        fields = (
            "id",
            "uid",
            "author_name",
            "author_avatar",
            "comment",
            "created_at",
            "likes_count",
            "is_liked",
        )
