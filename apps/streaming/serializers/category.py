from rest_framework import serializers
from apps.streaming.models import Category, Video
from apps.streaming.serializers.video import VideoLightSerializer


class CategorySerializer(serializers.ModelSerializer):
    videos = serializers.SerializerMethodField()
    video_count = serializers.SerializerMethodField()
    category_count = serializers.SerializerMethodField()
    children_count = serializers.SerializerMethodField()
    subcategories = serializers.SerializerMethodField()
    parent_name = serializers.CharField(source='parent.name', read_only=True)
    
    class Meta:
        model = Category
        fields = '__all__'
    
    def __init__(self, *args, **kwargs):
        # Extract custom parameters
        self.include_videos = kwargs.pop('include_videos', False)
        self.video_limit = kwargs.pop('video_count', 10)
        self.include_parents = kwargs.pop('parents', False)
        super().__init__(*args, **kwargs)
    
    def get_video_count(self, obj):
        """Return total number of published videos in this category and subcategories"""
        if obj.parent_id is None:
            # Parent category: count only videos in subcategories
            return Video.objects.filter(
                is_published=True,
                processing_status='completed',
                category__in=obj.subcategories.values_list('id', flat=True)
            ).count()
        
        return obj.videos.filter(is_published=True, processing_status='completed').count()
    
    def get_category_count(self, obj):
        if obj.parent_id is None:
            return Category.objects.filter(parent_id=obj.id).count()
        return 0

    def get_children_count(self, obj):
        """Alias for category_count — used by CMS frontend."""
        return self.get_category_count(obj)
    
    def get_videos(self, obj):
        """Return most viewed videos if include_videos is True"""
        if not self.include_videos:
            return None
        
        # Get most viewed published videos, limited by video_count
        most_viewed = obj.videos.filter(
            processing_status='completed',
            is_published=True
        ).order_by('-views_count')[:self.video_limit]
        
        return VideoLightSerializer(most_viewed, many=True).data
    
    def get_subcategories(self, obj):
        """Return subcategories with videos if parents is True"""
        if not self.include_parents:
            return None
        
        # Get all subcategories for this parent category
        subcategories = obj.subcategories.all()
        
        # Serialize each subcategory with videos
        return CategorySerializer(
            subcategories,
            many=True,
            include_videos=True,  # Always include videos in subcategories
            video_count=self.video_limit,
            parents=False  # Don't nest further
        ).data