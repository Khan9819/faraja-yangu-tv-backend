"""
Shared HLS quality preset definitions used by both the legacy Python converter
and the C++ conversion microservice job builder.
"""
from django.conf import settings


QUALITY_PRESETS = [
    {'name': '1080p', 'resolution': '1920x1080', 'video_bitrate': '5000k', 'audio_bitrate': '192k'},
    {'name': '720p', 'resolution': '1280x720', 'video_bitrate': '2800k', 'audio_bitrate': '128k'},
    {'name': '480p', 'resolution': '854x480', 'video_bitrate': '1400k', 'audio_bitrate': '128k'},
    {'name': '360p', 'resolution': '640x360', 'video_bitrate': '800k', 'audio_bitrate': '96k'},
]


def get_enabled_hls_variants() -> list[dict]:
    enabled = getattr(settings, 'HLS_VARIANTS', ['1080p', '720p', '480p', '360p'])
    return [p for p in QUALITY_PRESETS if p['name'] in enabled]
