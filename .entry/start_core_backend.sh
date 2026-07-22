#!/bin/bash

# Ensure timezone is correctly set
export TZ=Africa/Dar_es_Salaam

# Run database migrations before starting services
echo "Running database migrations..."
python3.12 manage.py migrate --noinput
echo "Migrations complete."

# Create logs directory if it doesn't exist
mkdir -p logs

# Set log file paths
NGINX_ACCESS_LOG="logs/nginx_access.log"
NGINX_ERROR_LOG="logs/nginx_error.log"
GUNICORN_ACCESS_LOG="logs/gunicorn_access.log"
GUNICORN_ERROR_LOG="logs/gunicorn_error.log"

echo "Starting Django application server..."
echo "Log files:"
echo "  - Nginx Access: $NGINX_ACCESS_LOG"
echo "  - Nginx Error: $NGINX_ERROR_LOG"
echo "  - Gunicorn Access: $GUNICORN_ACCESS_LOG"
echo "  - Gunicorn Error: $GUNICORN_ERROR_LOG"

# Start nginx in background (logs configured in nginx.conf)
nginx -g 'daemon off;' &
NGINX_PID=$!
echo "Nginx started with PID: $NGINX_PID"

# Start gunicorn with log files
gunicorn -c .config/gunicorn_config.py farajayangu_be.asgi \
  -k uvicorn.workers.UvicornWorker \
  --access-logfile "$GUNICORN_ACCESS_LOG" \
  --error-logfile "$GUNICORN_ERROR_LOG" &
GUNICORN_PID=$!
echo "Gunicorn started with PID: $GUNICORN_PID"

# Celery workers (temporary — will move to background-tasks-backend once stable)
CELERY_WORKER_LOG="logs/celery_video_worker.log"
CELERY_GENERAL_LOG="logs/celery_general_worker.log"
CELERY_BEAT_LOG="logs/celery_beat.log"
echo "Starting Celery workers..."

celery -A farajayangu_be.celery worker -Q video_processing \
  -n video_worker@%h --pool=prefork --concurrency=1 \
  --max-tasks-per-child=50 --loglevel=INFO > "$CELERY_WORKER_LOG" 2>&1 &
CELERY_VIDEO_PID=$!

celery -A farajayangu_be.celery worker -Q general,celery \
  -n general_worker@%h --pool=threads --concurrency=4 \
  --max-tasks-per-child=50 --loglevel=INFO > "$CELERY_GENERAL_LOG" 2>&1 &
CELERY_GENERAL_PID=$!

celery -A farajayangu_be beat \
  --scheduler django_celery_beat.schedulers:DatabaseScheduler \
  > "$CELERY_BEAT_LOG" 2>&1 &
CELERY_BEAT_PID=$!

echo "  Workers started: video=$CELERY_VIDEO_PID general=$CELERY_GENERAL_PID beat=$CELERY_BEAT_PID"

# Wait for all processes (keeps container running)
wait $NGINX_PID $GUNICORN_PID
