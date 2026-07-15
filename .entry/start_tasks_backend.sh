#!/bin/bash

# Ensure timezone is correctly set
export TZ=Africa/Dar_es_Salaam

# Create logs directory if it doesn't exist
mkdir -p logs

# Set log file paths
VIDEO_WORKER_LOG="logs/celery_video_worker.log"
GENERAL_WORKER_LOG="logs/celery_general_worker.log"
BEAT_LOG="logs/celery_beat.log"

echo "Starting Celery workers and beat scheduler..."
echo "Log files:"
echo "  - Video Worker: $VIDEO_WORKER_LOG"
echo "  - General Worker: $GENERAL_WORKER_LOG"
echo "  - Beat Scheduler: $BEAT_LOG"

# Start Celery worker for video processing (dedicated queue)
# Uses prefork pool for CPU-intensive video processing tasks (FFmpeg, assembly)
# Limited concurrency to prevent resource exhaustion
# max-tasks-per-child=5 recycles workers to prevent memory leaks
celery -A farajayangu_be.celery worker \
  -Q video_processing \
  -n video_worker@%h \
  -l info \
  --pool=prefork \
  --concurrency=2 \
  --max-tasks-per-child=5 \
  -E \
  --logfile="$VIDEO_WORKER_LOG" &
VIDEO_WORKER_PID=$!

# Start Celery worker for general tasks (emails, notifications, cleanup, etc.)
# Uses threads pool for I/O-bound tasks
# Higher concurrency since threads are lightweight
# Handles both 'general' and 'celery' (default) queues
celery -A farajayangu_be.celery worker \
  -Q general,celery \
  -n general_worker@%h \
  -l info \
  --pool=threads \
  --concurrency=4 \
  --max-tasks-per-child=50 \
  -E \
  --logfile="$GENERAL_WORKER_LOG" &
GENERAL_WORKER_PID=$!

# Start Celery beat scheduler in background
celery -A farajayangu_be beat \
  -l INFO \
  --scheduler django_celery_beat.schedulers:DatabaseScheduler \
  --logfile="$BEAT_LOG" &
BEAT_PID=$!

echo "Video Processing Worker started with PID: $VIDEO_WORKER_PID (queue: video_processing, pool: prefork, concurrency: 2)"
echo "General Tasks Worker started with PID: $GENERAL_WORKER_PID (queues: general,celery, pool: threads, concurrency: 4)"
echo "Celery Beat started with PID: $BEAT_PID"

# Wait for all processes (keeps container running)
wait $VIDEO_WORKER_PID $GENERAL_WORKER_PID $BEAT_PID
