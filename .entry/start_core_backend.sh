#!/bin/bash

# Ensure timezone is correctly set
export TZ=Africa/Dar_es_Salaam

# Environment diagnostics: make package drift visible in logs immediately
echo "=== ENV DIAGNOSTICS ==="
python3.12 --version
python3.12 -c "import django; print('Django', django.get_version())" || echo "!!! DJANGO IMPORT FAILED !!!"
python3.12 -c "import rest_framework; print('DRF', rest_framework.VERSION)" || echo "!!! DRF IMPORT FAILED !!!"
echo "=== END DIAGNOSTICS ==="

# Run database migrations before starting services
echo "Running database migrations..."
python3.12 manage.py migrate --noinput || echo "!!! MIGRATION FAILED — CHECK ERRORS ABOVE !!!"
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

# Start nginx in background
nginx -g 'daemon off;' &
NGINX_PID=$!
echo "Nginx started with PID: $NGINX_PID"

# Start gunicorn
gunicorn -c .config/gunicorn_config.py farajayangu_be.asgi \
  -k uvicorn.workers.UvicornWorker \
  --access-logfile "$GUNICORN_ACCESS_LOG" \
  --error-logfile "$GUNICORN_ERROR_LOG" &
GUNICORN_PID=$!
echo "Gunicorn started with PID: $GUNICORN_PID"

# Celery workers run on farajayangu-background-tasks-backend service only
echo "Celery handled by background-tasks-backend service"

# Wait for all processes
wait $NGINX_PID $GUNICORN_PID
