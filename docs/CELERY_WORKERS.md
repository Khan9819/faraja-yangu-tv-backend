# Celery Workers Configuration

This document describes the Celery worker architecture for the FarajaTV backend, including queue separation and resource allocation.

## Architecture Overview

The system uses **two separate Celery workers** to handle different types of tasks:

1. **Video Processing Worker** - Handles CPU-intensive video processing tasks
2. **General Tasks Worker** - Handles I/O-bound tasks (emails, notifications, etc.)

This separation ensures that resource-intensive video processing doesn't block lightweight tasks like sending emails or push notifications.

---

## Queue Configuration

### Queues Defined

**File:** `farajayangu_be/celery.py`

```python
app.conf.task_routes = {
    'apps.streaming.tasks.tasks.assemble_chunks_task': {'queue': 'video_processing'},
    'apps.streaming.tasks.tasks.convert_video_to_hls': {'queue': 'video_processing'},
    'apps.streaming.tasks.tasks.cleanup_stale_chunks': {'queue': 'general'},
    'apps.authentication.tasks.main.*': {'queue': 'general'},
    'apps.streaming.tasks.tasks.send_push_notification': {'queue': 'general'},
}

app.conf.task_default_queue = 'general'
```

### Queue Assignments

| Queue | Tasks | Purpose |
|-------|-------|---------|
| `video_processing` | `assemble_chunks_task`, `convert_video_to_hls` | CPU-intensive video encoding and processing |
| `general` | Email tasks, notifications, cleanup, device sync | I/O-bound operations and lightweight tasks |

---

## Worker Configuration

### 1. Video Processing Worker

**Queue:** `video_processing`  
**Pool Type:** `prefork` (process-based)  
**Concurrency:** `2`  
**Worker Name:** `video_worker@hostname`

**Why prefork?**
- Video processing is CPU-intensive (FFmpeg encoding)
- Process isolation prevents memory leaks from affecting other tasks
- Better for long-running tasks

**Why concurrency 2?**
- Video encoding is resource-intensive
- Limits parallel processing to prevent CPU/memory exhaustion
- Adjust based on server resources (increase for more powerful servers)

**Command:**
```bash
celery -A farajayangu_be.celery worker \
  -Q video_processing \
  -n video_worker@%h \
  -l info \
  --pool=prefork \
  --concurrency=2 \
  -E
```

---

### 2. General Tasks Worker

**Queue:** `general`  
**Pool Type:** `threads` (thread-based)  
**Concurrency:** `4`  
**Worker Name:** `general_worker@hostname`

**Why threads?**
- General tasks are I/O-bound (network requests, database queries)
- Threads are lightweight and efficient for I/O operations
- Faster task switching for quick operations

**Why concurrency 4?**
- Allows multiple lightweight tasks to run simultaneously
- Can be increased if needed (e.g., 8-16 for high-traffic scenarios)
- Threads share memory, so overhead is minimal

**Command:**
```bash
celery -A farajayangu_be.celery worker \
  -Q general \
  -n general_worker@%h \
  -l info \
  --pool=threads \
  --concurrency=4 \
  -E
```

---

## Startup Script

**File:** `.entry/start_tasks_backend.sh`

The startup script launches both workers and the beat scheduler:

```bash
#!/bin/bash

# Video Processing Worker (prefork, concurrency 2)
celery -A farajayangu_be.celery worker \
  -Q video_processing \
  -n video_worker@%h \
  -l info \
  --pool=prefork \
  --concurrency=2 \
  -E &
VIDEO_WORKER_PID=$!

# General Tasks Worker (threads, concurrency 4)
celery -A farajayangu_be.celery worker \
  -Q general \
  -n general_worker@%h \
  -l info \
  --pool=threads \
  --concurrency=4 \
  -E &
GENERAL_WORKER_PID=$!

# Beat Scheduler
celery -A farajayangu_be beat \
  -l INFO \
  --scheduler django_celery_beat.schedulers:DatabaseScheduler &
BEAT_PID=$!

# Wait for all processes
wait $VIDEO_WORKER_PID $GENERAL_WORKER_PID $BEAT_PID
```

---

## Benefits of Worker Separation

### 1. **Resource Isolation**
- Video processing can't starve other tasks of resources
- Email/notification tasks remain responsive even during heavy video processing

### 2. **Independent Scaling**
- Scale video workers independently based on encoding load
- Scale general workers based on user activity

### 3. **Better Monitoring**
- Separate metrics for each worker type
- Easier to identify bottlenecks

### 4. **Fault Tolerance**
- If video worker crashes, general tasks continue
- Critical operations (emails, notifications) remain unaffected

### 5. **Performance Optimization**
- Prefork pool for CPU-bound tasks (video processing)
- Thread pool for I/O-bound tasks (network operations)

---

## Monitoring Workers

### Check Worker Status

```bash
# List all active workers
celery -A farajayangu_be inspect active

# Check registered tasks
celery -A farajayangu_be inspect registered

# Monitor queue lengths
celery -A farajayangu_be inspect stats
```

### Monitor Specific Queue

```bash
# Check video_processing queue
celery -A farajayangu_be inspect active_queues | grep video_processing

# Check general queue
celery -A farajayangu_be inspect active_queues | grep general
```

### View Worker Logs

```bash
# Docker logs for Celery container
docker-compose logs -f celery

# Filter for specific worker
docker-compose logs -f celery | grep video_worker
docker-compose logs -f celery | grep general_worker
```

---

## Scaling Recommendations

### Development Environment
- Video worker: concurrency 1-2
- General worker: concurrency 2-4

### Production (Small - 2-4 CPU cores)
- Video worker: concurrency 2
- General worker: concurrency 4-8

### Production (Medium - 8-16 CPU cores)
- Video worker: concurrency 4-6
- General worker: concurrency 8-16

### Production (Large - 16+ CPU cores)
- Video worker: concurrency 8-12
- General worker: concurrency 16-32
- Consider running multiple worker containers

---

## Adding New Tasks

### To Video Processing Queue

```python
from celery import shared_task

@shared_task(queue='video_processing')
def my_video_task(video_id):
    # CPU-intensive video processing
    pass
```

Or add to routing in `celery.py`:

```python
app.conf.task_routes = {
    'apps.streaming.tasks.tasks.my_video_task': {'queue': 'video_processing'},
}
```

### To General Queue

Tasks automatically go to `general` queue (default), or explicitly:

```python
@shared_task(queue='general')
def my_general_task():
    # I/O-bound task
    pass
```

---

## Troubleshooting

### Video Processing Tasks Not Running

**Check if video worker is running:**
```bash
celery -A farajayangu_be inspect active_queues | grep video_processing
```

**Check task routing:**
```bash
celery -A farajayangu_be inspect registered | grep video_processing
```

### General Tasks Delayed

**Check queue length:**
```bash
celery -A farajayangu_be inspect stats
```

**Increase general worker concurrency:**
Edit `.entry/start_tasks_backend.sh` and increase `--concurrency=4` to `--concurrency=8`

### High Memory Usage

**Video worker:**
- Reduce concurrency from 2 to 1
- Video processing is memory-intensive

**General worker:**
- Check for memory leaks in tasks
- Restart workers periodically if needed

---

## Docker Compose Configuration

If you need to run workers in separate containers:

```yaml
services:
  celery_video:
    build: .
    command: celery -A farajayangu_be.celery worker -Q video_processing -n video_worker@%h --pool=prefork --concurrency=2 -E
    depends_on:
      - redis
      - db
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      
  celery_general:
    build: .
    command: celery -A farajayangu_be.celery worker -Q general -n general_worker@%h --pool=threads --concurrency=4 -E
    depends_on:
      - redis
      - db
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      
  celery_beat:
    build: .
    command: celery -A farajayangu_be beat -l INFO --scheduler django_celery_beat.schedulers:DatabaseScheduler
    depends_on:
      - redis
      - db
```

---

## Performance Metrics

### Expected Performance

| Metric | Video Worker | General Worker |
|--------|--------------|----------------|
| Task throughput | 1-2 videos/hour (depends on video size) | 100-500 tasks/minute |
| Memory usage | 500MB-2GB per task | 50-200MB total |
| CPU usage | 80-100% per worker | 10-30% total |
| Task duration | 5-30 minutes | 1-10 seconds |

---

## Best Practices

1. **Monitor queue lengths** - If video_processing queue grows, scale video workers
2. **Set task timeouts** - Prevent hung tasks from blocking workers
3. **Use task retries** - Handle transient failures gracefully
4. **Log task execution** - Track performance and debug issues
5. **Regular restarts** - Restart workers weekly to clear memory leaks
6. **Resource limits** - Set Docker memory/CPU limits to prevent resource exhaustion

---

## Related Documentation

- [PERFORMANCE_OPTIMIZATIONS.md](./PERFORMANCE_OPTIMIZATIONS.md) - Backend performance improvements
- [TECHNICAL_OVERVIEW.md](./TECHNICAL_OVERVIEW.md) - System architecture
- [CHANGELOG.md](../.changelog/CHANGELOG.md) - Recent changes and improvements
