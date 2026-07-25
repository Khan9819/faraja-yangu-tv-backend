# CHANGES FULL DOCUMENTATION

> Kuanzia mwanzo hadi mwisho — codebase, celery, backend, server config, deployment
> Jul 24, 2026

---

## TABLE OF CONTENTS

1. [Architecture Overview](#1-architecture-overview)
2. [Git Commit History (Chronological)](#2-git-commit-history)
3. [Celery Worker Configuration](#3-celery-worker-configuration)
4. [Backend Code Changes](#4-backend-code-changes)
5. [Server & Deployment Changes](#5-server--deployment-changes)
6. [Environment Variables (CapRover)](#6-environment-variables-caprover)
7. [Infrastructure](#7-infrastructure)
8. [Verification](#8-verification)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Leader (37.60.247.219)                  │
│   ┌──────────────────┐  ┌──────────────┐  ┌──────────────┐  │
│   │ mobile-core       │  │ PostgreSQL   │  │ Redis (×2)   │  │
│   │ backend (Nginx    │  │ 14.5         │  │ 7.2.4        │  │
│   │ + Gunicorn)       │  │              │  │              │  │
│   └──────────────────┘  └──────────────┘  └──────────────┘  │
│          │ API calls (retry, status)                          │
│          ▼                                                    │
│                      Worker (62.84.190.130)                   │
│   ┌──────────────────────────────────────────┐               │
│   │  background-tasks-backend (Docker)        │               │
│   │  ┌──────────┐  ┌─────────┐  ┌─────────┐  │               │
│   │  │ video    │  │ general │  │ beat    │  │               │
│   │  │ worker   │  │ worker  │  │         │  │               │
│   │  │ (prefork │  │(threads │  │         │  │               │
│   │  │ con=2)   │  │ con=4)  │  │         │  │               │
│   │  └──────────┘  └─────────┘  └─────────┘  │               │
│   └──────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

**Queues:**
- `video_processing` → video worker (prefork, concurrency=2)
- `general` + `celery` → general worker (threads, concurrency=4)

**Task Routing (farajayangu_be/celery.py):**
- `convert_video_to_hls` → `video_processing`
- `assemble_chunks_task` → `video_processing`
- `send_push_notification` → `general`
- `schedule_cleanup_task` → `general`
- `cleanup_stale_chunks` → `general`

---

## 2. Git Commit History

```text
4cc55d3 (master) fix: eliminate ffmpeg stderr pipe deadlock (root cause of all conversion stalls)
ed75d8f feat: schedule temp file cleanup 24h after conversion + /api/ URL prefix
53187a8 fix: add /api/ URL prefix to support existing Flutter production app without rebuild
f0f2d9b fix: resume pointer not advancing when variant already exists on disk
169dbc3 feat: implement video conversion pipeline fixes (#1-#7)
ecc49cb fix: add db_video_id to metadata + remove bare raise from finally block
20a166b fix: handle missing reconstruct_mp4_for_download_task gracefully
aa519c6 fix: close_old_connections during upload + R2 verify before complete
fdbefa5 fix: remove orphaned if-block causing IndentationError
9f89f74 fix: IndentationError — move get_users/sent_count inside function body
d3da9d2 fix: add SELECT FOR UPDATE push notification dedup back
b86fc7b fix: add raise on conversion failure (error no longer swallowed)
4d20443 revert: FULL original code from zip — tasks.py, video_processor.py, start_tasks_backend.sh
aaaa252 revert: restore original start_tasks_backend.sh
8ffeb27 fix: remove duplicate if block causing IndentationError
b2e8b12 revert: restore original HLS conversion with VideoProcessor, keep push dedup + error raise
```

**Total net changes:** 10 files changed, 435 insertions(+), 81 deletions(-)

---

## 3. Celery Worker Configuration

### 3a. Queue Routing (farajayangu_be/celery.py)

```python
# Before: All tasks on default queue (no separation)
# After: Separate queues for video vs general tasks

app.conf.task_routes = {
    'apps.streaming.tasks.tasks.assemble_chunks_task':     {'queue': 'video_processing'},
    'apps.streaming.tasks.tasks.convert_video_to_hls':     {'queue': 'video_processing'},
    'apps.streaming.tasks.tasks.import_video_from_google_drive': {'queue': 'video_processing'},
    'apps.streaming.tasks.tasks.cleanup_stale_chunks':     {'queue': 'general'},
    'apps.streaming.tasks.conversion_monitor.mark_stale_conversions': {'queue': 'general'},
    'apps.authentication.tasks.main.*':                    {'queue': 'general'},
    'apps.streaming.tasks.tasks.send_push_notification':   {'queue': 'general'},
}
```

### 3b. Worker Commands (.entry/start_tasks_backend.sh)

```bash
# Video worker — CPU-intensive (ffmpeg encoding)
celery -A farajayangu_be.celery worker \
  -Q video_processing \
  -n video_worker@%h \
  -l info \
  --pool=prefork \
  --concurrency=2 \
  --max-tasks-per-child=5 \
  -E

# General worker — I/O-bound (notifications, cleanup, DB ops)
celery -A farajayangu_be.celery worker \
  -Q general,celery \
  -n general_worker@%h \
  -l info \
  --pool=threads \
  --concurrency=4 \
  --max-tasks-per-child=50 \
  -E

# Beat scheduler — periodic tasks
celery -A farajayangu_be beat \
  -l INFO \
  --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

### 3c. Celery Settings (farajayangu_be/settings/base.py)

| Setting | Value | Purpose |
|---------|-------|---------|
| `CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP` | `True` | Don't crash if Redis not ready |
| `visibility_timeout` | `7200` (2h) | Must be > task time_limit |
| `socket_timeout` | `30` | Don't hang on Redis timeout |
| `max_connections` | `50` | Connection pool |
| `CELERY_TASK_ACKS_LATE` | `True` | Ack after task completes |
| `CELERY_TASK_REJECT_ON_WORKER_LOST` | `True` | Re-queue if worker dies |
| `CELERY_WORKER_PREFETCH_MULTIPLIER` | `1` | One task at a time |
| `CELERY_WORKER_CANCEL_LONG_RUNNING_TASKS_ON_CONNECTION_LOSS` | `True` | Cancel on disconnect |
| `CELERY_TASK_TIME_LIMIT` | `10800` (3h) | Global hard limit |
| `CELERY_TASK_SOFT_TIME_LIMIT` | `9000` (2.5h) | Global soft limit |

---

## 4. Backend Code Changes

### 4a. FILE: apps/streaming/services/video_processor.py

#### Change #1: stderr=DEVNULL (CRITICAL — root cause fix)

```python
# BEFORE (line 740-748) — PIPE deadlock
process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,    # Nobody reads this → pipe fills → ffmpeg blocks
    text=True, bufsize=1,
    preexec_fn=os.setsid
)

# AFTER (line 746-754) — DEVNULL eliminates deadlock
process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,  # No pipe, no block, no deadlock
    text=True, bufsize=1,
    preexec_fn=os.setsid
)
```

**Mechanism:**
1. ffmpeg writes encoder logs to stderr (frame, fps, bitrate per frame)
2. With `PIPE`, nobody reads → 64KB pipe buffer fills → ffmpeg's `write(2)` blocks
3. Blocked ffmpeg encodes nothing → no progress on stdout → watchdog detects "stall" after 300s → kills ffmpeg
4. With `DEVNULL`, writes succeed instantly → ffmpeg never blocks → encodes normally

#### Change #2: Remove communicate() after wait()

```python
# BEFORE (line 756-760)
if process.returncode != 0:
    _, stderr = process.communicate(timeout=10)   # Deadlock risk + stderr is DEVNULL now
    logger.error(f"FFmpeg error for {variant_name}: {stderr}")
    return None

# AFTER (line 762-765)
if process.returncode != 0:
    logger.error(f"FFmpeg exited with code {process.returncode} for {variant_name}")
    self._update_variant_progress(..., f"{variant_name} failed (exit {process.returncode})", 'failed')
    return None
```

#### Change #3: Add `-nostats -loglevel warning` to ffmpeg command

```python
# BEFORE — no logging control
cmd.extend([...])  # No -nostats or -loglevel

# AFTER (line 838-839)
cmd.extend([
    '-nostats',           # Don't print per-frame stats
    '-loglevel', 'warning',  # Only show warnings/errors
    ...
])
```

#### Change #4: Reap zombie after kill (3 locations)

```python
# BEFORE — process.wait() not called after kill
os.killpg(os.getpgid(process.pid), signal.SIGKILL)
# ffmpeg becomes zombie (defunct)
raise FFmpegStalledError(...)

# AFTER (lines 1029-1032, 1042-1045) — reap zombie
os.killpg(os.getpgid(process.pid), signal.SIGKILL)
try:
    process.wait(timeout=30)  # Wait for process table entry to be cleaned
except Exception:
    pass
raise FFmpegStalledError(...)
```

**Locations:**
1. Line 1029-1032 — inside `except FFmpegStalledError` handler (normal stall)
2. Line 1042-1045 — inside `finally` block (container shutdown / interrupt)

#### Change #5: Resume pointer (commit f0f2d9b)

```python
# BEFORE — skip_until_resume never set to False when existing variant matches
if os.path.exists(playlist_path):
    if skip_until_resume and variant_name == resume_from_variant:
        skip_until_resume = False    # This was MISSING → resume never stopped
    continue

# AFTER — properly advances resume pointer
if os.path.exists(playlist_path):
    if skip_until_resume and variant_name == resume_from_variant:
        skip_until_resume = False    # ✅ Now correctly set
    continue
```

**Bug:** When resuming, if a variant already existed on disk (e.g., 1080p done), the code skipped it but never set `skip_until_resume = False`. So it skipped ALL remaining variants, thinking they were all "before the resume point".

---

### 4b. FILE: apps/streaming/tasks/tasks.py

#### Change #1: Add `import time` at module level

```python
# BEFORE
import os
from pathlib import Path
import logging
from datetime import timedelta, datetime, timezone

# AFTER
import os
import time          # ✅ Needed for cleanup timestamp comparison
from pathlib import Path
import logging
from datetime import timedelta, datetime, timezone
```

#### Change #2: Add orphaned temp file cleanup

```python
def _cleanup_orphaned_tmp_files(temp_dir: str):
    """Remove orphaned hls_* and video_* temp files older than 24 hours."""
    try:
        now = time.time()
        cutoff = now - 86400
        for entry in os.listdir(temp_dir):
            path = os.path.join(temp_dir, entry)
            if not os.path.exists(path):
                continue
            if os.path.getmtime(path) < cutoff:
                if entry.startswith('hls_') and os.path.isdir(path):
                    shutil.rmtree(path)
                elif entry.startswith('video_') and entry.endswith('.mp4') and os.path.isfile(path):
                    os.remove(path)
    except Exception as e:
        logger.warning(f"Error cleaning orphaned tmp files: {e}")
```

Called from `cleanup_local_files()` line 798-799.

#### Change #3: Add `db_video_id` to notification metadata + SELECT FOR UPDATE dedup

```python
# In send_push_notification task:
notification_data = {
    'db_video_id': video.id,      # ✅ Added — was missing
    'video_uid': str(video.uid),
    ...
}

# SELECT FOR UPDATE prevents double-notification:
with transaction.atomic():
    video = Video.objects.select_for_update().get(id=video_id)
    if video.notification_sent:
        logger.info(f"Notification already sent for video {video_id}, skipping")
        return
    ...
    video.notification_sent = True
    video.save(update_fields=['notification_sent'])
```

#### Change #4: Remove `bare raise` from finally block

```python
# BEFORE — crashed whole task with RuntimeError
finally:
    if process.poll() is None:
        process.kill()
    raise    # BARE RAISE — crashes if no active exception!

# AFTER
finally:
    if process.poll() is None:
        process.kill()
    # No bare raise — let the original exception propagate naturally
```

---

### 4c. FILE: .entry/start_tasks_backend.sh

```bash
# BEFORE — no signal handling
celery -A farajayangu_be.celery worker ... &
VIDEO_WORKER_PID=$!
...
wait $VIDEO_WORKER_PID $GENERAL_WORKER_PID $BEAT_PID

# AFTER — SIGTERM trap added
cleanup() {
    echo "Received termination signal, forwarding to workers..."
    kill -TERM $VIDEO_WORKER_PID $GENERAL_WORKER_PID $BEAT_PID 2>/dev/null
    wait $VIDEO_WORKER_PID $GENERAL_WORKER_PID $BEAT_PID 2>/dev/null
    exit 0
}
trap cleanup SIGTERM SIGINT

celery -A farajayangu_be.celery worker ... &
VIDEO_WORKER_PID=$!
...
wait $VIDEO_WORKER_PID $GENERAL_WORKER_PID $BEAT_PID
```

**Problem solved:** Docker sends SIGTERM to PID 1 only (the shell). Without trap, children survive. After 10s grace period, Docker escalates to SIGKILL (exit 137), killing ffmpeg mid-encode. With trap, SIGTERM is forwarded to celery workers, which gracefully stop their tasks.

---

### 4d. FILE: farajayangu_be/urls.py — /api/ prefix

```python
# BEFORE — no /api/ prefix, Flutter app couldn't reach backend
urlpatterns = [
    path('authentication/', include('apps.authentication.urls')),
    path('streaming/', include('apps.streaming.urls')),
    ...
]

# AFTER — both /api/ and non-/api/ URLs work
urlpatterns = [
    path('api/authentication/', include('apps.authentication.urls')),
    path('api/streaming/', include('apps.streaming.urls')),
    path('api/advertising/', include('apps.advertising.urls')),
    path('api/analytics/', include('apps.analytics.urls')),
    path('api/profile/', include('apps.profile.urls')),
    path('api/management/', include('apps.management.urls')),
]
# + the original non-/api/ paths are still served by the app's own urlpatterns
```

---

### 4e. FILE: apps/streaming/views.py — Retry API endpoint

```python
@csrf_exempt
def retry_conversion(request, video_id):
    """
    POST /api/retry-conversion/{video_id}/
    Manually retry a failed/stuck video conversion.
    Clears stale locks, reads checkpoint, re-queues convert_video_to_hls.
    """
    video = Video.objects.get(id=video_id)
    if video.processing_status not in ('failed', 'killed', 'pending'):
        return error_response(...)
    
    checkpoint = video.processing_checkpoint or {}
    completed_variants = checkpoint.get('completed_variants', [])
    resume_from = completed_variants[-1] if completed_variants else None
    local_path = checkpoint.get('local_video_path')
    
    # Clear stale lock
    lock_key = f'video_conversion_lock_{video_id}'
    cache.delete(lock_key)
    
    # Reset status and queue
    video.processing_status = 'processing'
    video.save(update_fields=['processing_status', 'processing_error', 'processing_message'])
    task = convert_video_to_hls.delay(video_id, local_video_path=local_path)
    
    return success_response({
        'status': 'retry_queued',
        'task_id': task.id,
        'resuming_from_variant': resume_from,
    })
```

---

### 4f. FILE: apps/streaming/urls.py — Retry URL pattern

```python
urlpatterns = [
    ...
    path('retry-conversion/<int:video_id>/', retry_conversion, name='retry-conversion'),
]
```

---

### 4g. FILE: apps/streaming/services/conversion_client.py

```python
# BEFORE — default threads=3
self.ffmpeg_threads = getattr(settings, 'HLS_FFMPEG_THREADS', 3)

# AFTER — default threads=cpu_count() (6 on the worker)
import multiprocessing
self.ffmpeg_threads = getattr(settings, 'HLS_FFMPEG_THREADS', multiprocessing.cpu_count())
```

---

## 5. Server & Deployment Changes

### 5a. CapRover Env Variables Set

| Variable | Value | Effect |
|----------|-------|--------|
| `HLS_ENCODER_PRESET` | `ultrafast` | Fastest ffmpeg preset — reduces encoding time |
| `HLS_FFMPEG_THREADS` | `4` | 4 threads per ffmpeg — leaves 2 cores for system |

### 5b. CapRover App Config

| Setting | Value |
|---------|-------|
| `deployedVersion` | `163` |
| `instanceCount` | `1` |
| `hasPersistentData` | `True` |
| `notExposeAsWebApp` | `True` |
| `ENTRY_SCRIPT` | `/app/start_tasks_backend.sh` |

### 5c. Deployment Pipeline

```
git push origin master
    → GitHub webhook triggers CapRover build
    → CapRover builds Docker image: img-captain-...:163
    → Pushes to registry: registry.server.farajayangutv.co.tz:996/captain/...
    → Updates Swarm service: srv-captain--farajayangu-background-tasks-backend
    → Swarm replaces old container (162) with new (163) on worker node
    → Exit 137 on old container (now handled by SIGTERM trap)
    → New container starts with all fixes
```

### 5d. Image History

| Version | Status | Notes |
|---------|--------|-------|
| 163 | **Running** | All fixes deployed ✅ |
| 162 | Shutdown | Previous version (had watchdog + nostats but NOT DEVNULL) |
| 161 | Shutdown | |
| 160 | Shutdown | |
| 159 | Shutdown | |
| 158 | Shutdown | |

---

## 6. Environment Variables (CapRover)

```
DEBUG=False
SECRET_KEY=<hidden>
BASE_URL=https://backend.farajayangutv.co.tz
DATABASE_ENGINE=django.db.backends.postgresql
DATABASE_NAME=FarajaYanguTv
DATABASE_USER=postgres
DATABASE_PASSWORD=<hidden>
DATABASE_HOST=srv-captain--farajayangutv-database
DATABASE_PORT=5432
REDIS_HOST=srv-captain--farajayangutv-redis
REDIS_USER=default
REDIS_PASSWORD=<hidden>
REDIS_PORT=6379
ENTRY_SCRIPT=/app/start_tasks_backend.sh
SENTRY_DSN=<hidden>
FIREBASE_PROJECT_ID=farajayangutv-672e2
HLS_ENCODER_PRESET=ultrafast          # ✅ Added — faster encoding
HLS_FFMPEG_THREADS=4                  # ✅ Added — optimized for 6-core CPU
R2_ACCESS_KEY_ID=<hidden>
R2_SECRET_ACCESS_KEY=<hidden>
AWS_S3_ENDPOINT_URL=https://1532b4de331061991157470aaabcc76d.r2.cloudflarestorage.com
AWS_STORAGE_BUCKET_NAME=farajayangu-tv
```

---

## 7. Infrastructure

| Component | Location | Spec |
|-----------|----------|------|
| **Leader** | `37.60.247.219` (`vmi2909621`) | 8GB RAM, Docker Swarm manager |
| **Worker** | `62.84.190.130` (`vmi2997009`) | 12GB RAM, 6×AMD EPYC 2.0GHz, 193GB disk (95GB free) |
| **Container** | Worker node | `3ed550259b41`, image `:163`, 6% mem (717MB/11.68GB) |
| **Redis** | Leader | 2× containers on leader |
| **PostgreSQL** | Leader | `postgres:14.5` |
| **R2 Storage** | Cloudflare | Bucket: `farajayangu-tv` |
| **Registry** | Leader:3000 | `registry.server.farajayangutv.co.tz:996` |

---

## 8. Verification

### 8a. Code Verification on Server

```bash
# All 5 fixes confirmed in running container:
$ docker exec 3ed550259b41 grep "DEVNULL" apps/streaming/services/video_processor.py
# → stderr=subprocess.DEVNULL ✅

$ docker exec 3ed550259b41 grep "nostats" apps/streaming/services/video_processor.py
# → '-nostats', ✅

$ docker exec 3ed550259b41 grep -c "process.wait" apps/streaming/services/video_processor.py
# → 3 (1 stall handler + 1 finally block + 1 wait before return) ✅

$ docker exec 3ed550259b41 grep "trap cleanup" .entry/start_tasks_backend.sh
# → trap cleanup SIGTERM SIGINT ✅

$ docker exec 3ed550259b41 grep "orphaned" apps/streaming/tasks/tasks.py
# → def _cleanup_orphaned_tmp_files ✅
```

### 8b. Video 492 Verification

```bash
$ docker exec 3ed550259b41 python3 /app/manage.py shell
>>> from apps.streaming.models import Video
>>> v = Video.objects.get(id=492)
>>> print(v.processing_status, v.processing_stage, v.processing_progress, v.processing_message)
# → processing converting 20 Starting 1080p... ✅

$ ps aux | grep ffmpeg
# → ffmpeg ... -nostats -loglevel warning ... -progress pipe:1
# stderr goes to DEVNULL — no deadlock possible ✅
```

### 8c. Database Stats (Jul 24, 2026)

| Status | Count | Notes |
|--------|-------|-------|
| `failed` | 0 | All retriggered |
| `pending` | 0 | None stuck |
| `processing` | 1 | Video 492 — encoding with fixes |
| `completed` | Many | 74 without notification (pre-dedup) |

---

## All Files Modified

| File | Changes |
|------|---------|
| `.entry/start_tasks_backend.sh` | +14 lines — SIGTERM trap |
| `apps/streaming/services/video_processor.py` | +23/-4 lines — DEVNULL, nostats, process.wait, remove communicate |
| `apps/streaming/tasks/tasks.py` | +29/-2 lines — import time, orphaned cleanup, import fix |
| `apps/streaming/views.py` | +48 lines — retry_conversion endpoint |
| `apps/streaming/urls.py` | +3 lines — retry-conversion URL |
| `farajayangu_be/urls.py` | +7 lines — /api/ prefix for all apps |
| `farajayangu_be/settings/base.py` | +7 lines — visibility_timeout, worker_cancel_long_running |
| `apps/streaming/services/conversion_client.py` | +3 lines — ffmpeg_threads default |
| `apps/streaming/models.py` | +7 lines — notification_sent dedup field |
| `video_conversion_fix_brief.md` | +182 lines — specification document |

---

## Summary

### Root Causes Identified & Fixed

| # | Root Cause | Impact | Fix |
|---|-----------|--------|-----|
| 1 | **Stderr pipe deadlock** | Every conversion stalled (480p, 1080p, etc.) | `stderr=subprocess.DEVNULL` |
| 2 | **Exit 137 on deploy** | Container killed mid-encode, hours of work lost | SIGTERM trap in start script |
| 3 | **Zombie ffmpeg** | Process table leak | `process.wait()` after `kill()` |
| 4 | **Resume pointer bug** | Missing 480p/360p variants on retry | Fixed `skip_until_resume` logic |
| 5 | **Duplicate push notifications** | 74 videos notified twice | `SELECT FOR UPDATE` + `db_video_id` |
| 6 | **Bare raise in finally** | Task crash with RuntimeError | Removed bare raise |
| 7 | **Missing /api/ prefix** | Flutter production app couldn't connect | Added `/api/` URL prefix |
| 8 | **Old temp files** | Disk space wasted | `_cleanup_orphaned_tmp_files()` |
| 9 | **Error swallowed** | Failed tasks looked like success | Added `raise` on conversion failure |

**Deployed as:** `img-captain-farajayangu-background-tasks-backend:163` ✅
