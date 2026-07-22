#!/bin/bash

# Ensure timezone is correctly set
export TZ=Africa/Dar_es_Salaam

# Create logs directory if it doesn't exist
mkdir -p logs

echo "Starting Celery workers and beat scheduler..."

# Video processing worker
celery -A farajayangu_be.celery worker \
  -Q video_processing \
  -n video_worker@%h \
  --pool=prefork \
  --concurrency=3 \
  -Ofair \
  --prefetch-multiplier=1 \
  --max-tasks-per-child=2 \
  --max-memory-per-child=3000000 \
  --loglevel=INFO \
  --logfile=logs/celery_video_worker.log &
VIDEO_WORKER_PID=$!

# General tasks worker
celery -A farajayangu_be.celery worker \
  -Q general,celery \
  -n general_worker@%h \
  --pool=threads \
  --concurrency=4 \
  --max-tasks-per-child=50 \
  --loglevel=INFO \
  --logfile=logs/celery_general_worker.log &
GENERAL_WORKER_PID=$!

# Celery Beat scheduler
celery -A farajayangu_be beat \
  --scheduler django_celery_beat.schedulers:DatabaseScheduler \
  --loglevel=INFO \
  --logfile=logs/celery_beat.log &
BEAT_PID=$!

echo "Video Worker PID: $VIDEO_WORKER_PID"
echo "General Worker PID: $GENERAL_WORKER_PID"
echo "Beat Scheduler PID: $BEAT_PID"

wait $VIDEO_WORKER_PID $GENERAL_WORKER_PID $BEAT_PID
