#!/bin/bash

# Ensure timezone is correctly set
export TZ=Africa/Dar_es_Salaam

# Create logs directory if it doesn't exist
mkdir -p logs

VIDEO_WORKER_LOG="logs/celery_video_worker.log"
GENERAL_WORKER_LOG="logs/celery_general_worker.log"
BEAT_LOG="logs/celery_beat.log"

echo "Starting Celery workers and beat scheduler..."
echo "  - Video Worker: $VIDEO_WORKER_LOG (queue: video_processing)"
echo "  - General Worker: $GENERAL_WORKER_LOG (queues: general, celery)"
echo "  - Beat Scheduler: $BEAT_LOG"

# Video processing worker — dedicated pool for CPU-intensive tasks
# Concurrency=3 with 2GB/child = 6GB RAM budget
# prefetch=1 prevents task hoarding, Ofair ensures fair distribution
# max-tasks-per-child=2 recycles workers to prevent memory leaks
celery -A farajayangu_be.celery worker \
  -Q video_processing \
  -n video_worker@%h \
  --pool=prefork \
  --concurrency=3 \
  -Ofair \
  --prefetch-multiplier=1 \
  --max-tasks-per-child=2 \
  --max-memory-per-child=3000000 \
  --time-limit=32400 \
  --soft-time-limit=28800 \
  -E \
  --loglevel=INFO \
  --logfile="$VIDEO_WORKER_LOG" &
VIDEO_WORKER_PID=$!

# General tasks worker — thread pool for I/O-bound tasks
celery -A farajayangu_be.celery worker \
  -Q general,celery \
  -n general_worker@%h \
  --pool=threads \
  --concurrency=4 \
  --max-tasks-per-child=50 \
  -E \
  --loglevel=INFO \
  --logfile="$GENERAL_WORKER_LOG" &
GENERAL_WORKER_PID=$!

# Celery Beat scheduler
celery -A farajayangu_be beat \
  --scheduler django_celery_beat.schedulers:DatabaseScheduler \
  --loglevel=INFO \
  --logfile="$BEAT_LOG" &
BEAT_PID=$!

echo "Video Worker PID: $VIDEO_WORKER_PID (prefork, concurrency=3, 2GB/child, 8hr limit)"
echo "General Worker PID: $GENERAL_WORKER_PID (threads, concurrency=4)"
echo "Beat Scheduler PID: $BEAT_PID"

# Wait for all processes (keeps container running)
wait $VIDEO_WORKER_PID $GENERAL_WORKER_PID $BEAT_PID
