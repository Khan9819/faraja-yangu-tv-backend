# Faraja Yangu TV Backend – Technical Overview

## Overview
This repository is a Django-based backend for Faraja Yangu TV, providing APIs and realtime infrastructure for uploading, processing, and streaming video content using HTTP Live Streaming (HLS). It includes user authentication, profile management, analytics/notifications, advertising, and admin/management endpoints.

## Tech Stack
- **Language**: Python 3.12
- **Framework**: Django 5.x, Django REST Framework (DRF)
- **Realtime**: Django Channels 4 (ASGI) + Redis (channels_redis)
- **Background Jobs**: Celery 5 + Celery Beat
- **Message Broker/Result Backend**: Redis
- **Storage**: django-storages (S3 backend) + Boto3 targeting Cloudflare R2
- **Video Processing**: FFmpeg (ffmpeg, ffprobe) via `ffmpeg-python` and subprocess execution
- **Email**: Azure Communication Services Email SDK
- **Push Notifications**: Firebase Admin SDK
- **Docs (OpenAPI/Swagger)**: drf-spectacular (route wired; ensure dependency is installed)
- **Runtime in Prod**: Nginx + Gunicorn (Uvicorn worker) ASGI app
- **Observability**: Sentry SDK
- **Containerization**: Docker, CapRover deployment

## Key Services (Django Apps)
- **apps.authentication**: JWT-based auth, registration, OTP flows (email via Azure), Google login hooks, profile completion, password reset.
- **apps.streaming**: Categories, videos, HLS streaming endpoints, likes/dislikes, comments, playlists, chunked uploads, download tracking, related videos.
- **apps.streaming.tasks**: Celery tasks for chunk assembly, MP4→HLS conversion, cleanup, and push notifications.
- **apps.streaming.socket**: WebSocket consumer for video processing progress (`VideoProcessorConsumer`).
- **apps.analytics**: Notifications: list, read, delete, clear.
- **apps.advertising**: Carousel and interceptor ads management and reward claiming.
- **apps.profile**: User profile retrieval/update, avatar upload, password reset, data/account deletion requests.
- **apps.management**: Dashboard summaries, stats, analytics charts, and ads management.
- **apps.common**: Shared services (e.g., OTP service with email templates) and base models/utilities.

## Core Dependencies and Integrations
- **Django + DRF**: API foundation. Standardized responses via `core/response_wrapper.py`.
- **SimpleJWT**: Configured in `settings/base.py` for access/refresh tokens.
- **Channels + channels_redis**: ASGI routing in `farajayangu_be/asgi.py`, channel layer configured to Redis using env vars.
- **Celery + Beat**: Config in `farajayangu_be/celery.py`, schedules daily cleanup of stale chunks.
- **Storage**: `django-storages` S3 backend pointed at Cloudflare R2 via endpoint/region/keys env vars for both default and static storage.
- **FFmpeg**: Conversion to multi-bitrate HLS variants; master playlist creation; upload of generated files to R2.
- **Azure Communication Services**: Outbound email (OTP, etc.).
- **Firebase Admin**: Push notifications to device tokens for new videos or comment replies.
- **Sentry**: Error and performance monitoring.

## Runtime Architecture
- **ASGI App**: `farajayangu_be.asgi.application` with `ProtocolTypeRouter` for `http`, `websocket`, and custom lifespan hooks for structured startup/shutdown logs.
- **Web Server (Prod)**: Nginx reverse proxy → Gunicorn (`uvicorn.workers.UvicornWorker`) → ASGI app.
- **Background Processing**: Separate Celery worker and Celery Beat processes (entry scripts provided).
- **Redis**: Required for Channels (websockets) and Celery broker/result backend.

## WebSocket Interface
- **Endpoint**: `ws://<host>/socket/stream/progress/<int:video_uid>/?token=<JWT>`
- **Auth**: Query string `token` (SimpleJWT access token).
- **Events**: `video_progress`, `video_complete`, `video_error` sent to groups named `video_progress_<video_uid>`.

## Video Ingestion and HLS Flow
1. Client uploads in chunks to S3-compatible storage (R2) through chunk endpoints.
2. `assemble_chunks_task` merges chunks into an MP4 and saves to storage.
3. `convert_video_to_hls` downloads the MP4 to a temp path, runs FFmpeg to produce variants (1080p, 720p, 480p, 360p), writes a master playlist, and uploads HLS assets to `videos/hls/<video.uid>` in R2.
4. On success, original MP4 can be removed; progress and completion are emitted over websockets; push notifications optionally sent to users.
5. Daily `cleanup_stale_chunks` removes incomplete/orphan chunk files.

## Configuration and Environment
Environment loaded from `.env` in project root. Important variables (see `farajayangu_be/settings/base.py`):
- **Core**: `DEBUG`, `SECRET_KEY`, `BASE_URL`, `BACKEND_URL`.
- **Database**: `DATABASE_ENGINE`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_HOST`, `DATABASE_PORT`.
- **Redis**: `REDIS_HOST`, `REDIS_PORT`, `REDIS_USER`, `REDIS_PASSWORD`.
- **JWT**: `JWT_ACCESS_TTL_MINUTES`.
- **Storage (R2/S3)**: `R2_ACCESS_KEY_ID` (aliased to `AWS_ACCESS_KEY_ID`), `R2_SECRET_ACCESS_KEY` (aliased), `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL`, `AWS_S3_REGION_NAME`.
- **Email (Azure)**: `AZURE_EMAIL_ENDPOINT`, `AZURE_EMAIL_KEY`, `NO_REPLY_SENDER_EMAIL`.
- **Sentry**: `SENTRY_DSN`.
- **OAuth/Google**: `GOOGLE_CLIENT_ID` (if used).
- **Firebase**: `FIREBASE_PROJECT_ID`, `FIREBASE_PRIVATE_KEY_ID`, `FIREBASE_PRIVATE_KEY`, `FIREBASE_CLIENT_EMAIL`, `FIREBASE_CLIENT_ID`.

## Deployment
- **Dockerfile**: Installs Python 3.12, FFmpeg, dependencies; copies Nginx configs; exposes port 80; entry controlled via `ENTRY_SCRIPT`.
  - `ENTRY_SCRIPT=/app/start_core_backend.sh` runs Nginx + Gunicorn ASGI web.
  - `ENTRY_SCRIPT=/app/start_tasks_backend.sh` runs Celery worker + Beat.
- **CapRover**: `captain-definition` present. Recommended to create two CapRover apps: one for the web process, one for Celery tasks, both built from the same image but different `ENTRY_SCRIPT` env.

## Local Development
- Use Python 3.12 virtualenv and `pip install -r requirements.txt`.
- Ensure Redis is available (e.g., `docker run -d -p 6379:6379 redis:7`).
- Run server: `python manage.py migrate && python manage.py runserver`.
- Run workers: `celery -A farajayangu_be.celery worker -l info --pool=threads -E` and `celery -A farajayangu_be beat -l INFO --scheduler django_celery_beat.schedulers:DatabaseScheduler`.
- `docker-compose.yml` supports a development web container (Django runserver). It uses `.env` from project root.

## API Documentation
- Routes declared in `farajayangu_be/schema.py`:
  - `/schema/` (OpenAPI JSON)
  - `/docs/` (Swagger UI)
- Requires `drf-spectacular` and `drf-spectacular[sidecar]` (not pinned in requirements by default). Install if you intend to serve interactive docs.

## Notable Files and Entry Points
- `manage.py` – CLI/management commands.
- `farajayangu_be/asgi.py` – ASGI app (http + websocket + lifespan).
- `farajayangu_be/urls.py` – Root HTTP routes; includes app URLs and a Sentry test endpoint.
- `farajayangu_be/ws_urls.py` – WebSocket URL patterns.
- `farajayangu_be/celery.py` – Celery app and Beat schedule.
- `apps/streaming/services/video_processor.py` – FFmpeg-based HLS processing.
- `.entry/start_core_backend.sh`, `.entry/start_tasks_backend.sh` – process launchers for prod containers.

## Security & CORS
- `ALLOWED_HOSTS` and CORS/CSRF origins adapt to `DEBUG` mode.
- SimpleJWT-based authentication for APIs and WebSocket token auth.

## Observability
- Sentry initialized in settings with environment set by `DEBUG` flag.

## Known Considerations
- Ensure FFmpeg is installed on host for local processing (see `docs/INSTALL_FFMPEG.md`). Docker image already installs FFmpeg.
- Interactive API docs require drf-spectacular which may need to be added to requirements.
- For production storage, use Cloudflare R2 credentials and endpoint; for development, you can also rely on default local filesystem if desired by adjusting `STORAGES` accordingly.
 - The Dockerfile references Nginx and Gunicorn config files under `.config/` (e.g., `default.conf`, `site.com`) and `-c .config/gunicorn_config.py` in the start script. Ensure these files exist in the repo or update the Dockerfile/start script accordingly.
 - `wsgi.py` points to `farajayangu_be.settings.dev` which is not present; production uses ASGI via `asgi.py`. If you need WSGI (e.g., for certain hosting environments), create appropriate settings or repoint to `settings.base`.
