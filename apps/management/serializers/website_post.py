from rest_framework import serializers
from apps.management.models import WebsitePost


class WebsitePostSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebsitePost
        fields = ['id', 'uid', 'title', 'description', 'cover_image', 'date', 'created_at', 'updated_at']
        read_only_fields = ['id', 'uid', 'created_at', 'updated_at']


class WebsitePostCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebsitePost
        fields = ['title', 'description', 'cover_image', 'date']
