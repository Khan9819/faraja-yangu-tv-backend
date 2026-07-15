from rest_framework import serializers


class ClaimRewardSerializer(serializers.Serializer):
    """Serializer for claiming ad rewards."""
    
    time_spent_seconds = serializers.IntegerField(min_value=0)
    ad_clicked = serializers.BooleanField(default=False)
    ad_id = serializers.IntegerField(required=False, allow_null=True)
    ad_session_id = serializers.UUIDField(required=False, allow_null=True)
