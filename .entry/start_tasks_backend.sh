#!/bin/bash
export TZ=Africa/Dar_es_Salaam
mkdir -p logs

echo "Starting Celery workers..."

# Video worker — dedicated CPU pool, 3 concurrent, 2GB/child
celery -A farajayangu_be.celery worker \
  -Q video_processing \
  -n video_worker@%h \
  --pool=prefork \
  --concurrency=3 \
  -Ofair \
  --prefetch-multiplier=1 \
  --max-tasks-per-child=2 \
  --max-memory-per-child=2000000 \
  --loglevel=INFO &
VIDEO_PID=$!

# General worker — thread pool for I/O tasks
celery -A farajayangu_be.celery worker \
  -Q general,celery \
  -n general_worker@%h \
  --pool=threads \
  --concurrency=4 \
  --max-tasks-per-child=50 \
  --loglevel=INFO &
GENERAL_PID=$!

# Beat scheduler
celery -A farajayangu_be beat \
  --scheduler django_celery_beat.schedulers:DatabaseScheduler &
BEAT_PID=$!

echo "Video PID: $VIDEO_PID, General PID: $GENERAL_PID, Beat PID: $BEAT_PID"
wait $VIDEO_PID $GENERAL_PID $BEAT_PID
