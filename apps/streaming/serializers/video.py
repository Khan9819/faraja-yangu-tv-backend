from rest_framework import serializers
from django.conf import settings
from apps.streaming.models import Video
from apps.streaming.services.hls_service import get_starter_segments_for_video


class VideoSerializer(serializers.ModelSerializer):
    """
    Serializer for Video model with HLS streaming support.
    """
    streaming_url = serializers.ReadOnlyField()
    is_ready_for_streaming = serializers.ReadOnlyField()
    category_name = serializers.CharField(source='category.name', read_only=True)
    master_playlist = serializers.SerializerMethodField()
    starter_segments = serializers.SerializerMethodField()
    
    class Meta:
        model = Video
        fields = '__all__'
        read_only_fields = [
            'hls_master_playlist', 
            'hls_path', 
            'processing_status',
            'processing_error',
            'duration',
            'streaming_url',
            'is_ready_for_streaming',
            'created_at',
            'master_playlist',
            'starter_segments',
        ]

    def get_master_playlist(self, obj):
        if obj.hls_master_playlist:
            base_url = getattr(settings, 'BASE_URL', 'http://127.0.0.1:8000')
            return f"{base_url}/streaming/hls/{obj.uid}/master.m3u8"
        return None

    def get_starter_segments(self, obj):
        # Skip if context says to exclude (for performance in list views)
        if not self.context.get('include_starter_segments', True):
            return []
        if obj.hls_master_playlist and obj.processing_status == 'completed':
            return get_starter_segments_for_video(obj.uid, count=3)
        return []


class VideoLightSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for Video model with only essential fields.
    Used for listing videos in categories or feeds.
    """
    class Meta:
        model = Video
        fields = [
            'id',
            'uid',
            'created_at',
            'updated_at',
            'is_published',
            'title',
            'description',
            'slug',
            'thumbnail',
            'tv_poster',
            'tv_landscape',
            'tv_square',
            'duration',
            'views_count',
            'likes_count',
            'dislikes_count',
        ]

class VideoFeedSerializer(serializers.ModelSerializer):
    """Serializer for video feed with category and parent category info."""

    category_id = serializers.IntegerField(source='category.id', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    master_playlist = serializers.SerializerMethodField()
    starter_segments = serializers.SerializerMethodField()
    parent_category_id = serializers.SerializerMethodField()
    parent_category_name = serializers.SerializerMethodField()

    class Meta:
        model = Video
        fields = [
            'id',
            'uid',
            'created_at',
            'updated_at',
            'is_published',
            'title',
            'description',
            'slug',
            'thumbnail',
            'tv_poster',
            'tv_landscape',
            'tv_square',
            'duration',
            'views_count',
            'likes_count',
            'dislikes_count',
            'category_id',
            'category_name',
            'parent_category_id',
            'parent_category_name',
            'master_playlist',
            'starter_segments',
        ]

    def get_parent_category_id(self, obj):
        category = getattr(obj, 'category', None)
        parent = getattr(category, 'parent', None) if category else None
        return parent.id if parent else None

    def get_parent_category_name(self, obj):
        category = getattr(obj, 'category', None)
        parent = getattr(category, 'parent', None) if category else None
        return parent.name if parent else None

    def get_master_playlist(self, obj):
        if obj.hls_master_playlist:
            base_url = getattr(settings, 'BASE_URL', 'http://127.0.0.1:8000')
            return f"{base_url}/streaming/hls/{obj.uid}/master.m3u8"
        return None

    def get_starter_segments(self, obj):
        # Skip if context says to exclude (for performance in list views)
        if not self.context.get('include_starter_segments', True):
            return []
        if obj.hls_master_playlist and obj.processing_status == 'completed':
            return get_starter_segments_for_video(obj.uid, count=3)
        return []


class VideoHistorySerializer(VideoFeedSerializer):
    """Simplified watch history serializer based on VideoFeedSerializer.

    The API spec mentions `last_watched_at`, but since we're using a plain
    ManyToMany relation on Profile without per-item timestamps, this field is
    provided as null for now.
    """

    last_watched_at = serializers.SerializerMethodField()

    class Meta(VideoFeedSerializer.Meta):
        fields = VideoFeedSerializer.Meta.fields + ['last_watched_at']

    def get_last_watched_at(self, obj):  # pragma: no cover - placeholder
        return None


class FavoriteVideoSerializer(VideoFeedSerializer):
    """Simplified favorites serializer based on VideoFeedSerializer.

    The API spec mentions `favorited_at`, but we don't persist timestamps yet,
    so it is always null in this first version.
    """

    favorited_at = serializers.SerializerMethodField()

    class Meta(VideoFeedSerializer.Meta):
        fields = VideoFeedSerializer.Meta.fields + ['favorited_at']

    def get_favorited_at(self, obj):  # pragma: no cover - placeholder
        return None


class RelatedVideoSerializer(VideoFeedSerializer):
    """Serializer for related videos with user interaction flags.
    
    Extends VideoFeedSerializer with has_liked, has_disliked, is_ready, and stream_url
    to match the expected response structure for related videos.
    
    Usage:
        Pass 'user' in context for like/dislike annotations.
        Videos should be annotated with has_liked, has_disliked via queryset.
    """
    
    has_liked = serializers.SerializerMethodField()
    has_disliked = serializers.SerializerMethodField()
    is_ready = serializers.SerializerMethodField()
    stream_url = serializers.SerializerMethodField()
    views = serializers.IntegerField(source='views_count', read_only=True)

    class Meta(VideoFeedSerializer.Meta):
        fields = VideoFeedSerializer.Meta.fields + [
            'has_liked',
            'has_disliked',
            'is_ready',
            'stream_url',
            'views',
        ]

    def get_has_liked(self, obj):
        # Use annotated value if available, otherwise check via context user
        if hasattr(obj, 'has_liked'):
            return obj.has_liked
        user = self.context.get('user')
        if user and user.is_authenticated:
            from apps.streaming.models import Like
            return Like.objects.filter(video=obj, user=user).exists()
        return False

    def get_has_disliked(self, obj):
        # Use annotated value if available, otherwise check via context user
        if hasattr(obj, 'has_disliked'):
            return obj.has_disliked
        user = self.context.get('user')
        if user and user.is_authenticated:
            from apps.streaming.models import Dislike
            return Dislike.objects.filter(video=obj, user=user).exists()
        return False

    def get_is_ready(self, obj):
        # Use annotated value if available, otherwise use model property
        if hasattr(obj, 'is_ready'):
            return obj.is_ready
        return obj.is_ready_for_streaming

    def get_stream_url(self, obj):
        # Alias for master_playlist to maintain backward compatibility
        return self.get_master_playlist(obj)