from rest_framework import serializers
from apps.streaming.models import Video, VideoAdSlot


class VideoNestedSerializer(serializers.ModelSerializer):
    """Nested serializer for Video in interceptor ads."""
    thumbnail_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Video
        fields = ['id', 'uid', 'title', 'thumbnail', 'thumbnail_url', 'duration', 'processing_status', 'hls_master_playlist']
    
    def get_thumbnail_url(self, obj):
        if obj.thumbnail:
            try:
                return obj.thumbnail.url
            except ValueError:
                return None
        return None


class VideoAdSlotSerializer(serializers.ModelSerializer):
    """Serializer for VideoAdSlot model (list/detail response)."""
    
    video = VideoNestedSerializer(read_only=True)
    content_video = VideoNestedSerializer(read_only=True)
    media_file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = VideoAdSlot
        fields = [
            'id',
            'video',
            'ad',
            'content_video',
            'title',
            'is_active',
            'description',
            'media_type',
            'media_file',
            'media_file_url',
            'redirect_link',
            'display_duration',
            'start_time',
            'end_time',
            'created_at',
        ]
    
    def get_media_file_url(self, obj):
        """Return absolute URL for media file."""
        if obj.media_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.media_file.url)
            return obj.media_file.url
        return None


class VideoAdSlotCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating VideoAdSlot with support for self-contained interceptor ads."""
    
    class Meta:
        model = VideoAdSlot
        fields = [
            'id',
            'video',
            'ad',
            'content_video',
            'title',
            'description',
            'is_active',
            'media_type',
            'media_file',
            'redirect_link',
            'display_duration',
            'start_time',
            'end_time',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']
    
    def validate(self, data):
        """Validate time fields and media requirements."""
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        video = data.get('video')
        ad = data.get('ad')
        media_file = data.get('media_file')
        content_video = data.get('content_video')
        
        # Validate end_time > start_time
        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError({
                'end_time': 'End time must be after start time.'
            })
        
        # Validate that either ad, media_file, or content_video is provided (for create or full update)
        # For partial updates, check if instance already has one
        instance = getattr(self, 'instance', None)
        has_existing_ad = instance and instance.ad_id
        has_existing_media = instance and instance.media_file
        has_existing_content_video = instance and instance.content_video_id
        
        if not ad and not media_file and not content_video and not has_existing_ad and not has_existing_media and not has_existing_content_video:
            raise serializers.ValidationError(
                'Either an Ad reference, media_file, or content_video must be provided.'
            )
        
        # Validate times are within video duration if video has duration
        duration_ref = content_video or video
        if duration_ref and duration_ref.duration:
            video_duration_seconds = duration_ref.duration.total_seconds()
            
            def time_to_seconds(t):
                return t.hour * 3600 + t.minute * 60 + t.second
            
            if start_time:
                start_seconds = time_to_seconds(start_time)
                if start_seconds > video_duration_seconds:
                    raise serializers.ValidationError({
                        'start_time': 'Start time exceeds video duration.'
                    })
            
            if end_time:
                end_seconds = time_to_seconds(end_time)
                if end_seconds > video_duration_seconds:
                    raise serializers.ValidationError({
                        'end_time': 'End time exceeds video duration.'
                    })
        
        return data
    
    def validate_video(self, value):
        """Validate that video exists if provided."""
        if value and not Video.objects.filter(pk=value.pk).exists():
            raise serializers.ValidationError('Video does not exist.')
        return value
    
    def validate_content_video(self, value):
        """Validate that content_video exists if provided."""
        if value and not Video.objects.filter(pk=value.pk).exists():
            raise serializers.ValidationError('Content video does not exist.')
        return value
    
    def validate_media_file(self, value):
        """Validate media file type and size."""
        if value:
            # Max file size: 50MB
            max_size = 50 * 1024 * 1024
            if value.size > max_size:
                raise serializers.ValidationError(
                    'Media file size must be less than 50MB.'
                )
            
            # Validate content type
            allowed_types = [
                'image/jpeg', 'image/png', 'image/gif', 'image/webp',
                'video/mp4', 'video/webm', 'video/quicktime'
            ]
            content_type = getattr(value, 'content_type', None)
            if content_type and content_type not in allowed_types:
                raise serializers.ValidationError(
                    f'Invalid file type. Allowed: JPEG, PNG, GIF, WebP, MP4, WebM, MOV.'
                )
        return value
