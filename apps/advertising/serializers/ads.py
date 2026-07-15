from rest_framework import serializers
from apps.advertising.models import Ad


class AdSerializer(serializers.ModelSerializer):
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = Ad
        fields = '__all__'

    def get_thumbnail_url(self, obj):
        if obj.thumbnail:
            try:
                return obj.thumbnail.url
            except ValueError:
                return None
        return None

    def validate(self, data):
        ad_type = data.get('type')
        render_type = data.get('ad_render_type')
        instance = getattr(self, 'instance', None)

        # Carousel-specific validation
        if ad_type == Ad.AD_TYPES.CAROUSEL or (instance and instance.type == Ad.AD_TYPES.CAROUSEL):
            effective_render = render_type or (instance.ad_render_type if instance else None)

            if effective_render == Ad.AD_RENDER_TYPES.CUSTOM:
                # Custom carousel requires thumbnail, no video
                has_thumbnail = data.get('thumbnail') or (instance and instance.thumbnail)
                if not has_thumbnail:
                    raise serializers.ValidationError(
                        {'thumbnail': 'Custom carousel ads require a thumbnail image.'}
                    )
                if data.get('video'):
                    raise serializers.ValidationError(
                        {'video': 'Carousel ads do not support video uploads.'}
                    )

            elif effective_render == Ad.AD_RENDER_TYPES.GOOGLE:
                # Google carousel requires ad_unit_id
                ad_unit_id = data.get('ad_unit_id')
                if not ad_unit_id and not (instance and instance.ad_unit_id):
                    raise serializers.ValidationError(
                        {'ad_unit_id': 'Google placement carousel ads require an Ad Unit ID.'}
                    )

        return data