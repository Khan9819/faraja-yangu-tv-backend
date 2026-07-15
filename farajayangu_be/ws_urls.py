from django.urls import path
from apps.streaming.socket.consumers import VideoProcessorConsumer

# WebSocket URL patterns used by Channels' URLRouter
ws_urlpatterns = [
    path("socket/stream/progress/<int:video_uid>/", VideoProcessorConsumer.as_asgi()),
]