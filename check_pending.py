import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'farajayangu_be.settings')
import django
django.setup()
from apps.streaming.models import Video

qs = Video.objects.filter(processing_status__in=['failed', 'pending', 'processing']).order_by('-uploaded_at')[:15]
print('ID|TITLE|STATUS|UID')
for v in qs:
    title = (v.title or 'NONE')[:40]
    print(f'{v.id}|{title}|{v.processing_status}|{str(v.uid)[:8]}')

total = Video.objects.filter(processing_status='failed').count()
print(f'\nFAILED total: {total}')
total = Video.objects.filter(processing_status='pending').count()
print(f'PENDING total: {total}')
total = Video.objects.filter(processing_status='processing').count()
print(f'PROCESSING total: {total}')

# Also show videos that are "completed" but notification_sent=False
completed_no_notif = Video.objects.filter(processing_status='completed', notification_sent=False).count()
print(f'COMPLETED but notification_sent=False: {completed_no_notif}')
