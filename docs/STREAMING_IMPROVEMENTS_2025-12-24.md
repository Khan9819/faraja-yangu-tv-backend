# Streaming Pipeline Improvements - December 24, 2025

This document details the comprehensive improvements made to the video streaming pipeline, focusing on performance optimization, bug fixes, and infrastructure alignment.

## Table of Contents

1. [Overview](#overview)
2. [Performance Optimizations](#performance-optimizations)
3. [Bug Fixes](#bug-fixes)
4. [Infrastructure Changes](#infrastructure-changes)
5. [Technical Details](#technical-details)
6. [Testing Recommendations](#testing-recommendations)
7. [Troubleshooting](#troubleshooting)

---

## Overview

### Problems Addressed

1. **Slow HLS Conversion**: Videos taking excessively long to convert due to suboptimal FFmpeg settings
2. **Push Notification Crashes**: `NameError: name 'video' is not defined` in notification task
3. **Invalid Field References**: Views setting non-existent `upload_status` field
4. **Incomplete HLS Deletion**: Only top-level files deleted, leaving orphaned subdirectories
5. **Worker Misconfiguration**: Single worker with thread pool handling CPU-bound FFmpeg tasks

### Summary of Changes

| Area | Before | After | Impact |
|------|--------|-------|--------|
| FFmpeg Preset | `medium` (default) | `veryfast` | 2-3x faster encoding |
| HLS Upload | Sequential | Parallel (8 workers) | 4-8x faster uploads |
| Notification Task | Crashes on video reference | Extracts from metadata | No more crashes |
| Upload Tracking | Invalid field | Proper model fields | Correct persistence |
| HLS Deletion | Shallow (top-level only) | Recursive (boto3 prefix) | Complete cleanup |
| Celery Workers | 1 worker (threads) | 2 workers (prefork + threads) | Proper isolation |

---

## Performance Optimizations

### 1. FFmpeg Encoding Speed Boost

**File**: `apps/streaming/services/video_processor.py`

#### Changes Made

```python
# New class constants
ENCODING_PRESET = 'veryfast'  # Was default 'medium'
CRF_VALUE = '23'              # Constant Rate Factor for quality

# Updated FFmpeg command
cmd = [
    self.ffmpeg_path,
    '-i', self.input_path,
    '-c:v', 'libx264',
    '-preset', self.ENCODING_PRESET,  # NEW: 2-3x faster
    '-crf', self.CRF_VALUE,           # NEW: consistent quality
    '-c:a', 'aac',
    '-b:v', preset['video_bitrate'],
    '-b:a', preset['audio_bitrate'],
    '-maxrate', preset['maxrate'],
    '-bufsize', preset['bufsize'],
    '-s', preset['resolution'],
    '-profile:v', 'main',
    '-level', '4.0',
    '-movflags', '+faststart',        # NEW: optimized streaming
    '-threads', '0',                   # NEW: auto CPU detection
    # ... rest of command
]
```

#### Preset Comparison

| Preset | Speed | Quality | Use Case |
|--------|-------|---------|----------|
| ultrafast | Fastest | Lowest | Testing only |
| superfast | Very fast | Low | Real-time streaming |
| **veryfast** | Fast | Good | **Our choice** |
| faster | Medium-fast | Good | Balanced |
| fast | Medium | Better | Higher quality needs |
| medium | Slow | High | Default (was using) |
| slow | Very slow | Higher | Archival |

**Why `veryfast`?**
- 2-3x faster than `medium` with minimal quality loss
- Acceptable for streaming where bandwidth is the bottleneck
- CRF 23 ensures consistent quality across all presets

### 2. Parallel HLS Upload

**File**: `apps/streaming/tasks/tasks.py`

#### Before (Sequential)
```python
for root, dirs, files in os.walk(local_dir):
    for file in files:
        # Upload one file at a time
        with open(local_file_path, 'rb') as f:
            default_storage.save(remote_file_path, f)
```

#### After (Parallel)
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def upload_hls_files_to_storage(local_dir: str, remote_dir: str, max_workers: int = 8):
    # Collect all files first
    files_to_upload = []
    for root, dirs, files in os.walk(local_dir):
        for file in files:
            files_to_upload.append((local_file_path, remote_file_path))
    
    # Upload in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(upload_single_file, fp): fp for fp in files_to_upload}
        for future in as_completed(future_to_file):
            remote_path = future.result()
            uploaded_files.append(remote_path)
```

#### Performance Impact

For a typical video with 4 quality variants:
- ~100 segment files per variant = 400+ files total
- Sequential: 400 × 200ms = 80 seconds
- Parallel (8 workers): 400 / 8 × 200ms = 10 seconds
- **8x improvement**

---

## Bug Fixes

### 1. Push Notification NameError

**File**: `apps/streaming/tasks/tasks.py`

#### Problem
```python
# 'video' was never defined in this function!
user.notifications.create(
    target_video_slug = video.uid,  # NameError!
    target_url = f'/Player/{video.uid}'
)
```

#### Solution
```python
@celery_app.task(bind=True)
def send_push_notification(self, target, notification_type, title, message, metadata=None):
    """
    Args:
        metadata: Optional dict with extra data. For videos, include 'video_id' key.
    """
    # Extract video_id from metadata if present
    video_uid = metadata.get('video_id') if metadata else None
    
    # Build notification kwargs
    notification_kwargs = {
        'user': user,
        'title': title,
        'message': user_message,
        'type': notification_type,
        'is_read': False,
    }
    
    # Only set video-related fields if video_uid is available
    if video_uid:
        notification_kwargs['target_video_slug'] = str(video_uid)
        notification_kwargs['target_url'] = f'/Player/{video_uid}'
    
    user.notifications.create(**notification_kwargs)
```

### 2. Invalid upload_status Field

**File**: `apps/streaming/views.py`

#### Problem
```python
video.upload_status = 'uploading'  # Field doesn't exist!
video.save()
```

#### Solution
```python
# Use existing model fields
video.upload_total_chunks = total_chunks
video.upload_completed_chunks = 0
video.upload_progress = 0
video.save(update_fields=['upload_total_chunks', 'upload_completed_chunks', 'upload_progress'])
```

### 3. Variable Scope Issue

**File**: `apps/streaming/tasks/tasks.py`

#### Problem
```python
# Fragile pattern - 'result' might not be defined
if 'result' in dir() and result.get('duration'):
    video.duration = timedelta(seconds=result['duration'])
```

#### Solution
```python
conversion_result = None  # Initialize at function scope

# Later in the code
conversion_result = processor.convert_to_hls(resume_from_variant=resume_from)

# Safe access
if conversion_result and conversion_result.get('duration'):
    video.duration = timedelta(seconds=conversion_result['duration'])
```

---

## Infrastructure Changes

### Celery Worker Architecture

**File**: `docker-compose.yml`

#### Before: Single Worker
```yaml
celery_worker:
  command: celery -A farajayangu_be.celery worker -l info --pool=threads -E --concurrency=2
```

**Problems**:
- Thread pool is inefficient for CPU-bound FFmpeg tasks
- No queue isolation - video tasks block notifications
- Single point of failure

#### After: Two Specialized Workers

```yaml
# CPU-intensive video processing
celery_video_worker:
  command: >
    celery -A farajayangu_be.celery worker -l info 
    -Q video_processing 
    --pool=prefork 
    --concurrency=2 
    --max-tasks-per-child=5 
    -n video_worker@%h
  deploy:
    resources:
      limits:
        memory: 4G
      reservations:
        memory: 1G

# I/O-bound general tasks
celery_general_worker:
  command: >
    celery -A farajayangu_be.celery worker -l info 
    -Q general,celery 
    --pool=threads 
    --concurrency=4 
    --max-tasks-per-child=50 
    -n general_worker@%h
  deploy:
    resources:
      limits:
        memory: 1G
      reservations:
        memory: 256M
```

#### Worker Comparison

| Aspect | Video Worker | General Worker |
|--------|--------------|----------------|
| Queue | `video_processing` | `general`, `celery` |
| Pool | `prefork` (processes) | `threads` |
| Concurrency | 2 | 4 |
| Memory Limit | 4GB | 1GB |
| Tasks | FFmpeg, assembly | Notifications, cleanup |

### Recursive HLS Deletion

**File**: `apps/streaming/tasks/tasks.py`

#### Before: Shallow Delete
```python
# Only deletes top-level files, misses subdirectories!
_, files = default_storage.listdir(hls_path)
for filename in files:
    default_storage.delete(f"{hls_path}/{filename}")
```

#### After: Recursive Delete with boto3
```python
import boto3

# List ALL objects with prefix (includes subdirectories)
paginator = s3_client.get_paginator('list_objects_v2')
pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)

for page in pages:
    for obj in page.get('Contents', []):
        objects_to_delete.append({'Key': obj['Key']})

# Batch delete (up to 1000 per request)
for i in range(0, len(objects_to_delete), 1000):
    batch = objects_to_delete[i:i+1000]
    s3_client.delete_objects(Bucket=bucket_name, Delete={'Objects': batch})
```

---

## Technical Details

### Task Routing Configuration

**File**: `farajayangu_be/celery.py`

```python
app.conf.task_routes = {
    'apps.streaming.tasks.tasks.assemble_chunks_task': {'queue': 'video_processing'},
    'apps.streaming.tasks.tasks.convert_video_to_hls': {'queue': 'video_processing'},
    'apps.streaming.tasks.tasks.send_push_notification': {'queue': 'general'},
    'apps.streaming.tasks.tasks.cleanup_stale_chunks': {'queue': 'general'},
    'apps.streaming.tasks.tasks.delete_video_files_task': {'queue': 'general'},
}
```

### HLS Directory Structure

```
videos/hls/<video_uid>/
├── master.m3u8           # Master playlist
├── 1080p/
│   ├── 1080p.m3u8        # Variant playlist
│   ├── 1080p_000.ts      # Segments
│   ├── 1080p_001.ts
│   └── ...
├── 720p/
│   ├── 720p.m3u8
│   └── ...
├── 480p/
│   └── ...
└── 360p/
    └── ...
```

---

## Testing Recommendations

### 1. Encoding Speed Test

```bash
# Time a conversion with the new settings
time python manage.py shell -c "
from apps.streaming.tasks.tasks import convert_video_to_hls
convert_video_to_hls(video_id=1)
"
```

### 2. Parallel Upload Test

```python
# In Django shell
from apps.streaming.tasks.tasks import upload_hls_files_to_storage
import time

start = time.time()
files = upload_hls_files_to_storage('/tmp/hls_test', 'videos/hls/test')
print(f"Uploaded {len(files)} files in {time.time() - start:.2f}s")
```

### 3. Notification Test

```python
from apps.streaming.tasks.tasks import send_push_notification, UserGroupTypes, NotificationTypes

# Should not crash
send_push_notification(
    UserGroupTypes.CLIENTS,
    NotificationTypes.NEW_VIDEO,
    title="Test",
    message="Test message",
    metadata={"video_id": "test-uuid"}
)
```

### 4. HLS Deletion Test

```python
from apps.streaming.tasks.tasks import delete_video_files_task

result = delete_video_files_task('videos/hls/test-uuid', 'test-uuid')
print(f"Deleted {result['deleted']} files")
```

---

## Troubleshooting

### Video Processing Still Slow

1. **Check FFmpeg version**: Ensure FFmpeg 4.4+ is installed
2. **Verify preset**: Check logs for `-preset veryfast` in command
3. **CPU bottleneck**: Monitor CPU usage during conversion
4. **Disk I/O**: Check if temp directory is on SSD

### Notifications Not Working

1. **Check metadata**: Ensure `video_id` is passed in metadata dict
2. **Firebase config**: Verify Firebase credentials in settings
3. **User devices**: Check if users have registered FCM tokens

### HLS Files Not Deleted

1. **Check boto3 credentials**: Verify R2 access keys
2. **Prefix format**: Ensure path ends with `/`
3. **Permissions**: Verify bucket delete permissions

### Workers Not Processing

1. **Check queue binding**: Verify `-Q` flag matches task routing
2. **Redis connection**: Ensure Redis is accessible
3. **Worker logs**: Check `logs/celery_video_worker.log`

---

## Migration Notes

**No database migrations required** for these changes.

All improvements are code-level:
- FFmpeg command parameters
- Python function implementations
- Docker Compose configuration

Existing videos in processing will:
- Continue from their last checkpoint
- Benefit from faster encoding on retry
- Use parallel uploads for remaining files

---

## Files Modified

| File | Changes |
|------|---------|
| `apps/streaming/services/video_processor.py` | FFmpeg preset, CRF, threads, movflags |
| `apps/streaming/tasks/tasks.py` | Parallel upload, notification fix, deletion fix, variable scope |
| `apps/streaming/views.py` | Fixed upload_status references |
| `docker-compose.yml` | Split workers, YAML anchors |
| `.changelog/CHANGELOG.md` | Documented all changes |

---

*Document created: December 24, 2025*
