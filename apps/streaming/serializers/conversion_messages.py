"""
Schema validation serializers for conversion job payloads and inbound events.
Prevents contract drift between Django and the C++ conversion microservice.
"""
from rest_framework import serializers


# --- Outbound: Job payload validation ---

class ConversionJobSourceSerializer(serializers.Serializer):
    type = serializers.CharField()
    bucket = serializers.CharField()
    key = serializers.CharField()
    endpoint = serializers.CharField()


class ConversionJobOutputSerializer(serializers.Serializer):
    bucket = serializers.CharField()
    base_path = serializers.CharField()
    endpoint = serializers.CharField()


class ConversionJobVariantSerializer(serializers.Serializer):
    name = serializers.CharField()
    resolution = serializers.CharField()
    video_bitrate = serializers.CharField()
    audio_bitrate = serializers.CharField()


class ConversionJobOptionsSerializer(serializers.Serializer):
    segment_duration = serializers.IntegerField()
    encoder_preset = serializers.CharField()
    skip_upscaling = serializers.BooleanField()
    threads = serializers.IntegerField()
    prefer_hardware = serializers.BooleanField()


class ConversionJobSerializer(serializers.Serializer):
    job_id = serializers.UUIDField()
    video_id = serializers.IntegerField()
    video_uid = serializers.CharField()
    source = ConversionJobSourceSerializer()
    output = ConversionJobOutputSerializer()
    variants = ConversionJobVariantSerializer(many=True)
    options = ConversionJobOptionsSerializer()
    checkpoint = serializers.JSONField(required=False, default=dict)


# --- Inbound: Event validation ---

class ConversionHeartbeatEventSerializer(serializers.Serializer):
    job_id = serializers.UUIDField()
    video_id = serializers.IntegerField()
    type = serializers.ChoiceField(choices=["heartbeat"])
    timestamp = serializers.DateTimeField(required=False)


class ConversionProgressEventSerializer(serializers.Serializer):
    job_id = serializers.UUIDField()
    video_id = serializers.IntegerField()
    type = serializers.ChoiceField(choices=["progress"])
    stage = serializers.CharField()
    progress = serializers.IntegerField(min_value=0, max_value=100)
    message = serializers.CharField(required=False, allow_blank=True, default="")
    variants = serializers.JSONField(required=False, default=dict)
    checkpoint = serializers.JSONField(required=False, default=dict)
    timestamp = serializers.DateTimeField(required=False)


class ConversionCompleteEventSerializer(serializers.Serializer):
    job_id = serializers.UUIDField()
    video_id = serializers.IntegerField()
    type = serializers.ChoiceField(choices=["complete"])
    hls_path = serializers.CharField()
    master_playlist = serializers.CharField()
    variants_created = serializers.ListField(child=serializers.CharField(), required=False)
    duration_seconds = serializers.FloatField(required=False)
    source_deleted = serializers.BooleanField(required=False, default=False)
    timestamp = serializers.DateTimeField(required=False)


class ConversionErrorEventSerializer(serializers.Serializer):
    job_id = serializers.UUIDField()
    video_id = serializers.IntegerField()
    type = serializers.ChoiceField(choices=["error"])
    message = serializers.CharField(required=False, allow_blank=True, default="Processing failed")
    error = serializers.CharField(required=False, allow_blank=True, default="Unknown error")
    timestamp = serializers.DateTimeField(required=False)
