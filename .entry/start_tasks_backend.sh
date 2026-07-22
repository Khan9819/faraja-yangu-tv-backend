#!/bin/bash
export TZ=Africa/Dar_es_Salaam
mkdir -p logs

celery -A farajayangu_be.celery worker -Q video_processing -n video_worker@%h --pool=prefork --concurrency=1 --loglevel=INFO &
PID1=$!
celery -A farajayangu_be.celery worker -Q general,celery -n general_worker@%h --pool=threads --concurrency=4 --loglevel=INFO &
PID2=$!
celery -A farajayangu_be beat --scheduler django_celery_beat.schedulers:DatabaseScheduler &
PID3=$!

echo "All started. PIDs: $PID1 $PID2 $PID3"
wait $PID1 $PID2 $PID3
