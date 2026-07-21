"""
Standalone FCM test — sends a push notification with image + custom sound.
No Django needed. Run directly: python test_fcm.py <fcm_token> [--image URL]
"""
import sys, os, json, argparse, re

env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
if os.path.exists(env_path):
    print(f"[*] Loading .env from {env_path}")
    for line in open(env_path, encoding='utf-8', errors='ignore'):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            v = v.strip().strip('"').strip("'")
            # Unescape \\n -> \n for private keys
            v = v.replace('\\n', '\n')
            os.environ.setdefault(k.strip(), v)


def send_test_notification(token, title=None, body=None, image_url=None):
    import firebase_admin
    from firebase_admin import messaging, credentials

    if not firebase_admin._apps:
        private_key = os.environ.get('FIREBASE_PRIVATE_KEY', '')
        cred = credentials.Certificate({
            "type": "service_account",
            "project_id": os.environ.get('FIREBASE_PROJECT_ID', ''),
            "private_key_id": os.environ.get('FIREBASE_PRIVATE_KEY_ID', ''),
            "private_key": private_key,
            "client_email": os.environ.get('FIREBASE_CLIENT_EMAIL', ''),
            "client_id": os.environ.get('FIREBASE_CLIENT_ID', ''),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{os.environ.get('FIREBASE_CLIENT_EMAIL', '').replace('@', '%40')}",
        })
        firebase_admin.initialize_app(cred)

    data = {
        'type': 'video_upload',
        'video_id': 'test-001',
        'video_title': title or 'Faraja Yangu TV Test',
        'video_thumbnail': image_url or '',
        'video_category': 'Test',
        'video_description': body or 'Test notification with custom sound and thumbnail',
        'video_duration': '120',
        'master_playlist': '',
        'title': title or 'Faraja Yangu TV | Test Notification',
        'body': body or 'This is a test notification with custom sound and thumbnail',
    }

    string_data = {k: str(v) for k, v in data.items()}

    android_notif_title = title or 'Faraja Yangu TV | Test Notification'
    android_notif_body = body or 'This is a test notification with custom sound and thumbnail'

    android_config = messaging.AndroidConfig(
        priority='high',
        notification=messaging.AndroidNotification(
            title=android_notif_title,
            body=android_notif_body,
            sound='faraja_notification',
            channel_id='video_upload_channel',
            color='#E7792A',
            image=image_url,
        ),
    )

    apns_config = messaging.APNSConfig(
        payload=messaging.APNSPayload(
            aps=messaging.Aps(
                alert=messaging.ApsAlert(
                    title=android_notif_title,
                    body=android_notif_body,
                ),
                sound='default',
                mutable_content=True,
                content_available=True,
            ),
        ),
    )

    message = messaging.Message(
        data=string_data,
        token=token,
        android=android_config,
        apns=apns_config,
    )

    print(f"[*] Sending to: {token[:20]}...")
    print(f"[*] Android notification: title='{android_notif_title}'")
    print(f"[*] Android notification: body='{android_notif_body}'")
    print(f"[*] Android notification: sound='faraja_notification'")
    print(f"[*] Android notification: channel_id='video_upload_channel'")
    print(f"[*] Android notification: image='{image_url}'")
    print(f"[*] iOS APNs: alert with title + body, sound='default'")
    print(f"[*] Data payload: {json.dumps(string_data, indent=2)}")
    print("---")

    try:
        response = messaging.send(message)
        print(f"[+] SUCCESS! Response: {response}")
        return True
    except Exception as e:
        cls = type(e).__name__
        print(f"[-] FAILED: {cls}: {e}")
        return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Test FCM push notification')
    parser.add_argument('fcm_token', help='Device FCM registration token')
    parser.add_argument('--image', '-i', default=None, help='Thumbnail image URL')
    parser.add_argument('--title', '-t', default=None, help='Notification title')
    parser.add_argument('--body', '-b', default=None, help='Notification body')
    args = parser.parse_args()

    success = send_test_notification(args.fcm_token, args.title, args.body, args.image)
    sys.exit(0 if success else 1)
