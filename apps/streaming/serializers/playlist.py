from rest_framework import serializers

from apps.streaming.models import Playlist, PlaylistVideo, Video
from apps.streaming.serializers.video import VideoLightSerializer


class PlaylistListSerializer(serializers.ModelSerializer):
    videos_count = serializers.SerializerMethodField()

    class Meta:
        model = Playlist
        fields = [
            'id',
            'uid',
            'name',
            'description',
            'thumbnail',
            'videos_count',
            'created_at',
            'updated_at',
        ]

    def get_videos_count(self, obj):
        return obj.playlist_videos.count()


class PlaylistDetailSerializer(PlaylistListSerializer):
    videos = serializers.SerializerMethodField()

    class Meta(PlaylistListSerializer.Meta):
        fields = PlaylistListSerializer.Meta.fields + ['videos']

    def get_videos(self, obj):
        videos = Video.objects.filter(in_playlists__playlist=obj).select_related('category')
        return VideoLightSerializer(videos, many=True).data
