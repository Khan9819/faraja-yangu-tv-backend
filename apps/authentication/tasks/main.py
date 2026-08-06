"""
Celery tasks for video processing and HLS conversion.
"""
import os
import logging
from datetime import timedelta
from celery import shared_task
from django.conf import settings
from django.core.files.storage import default_storage
from apps.authentication.models import User
from apps.common.services.templates import EmailTemplates, EmailTemplateType
from apps.streaming.models import Video
from apps.streaming.services.video_processor import VideoProcessor
from core.services.azure.email.main import AzureEmailService
from farajayangu_be.celery import app as celery_app
from apps.common.services.otp import OTPService
from apps.authentication.models import OTP
from django.utils.timezone import datetime
from django.db import close_old_connections
from django.db.models import Q
logger = logging.getLogger(__name__)

@celery_app.task(bind=True)
def send_welcome_email(self):
    close_old_connections()
    pass

@celery_app.task(bind=True)
def send_verification_email(self, id):
    close_old_connections()
    
    user: User = User.objects.get(id=id)
    
    otp: OTPService = OTPService()
    otp_code = otp.send_otp_email(user)
    
    if otp_code:
        OTP.objects.update_or_create(
            user=user,
            defaults={
                'expires_at': datetime.now() + timedelta(minutes=otp.otp_expiry_minutes),
                'otp': otp_code,
            },
        )
    
    return

@celery_app.task(bind=True)
def send_password_reset_email(self, id):
    close_old_connections()
    
    user: User = User.objects.get(id=id)
    
    otp: OTPService = OTPService()
    otp_code = otp._generate_otp()
    email_templates: EmailTemplates = EmailTemplates()
    html_content = email_templates.get_template(
        EmailTemplateType.PASSWORD_RESET,
        first_name=getattr(user, "first_name", ""),
        otp_code=otp_code,
        otp_expiry_minutes=otp.otp_expiry_minutes,
    )
    
    OTP.objects.update_or_create(
        user=user,
        defaults={
            'expires_at': datetime.now() + timedelta(minutes=otp.otp_expiry_minutes),
            'otp': otp_code,
        },
    )

    azure = AzureEmailService(is_no_reply=True)
    azure.send_email(
        recipient_email=user.email,
        subject="Reset your Faraja Yangu TV password",
        content=html_content,
    )


@celery_app.task(bind=True)
def sync_user_device(self, user_id: int, device_id: str, device_type: str, app_version: str, fcm_token: str):
    """
    Sync user device info in the background.

    Keeps ONE canonical Devices row per physical device and deactivates
    duplicate/stale rows (same device_id or same fcm_token) so the push
    notification path never sends to the same device more than once.

    FCM tokens rotate periodically; without this cleanup every rotation
    would leave an active duplicate row behind and users would receive
    several notifications per video.
    """
    close_old_connections()

    from apps.authentication.models import Devices

    try:
        user = User.objects.get(id=user_id)
        device_id = (device_id or '').strip()
        fcm_token = (fcm_token or '').strip()

        # 1) Locate the canonical row: prefer an exact (device_id, fcm_token)
        #    match, then the most recent row for this device_id, then the most
        #    recent row holding this fcm_token.
        device = None
        if device_id and fcm_token:
            device = Devices.objects.filter(device_id=device_id, fcm_token=fcm_token).first()
        if device is None and device_id:
            device = Devices.objects.filter(device_id=device_id).order_by('-updated_at').first()
        if device is None and fcm_token:
            device = Devices.objects.filter(fcm_token=fcm_token).order_by('-updated_at').first()

        if device is None:
            device = Devices.objects.create(
                device_id=device_id or '',
                fcm_token=fcm_token or '',
                device_type=device_type or '',
                device_os=device_type or '',
                app_version=app_version or '',
                is_active=True,
            )
        else:
            # Update the canonical row in place (token may have rotated).
            device.device_id = device_id or device.device_id
            device.fcm_token = fcm_token or device.fcm_token
            device.device_type = device_type or device.device_type
            device.device_os = device_type or device.device_os
            device.app_version = app_version or device.app_version
            device.is_active = True
            device.save()

        # 2) Deactivate stale duplicates sharing this device_id or fcm_token.
        #    Only the canonical row stays active -> one notification per device.
        Devices.objects.filter(
            Q(device_id=device.device_id) | Q(fcm_token=device.fcm_token)
        ).exclude(id=device.id).update(is_active=False)

        # 3) Ensure the canonical device is linked to the user (M2M).
        if not user.devices.filter(id=device.id).exists():
            user.devices.add(device)
        logger.debug(f"Synced device {device_id} for user {user_id} (canonical row {device.id})")
    except User.DoesNotExist:
        logger.warning(f"sync_user_device: User {user_id} not found")
    except Exception as e:
        logger.error(f"sync_user_device failed: {e}")