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
from apps.streaming.services.video_processor import (
    VideoProcessor,
    CONVERSION_START,
    CONVERSION_END,
    UPLOAD_NEAR_DONE,
)
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
    from firebase_admin.exceptions import InvalidArgumentError
    
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
    string_data['title'] = title
    string_data['body'] = body
    
    # Data-only message on Android: the Flutter app renders ONE rich notification
    # (with the cover image) via firebase_messaging_background_handler.
    # If we also sent a `notification` block, Android would show a second plain
    # notification (no image) on top of the app's rich one -> duplicates.
    android_config = messaging.AndroidConfig(
        priority='high',
    )
    
    # iOS keeps a real APNS alert so notifications still display reliably.
    apns_config = messaging.APNSConfig(
        payload=messaging.APNSPayload(
            aps=messaging.Aps(
                alert=messaging.ApsAlert(
                    title=title,
                    body=body,
                ),
                sound='default',
                mutable_content=True,
                content_available=True,
            ),
        ),
    )
    
    message = messaging.Message(
        data=string_data,
        token=fcm_token,
        android=android_config,
        apns=apns_config,
    )
    
    try:
        response = messaging.send(message)
        logger.info(f"Successfully sent notification: {response}")
        return response
    except messaging.UnregisteredError:
        # Distinct value (False) so callers can deactivate the stale device row.
        logger.warning("FCM token is unregistered")
        return False
    except InvalidArgumentError as e:
        # Invalid/malformed token (e.g. fake or corrupted). Treat like a dead
        # token so callers deactivate the row instead of crashing the whole
        # notification task for every other device.
        logger.warning(f"Invalid FCM token (deactivating row): {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")
        return None


def _video_notification_image(video) -> str:
    """Best available image URL for a video's rich push notification.

    Falls back down the chain (thumbnail -> portrait_cover -> tv_poster ->
    tv_landscape -> category thumbnail) so notifications always carry an
    image when ANY cover is set — otherwise the app shows a plain
    text-only notification ("notification without image").
    """
    for field in ('thumbnail', 'portrait_cover', 'tv_poster', 'tv_landscape'):
        image_field = getattr(video, field, None)
        if image_field:
            try:
                return image_field.url
            except Exception:
                continue
    category = getattr(video, 'category', None)
    if category and category.thumbnail:
        try:
            return category.thumbnail.url
        except Exception:
            pass
    return ''


@celery_app.task(bind=True)
def send_push_notification(self, target: UserGroupTypes, notification_type: NotificationTypes, title: str, message: str, metadata: dict = None):
    """Send push notifications with DB atomic dedup (SELECT FOR UPDATE).

    Sends at most ONE FCM message per unique device token so users with
    accumulated/stale device rows (rotated FCM tokens, re-installs) receive
    a single notification instead of several duplicates.
    """
    close_old_connections()
    from django.db import transaction
    
    video_uid = metadata.get('video_id') if metadata else None
    video_id = metadata.get('db_video_id') if metadata else None
    
    # Atomic DB idempotency — one notification per video
    if video_id:
        try:
            with transaction.atomic():
                v = Video.objects.select_for_update().only('notification_sent').get(id=video_id)
                if v.notification_sent:
                    logger.info(f"Video {video_id} notification already sent, skipping")
                    return
                Video.objects.filter(id=video_id).update(notification_sent=True)
        except Video.DoesNotExist:
            pass
        except Exception as e:
            logger.error(f"DB idempotency failed for {video_id}: {e}")
    
    # Sensible default titles when none supplied (empty-title notifications
    # render as blank alerts on devices).
    if not title:
        title = "New Video Uploaded" if notification_type == NotificationTypes.NEW_VIDEO else "You have a new comment reply"

    get_users = _get_users(target)
    sent_count = 0
    failed_count = 0
    seen_tokens = set()  # One send per physical device, never per device row
    
    print("Notification sent to: ", get_users)
    
    for user in get_users:
        devices: list[Devices] = user.devices.filter(is_active=True)
        user_message = message.replace("--username--", user.username)
        print(user_message)
        for device in devices:
            token = (device.fcm_token or '').strip()
            if not token or token in seen_tokens:
                continue
            seen_tokens.add(token)
            result = _send_notification(token, title, user_message, data=metadata)
            if result:
                sent_count += 1
            else:
                failed_count += 1
                if result is False:  # UnregisteredError -> deactivate ALL rows
                    # holding this dead token (incl. duplicates on other users).
                    Devices.objects.filter(fcm_token=token).update(is_active=False)
            logger.debug(f"Push notification sent: {user.username} | {token}")
        
        # Create in-app notification record
        notification_kwargs = {
            'user': user,
            'title': title,
            'message': user_message,
            'type': Notification.NOTIFICATION_TYPES.VIDEO if notification_type == NotificationTypes.NEW_VIDEO else Notification.NOTIFICATION_TYPES.PROMO,
            'is_read': False,
        }
        
        # Only set video-related fields if video_uid is available
        if video_uid:
            notification_kwargs['target_video_slug'] = str(video_uid)
            notification_kwargs['target_url'] = f'/Player/{video_uid}'
        
        user.notifications.create(**notification_kwargs)
    
    logger.info(f"Push notifications sent: {sent_count}, failed: {failed_count}")

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

    # Attach the video cover so the app renders the same rich (image)
    # notification style used for new-video notifications.
    thumbnail_url = ''
    try:
        v = Video.objects.filter(uid=video_uid).first()
        if v:
            thumbnail_url = _video_notification_image(v)
    except Exception:
        thumbnail_url = ''

    metadata = {
        'type': 'comment_reply',
        'video_id': str(video_uid),
        'video_title': video_title,
        'video_thumbnail': thumbnail_url,
    }

    sent = 0
    seen_tokens = set()  # One send per physical device, never per device row
    for device in user.devices.filter(is_active=True):
        token = (device.fcm_token or '').strip()
        if not token or token in seen_tokens:
            continue
        seen_tokens.add(token)
        result = _send_notification(token, title, body, data=metadata)
        if result:
            sent += 1
        elif result is False:  # UnregisteredError -> deactivate ALL rows
            # holding this dead token (incl. duplicates on other users).
            Devices.objects.filter(fcm_token=token).update(is_active=False)

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
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=39600,
    time_limit=43200,
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
    
    # Initialize database update queue for async writes
    db_queue = DatabaseUpdateQueue()
    db_queue.start()
    
    # Acquire a lock to prevent duplicate task execution for the same video
    lock_key = f"video_conversion_lock_{video_id}"
    lock_acquired = cache.add(lock_key, self.request.id, timeout=18000)  # 5 hour timeout
    
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
    processor = None  # Track VideoProcessor for cleanup on timeout
    
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
        # Fresh run (no checkpoint and not a celery retry): reset the monotonic
        # progress floor so a re-conversion of an already-processed video doesn't
        # get stuck at the old (e.g. 100%) percentage. Resumes keep the floor.
        if not checkpoint and self.request.retries == 0:
            video.processing_progress = 0
        video.save(update_fields=['processing_status', 'processing_progress'])
        
        temp_dir = tempfile.gettempdir()
        hls_output_dir = f"videos/hls/{video.uid}"  # Remote path in R2
        local_hls_dir = os.path.join(temp_dir, f"hls_{video_id}")  # Local temp only
        Path(local_hls_dir).mkdir(parents=True, exist_ok=True)
        
        # Determine video file path - use local path if provided, otherwise download from R2
        if local_video_path and os.path.exists(local_video_path):
            video_file_path = local_video_path
            logger.info(f"Using local video file: {video_file_path}")
            send_video_progress(video_id, "converting", CONVERSION_START, "Using local video file, starting conversion...",
                               checkpoint={'stage': 'converting'})
            stage = 'converting'  # Skip download stage
        else:
            video_file_path = os.path.join(temp_dir, f"video_{video_id}_original.mp4")
        
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
        
        # Stage 1: Download video from R2 (skip if local path provided or already downloaded)
        if stage in ('start', 'downloading'):
            if not os.path.exists(video_file_path) or stage == 'start':
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
            else:
                logger.info(f"Resuming: video already downloaded for {video_id}")
            
            send_video_progress(video_id, "converting", 10, "Video downloaded, starting conversion...",
                               checkpoint={'stage': 'converting'})
        
        # Stage 2: Convert to HLS (skip if already converted)
        if stage in ('start', 'downloading', 'converting'):
            # Check if HLS files already exist locally
            master_playlist_local = os.path.join(local_hls_dir, 'master.m3u8')
            if not os.path.exists(master_playlist_local):
                # Variant progress callback for consolidated updates with per-variant progress
                def variant_progress_callback(overall_progress: int, message: str, variants_progress: dict):
                    send_video_progress(
                        video_id, 
                        "converting", 
                        overall_progress, 
                        message,
                        checkpoint={
                            'stage': 'converting',
                            'completed_variants': completed_variants,
                        },
                        variants_progress=variants_progress
                    )
                    # Update completed variants list when variants finish
                    for variant_name, vp in variants_progress.items():
                        status = getattr(vp, 'status', vp.get('status') if isinstance(vp, dict) else 'pending')
                        if status == 'completed' and variant_name not in completed_variants:
                            completed_variants.append(variant_name)
                            # Queue database update instead of blocking
                            cv_snapshot = list(completed_variants)
                            def update_checkpoint(cv=cv_snapshot):
                                try:
                                    v = Video.objects.get(id=video_id)
                                    v.processing_checkpoint = {
                                        'stage': 'converting',
                                        'completed_variants': cv
                                    }
                                    v.save(update_fields=['processing_checkpoint'])
                                except Exception as e:
                                    logger.error(f"Failed to update checkpoint for video {video_id}: {e}")
                            db_queue.submit(update_checkpoint)
                            # ALSO save synchronously as fallback (critical: async queue may not flush on hard kill)
                            try:
                                close_old_connections()
                                Video.objects.filter(id=video_id).update(
                                    processing_checkpoint={
                                        'stage': 'converting',
                                        'completed_variants': cv_snapshot
                                    }
                                )
                            except Exception as e:
                                logger.error(f"Failed synchronous checkpoint save for video {video_id}: {e}")
                
                # Legacy callback for backward compatibility
                def progress_callback(variant_name: str, progress: int, message: str):
                    pass  # Handled by variant_progress_callback now
                
                # Get recommended parallel workers based on system resources
                parallel_workers = VideoProcessor.get_recommended_parallel_workers()
                
                # Initialize video processor with new features
                processor = VideoProcessor(
                    input_path=video_file_path,
                    output_dir=local_hls_dir,
                    progress_callback=progress_callback,
                    use_hardware_acceleration=True,
                    parallel_variants=parallel_workers,
                    variant_progress_callback=variant_progress_callback
                )
                
                send_video_progress(video_id, "converting", CONVERSION_START, "Starting HLS conversion...",
                                   checkpoint={'stage': 'converting', 'completed_variants': completed_variants})
                
                # Resume from last completed variant if retrying
                resume_from = completed_variants[-1] if completed_variants else None
                if resume_from:
                    logger.info(f"Resuming conversion from variant: {resume_from}")
                    send_video_progress(video_id, "converting", CONVERSION_START, f"Resuming from {resume_from}...",
                                       checkpoint={'stage': 'converting', 'completed_variants': completed_variants})
                
                conversion_result = processor.convert_to_hls(resume_from_variant=resume_from)
                
                if not conversion_result['success']:
                    raise Exception(conversion_result.get('error', 'Unknown conversion error'))
            else:
                logger.info(f"Resuming: HLS files already exist locally for {video_id}")
                # Get duration from existing files
                conversion_result = {'success': True, 'duration': 0}  # Duration will be recalculated if needed
            
            send_video_progress(video_id, "uploading", CONVERSION_END, "Conversion complete, uploading HLS files...",
                               checkpoint={'stage': 'uploading'})
        
        # Stage 3: Upload HLS files (skip if already uploaded)
        if stage in ('start', 'downloading', 'converting', 'uploading'):
            # Check if already uploaded by checking remote storage
            try:
                remote_master = f"{hls_output_dir}/master.m3u8"
                if default_storage.exists(remote_master):
                    logger.info(f"Resuming: HLS files already uploaded for {video_id}")
                    uploaded_paths = []  # Already uploaded
                    send_video_progress(video_id, "uploading", UPLOAD_NEAR_DONE, "HLS files already uploaded",
                                       checkpoint={'stage': 'finalizing'})
                else:
                    send_video_progress(video_id, "uploading", CONVERSION_END, "Uploading HLS files to storage...",
                                       checkpoint={'stage': 'uploading'})
                    try:
                        uploaded_paths = upload_hls_files_to_storage(local_hls_dir, hls_output_dir)
                        logger.info(f"Uploaded {len(uploaded_paths)} files to R2 storage")
                        send_video_progress(video_id, "uploading", UPLOAD_NEAR_DONE, f"Uploaded {len(uploaded_paths)} HLS files",
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
                send_video_progress(video_id, "uploading", CONVERSION_END, "Uploading HLS files to storage...",
                                   checkpoint={'stage': 'uploading'})
                try:
                    uploaded_paths = upload_hls_files_to_storage(local_hls_dir, hls_output_dir)
                    logger.info(f"Uploaded {len(uploaded_paths)} files to R2 storage")
                    send_video_progress(video_id, "uploading", UPLOAD_NEAR_DONE, f"Uploaded {len(uploaded_paths)} HLS files",
                                       checkpoint={'stage': 'finalizing'})
                except Exception as upload_error:
                    logger.error(f"HLS upload failed for video {video_id}: {upload_error}")
                    send_video_error(video_id, "Failed to upload HLS files", str(upload_error))
                    raise
        
        # Stage 4: Finalize
        send_video_progress(video_id, "uploading", UPLOAD_NEAR_DONE, "Finalizing video processing...",
                           checkpoint={'stage': 'finalizing'})
        
        # Verify master playlist exists on R2 before marking complete
        remote_master = f"{hls_output_dir}/master.m3u8"
        if not default_storage.exists(remote_master):
            logger.error(f"Upload verification failed: {remote_master} not found on R2")
            send_video_error(video_id, "R2 upload failed", f"Master playlist not found: {remote_master}")
            video.processing_status = 'failed'
            video.processing_error = f"R2 upload verification failed: {remote_master} not found"
            video.save(update_fields=['processing_status', 'processing_error'])
            raise Exception(f"R2 upload verification failed")
        
        # Update video object with HLS information
        video.hls_path = hls_output_dir
        video.hls_master_playlist = f"{hls_output_dir}/master.m3u8"
        if conversion_result and conversion_result.get('duration'):
            video.duration = timedelta(seconds=conversion_result['duration'])
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
        if video.video:
            try:
                video.video.delete(save=False)
                video.video = None
                video.save(update_fields=['video'])
                logger.info(f"Deleted original MP4 from R2 for video {video_id}")
            except Exception as e:
                logger.warning(f"Could not delete original video from R2: {str(e)}")
        
        # Schedule local temp file cleanup after 24 hours
        schedule_cleanup_task.apply_async(
            args=[video_id, video_file_path, local_hls_dir],
            countdown=86400
        )

        logger.info(f"Successfully converted video {video_id} to HLS")
        
        send_video_complete(video_id, "Video processing completed successfully", hls_output_dir)
        
        # Refresh video object to get updated data for push notification
        video.refresh_from_db()
        category_name = getattr(video.category, 'name', 'Uncategorized') if video.category else 'Uncategorized'
        
        # Build enriched metadata for deep-link support
        # Fall back through portrait_cover / tv_poster / category thumbnail so
        # the notification always carries an image when any cover exists.
        thumbnail_url = _video_notification_image(video)
        
        notification_metadata = {
            'type': 'video_upload',
            'video_id': str(video.uid),
            'db_video_id': video.id,
            'video_title': video.title or '',
            'video_thumbnail': thumbnail_url,
            'video_category': category_name,
            'video_description': video.description or '',
            'video_duration': str(int(video.duration.total_seconds())) if video.duration else '0',
            'video_created_at': video.created_at.isoformat() if video.created_at else '',
            'master_playlist': f'/streaming/hls/{video.uid}/master.m3u8' if video.hls_master_playlist else '',
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
        
        # Kill active ffmpeg subprocess
        if processor:
            processor.cleanup()
        
        try:
            video = Video.objects.get(id=video_id)
            video.processing_status = 'killed'
            video.processing_error = 'Task killed - time limit exceeded'
            video.processing_checkpoint = video.processing_checkpoint or {}
            video.save(update_fields=['processing_status', 'processing_error', 'processing_checkpoint'])
        except:
            pass
        
        db_queue.stop(timeout=5)
        cache.delete(lock_key)
        return {'success': False, 'error': 'Task killed - time limit exceeded', 'killed': True}
    
    except celery.exceptions.Terminated:
        # Task was forcefully terminated (SIGTERM/SIGKILL)
        logger.error(f"Video {video_id} conversion terminated by signal")
        send_video_error(video_id, "Conversion terminated")
        
        # Kill active ffmpeg subprocess
        if processor:
            processor.cleanup()
        
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
        
        # Kill active ffmpeg subprocess
        if processor:
            processor.cleanup()
        
        # Update video status to failed (but keep checkpoint for retry)
        try:
            video = Video.objects.get(id=video_id)
            video.processing_status = 'failed'
            video.processing_error = str(e)
            video.save(update_fields=['processing_status', 'processing_error'])
        except:
            pass
        
        db_queue.stop(timeout=5)
        # Release lock before retry so the retry can acquire it
        cache.delete(lock_key)
        
        # Retry the task
        raise
    
    finally:
        # Kill any remaining ffmpeg subprocess
        if processor:
            try:
                processor.cleanup()
            except:
                pass
        
        # Always stop the queue and release the lock when task ends
        try:
            db_queue.stop(timeout=5)
        except:
            pass
        try:
            cache.delete(lock_key)
        except:
            pass

def upload_hls_files_to_storage(local_dir: str, remote_dir: str, max_workers: int = 2) -> list:
    """
    Upload HLS files from local directory to remote storage.
    
    Uses sequential uploads by default to avoid overwhelming R2 and causing hangs.
    Each upload has retry logic for resilience.
    
    Args:
        local_dir: Local directory containing HLS files
        remote_dir: Remote directory path in storage
        max_workers: Number of parallel upload workers (default 2, reduced for stability)
        
    Returns:
        List of uploaded file paths
    """
    import time
    
    uploaded_files = []
    files_to_upload = []
    
    try:
        # Collect all files to upload
        for root, dirs, files in os.walk(local_dir):
            for file in files:
                local_file_path = os.path.join(root, file)
                rel_path = os.path.relpath(local_file_path, local_dir)
                remote_file_path = os.path.join(remote_dir, rel_path).replace('\\', '/')
                files_to_upload.append((local_file_path, remote_file_path))
        
        total_files = len(files_to_upload)
        logger.info(f"Uploading {total_files} HLS files to R2 storage...")
        
        def upload_single_file_with_retry(local_path: str, remote_path: str, max_retries: int = 3) -> str:
            """
            Upload a single file with retry logic.
            """
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
                        time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
            raise last_error
        
        # Sequential upload for stability (avoids R2 connection issues)
        for i, (local_path, remote_path) in enumerate(files_to_upload):
            try:
                uploaded_path = upload_single_file_with_retry(local_path, remote_path)
                uploaded_files.append(uploaded_path)
                
                # Close stale DB connections every 50 files to prevent connection pool exhaustion
                if (i + 1) % 50 == 0 or i == total_files - 1:
                    close_old_connections()
                    logger.info(f"Uploaded {i + 1}/{total_files} HLS files")
                    
            except Exception as e:
                logger.error(f"Failed to upload {remote_path} after retries: {str(e)}")
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
            if os.path.dirname(video_file_path).startswith(temp_dir):
                os.remove(video_file_path)
                logger.debug(f"Removed temp video file: {video_file_path}")
        
        # Remove HLS directory if it's a temp location
        if hls_dir and os.path.exists(hls_dir):
            if hls_dir.startswith(temp_dir):
                import shutil
                shutil.rmtree(hls_dir)
                logger.debug(f"Removed temp HLS directory: {hls_dir}")
        
        # Clean orphaned temp dirs older than 24 hours
        _cleanup_orphaned_tmp_files(temp_dir)
            
    except Exception as e:
        logger.warning(f"Error during cleanup: {str(e)}")


def _cleanup_orphaned_tmp_files(temp_dir: str):
    """Remove orphaned hls_* and video_* temp files older than 24 hours."""
    try:
        now = time.time()
        cutoff = now - 86400  # 24 hours
        for entry in os.listdir(temp_dir):
            path = os.path.join(temp_dir, entry)
            if not os.path.exists(path):
                continue
            is_old = os.path.getmtime(path) < cutoff
            if not is_old:
                continue
            if entry.startswith('hls_') and os.path.isdir(path):
                import shutil
                shutil.rmtree(path)
                logger.info(f"Cleaned orphaned temp dir: {entry}")
            elif entry.startswith('video_') and entry.endswith('.mp4') and os.path.isfile(path):
                os.remove(path)
                logger.info(f"Cleaned orphaned temp file: {entry}")
    except Exception as e:
        logger.warning(f"Error cleaning orphaned tmp files: {e}")


@celery_app.task(bind=True)
def schedule_cleanup_task(self, video_id, video_file_path, hls_dir):
    cleanup_local_files(video_file_path, hls_dir)
    logger.info(f"Scheduled cleanup completed for video {video_id}")


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=1800,
    time_limit=2100,
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

    close_old_connections()
    
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
            send_video_progress(video_id, "assembling", CONVERSION_START, "Assembly complete, starting HLS conversion...")
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
        
        send_video_progress(video_id, "assembling", 85, "Cleaning up chunks from storage...")
        
        # Delete chunks from R2 in batches to avoid connection pool exhaustion
        s3_client = default_storage.connection.meta.client
        bucket_name = default_storage.bucket_name
        CHUNK_BATCH = 1000
        
        for batch_start in range(0, total_chunks, CHUNK_BATCH):
            batch = chunk_files[batch_start:batch_start + CHUNK_BATCH]
            try:
                s3_client.delete_objects(
                    Bucket=bucket_name,
                    Delete={'Objects': [{'Key': k} for k in batch]}
                )
            except Exception as e:
                logger.warning(f"Batch delete failed for video {video_id}, falling back to individual: {e}")
                for chunk_path in batch:
                    try:
                        default_storage.delete(chunk_path)
                    except Exception as ie:
                        logger.warning(f"Could not delete chunk {chunk_path}: {str(ie)}")
        
        try:
            if hasattr(default_storage, 'delete'):
                default_storage.delete(chunk_dir)
        except Exception as e:
            logger.warning(f"Could not delete chunk directory {chunk_dir}: {str(e)}")
        
        # Save checkpoint with local path - DO NOT upload to R2 (queue this update)
        def save_final_checkpoint():
            try:
                v = Video.objects.get(id=video_id)
                v.processing_checkpoint = {'stage': 'assembled', 'local_video_path': temp_assembled_path}
                v.save(update_fields=['processing_checkpoint'])
            except Exception as e:
                logger.error(f"Failed to save final checkpoint for video {video_id}: {e}")
        db_queue.submit(save_final_checkpoint)
        
        # Wait for queue to process pending updates before continuing
        db_queue.stop(timeout=10)
        
        logger.info(f"Successfully assembled video {video_id} at local path: {temp_assembled_path}")
        send_video_progress(video_id, "assembling", 88, "Assembly complete, starting HLS conversion...")
        
        try:
            # Route through shared trigger (feature-flagged)
            from apps.streaming.services.conversion_client import trigger_video_processing
            trigger_video_processing(video, source_key=temp_assembled_path)
            logger.info(f"Triggered video processing for video {video.id} with local path")
        except Exception as e:
            logger.error(f"Could not queue video conversion task: {str(e)}", exc_info=True)
            send_video_error(video_id, "Could not start HLS conversion", str(e))
        
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
        # Always stop the queue when task ends
        try:
            db_queue.stop(timeout=5)
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

        # Fresh Google Drive import: clear any stale conversion state from a
        # previous chunk-upload attempt so the monotonic progress floor can't
        # pin the new conversion at an old percentage (or wrongly resume from
        # completed_variants of a different source file).
        video.processing_checkpoint = None
        video.processing_progress = 0
        video.processing_status = 'pending'
        video.save(update_fields=['processing_checkpoint', 'processing_progress', 'processing_status'])

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

        raise