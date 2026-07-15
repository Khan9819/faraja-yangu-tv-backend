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
    Uses update_or_create for a single DB round-trip.
    """
    close_old_connections()
    
    from apps.authentication.models import Devices
    
    try:
        user = User.objects.get(id=user_id)
        device, _ = Devices.objects.update_or_create(
            device_id=device_id,
            defaults={
                'device_type': device_type or '',
                'device_os': device_type or '',
                'app_version': app_version or '',
                'fcm_token': fcm_token or '',
                'is_active': True,
            }
        )
        # Ensure device is linked to user (M2M)
        if not user.devices.filter(id=device.id).exists():
            user.devices.add(device)
        logger.debug(f"Synced device {device_id} for user {user_id}")
    except User.DoesNotExist:
        logger.warning(f"sync_user_device: User {user_id} not found")
    except Exception as e:
        logger.error(f"sync_user_device failed: {e}")