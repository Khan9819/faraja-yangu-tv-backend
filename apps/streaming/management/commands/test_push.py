"""
Management command to test push notification delivery.
Run: python manage.py test_push <fcm_token> [--image URL]
"""
from django.core.management.base import BaseCommand, CommandError
from apps.streaming.tasks.tasks import _send_notification


class Command(BaseCommand):
    help = 'Send a test push notification to verify FCM delivery with image + sound'

    def add_arguments(self, parser):
        parser.add_argument('fcm_token', type=str, help='Device FCM registration token')
        parser.add_argument('--image', type=str, default=None, help='Thumbnail image URL for notification')

    def handle(self, *args, **options):
        token = options['fcm_token']
        image_url = options['image']

        data = {
            'type': 'test_notification',
            'video_id': 'test-001',
            'video_title': 'Faraja Yangu TV Test',
            'video_thumbnail': image_url or '',
            'video_category': 'Test',
            'master_playlist': '',
        }

        self.stdout.write(f'Sending test notification to: {token[:20]}...')
        self.stdout.write(f'Payload data: {data}')
        self.stdout.write(f'Notification: title="Faraja Yangu TV | Test Notification", body="This is a test notification from Faraja Yangu TV"')
        self.stdout.write(f'Android: sound=faraja_notification, channel=video_upload_channel, image={image_url}')
        self.stdout.write('---')

        result = _send_notification(
            fcm_token=token,
            title='Faraja Yangu TV | Test Notification',
            body='This is a test notification from Faraja Yangu TV',
            data=data,
        )

        if result:
            self.stdout.write(self.style.SUCCESS(f'Notification sent successfully! Response: {result}'))
        else:
            self.stdout.write(self.style.WARNING('Notification send returned None (check logs for details)'))
