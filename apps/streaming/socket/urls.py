from django.urls import path
from apps.streaming.socket.consumers import VideoProcessorConsumer

urls = [
    path("stream/progress/<int:video_uid>/", VideoProcessorConsumer.as_asgi()),
]