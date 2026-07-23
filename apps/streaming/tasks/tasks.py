"""
Celery tasks for video processing and HLS conversion.
"""
import os
import time
from pathlib import Path
import logging
from datetime import timedelta, datetime, timezone
import celery
from celery import shared_task
from django.conf import settings
from django.core.files.storage import default_storage
from apps.analytics.models import Notification
from apps.streaming.models import Video
from apps.streaming.services.video_processor import VideoProcessor
from farajayangu_be.celery import app as celery_app
from apps.authentication.models import Devices, User
from apps.authentication.models import Role
from apps.streaming.socket.utils import send_video_progress, send_video_complete, send_video_error
from django.db import close_old_connections
import threading
import queue
from typing import Callable, Any
logger = logging.getLogger(__name__)

class UserGroupTypes:
    ALL = "all"
    CLIENTS = "clients"
    ADMINS = "admins"
    

class NotificationTypes:
    NEW_VIDEO = "new_video"
    COMMENT_REPLY = "comment_reply"


# Maximum concurrent video processing tasks (assembly + conversion combined).
# Prevents all workers from being occupied by large videos simultaneously,
# which would exhaust DB and Redis connection pools for other requests.
MAX_CONCURRENT_VIDEO_PROCESSING = 3  # Matches --concurrency=3, ~6GB total (3x2GB)
VIDEO_PROCESSING_SEMAPHORE_KEY = "video_processing_semaphore"
SEMAPHORE_TTL = 7200  # 2 hours — auto-expires if counter gets stuck (worker crash without release)


def _acquire_processing_slot(video_id: int, task_id: str) -> bool:
    """Try to acquire a slot in the video processing semaphore.
    
    Uses Redis to track how many video processing tasks are currently running.
    Returns True if a slot was acquired, False if the limit is reached.
    """
    from django.core.cache import cache
    try:
        # Get current count of active processing tasks
        active = cache.get(VIDEO_PROCESSING_SEMAPHORE_KEY, 0)
        if active >= MAX_CONCURRENT_VIDEO_PROCESSING:
            logger.warning(
                f"Video processing slot limit reached ({active}/{MAX_CONCURRENT_VIDEO_PROCESSING}), "
                f"cannot start task {task_id} for video {video_id}"
            )
            return False
        # Try to atomically increment
        new_count = cache.incr(VIDEO_PROCESSING_SEMAPHORE_KEY)
        if new_count is None:
            # Key expired or doesn't exist — set initial value
            cache.set(VIDEO_PROCESSING_SEMAPHORE_KEY, 1, timeout=SEMAPHORE_TTL)
            new_count = 1
        elif new_count > MAX_CONCURRENT_VIDEO_PROCESSING:
            # Overshot — decrement back and fail
            cache.decr(VIDEO_PROCESSING_SEMAPHORE_KEY)
            logger.warning(
                f"Video processing slot race condition: count={new_count}, "
                f"cannot start task {task_id} for video {video_id}"
            )
            return False
        else:
            # Refresh TTL so key doesn't expire mid-processing
            try:
                cache.touch(VIDEO_PROCESSING_SEMAPHORE_KEY, SEMAPHORE_TTL)
            except Exception:
                pass
        logger.info(f"Acquired video processing slot ({new_count}/{MAX_CONCURRENT_VIDEO_PROCESSING}) for task {task_id}")
        return True
    except ValueError:
        # Key doesn't exist yet — set initial value
        try:
            cache.set(VIDEO_PROCESSING_SEMAPHORE_KEY, 1, timeout=SEMAPHORE_TTL)
            return True
        except Exception:
            return False
    except Exception as e:
        logger.error(f"Error acquiring processing slot: {e}")
        return True  # Allow on error to avoid blocking


def _release_processing_slot(task_id: str) -> None:
    """Release a slot in the video processing semaphore."""
    from django.core.cache import cache
    try:
        current = cache.get(VIDEO_PROCESSING_SEMAPHORE_KEY, 0)
        if current > 0:
            new_count = cache.decr(VIDEO_PROCESSING_SEMAPHORE_KEY)
            if new_count is not None and new_count <= 0:
                # Counter at zero — delete key to prevent stale counters
                cache.delete(VIDEO_PROCESSING_SEMAPHORE_KEY)
            else:
                # Refresh TTL so active slots don't expire
                try:
                    cache.touch(VIDEO_PROCESSING_SEMAPHORE_KEY, SEMAPHORE_TTL)
                except Exception:
                    pass
            logger.info(f"Released video processing slot ({max(new_count or 0, 0)}/{MAX_CONCURRENT_VIDEO_PROCESSING}) for task {task_id}")
    except Exception as e:
        logger.error(f"Error releasing processing slot: {e}")    


class DatabaseUpdateQueue:
    """
    Thread-safe FIFO queue for processing database updates asynchronously.
    Prevents blocking in recursive functions and loops.
    """
    def __init__(self):
        self._queue = queue.Queue()
        self._worker_thread = None
        self._stop_event = threading.Event()
        self._started = False
        self._lock = threading.Lock()
    
    def start(self):
        """Start the background worker thread."""
        with self._lock:
            if self._started:
                return
            self._started = True
            self._stop_event.clear()
            self._worker_thread = threading.Thread(target=self._process_queue, daemon=True)
            self._worker_thread.start()
            logger.debug("DatabaseUpdateQueue worker thread started")
    
    def stop(self, timeout=5):
        """Stop the background worker thread and wait for pending updates."""
        with self._lock:
            if not self._started:
                return
            self._stop_event.set()
            if self._worker_thread and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=timeout)
            self._started = False
            logger.debug("DatabaseUpdateQueue worker thread stopped")
    
    def submit(self, update_func: Callable[[], Any]):
        """
        Submit a database update function to the queue.
        The function will be executed in FIFO order by the background thread.
        
        Args:
            update_func: A callable that performs the database update
        """
        if not self._started:
            self.start()
        self._queue.put(update_func)
    
    def _process_queue(self):
        """Background worker that processes queued database updates."""
        while not self._stop_event.is_set():
            try:
                # Wait for next update with timeout to check stop event
                update_func = self._queue.get(timeout=0.5)
                try:
                    update_func()
                except Exception as e:
                    logger.error(f"Error processing database update: {e}", exc_info=True)
                finally:
                    close_old_connections()
                    self._queue.task_done()
            except queue.Empty:
                continue
        
        # Process remaining items in queue before stopping
        while not self._queue.empty():
            try:
                update_func = self._queue.get_nowait()
                try:
                    update_func()
                except Exception as e:
                    logger.error(f"Error processing database update during shutdown: {e}", exc_info=True)
                finally:
                    self._queue.task_done()
            except queue.Empty:
                break


def _get_users(target: UserGroupTypes):
    if target == UserGroupTypes.ALL:
        return User.objects.all()
    elif target == UserGroupTypes.CLIENTS:
        return User.objects.filter(roles__name=Role.ROLES.USER)
    elif target == UserGroupTypes.ADMINS:
        return User.objects.filter(roles__name=Role.ROLES.ADMIN)
    else:
        return User.objects.none()

def _normalize_media_url(url: str) -> str:
    """Convert R2 or relative URLs to the public CMS proxy URL."""
    if not url:
        return ''
    # If already using the CMS domain, return as-is
    if 'cms.farajayangutv.co.tz' in url:
        return url
    # If it's a full R2 URL, extract the path and prefix with CMS
    if 'r2.cloudflarestorage.com' in url:
        import re
        match = re.search(r'/farajayangu-tv/(.+)$', url)
        if match:
            return f'https://cms.farajayangutv.co.tz/media/{match.group(1)}'
    # If absolute URL from another domain, try to extract path
    if url.startswith('http') and '/media/' in url:
        import re
        match = re.search(r'/media/(.+)$', url)
        if match:
            return f'https://cms.farajayangutv.co.tz/media/{match.group(1)}'
    # If relative path, prefix with CMS media URL
    if not url.startswith('http'):
        return f'https://cms.farajayangutv.co.tz/media/{url.lstrip("/")}'
    return url

def _send_notification(fcm_token: str, title: str, body: str, data: dict = None):
    """
    Send push notification to a device via FCM.
    
    Args:
        fcm_token: The device's FCM registration token
        title: Notification title
        body: Notification body
        data: Optional data payload
    """
    import firebase_admin
    from firebase_admin import messaging, credentials
    
    # Initialize Firebase app if not already initialized
    if not firebase_admin._apps:
        cred = credentials.Certificate({
            "type": "service_account",
            "project_id": settings.FIREBASE_PROJECT_ID,
            "private_key_id": settings.FIREBASE_PRIVATE_KEY_ID,
            "private_key": settings.FIREBASE_PRIVATE_KEY,
            "client_email": settings.FIREBASE_CLIENT_EMAIL,
            "client_id": settings.FIREBASE_CLIENT_ID,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{settings.FIREBASE_CLIENT_EMAIL.replace('@', '%40')}",
        })
        firebase_admin.initialize_app(cred)
    
    # FCM requires all data values to be strings
    string_data = {k: str(v) for k, v in (data or {}).items()}
    # Flutter handlers look for 'title' and 'body' in data payload (for foreground rendering)
    string_data.setdefault('title', title)
    string_data.setdefault('body', body)
    
    # Generate a fresh signed URL for the thumbnail (R2 files are private)
    normalized_thumbnail = ''
    raw_thumbnail = data.get('video_thumbnail', '') if data else ''
    if raw_thumbnail and raw_thumbnail != 'None' and raw_thumbnail != '':
        try:
            import boto3
            s3 = boto3.client(
                's3',
                endpoint_url=settings.AWS_S3_ENDPOINT_URL,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=getattr(settings, 'AWS_S3_REGION_NAME', 'auto'),
            )
            normalized_thumbnail = s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': settings.AWS_STORAGE_BUCKET_NAME, 'Key': raw_thumbnail},
                ExpiresIn=604800,  # 7 days
            )
            string_data['video_thumbnail'] = normalized_thumbnail
            logger.info(f"Generated signed thumbnail URL valid for 7 days")
        except Exception as e:
            logger.warning(f"Failed to generate signed thumbnail URL: {e}")
    
    android_config = messaging.AndroidConfig(
        priority='high',
        notification=messaging.AndroidNotification(
            title=title,
            body=body,
            sound='faraja_notification',
            channel_id='video_upload_channel',
            color='#E7792A',
            image=normalized_thumbnail or None,
        ),
    )
    
    apns_config = messaging.APNSConfig(
        payload=messaging.APNSPayload(
            aps=messaging.Aps(
                alert=messaging.ApsAlert(title=title, body=body),
                sound='default',
                mutable_content=True,
                content_available=True,
            ),
        ),
    )
    
    message = messaging.Message(
        notification=messaging.Notification(
            title=title,
            body=body,
            image=normalized_thumbnail or None,
        ),
        data=string_data,
        token=fcm_token,
        android=android_config,
        apns=apns_config,
    )
    
    try:
        response = messaging.send(message)
        logger.info(f"Successfully sent notification: {response}")
        return response
    except Exception as e:
        cls_name = type(e).__name__
        if 'Unregistered' in cls_name or 'NotFound' in cls_name:
            logger.warning(f"FCM token is unregistered: {e}")
        elif 'Invalid' in cls_name:
            logger.error(f"Invalid FCM argument: {e}")
        else:
            logger.error(f"Failed to send notification: {cls_name}: {e}")
        return None

    
@celery_app.task(bind=True)
def send_push_notification(self, target: UserGroupTypes, notification_type: NotificationTypes, title: str, message: str, metadata: dict = None):
    """
    Send push notifications to a group of users + record persistent history.
    Uses DB-level atomic idempotency (SELECT FOR UPDATE) to prevent duplicates.
    
    Args:
        target: User group to send notifications to (ALL, CLIENTS, ADMINS)
        notification_type: Type of notification (NEW_VIDEO, COMMENT_REPLY)
        title: Notification title
        message: Notification body (supports --username-- placeholder)
        metadata: Optional dict with extra data. For videos, include 'video_id' key.
    """
    close_old_connections()
    from django.db import transaction
    
    video_uid = metadata.get('video_id') if metadata else None
    video_id = metadata.get('db_video_id') if metadata else None
    
    # Atomic DB-level idempotency: SELECT FOR UPDATE prevents race conditions
    # where multiple tasks try to send for the same video simultaneously.
    if video_id:
        try:
            from apps.streaming.models import Video
            with transaction.atomic():
                v = Video.objects.select_for_update().only('notification_sent').get(id=video_id)
                if v.notification_sent:
                    logger.info(f"Video {video_id} notification already sent (DB), skipping")
                    return
                # Mark as sent BEFORE sending — any concurrent task will see this
                Video.objects.filter(id=video_id).update(notification_sent=True)
        except Video.DoesNotExist:
            pass
        except Exception as e:
            logger.error(f"DB idempotency check failed for video {video_id}: {e}")
            # Fallback to Redis lock if DB check fails
            from django.core.cache import cache
            notif_lock_key = f"push_notif_lock:{video_id}"
            acquired = cache.add(notif_lock_key, self.request.id, timeout=600)
            if not acquired:
                existing = cache.get(notif_lock_key)
                if existing and existing != self.request.id:
                    logger.info(f"Push notification for video {video_id} already sent (Redis), skipping")
                    return
    
    if not title:
        if notification_type == NotificationTypes.NEW_VIDEO:
            title = "New Video Uploaded"
        elif notification_type == NotificationTypes.COMMENT_REPLY:
            title = "You have a new comment reply"
    
    get_users = _get_users(target)
    sent_count = 0
    failed_count = 0
    
    # Get thumbnail URL for history recording
    thumbnail_url = metadata.get('video_thumbnail', '') if metadata else ''
    
    # Record notifications for ALL users (history) — separate from FCM push
    if notification_type == NotificationTypes.NEW_VIDEO:
        thumbnail_for_history = metadata.get('thumbnail_url', '') if metadata else ''
        try:
            notification_records = [
                Notification(
                    user=user,
                    title=title,
                    message=message.replace('--username--', user.username),
                    type=Notification.NOTIFICATION_TYPES.VIDEO,
                    is_read=False,
                    thumbnail_url=thumbnail_for_history,
                    target_video_slug=video_uid,
                    target_url=f'/Player/{video_uid}' if video_uid else None,
                )
                for user in get_users
            ]
            Notification.objects.bulk_create(notification_records, batch_size=500)
            logger.info(f"Recorded {len(notification_records)} notification history rows for video {video_id}")
        except Exception as e:
            logger.error(f"Failed to record notification history: {e}")
    
    # FCM push to active devices (real-time)
    for user in get_users:
        devices: list[Devices] = user.devices.filter(is_active=True)
        user_message = message.replace("--username--", user.username)
        for device in devices:
            if device.fcm_token:
                result = _send_notification(device.fcm_token, title, user_message, data=metadata)
                if result:
                    sent_count += 1
                else:
                    failed_count += 1
    
    logger.info(f"Push notifications: {sent_count} sent, {failed_count} failed")

@celery_app.task(bind=True, max_retries=2, retry_backoff=30)
def notify_user_of_reply(self, commenter_user_id: int, replier_name: str, comment_text: str, video_uid: str, video_title: str):
    """
    Send a push notification to a single user when someone replies to their comment.
    """
    close_old_connections()

    try:
        user = User.objects.get(id=commenter_user_id)
    except User.DoesNotExist:
        return

    title = f'{replier_name} replied to your comment'
    body = comment_text[:120]

    metadata = {
        'type': 'comment_reply',
        'video_id': str(video_uid),
        'video_title': video_title,
    }

    sent = 0
    for device in user.devices.filter(is_active=True):
        if device.fcm_token:
            result = _send_notification(device.fcm_token, title, body, data=metadata)
            if result:
                sent += 1

    # In-app notification
    Notification.objects.create(
        user=user,
        title=title,
        message=body,
        type=Notification.NOTIFICATION_TYPES.COMMENT,
        target_video_slug=str(video_uid),
        target_url=f'/Player/{video_uid}',
    )

    logger.info(f"Reply notification sent to user {commenter_user_id} ({sent} devices)")


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=2,  # Allow retry on failures (e.g. HLS upload timeout)
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=14400,
    time_limit=18000,
)
def convert_video_to_hls(self, video_id: int, local_video_path: str = None):
    """
    Convert uploaded video to HLS format with multiple quality levels.
    Supports resume from checkpoint on retry.
    Uses Redis lock to prevent duplicate task execution.
    
    Args:
        video_id: ID of the Video object to process
        local_video_path: Optional path to local video file (skips R2 download if provided)
        
    Returns:
        Dictionary with conversion results
    """
    import tempfile
    from django.core.cache import cache
    close_old_connections()
    
    # Acquire semaphore slot to limit concurrent video processing.
    # Poll with sleep instead of self.retry() to avoid consuming Celery max_retries.
    acquired_slot = _acquire_processing_slot(video_id, self.request.id)
    if not acquired_slot:
        logger.info(f"Video {video_id}: waiting for processing slot (max 30 min)...")
        for _ in range(180):  # 180 iterations * 10s = 30 min max wait
            time.sleep(10)
            acquired_slot = _acquire_processing_slot(video_id, self.request.id)
            if acquired_slot:
                break
        if not acquired_slot:
            logger.error(f"Video {video_id}: could not acquire processing slot after 30 min wait")
            return {'success': False, 'error': 'All video processing slots busy, try again later'}
    
    # Initialize database update queue for async writes
    db_queue = DatabaseUpdateQueue()
    db_queue.start()
    
    # Acquire a lock to prevent duplicate task execution for the same video
    # Lock TTL = soft_time_limit (14400s) + 1 hour buffer = 18000s
    lock_key = f"video_conversion_lock_{video_id}"
    lock_acquired = cache.add(lock_key, self.request.id, timeout=18000)
    
    if not lock_acquired:
        # Check if the existing lock is from a different task
        existing_task_id = cache.get(lock_key)
        if existing_task_id and existing_task_id != self.request.id:
            logger.warning(f"Video {video_id} conversion already in progress (task {existing_task_id}), skipping duplicate")
            return {'success': False, 'error': 'Conversion already in progress', 'duplicate': True}
        # If same task ID (retry), continue
        logger.info(f"Continuing conversion for video {video_id} (retry of same task)")
    
    video_file_path = None
    local_hls_dir = None
    conversion_result = None  # Track conversion result for duration
    
    try:
        # Get video object
        video: Video = Video.objects.get(id=video_id)
        
        # Check for checkpoint from previous attempt
        checkpoint = video.processing_checkpoint or {}
        stage = checkpoint.get('stage', 'start')
        completed_variants = checkpoint.get('completed_variants', [])
        
        # If already completed, just return success
        if video.processing_status == 'completed' and video.hls_master_playlist:
            logger.info(f"Video {video_id} already completed, skipping")
            return {'success': True, 'video_id': video_id, 'hls_path': video.hls_path, 'already_complete': True}
        
        video.processing_status = 'processing'
        video.save(update_fields=['processing_status'])
        
        temp_dir = tempfile.gettempdir()
        hls_output_dir = f"videos/hls/{video.uid}"  # Remote path in R2
        local_hls_dir = os.path.join(temp_dir, f"hls_{video_id}")  # Local temp only
        Path(local_hls_dir).mkdir(parents=True, exist_ok=True)
        
        # Determine video file path - use local path if provided, otherwise download from R2
        if local_video_path and os.path.exists(local_video_path):
            video_file_path = local_video_path
            logger.info(f"Using local video file: {video_file_path}")
            send_video_progress(video_id, "converting", 15, "Using local video file, starting conversion...",
                               checkpoint={'stage': 'converting'})
            stage = 'converting'  # Skip download stage
        else:
            if local_video_path:
                logger.warning(f"Local video path provided but file does not exist: {local_video_path}. Will fall back to R2 download.")
            video_file_path = os.path.join(temp_dir, f"video_{video_id}_original.mp4")
        
        # If local file is missing, try downloading assembled backup from R2
        if not os.path.exists(video_file_path):
            assembled_r2_key = checkpoint.get('assembled_r2_key') if checkpoint else None
            if assembled_r2_key and default_storage.exists(assembled_r2_key):
                logger.info(f"Downloading assembled file from R2: {assembled_r2_key}")
                with default_storage.open(assembled_r2_key, 'rb') as src:
                    with open(video_file_path, 'wb') as dst:
                        while True:
                            chunk = src.read(8 * 1024 * 1024)
                            if not chunk: break
                            dst.write(chunk)
                logger.info(f"Downloaded assembled file from R2 to: {video_file_path}")
        
        # Validate disk space before starting
        try:
            import shutil
            stat = shutil.disk_usage(temp_dir)
            free_gb = stat.free / (1024**3)
            logger.info(f"Available disk space: {free_gb:.2f}GB")
            send_video_progress(
                video_id,
                "checking_disk_space",
                0,
                f"Available disk space: {free_gb:.2f}GB",
                checkpoint={'stage': 'disk_space_check'}
            )
            if free_gb < 10:
                raise Exception(f"Insufficient disk space: {free_gb:.2f}GB available, minimum 10GB required")
        except Exception as e:
            logger.warning(f"Could not validate disk space: {str(e)}")
        
        # Stage 1: Download video from R2 (skip if local file already assembled or downloaded)
        # 'assembled' stage comes from assemble_chunks_task checkpoint — file is already local
        if stage in ('start', 'downloading', 'assembled'):
            # Case A: Assembled file from chunk assembly already exists locally — skip download
            if stage == 'assembled' and os.path.exists(video_file_path):
                logger.info(f"Using locally assembled video file for {video_id}: {video_file_path}")
                send_video_progress(video_id, "converting", 10, "Using assembled video, starting conversion...",
                                   checkpoint={'stage': 'converting'})
            # Case B: File doesn't exist locally — must download from R2
            elif not os.path.exists(video_file_path) or stage == 'start':
                send_video_progress(video_id, "downloading", 0, "Starting HLS conversion...",
                                   checkpoint={'stage': 'downloading'})
                logger.info(f"Starting HLS conversion for video {video_id}: {video.title}")
                
                if not video.video:
                    raise ValueError("No video file uploaded")
                
                send_video_progress(video_id, "downloading", 5, "Downloading video from storage...",
                                   checkpoint={'stage': 'downloading'})
                logger.info(f"Downloading video from storage: {video.video.name}")
                
                # Stream download in chunks to avoid loading entire video into memory
                DOWNLOAD_CHUNK_SIZE = 8 * 1024 * 1024  # 8MB chunks
                with default_storage.open(video.video.name, 'rb') as source:
                    with open(video_file_path, 'wb') as dest:
                        while True:
                            chunk = source.read(DOWNLOAD_CHUNK_SIZE)
                            if not chunk:
                                break
                            dest.write(chunk)
                logger.info(f"Video downloaded to: {video_file_path}")
            # Case C: File already downloaded (resume)
            else:
                logger.info(f"Resuming: video already downloaded for {video_id}")
            
            send_video_progress(video_id, "converting", 15, "Video downloaded, starting conversion...",
                               checkpoint={'stage': 'converting'})
        
        # STAGE 2+3: Convert to MP4 per quality (simple, fast, reliable)
        # Replaces complex HLS with single MP4 per quality like BingwaFlix.
        if stage in ('start', 'downloading', 'converting', 'assembled'):
            QUALITY_PRESETS = [
                {'name': '1080p', 'height': 1080, 'bitrate': '2000k', 'audio_bitrate': '128k', 'scale': '1920:1080', 'bandwidth': 2000000},
                {'name': '720p', 'height': 720, 'bitrate': '1200k', 'audio_bitrate': '96k', 'scale': '1280:720', 'bandwidth': 1200000},
                {'name': '480p', 'height': 480, 'bitrate': '600k', 'audio_bitrate': '64k', 'scale': '854:480', 'bandwidth': 600000},
                {'name': '360p', 'height': 360, 'bitrate': '400k', 'audio_bitrate': '64k', 'scale': '640:360', 'bandwidth': 400000},
            ]
            
            video_urls = {}
            quality_count = len(QUALITY_PRESETS)
            
            # Probe video duration for accurate progress
            try:
                probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                       '-of', 'default=noprint_wrappers=1:nokey=1', video_file_path],
                                      capture_output=True, text=True, timeout=30)
                if probe.returncode == 0 and probe.stdout.strip():
                    video_duration = float(probe.stdout.strip())
                    logger.info(f"Video duration: {video_duration}s")
            except Exception:
                video_duration = conversion_result.get('duration', 0) if conversion_result else 0
            
            for idx, q in enumerate(QUALITY_PRESETS):
                variant_name = q['name']
                base_pct = 15 + (idx * 80 // quality_count)
                send_video_progress(video_id, "converting", base_pct,
                                   f"Converting {variant_name}... ({idx+1}/{quality_count})",
                                   checkpoint={'stage': 'converting'})
                
                out_path = os.path.join(temp_dir, f"video_{video_id}_{variant_name}.mp4")
                
                try:
                    cmd = [
                        'ffmpeg', '-i', video_file_path,
                        '-vf', f'scale={q["scale"]}',
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
                        '-profile:v', 'baseline',
                        '-c:a', 'aac', '-b:a', q['audio_bitrate'],
                        '-threads', '3',
                        '-movflags', '+faststart',
                        '-y', out_path,
                    ]
                    
                    logger.info(f"Converting {variant_name}: ultrafast, {q['scale']}, {q['bitrate']}")
                    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True, bufsize=1)
                    
                    for line in proc.stderr:
                        match = re.search(r'time=(\d+):(\d+):(\d+\.?\d*)', line)
                        if match and video_duration > 0:
                            secs = int(match.group(1))*3600 + int(match.group(2))*60 + float(match.group(3))
                            pct = int((secs / video_duration) * 100)
                            if pct % 10 == 0:
                                send_video_progress(video_id, "converting", min(base_pct + pct // quality_count, 90),
                                                  f"Converting {variant_name}: {pct}%",
                                                  checkpoint={'stage': 'converting'})
                    
                    proc.wait()
                    if proc.returncode != 0:
                        raise Exception(f"ffmpeg exit {proc.returncode} for {variant_name}")
                    
                    logger.info(f"{variant_name} completed for video {video_id}")
                    
                    # Upload to R2
                    remote_key = f"{hls_output_dir}/{variant_name}.mp4"
                    with open(out_path, 'rb') as f:
                        default_storage.save(remote_key, f)
                    
                    video_urls[variant_name] = remote_key
                    try: os.remove(out_path)
                    except: pass
                    
                except Exception as e:
                    logger.error(f"{variant_name} failed for video {video_id}: {e}")
                    raise
            
            # Generate and upload master.m3u8
            master_lines = ['#EXTM3U', '#EXT-X-VERSION:3']
            for q in QUALITY_PRESETS:
                if q['name'] in video_urls:
                    master_lines.append(f'#EXT-X-STREAM-INF:BANDWIDTH={q["bandwidth"]},RESOLUTION={q["scale"]}')
                    master_lines.append(f'{q["name"]}.mp4')
            
            master_content = '\n'.join(master_lines) + '\n'
            master_key = f"{hls_output_dir}/master.m3u8"
            from io import BytesIO
            default_storage.save(master_key, BytesIO(master_content.encode()))
            logger.info(f"Master playlist uploaded for video {video_id}: {len(video_urls)} variants")
            
            send_video_progress(video_id, "uploading", 95, f"Converted {len(video_urls)} qualities",
                               checkpoint={'stage': 'finalizing'})
        
         # Stage 3: Upload HLS files (skip if already uploaded)
        if stage in ('start', 'downloading', 'converting', 'uploading', 'assembled'):
            # Guard: confirm the local HLS directory actually exists before attempting upload
            if local_hls_dir and not os.path.isdir(local_hls_dir):
                logger.error(f"Local HLS directory missing at {local_hls_dir} — stages may have been skipped incorrectly (stage={stage}).")
                if stage in ('uploading', 'converting', 'assembled'):
                    raise Exception(f"HLS output directory missing at {local_hls_dir} — conversion did not produce output")
            # Check if already uploaded by checking remote storage
            try:
                remote_master = f"{hls_output_dir}/master.m3u8"
                if default_storage.exists(remote_master):
                    logger.info(f"Resuming: HLS files already uploaded for {video_id}")
                    uploaded_paths = []  # Already uploaded
                    send_video_progress(video_id, "uploading", 90, "HLS files already uploaded",
                                       checkpoint={'stage': 'finalizing'})
                else:
                    # Regenerate master playlist from ACTUAL local files before upload.
                    # This ensures master.m3u8 matches what was actually produced,
                    # not an empty list from a failed/crashed processor run.
                    try:
                        from apps.streaming.services.video_presets import get_enabled_hls_variants
                        import os as _os
                        master_path = _os.path.join(local_hls_dir, 'master.m3u8')
                        existing = _os.path.exists(master_path)
                        master_size = _os.path.getsize(master_path) if existing else 0
                        logger.info(f"Master playlist before upload: exists={existing}, size={master_size}")
                        
                        if not existing or master_size < 100:
                            # Regenerate from actual variant directories in local_hls_dir
                            logger.info(f"Regenerating master playlist from local variant directories for video {video_id}")
                            variants_found = []
                            for preset in get_enabled_hls_variants():
                                variant_name = preset['name']
                                variant_playlist = _os.path.join(local_hls_dir, variant_name, f"{variant_name}.m3u8")
                                if _os.path.exists(variant_playlist):
                                    # Calculate bandwidth from segment files
                                    bandwidth = 800000  # default fallback
                                    try:
                                        seg_files = [f for f in _os.listdir(_os.path.join(local_hls_dir, variant_name)) if f.endswith('.ts')]
                                        if seg_files:
                                            total_bytes = sum(_os.path.getsize(_os.path.join(local_hls_dir, variant_name, f)) for f in seg_files[:5])
                                            avg_seg = total_bytes / len(seg_files[:5])
                                            bandwidth = int((avg_seg * 8) / 6)  # bits per second for ~6s segments
                                    except Exception:
                                        pass
                                    variants_found.append({
                                        'bandwidth': str(max(bandwidth, 500000)),
                                        'resolution': preset['resolution'],
                                        'playlist': f"{variant_name}/{variant_name}.m3u8"
                                    })
                            
                            if variants_found:
                                with open(master_path, 'w') as f:
                                    f.write('#EXTM3U\n')
                                    f.write('#EXT-X-VERSION:3\n')
                                    for v in variants_found:
                                        f.write(f"#EXT-X-STREAM-INF:BANDWIDTH={v['bandwidth']},RESOLUTION={v['resolution']}\n")
                                        f.write(f"{v['playlist']}\n")
                                logger.info(f"Regenerated master playlist with {len(variants_found)} variants")
                    except Exception as regen_err:
                        logger.warning(f"Could not regenerate master playlist: {regen_err}")
                    send_video_progress(video_id, "uploading", 75, "Uploading HLS files to storage...",
                                       checkpoint={'stage': 'uploading'})
                    try:
                        uploaded_paths = upload_hls_files_to_storage(local_hls_dir, hls_output_dir)
                        logger.info(f"Uploaded {len(uploaded_paths)} files to R2 storage")
                        if len(uploaded_paths) == 0:
                            raise Exception("No HLS files found to upload - conversion may have failed silently")
                        send_video_progress(video_id, "uploading", 90, f"Uploaded {len(uploaded_paths)} HLS files",
                                           checkpoint={'stage': 'finalizing'})
                    except Exception as upload_error:
                        logger.error(f"HLS upload failed for video {video_id}: {upload_error}")
                        send_video_error(video_id, "Failed to upload HLS files", str(upload_error))
                        raise
            except Exception as e:
                # If it's an upload error from inside, re-raise it
                if 'upload' in str(e).lower() or 'Failed to upload' in str(e):
                    raise
                # If storage check fails, try uploading anyway
                logger.warning(f"Storage check failed, attempting upload: {e}")
                send_video_progress(video_id, "uploading", 75, "Uploading HLS files to storage...",
                                   checkpoint={'stage': 'uploading'})
                try:
                    uploaded_paths = upload_hls_files_to_storage(local_hls_dir, hls_output_dir)
                    logger.info(f"Uploaded {len(uploaded_paths)} files to R2 storage")
                    if len(uploaded_paths) == 0:
                        raise Exception("No HLS files found to upload - conversion may have failed silently")
                    send_video_progress(video_id, "uploading", 90, f"Uploaded {len(uploaded_paths)} HLS files",
                                       checkpoint={'stage': 'finalizing'})
                except Exception as upload_error:
                    logger.error(f"HLS upload failed for video {video_id}: {upload_error}")
                    send_video_error(video_id, "Failed to upload HLS files", str(upload_error))
                    raise
        
        # Verify master playlist is on R2
        remote_master = f"{hls_output_dir}/master.m3u8"
        if not default_storage.exists(remote_master):
            raise Exception(f"Master playlist missing on R2: {remote_master}")
        
        # Update video object with HLS information
        video.hls_path = hls_output_dir
        video.hls_master_playlist = f"{hls_output_dir}/master.m3u8"
        duration_seconds = conversion_result.get('duration') if conversion_result else None
        if not duration_seconds:
            duration_seconds = extract_duration_from_hls_playlist(local_hls_dir)
        if duration_seconds is not None:
            video.duration = timedelta(seconds=float(duration_seconds))
        video.processing_status = 'completed'
        video.processing_error = None
        video.processing_checkpoint = None  # Clear checkpoint
        video.processing_stage = 'idle'
        video.processing_progress = 100
        video.processing_message = 'Video processing completed'
        video.save(update_fields=[
            'hls_path', 
            'hls_master_playlist', 
            'duration', 
            'processing_status',
            'processing_error',
            'processing_checkpoint',
            'processing_stage',
            'processing_progress',
            'processing_message'
        ])
        
        logger.info(f"Video {video_id} metadata updated successfully")
        
        # Clean up: Delete original video file from R2 if it exists (legacy support)
        # Note: With the new flow, MP4 is kept local and never uploaded to R2
        if video.video:
            try:
                video.video.delete(save=False)
                video.video = None
                video.save(update_fields=['video'])
                logger.info(f"Deleted original MP4 from R2 for video {video_id}")
            except Exception as e:
                logger.warning(f"Could not delete original video from R2: {str(e)}")
        
        # Clean up: Delete ALL local temp files (video + HLS directory)
        cleanup_local_files(video_file_path, local_hls_dir)
        logger.info(f"Cleaned up local temp files for video {video_id}")
        
        logger.info(f"Successfully converted video {video_id} to HLS")
        
        send_video_complete(video_id, "Video processing completed successfully", hls_output_dir)
        
        # Refresh video object to get updated data for push notification
        video.refresh_from_db()
        category_name = getattr(video.category, 'name', 'Uncategorized') if video.category else 'Uncategorized'
        
        # Build enriched metadata for deep-link support
        # Store the raw thumbnail S3 key — _send_notification will generate a signed URL at send-time
        thumbnail_key = ''
        if video.thumbnail:
            try:
                thumbnail_key = video.thumbnail.name
            except Exception:
                thumbnail_key = ''
        
        notification_metadata = {
            'type': 'video_upload',
            'video_id': str(video.uid),
            'db_video_id': video.id,
            'video_title': video.title or '',
            'video_thumbnail': thumbnail_key,
            'video_category': category_name,
            'video_description': video.description or '',
            'video_duration': str(int(video.duration.total_seconds())) if video.duration else '0',
            'video_created_at': video.created_at.isoformat() if video.created_at else '',
            'master_playlist': f"{getattr(settings, 'BASE_URL', 'http://127.0.0.1:8000')}/streaming/hls/{video.uid}/master.m3u8" if video.hls_master_playlist else '',
            'thumbnail_url': video.thumbnail.url if video.thumbnail else '',
        }
        
        send_push_notification.delay(
            UserGroupTypes.CLIENTS,
            NotificationTypes.NEW_VIDEO,
            title=f"{category_name} | {video.title}",
            message=f"new {category_name} Video | {video.title}",
            metadata=notification_metadata,
        )
        
        # Stop the database queue and wait for pending updates
        db_queue.stop(timeout=10)
        
        # Release the lock on successful completion
        cache.delete(lock_key)
        
        return {
            'success': True,
            'video_id': video_id,
            'hls_path': hls_output_dir,
            'duration': conversion_result.get('duration', 0) if conversion_result else 0
        }
        
    except Video.DoesNotExist:
        logger.error(f"Video {video_id} not found")
        send_video_error(video_id, "Video not found")
        db_queue.stop(timeout=5)
        cache.delete(lock_key)  # Release lock
        return {'success': False, 'error': 'Video not found'}
        
    except celery.exceptions.SoftTimeLimitExceeded:
        # Task was killed due to soft time limit
        logger.error(f"Video {video_id} conversion killed - soft time limit exceeded")
        send_video_error(video_id, "Conversion killed - time limit exceeded")
        
        try:
            video = Video.objects.get(id=video_id)
            video.processing_status = 'killed'
            video.processing_error = 'Task killed - time limit exceeded'
            video.save(update_fields=['processing_status', 'processing_error'])
        except:
            pass
        
        db_queue.stop(timeout=5)
        cache.delete(lock_key)
        return {'success': False, 'error': 'Task killed - time limit exceeded', 'killed': True}
    
    except celery.exceptions.Terminated:
        # Task was forcefully terminated (SIGTERM/SIGKILL)
        logger.error(f"Video {video_id} conversion terminated by signal")
        send_video_error(video_id, "Conversion terminated")
        
        try:
            video = Video.objects.get(id=video_id)
            video.processing_status = 'killed'
            video.processing_error = 'Task terminated by system'
            video.save(update_fields=['processing_status', 'processing_error'])
        except:
            pass
        
        db_queue.stop(timeout=5)
        cache.delete(lock_key)
        return {'success': False, 'error': 'Task terminated', 'killed': True}
        
    except Exception as e:
        logger.error(f"Error converting video {video_id} to HLS: {str(e)}")
        send_video_error(video_id, "HLS conversion failed", str(e))
        
        # Update video status to failed (but keep checkpoint for retry)
        try:
            video = Video.objects.get(id=video_id)
            video.processing_status = 'failed'
            video.processing_error = str(e)
            video.save(update_fields=['processing_status', 'processing_error'])
        except:
            pass
        
        db_queue.stop(timeout=5)
        
        # Re-raise so Celery autoretry works (delay() calls) and
        # direct callers (assemble_chunks_task) know conversion failed.
        raise
    
    finally:
        # Always release the semaphore slot, stop queue, and release the lock when task ends
        _release_processing_slot(self.request.id)
        try:
            db_queue.stop(timeout=5)
        except:
            pass
        try:
            cache.delete(lock_key)
        except:
            pass 


def extract_duration_from_hls_playlist(local_hls_dir: str) -> float | None:
    """Fallback: extract total duration from HLS variant playlist EXTINF tags."""
    try:
        if not os.path.isdir(local_hls_dir):
            logger.warning(f"HLS directory does not exist: {local_hls_dir}")
            return None

        playlist_path = None

        for root, dirs, files in os.walk(local_hls_dir):
            m3u8_files = sorted(f for f in files if f.endswith('.m3u8') and not f.startswith('master'))
            if m3u8_files:
                playlist_path = os.path.join(root, m3u8_files[0])
                break

        if not playlist_path:
            logger.warning(f"No variant playlist found for duration extraction in {local_hls_dir}")
            return None

        total = 0.0
        with open(playlist_path, encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.startswith('#EXTINF:'):
                    try:
                        total += float(line.split(':')[1].split(',')[0])
                    except (IndexError, ValueError):
                        pass
        if total > 0:
            logger.info(f"Extracted duration {total:.1f}s from {os.path.basename(playlist_path)}")
            return total
        else:
            logger.warning(f"Playlist {playlist_path} has no EXTINF tags (duration=0)")
    except Exception as e:
        logger.warning(f"Failed to extract duration from HLS playlist: {e}")
    return None


def upload_hls_files_to_storage(local_dir: str, remote_dir: str, max_workers: int = 4) -> list:
    """
    Upload HLS files from local directory to remote storage.
    
    Uses concurrent uploads with ThreadPoolExecutor for faster throughput.
    Each upload has retry logic for resilience.
    
    Args:
        local_dir: Local directory containing HLS files
        remote_dir: Remote directory path in storage
        max_workers: Number of parallel upload workers (default 4)
        
    Returns:
        List of uploaded file paths
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    uploaded_files = []
    files_to_upload = []
    
    try:
        for root, dirs, files in os.walk(local_dir):
            for file in files:
                local_file_path = os.path.join(root, file)
                rel_path = os.path.relpath(local_file_path, local_dir)
                remote_file_path = os.path.join(remote_dir, rel_path).replace('\\', '/')
                files_to_upload.append((local_file_path, remote_file_path))
        
        total_files = len(files_to_upload)
        logger.info(f"Uploading {total_files} HLS files to R2 storage with {max_workers} workers...")
        
        def upload_single_file_with_retry(local_path: str, remote_path: str, max_retries: int = 3) -> str:
            last_error = None
            for attempt in range(max_retries):
                try:
                    with open(local_path, 'rb') as f:
                        default_storage.save(remote_path, f)
                    return remote_path
                except Exception as e:
                    last_error = e
                    logger.warning(f"Upload attempt {attempt + 1}/{max_retries} failed for {remote_path}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
            raise last_error
        
        def upload_file(file_pair):
            local_path, remote_path = file_pair
            return upload_single_file_with_retry(local_path, remote_path)
        
        completed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(upload_file, pair): pair for pair in files_to_upload}
            for future in as_completed(futures):
                pair = futures[future]
                try:
                    uploaded_path = future.result()
                    uploaded_files.append(uploaded_path)
                    completed += 1
                    if completed % 50 == 0 or completed == total_files:
                        logger.info(f"Uploaded {completed}/{total_files} HLS files")
                except Exception as e:
                    logger.error(f"Failed to upload {pair[1]} after retries: {str(e)}")
                    raise
        
        logger.info(f"Successfully uploaded {len(uploaded_files)} HLS files to storage")
        return uploaded_files
        
    except Exception as e:
        logger.error(f"Error uploading HLS files: {str(e)}")
        raise


def cleanup_local_files(video_file_path: str, hls_dir: str):
    """
    Clean up local temporary files after processing.
    
    Args:
        video_file_path: Path to original video file
        hls_dir: Path to HLS output directory
    """
    try:
        import tempfile
        temp_dir = tempfile.gettempdir()
        
        # Remove original video if it's a temp file
        if video_file_path and os.path.exists(video_file_path):
            # Check if file is in temp directory
            if os.path.dirname(video_file_path).startswith(temp_dir):
                os.remove(video_file_path)
                logger.debug(f"Removed temp video file: {video_file_path}")
        
        # Remove HLS directory if it's a temp location
        if hls_dir and os.path.exists(hls_dir):
            # Check if directory is in temp directory
            if hls_dir.startswith(temp_dir):
                import shutil
                shutil.rmtree(hls_dir)
                logger.debug(f"Removed temp HLS directory: {hls_dir}")
            
    except Exception as e:
        logger.warning(f"Error during cleanup: {str(e)}")


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=28800,  # 8 hours — assembly + direct conversion for 46+ min videos
    time_limit=32400,   # 9 hours
)
def assemble_chunks_task(self, video_id: int, filename: str):
    """
    Assemble uploaded chunks into a complete video file in the background.
    
    Uses streaming approach to avoid loading all chunks into memory at once.
    Writes chunks to a LOCAL temp file and keeps it there for HLS conversion.
    Does NOT upload the assembled MP4 to R2 - only final HLS files are uploaded.
    
    Args:
        video_id: ID of the Video object
        filename: Original filename for the assembled video
        
    Returns:
        Dictionary with assembly results including local_video_path
    """
    import tempfile
    import shutil
    from django.core.cache import cache

    close_old_connections()
    
    # Acquire semaphore slot to limit concurrent video processing.
    # Poll with sleep instead of self.retry() to avoid consuming Celery max_retries.
    acquired_slot = _acquire_processing_slot(video_id, self.request.id)
    if not acquired_slot:
        logger.info(f"Video {video_id}: waiting for processing slot (max 30 min)...")
        for _ in range(180):  # 180 iterations * 10s = 30 min max wait
            time.sleep(10)
            acquired_slot = _acquire_processing_slot(video_id, self.request.id)
            if acquired_slot:
                break
        if not acquired_slot:
            logger.error(f"Video {video_id}: could not acquire processing slot after 30 min wait")
            return {'success': False, 'error': 'All video processing slots busy, try again later'}
    
    # Idempotency lock: prevent duplicate assembly tasks for the same video
    lock_key = f"chunk_assembly_lock_{video_id}"
    lock_acquired = cache.add(lock_key, self.request.id, timeout=10800)
    if not lock_acquired:
        existing_task_id = cache.get(lock_key)
        if existing_task_id and existing_task_id != self.request.id:
            logger.warning(f"Video {video_id} assembly already in progress (task {existing_task_id}), skipping")
            return {'success': False, 'error': 'Assembly already in progress', 'duplicate': True}
    
    # Initialize database update queue for async writes
    db_queue = DatabaseUpdateQueue()
    db_queue.start()
    
    temp_assembled_path = None
    
    try:
        video = Video.objects.get(id=video_id)
        
        # Check for checkpoint from previous attempt
        checkpoint = video.processing_checkpoint or {}
        start_chunk = checkpoint.get('assembled_chunks', 0)
        stage = checkpoint.get('stage', 'assembling')
        local_video_path = checkpoint.get('local_video_path')
        
        # If assembly was completed and local file exists, skip to conversion
        if stage == 'assembled' and local_video_path and os.path.exists(local_video_path):
            logger.info(f"Resuming from checkpoint: assembly already complete for video {video_id}")
            send_video_progress(video_id, "assembling", 100, "Assembly complete, starting HLS conversion...")
            # Route through shared trigger (feature-flagged)
            from apps.streaming.services.conversion_client import trigger_video_processing
            trigger_video_processing(video, source_key=local_video_path)
            logger.info(f"Triggered video processing for video {video.id}")
            return {'success': True, 'video_id': video.id, 'local_video_path': local_video_path, 'resumed': True}
        
        video.processing_status = 'assembling'
        video.save(update_fields=['processing_status'])
        
        if start_chunk > 0:
            logger.info(f"Resuming assembly from chunk {start_chunk} for video {video_id}")
            send_video_progress(video_id, "assembling", 5, f"Resuming from chunk {start_chunk}...")
        else:
            send_video_progress(video_id, "assembling", 0, "Starting chunk assembly...")
        
        chunk_dir = f"videos/chunks/{video_id}"
        
        # Use list_objects_v2 for fast chunk discovery (avoids 1800+ individual exists() calls)
        chunk_files = []
        try:
            if hasattr(default_storage, 'connection') and hasattr(default_storage.connection, 'meta'):
                s3_client = default_storage.connection.meta.client
                paginator = s3_client.get_paginator('list_objects_v2')
                pages = paginator.paginate(Bucket=default_storage.bucket_name, Prefix=f"{chunk_dir}/")
                for page in pages:
                    for obj in page.get('Contents', []):
                        chunk_files.append(obj['Key'])
                chunk_files.sort()
            else:
                # Fallback: iterate with exists()
                chunk_index = 0
                while True:
                    chunk_path = os.path.join(chunk_dir, f"chunk_{chunk_index:04d}")
                    if not default_storage.exists(chunk_path):
                        break
                    chunk_files.append(chunk_path)
                    chunk_index += 1
        except Exception as e:
            logger.warning(f"Bulk chunk listing failed, falling back to exists(): {e}")
            chunk_index = 0
            while True:
                chunk_path = os.path.join(chunk_dir, f"chunk_{chunk_index:04d}")
                if not default_storage.exists(chunk_path):
                    break
                chunk_files.append(chunk_path)
                chunk_index += 1
        
        if not chunk_files:
            logger.error(f"No chunks found for video {video_id}")
            send_video_error(video_id, "No chunks found for this video")
            return {'success': False, 'error': 'No chunks found for this video'}
        
        total_chunks = len(chunk_files)
        logger.info(f"Assembling {total_chunks} chunks for video {video_id}")
        send_video_progress(video_id, "assembling", 5, f"Found {total_chunks} chunks to assemble")
        
        # Use local temp file - DO NOT upload to R2
        # The file stays local until HLS conversion is complete
        temp_assembled_path = os.path.join(tempfile.gettempdir(), f"video_{video_id}_original.mp4")
        STREAM_CHUNK_SIZE = 8 * 1024 * 1024  # 8MB read buffer
        
        # Determine file mode based on resume state
        file_mode = 'ab' if start_chunk > 0 and os.path.exists(temp_assembled_path) else 'wb'
        
        # Stream chunks to local temp file
        with open(temp_assembled_path, file_mode) as assembled_file:
            for i, chunk_path in enumerate(chunk_files):
                # Skip already processed chunks on resume
                if i < start_chunk:
                    continue
                    
                with default_storage.open(chunk_path, 'rb') as chunk_file:
                    while True:
                        data = chunk_file.read(STREAM_CHUNK_SIZE)
                        if not data:
                            break
                        assembled_file.write(data)
                
                # Close stale DB connections periodically to prevent connection pool exhaustion
                # during long-running assembly (especially for large videos)
                if i % 20 == 0:
                    close_old_connections()
                
                progress = int(10 + (i + 1) / total_chunks * 70)  # 10-80% for assembly
                
                # Save checkpoint every 50 chunks using queue
                if (i + 1) % 50 == 0:
                    send_video_progress(
                        video_id, "assembling", progress, 
                        f"Assembled chunk {i + 1}/{total_chunks}",
                        checkpoint={'stage': 'assembling', 'assembled_chunks': i + 1}
                    )
                    # Queue checkpoint update instead of blocking
                    current_chunk = i + 1
                    def update_checkpoint(cc=current_chunk):
                        try:
                            v = Video.objects.get(id=video_id)
                            v.processing_checkpoint = {'stage': 'assembling', 'assembled_chunks': cc}
                            v.save(update_fields=['processing_checkpoint'])
                        except Exception as e:
                            logger.error(f"Failed to update checkpoint for video {video_id}: {e}")
                    db_queue.submit(update_checkpoint)
                elif i == total_chunks - 1:
                    send_video_progress(video_id, "assembling", progress, f"Assembled chunk {i + 1}/{total_chunks}")
        
        send_video_progress(video_id, "assembling", 85, "Assembly complete")
        
        # Chunks retained in R2 for streaming download support
        # (previously deleted — now kept as downloadable MP4 source)
        
        # Save checkpoint with local path - DO NOT upload to R2 (queue this update)
        def save_final_checkpoint():
            try:
                v = Video.objects.get(id=video_id)
                v.processing_checkpoint = {'stage': 'assembled', 'local_video_path': temp_assembled_path, 'assembled_r2_key': assembled_r2_key}
                v.save(update_fields=['processing_checkpoint'])
            except Exception as e:
                logger.error(f"Failed to save final checkpoint for video {video_id}: {e}")
        db_queue.submit(save_final_checkpoint)
        
        # Upload assembled file to R2 as backup (survives container restarts)
        assembled_r2_key = f"videos/assembled/{video_id}.mp4"
        try:
            with open(temp_assembled_path, 'rb') as f:
                default_storage.save(assembled_r2_key, f)
            logger.info(f"Uploaded assembled file to R2: {assembled_r2_key}")
        except Exception as e:
            logger.warning(f"Could not upload assembled file to R2: {e}. Will rely on local file.")
            assembled_r2_key = None
        
        # Wait for queue to process pending updates before continuing
        db_queue.stop(timeout=10)
        
        logger.info(f"Successfully assembled video {video_id} at local path: {temp_assembled_path}")
        send_video_progress(video_id, "assembling", 100, "Assembly complete, starting HLS conversion...")
        
        try:
            logger.info(f"Starting HLS conversion directly for video {video.id}")
            result = convert_video_to_hls(video.id, temp_assembled_path)
            if result and isinstance(result, dict) and not result.get('success', True):
                raise Exception(result.get('error', 'Conversion returned failure'))
            logger.info(f"HLS conversion completed for video {video.id}")
        except Exception as e:
            logger.error(f"Conversion failed for video {video.id}: {str(e)}", exc_info=True)
            send_video_error(video_id, "HLS conversion failed", str(e))
            return {'success': False, 'error': str(e), 'video_id': video.id}
        
        return {
            'success': True,
            'video_id': video.id,
            'local_video_path': temp_assembled_path,
            'chunks_assembled': len(chunk_files)
        }
        
    except Video.DoesNotExist:
        logger.error(f"Video {video_id} not found")
        send_video_error(video_id, "Video not found")
        db_queue.stop(timeout=5)
        return {'success': False, 'error': 'Video not found'}
        
    except Exception as e:
        logger.error(f"Error assembling chunks for video {video_id}: {str(e)}", exc_info=True)
        send_video_error(video_id, "Error assembling video", str(e))
        db_queue.stop(timeout=5)
        raise
    
    finally:
        _release_processing_slot(self.request.id)
        try:
            db_queue.stop(timeout=5)
        except:
            pass
        try:
            cache.delete(lock_key)
        except:
            pass
    
    # NOTE: Do NOT clean up temp file here - it's needed by convert_video_to_hls
    # The conversion task will clean it up after successful HLS upload


@celery_app.task(bind=True)
def delete_video_files_task(self, hls_path: str, video_uid: str):
    """
    Delete HLS files and related video assets from storage in the background.
    Uses boto3 to recursively delete all files with the given prefix.
    
    Args:
        hls_path: Path to the HLS directory (e.g., 'videos/hls/<uid>')
        video_uid: The video's unique identifier
        
    Returns:
        Dictionary with deletion results
    """
    import boto3
    from django.conf import settings
    
    deleted_count = 0
    
    try:
        if not hls_path:
            logger.info(f"No HLS path provided for video {video_uid}")
            return {'success': True, 'deleted': 0, 'video_uid': video_uid}
        
        # Ensure path ends with / for proper prefix matching
        prefix = hls_path.rstrip('/') + '/'
        
        # Initialize S3 client for R2
        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            region_name=settings.AWS_S3_REGION_NAME
        )
        
        bucket_name = settings.AWS_STORAGE_BUCKET_NAME
        
        # List all objects with this prefix (recursively gets all files in subdirectories)
        objects_to_delete = []
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
        
        for page in pages:
            for obj in page.get('Contents', []):
                objects_to_delete.append({'Key': obj['Key']})
        
        if not objects_to_delete:
            logger.info(f"No files found at {prefix} for video {video_uid}")
            return {'success': True, 'deleted': 0, 'video_uid': video_uid}
        
        logger.info(f"Found {len(objects_to_delete)} files to delete for video {video_uid}")
        
        # Delete objects in batches (S3 allows up to 1000 per request)
        for i in range(0, len(objects_to_delete), 1000):
            batch = objects_to_delete[i:i+1000]
            response = s3_client.delete_objects(
                Bucket=bucket_name,
                Delete={'Objects': batch}
            )
            deleted_count += len(batch)
            
            # Log any errors
            if 'Errors' in response:
                for error in response['Errors']:
                    logger.warning(f"Error deleting {error['Key']}: {error['Message']}")
        
        logger.info(f"Deleted {deleted_count} files for video {video_uid}")
        return {'success': True, 'deleted': deleted_count, 'video_uid': video_uid}
        
    except Exception as e:
        logger.error(f"Error deleting video files for {video_uid}: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


@celery_app.task(bind=True)
def cleanup_stale_chunks(self):
    """
    Clean up chunk files older than 12 hours.
    
    This task runs daily at midnight to remove orphaned chunks
    from incomplete uploads.
    """
    chunk_base_dir = "videos/chunks"
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=12)
    deleted_count = 0
    
    try:
        # List all video chunk directories
        try:
            dirs, _ = default_storage.listdir(chunk_base_dir)
        except FileNotFoundError:
            logger.info("No chunk directory found, nothing to clean up")
            return {'success': True, 'deleted': 0}
        
        for video_dir in dirs:
            chunk_dir = f"{chunk_base_dir}/{video_dir}"
            try:
                _, files = default_storage.listdir(chunk_dir)
            except FileNotFoundError:
                continue
            
            dir_has_old_chunks = False
            for filename in files:
                if not filename.startswith('chunk_'):
                    continue
                
                chunk_path = f"{chunk_dir}/{filename}"
                try:
                    modified_time = default_storage.get_modified_time(chunk_path)
                    if modified_time < cutoff_time:
                        print(f"Deleting {chunk_path}")
                        default_storage.delete(chunk_path)
                        deleted_count += 1
                        dir_has_old_chunks = True
                        print(f"Deleted stale chunk: {chunk_path}")
                        logger.debug(f"Deleted stale chunk: {chunk_path}")
                except Exception as e:
                    logger.warning(f"Could not process chunk {chunk_path}: {e}")
            
            # Try to remove empty directory
            if dir_has_old_chunks:
                try:
                    _, remaining_files = default_storage.listdir(chunk_dir)
                    if not remaining_files:
                        default_storage.delete(chunk_dir)
                        logger.debug(f"Removed empty chunk directory: {chunk_dir}")
                except Exception:
                    pass
        
        logger.info(f"Chunk cleanup completed: deleted {deleted_count} stale chunks")
        return {'success': True, 'deleted': deleted_count}
        
    except Exception as e:
        logger.error(f"Error during chunk cleanup: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


@celery_app.task(bind=True)
def cleanup_orphaned_hls_files(self, force=False):
    """
    Clean up HLS files from storage where the corresponding Video record
    no longer exists in the database.
    
    Args:
        force: If True, also delete directories with irregular (non-UUID) names
    
    This task runs periodically to remove orphaned HLS directories
    from deleted videos.
    """
    hls_base_dir = "videos/hls"
    deleted_count = 0
    checked_count = 0
    irregular_deleted_count = 0
    
    try:
        # For S3/R2 storage, we need to use boto3 client directly
        import boto3
        from django.conf import settings
        
        # Initialize S3 client
        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            region_name=settings.AWS_S3_REGION_NAME
        )
        
        bucket_name = settings.AWS_STORAGE_BUCKET_NAME
        
        # List all objects with the HLS prefix to find unique video UIDs
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name, Prefix=f"{hls_base_dir}/", Delimiter='/')
        
        video_uids = set()
        for page in pages:
            # CommonPrefixes contains the "directory" prefixes
            for prefix_info in page.get('CommonPrefixes', []):
                prefix = prefix_info['Prefix']
                # Extract UID from prefix like "videos/hls/uuid/"
                parts = prefix.rstrip('/').split('/')
                if len(parts) >= 3:
                    video_uid = parts[2]
                    video_uids.add(video_uid)
        
        logger.info(f"Found {len(video_uids)} HLS directories to check")
        
        for video_uid in video_uids:
            checked_count += 1
            
            # Validate UUID format before querying database
            is_valid_uuid = False
            try:
                from uuid import UUID
                UUID(video_uid)
                is_valid_uuid = True
            except (ValueError, AttributeError):
                if force:
                    logger.warning(f"Invalid UUID format in directory name: {video_uid}, will delete (force=True)")
                else:
                    logger.warning(f"Invalid UUID format in directory name: {video_uid}, skipping (use force=True to delete)")
                    continue
            
            # Check if Video with this UID exists in database (only for valid UUIDs)
            video_exists = False
            if is_valid_uuid:
                video_exists = Video.objects.filter(uid=video_uid).exists()
            
            # Delete if: (1) invalid UUID and force=True, OR (2) valid UUID but video doesn't exist
            should_delete = (not is_valid_uuid and force) or (is_valid_uuid and not video_exists)
            
            if should_delete:
                hls_path = f"{hls_base_dir}/{video_uid}/"
                reason = "irregular name" if not is_valid_uuid else "not found in database"
                logger.warning(f"Video {video_uid} {reason}, deleting HLS files at {hls_path}")
                
                try:
                    # List all objects with this prefix (all files in the directory)
                    objects_to_delete = []
                    paginator = s3_client.get_paginator('list_objects_v2')
                    pages = paginator.paginate(Bucket=bucket_name, Prefix=hls_path)
                    
                    for page in pages:
                        for obj in page.get('Contents', []):
                            objects_to_delete.append({'Key': obj['Key']})
                    
                    logger.info(f"Found {len(objects_to_delete)} files in {hls_path}")
                    
                    # Delete objects in batches (S3 allows up to 1000 per request)
                    if objects_to_delete:
                        for i in range(0, len(objects_to_delete), 1000):
                            batch = objects_to_delete[i:i+1000]
                            response = s3_client.delete_objects(
                                Bucket=bucket_name,
                                Delete={'Objects': batch}
                            )
                            batch_deleted = len(batch)
                            deleted_count += batch_deleted
                            
                            if not is_valid_uuid:
                                irregular_deleted_count += batch_deleted
                            
                            logger.warning(f"Deleted {batch_deleted} orphaned HLS files from {hls_path}")
                            
                            # Log any errors
                            if 'Errors' in response:
                                for error in response['Errors']:
                                    logger.warning(f"Error deleting {error['Key']}: {error['Message']}")
                    else:
                        logger.info(f"No files found in {hls_path}")
                        
                except Exception as e:
                    logger.error(f"Error deleting orphaned HLS for {video_uid}: {e}")
        
        result_msg = f"Orphaned HLS cleanup completed: checked {checked_count} directories, deleted {deleted_count} files"
        if irregular_deleted_count > 0:
            result_msg += f" ({irregular_deleted_count} from irregular names)"
        logger.warning(result_msg)
        
        return {
            'success': True, 
            'deleted': deleted_count, 
            'checked': checked_count,
            'irregular_deleted': irregular_deleted_count
        }
        
    except Exception as e:
        logger.error(f"Error during orphaned HLS cleanup: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=2,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=7200,
    time_limit=9000,
)
def import_video_from_google_drive(self, video_id: int, google_drive_url: str):
    """
    Background task to download a video from Google Drive and trigger HLS processing.

    Workflow:
        1. Download the file from Google Drive to a local temp path.
        2. Update the GoogleDriveImport record with progress.
        3. Hand off the local file to convert_video_to_hls (same path used by
           assemble_chunks_task so the existing pipeline is reused).

    Args:
        video_id: ID of the Video record.
        google_drive_url: Public Google Drive share link.
    """
    import tempfile
    from apps.streaming.models import GoogleDriveImport
    from apps.streaming.services.google_drive import (
        extract_google_drive_file_id,
        download_from_google_drive,
    )

    close_old_connections()

    gdrive_import = None

    try:
        video = Video.objects.get(id=video_id)
        gdrive_import = GoogleDriveImport.objects.get(video=video)

        # Extract file ID (already validated in the view, but be safe)
        file_id = extract_google_drive_file_id(google_drive_url)
        if not file_id:
            gdrive_import.status = 'failed'
            gdrive_import.message = 'Could not extract file ID from URL'
            gdrive_import.save(update_fields=['status', 'message', 'updated_at'])
            return {'success': False, 'error': 'Invalid Google Drive URL'}

        # --- Stage 1: Download ------------------------------------------------
        gdrive_import.status = 'downloading'
        gdrive_import.progress = 0
        gdrive_import.message = 'Downloading from Google Drive...'
        gdrive_import.save(update_fields=['status', 'progress', 'message', 'updated_at'])

        # Also push a WebSocket update so the existing progress UI works
        send_video_progress(
            video_id, "downloading", 0,
            "Downloading from Google Drive...",
            status="processing",
        )

        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"video_{video_id}_gdrive.mp4")

        def update_progress(progress: int):
            """Callback invoked by the downloader (0-80 range)."""
            gdrive_import.progress = progress
            gdrive_import.message = f'Downloading from Google Drive... {progress}%'
            gdrive_import.save(update_fields=['progress', 'message', 'updated_at'])
            # Mirror to WebSocket
            send_video_progress(
                video_id, "downloading", progress,
                f"Downloading from Google Drive... {progress}%",
                status="processing",
                persist=False,  # already persisted above
            )

        download_from_google_drive(file_id, temp_path, progress_callback=update_progress)

        logger.info(f"Google Drive download complete for video {video_id}: {temp_path}")

        # --- Stage 2: Hand off to HLS pipeline --------------------------------
        gdrive_import.status = 'processing'
        gdrive_import.progress = 85
        gdrive_import.message = 'Download complete. Starting HLS conversion...'
        gdrive_import.save(update_fields=['status', 'progress', 'message', 'updated_at'])

        video.processing_status = 'processing'
        video.save(update_fields=['processing_status'])

        send_video_progress(
            video_id, "converting", 85,
            "Download complete. Starting HLS conversion...",
            status="processing",
        )

        # Route through shared trigger (feature-flagged)
        from apps.streaming.services.conversion_client import trigger_video_processing
        trigger_video_processing(video, source_key=temp_path)
        logger.info(
            f"Triggered video processing for video {video.id} "
            f"(Google Drive import)"
        )

        # Mark import itself as completed (HLS progress is tracked separately)
        gdrive_import.status = 'completed'
        gdrive_import.progress = 100
        gdrive_import.message = 'Import completed. HLS conversion in progress.'
        gdrive_import.save(update_fields=['status', 'progress', 'message', 'updated_at'])

        return {
            'success': True,
            'video_id': video_id,
            'local_video_path': temp_path,
            'hls_task_id': task.id,
        }

    except Video.DoesNotExist:
        logger.error(f"Video {video_id} not found for Google Drive import")
        if gdrive_import:
            gdrive_import.status = 'failed'
            gdrive_import.message = 'Video record not found'
            gdrive_import.save(update_fields=['status', 'message', 'updated_at'])
        return {'success': False, 'error': 'Video not found'}

    except GoogleDriveImport.DoesNotExist:
        logger.error(f"GoogleDriveImport record not found for video {video_id}")
        return {'success': False, 'error': 'Import record not found'}

    except Exception as e:
        logger.error(
            f"Error importing video {video_id} from Google Drive: {str(e)}",
            exc_info=True,
        )
        send_video_error(video_id, "Google Drive import failed", str(e))

        if gdrive_import:
            gdrive_import.status = 'failed'
            gdrive_import.progress = 0
            gdrive_import.message = str(e)
            gdrive_import.error = str(e)
            gdrive_import.save(update_fields=['status', 'progress', 'message', 'error', 'updated_at'])

        # Clean up temp file on failure
        try:
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.remove(temp_path)
                logger.debug(f"Cleaned up temp file after failure: {temp_path}")
        except Exception:
            pass


@celery_app.task(bind=True)
def reconstruct_mp4_for_download_task(self, video_id: int):
    """
    Reconstruct MP4 from existing HLS segments and upload to R2.
    
    Runs OUTSIDE the upload/conversion pipeline — triggered by a
    Django signal after processing_status becomes 'completed'.
    Does NOT touch chunks, upload, or HLS conversion.
    """
    import subprocess

    try:
        video = Video.objects.get(id=video_id)
    except Video.DoesNotExist:
        logger.error(f"reconstruct_mp4: Video {video_id} not found")
        return {'success': False, 'error': 'Video not found'}

    if video.download_path:
        logger.info(f"reconstruct_mp4: Video {video_id} already has download_path, skipping")
        return {'success': True, 'skipped': True}

    if not video.hls_path:
        logger.warning(f"reconstruct_mp4: Video {video_id} has no hls_path, skipping")
        return {'success': False, 'error': 'No HLS path'}

    from django.conf import settings
    backend_url = getattr(settings, 'BACKEND_URL', 'https://backend.farajayangutv.co.tz')
    playlist_url = f'{backend_url}/streaming/hls/{video.uid}/master.m3u8'

    tmp_fd, output_path = None, None
    try:
        tmp_fd, output_path = tempfile.mkstemp(suffix='.mp4')
        os.close(tmp_fd)

        cmd = [
            'ffmpeg', '-y',
            '-i', playlist_url,
            '-c', 'copy',
            '-bsf:a', 'aac_adtstoasc',
            '-movflags', '+faststart',
            '-reconnect', '1',
            '-reconnect_at_eof', '1',
            '-reconnect_streamed', '1',
            '-reconnect_delay_max', '30',
            '-timeout', '0',
            '-loglevel', 'error',
            output_path,
        ]

        logger.info(f"reconstruct_mp4: Running ffmpeg for video {video_id}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)

        if result.returncode != 0:
            logger.error(f"reconstruct_mp4: ffmpeg failed for {video_id}: {result.stderr}")
            return {'success': False, 'error': result.stderr[-200:]}

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 10000:
            logger.error(f"reconstruct_mp4: Output file too small for {video_id}")
            return {'success': False, 'error': 'Output file too small'}

        r2_path = f'videos/downloads/{video.uid}/original.mp4'
        with open(output_path, 'rb') as f:
            default_storage.save(r2_path, f)

        video.download_path = r2_path
        video.save(update_fields=['download_path'])

        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        logger.info(f"reconstruct_mp4: Done {video.uid} → {r2_path} ({size_mb:.1f} MB)")
        return {'success': True, 'path': r2_path, 'size_mb': size_mb}

    except subprocess.TimeoutExpired:
        logger.error(f"reconstruct_mp4: Timeout for video {video_id}")
        return {'success': False, 'error': 'Timeout'}
    except Exception as e:
        logger.error(f"reconstruct_mp4: Error for video {video_id}: {e}")
        return {'success': False, 'error': str(e)}
    finally:
        if output_path and os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass