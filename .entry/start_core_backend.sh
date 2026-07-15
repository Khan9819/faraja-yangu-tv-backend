#!/bin/bash

# Ensure timezone is correctly set
export TZ=Africa/Dar_es_Salaam

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
# Note: access_log and error_log must be configured in nginx.conf, not via -g flag
nginx -g 'daemon off;' &
NGINX_PID=$!

echo "Nginx started with PID: $NGINX_PID"
echo "Note: Configure nginx logs in nginx.conf using:"
echo "  error_log $NGINX_ERROR_LOG warn;"
echo "  access_log $NGINX_ACCESS_LOG;"

# Start gunicorn with log files
gunicorn -c .config/gunicorn_config.py farajayangu_be.asgi \
  -k uvicorn.workers.UvicornWorker \
  --access-logfile "$GUNICORN_ACCESS_LOG" \
  --error-logfile "$GUNICORN_ERROR_LOG" &
GUNICORN_PID=$!

echo "Gunicorn started with PID: $GUNICORN_PID"

# Wait for both processes (keeps container running)
wait $NGINX_PID $GUNICORN_PID
