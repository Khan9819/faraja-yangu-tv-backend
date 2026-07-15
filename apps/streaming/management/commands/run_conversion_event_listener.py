"""
Management command to run the conversion event listener.

Usage:
    python manage.py run_conversion_event_listener

Listens for progress/heartbeat/complete/error events from the C++ conversion
microservice via Redis PubSub and updates Video model + WebSocket clients.
"""
import signal

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Listen for conversion events from the C++ microservice"

    def handle(self, *args, **options):
        from apps.streaming.services.conversion_events import listen_forever

        def shutdown(signum, frame):
            self.stdout.write("Shutting down conversion event listener...")
            raise SystemExit(0)

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)

        self.stdout.write("Starting conversion event listener...")
        listen_forever()
