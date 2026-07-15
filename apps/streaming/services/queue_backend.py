"""
Queue abstraction layer for publishing conversion jobs and consuming events.
Supports Redis (default) with a clean interface for adding RabbitMQ later.
"""
import json
import logging
from abc import ABC, abstractmethod

from django.conf import settings

logger = logging.getLogger(__name__)


class BaseQueueBackend(ABC):
    @abstractmethod
    def publish(self, queue_name: str, payload: dict) -> None:
        raise NotImplementedError

    @abstractmethod
    def subscribe(self, channel: str):
        raise NotImplementedError


class RedisQueueBackend(BaseQueueBackend):
    def __init__(self):
        import redis as redis_lib
        self._client = redis_lib.Redis(
            host=getattr(settings, 'REDIS_HOST', 'localhost'),
            port=int(getattr(settings, 'REDIS_PORT', 6379)),
            password=getattr(settings, 'REDIS_PASSWORD', '') or None,
            decode_responses=True,
        )

    def publish(self, queue_name: str, payload: dict) -> None:
        self._client.lpush(queue_name, json.dumps(payload))

    def subscribe(self, channel: str):
        pubsub = self._client.pubsub()
        pubsub.psubscribe(channel)
        return pubsub

    @property
    def client(self):
        return self._client


_backend_instance = None


def get_queue_backend() -> BaseQueueBackend:
    global _backend_instance
    if _backend_instance is None:
        backend_type = getattr(settings, 'CONVERSION_QUEUE_BACKEND', 'redis')
        if backend_type == 'redis':
            _backend_instance = RedisQueueBackend()
        else:
            raise ValueError(f"Unsupported queue backend: {backend_type}")
    return _backend_instance
