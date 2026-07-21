"""
Verify FCM fix: test Firebase Admin SDK init + payload structure.
No device token needed — just validates the code correctness.
"""
import json
import os

# ── Load Firebase credentials ──
env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
if not os.path.exists(env_path):
    env_path = os.path.join(os.path.dirname(__file__), '.env')

creds = {}
with open(env_path, encoding='utf-8', errors='ignore') as f:
    for line in f:
        line = line.strip()
        if line.startswith('FIREBASE_') and '=' in line:
            k, v = line.split('=', 1)
            creds[k] = v

# Reconstruct private key (handle .env quoting)
private_key = creds.get('FIREBASE_PRIVATE_KEY', '')
private_key = private_key.strip('"').strip("'")
private_key = private_key.replace('\\n', '\n')

cert = {
    'type': 'service_account',
    'project_id': creds.get('FIREBASE_PROJECT_ID', ''),
    'private_key_id': creds.get('FIREBASE_PRIVATE_KEY_ID', ''),
    'private_key': private_key,
    'client_email': creds.get('FIREBASE_CLIENT_EMAIL', ''),
    'client_id': creds.get('FIREBASE_CLIENT_ID', ''),
    'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
    'token_uri': 'https://oauth2.googleapis.com/token',
    'auth_provider_x509_cert_url': 'https://www.googleapis.com/oauth2/v1/certs',
    'client_x509_cert_url': (
        'https://www.googleapis.com/robot/v1/metadata/x509/'
        + creds.get('FIREBASE_CLIENT_EMAIL', '').replace('@', '%40')
    ),
}

print('[+] Firebase credentials loaded')
print(f'    project_id:       {cert["project_id"]}')
print(f'    client_email:     {cert["client_email"]}')
print(f'    private_key:      {len(cert["private_key"])} chars, starts with {cert["private_key"][:30]}...')
print()

# ── Initialize Firebase Admin SDK ──
import firebase_admin
from firebase_admin import credentials as fb_creds, messaging

if not firebase_admin._apps:
    cred = fb_creds.Certificate(cert)
    firebase_admin.initialize_app(cred)
    print('[+] Firebase Admin SDK initialized successfully')
else:
    print('[.] Firebase already initialized')
print()

# ── Build the EXACT payload our fixed _send_notification sends ──
android_config = messaging.AndroidConfig(
    priority='high',
    notification=messaging.AndroidNotification(
        title='Faraja Yangu TV | Test Notification',
        body='This is a test notification with custom sound and thumbnail',
        sound='faraja_notification',
        channel_id='video_upload_channel',
        image='https://example.com/thumbnail.jpg',
    ),
)

apns_config = messaging.APNSConfig(
    payload=messaging.APNSPayload(
        aps=messaging.Aps(
            alert=messaging.ApsAlert(
                title='Faraja Yangu TV | Test Notification',
                body='This is a test notification with custom sound and thumbnail',
            ),
            sound='default',
            mutable_content=True,
            content_available=True,
        ),
    ),
)

message = messaging.Message(
    data={
        'type': 'video_upload',
        'video_id': 'test-001',
        'video_title': 'Test Video Title',
        'video_thumbnail': 'https://example.com/thumbnail.jpg',
        'video_category': 'Entertainment',
        'video_description': 'A test video description',
        'video_duration': '180',
        'master_playlist': '',
        'title': 'Faraja Yangu TV | Test Notification',
        'body': 'This is a test notification with custom sound and thumbnail',
    },
    token='dummy_token_for_validation',
    android=android_config,
    apns=apns_config,
)

# ── Verify all fields ──
errors = []

# Android notification
an = message.android.notification
if an.title != 'Faraja Yangu TV | Test Notification':
    errors.append(f'Android title: got "{an.title}"')
if an.body != 'This is a test notification with custom sound and thumbnail':
    errors.append(f'Android body: got "{an.body}"')
if an.sound != 'faraja_notification':
    errors.append(f'Android sound: got "{an.sound}"')
if an.channel_id != 'video_upload_channel':
    errors.append(f'Android channel_id: got "{an.channel_id}"')
if an.image != 'https://example.com/thumbnail.jpg':
    errors.append(f'Android image: got "{an.image}"')

# APNs
aps = message.apns.payload.aps
if aps.alert.title != 'Faraja Yangu TV | Test Notification':
    errors.append(f'APNs alert title: got "{aps.alert.title}"')
if aps.alert.body != 'This is a test notification with custom sound and thumbnail':
    errors.append(f'APNs alert body: got "{aps.alert.body}"')
if aps.sound != 'default':
    errors.append(f'APNs sound: got "{aps.sound}"')

# Data payload
data = message.data
if data.get('title') != 'Faraja Yangu TV | Test Notification':
    errors.append(f'data.title: got "{data.get("title")}"')
if data.get('body') != 'This is a test notification with custom sound and thumbnail':
    errors.append(f'data.body: got "{data.get("body")}"')
if data.get('video_thumbnail') != 'https://example.com/thumbnail.jpg':
    errors.append(f'data.video_thumbnail: got "{data.get("video_thumbnail")}"')

# ── Results ──
print()
print('=== FCM PAYLOAD VERIFICATION ===')
print(f'  Android title:        {an.title}')
print(f'  Android body:         {an.body}')
print(f'  Android sound:        {an.sound}')
print(f'  Android channel_id:   {an.channel_id}')
print(f'  Android image:        {an.image}')
print(f'  APNs alert title:     {aps.alert.title}')
print(f'  APNs alert body:      {aps.alert.body}')
print(f'  APNs sound:           {aps.sound}')
print(f'  data.title:           {data.get("title")}')
print(f'  data.body:            {data.get("body")}')
print(f'  data.video_thumbnail: {data.get("video_thumbnail")}')
print()

if errors:
    print('ERRORS FOUND:')
    for e in errors:
        print(f'  - {e}')
    exit(1)
else:
    print('ALL FIELDS VERIFIED - payload structure is correct!')
    print()
    print('To send a real notification, get your FCM token and run:')
    print('  python test_fcm.py <YOUR_DEVICE_TOKEN> --image <THUMBNAIL_URL>')
    print()
