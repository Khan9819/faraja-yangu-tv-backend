# Faraja Yangu TV Backend

Django + DRF + Channels + Celery backend powering video upload, HLS streaming, authentication, analytics, and advertising for Faraja Yangu TV.

---

## 📋 Project Description

<!-- Add your project-specific description here -->
*This section is for you to describe what your project does, its main features, and business purpose.*

---

## 🏗️ Architecture Overview

This project uses a modular Django layout with production-grade components:

- **Django + DRF APIs** for core features under `apps/`
- **ASGI + Channels** with Redis for WebSocket progress updates
- **Celery workers + Beat** for video processing and scheduled cleanup
- **Cloud storage (S3-compatible R2)** via `django-storages` and `boto3`
- **JWT Authentication** with SimpleJWT
- **Sentry** for monitoring and error tracking
- **Dockerized runtime** with Nginx + Gunicorn (Uvicorn worker)
- **Firebase Admin** integration for push notifications

Client                    Django Views                 Celery Workers              R2 Storage
  │                           │                            │                         │
  ├─ POST create_video ──────►│ (creates Video record)     │                         │
  │                           │                            │                         │
  ├─ POST get_chunk_upload_url►│ (presigned PUT URL) ──────┼────────────────────────►│
  │  or POST upload_chunk ───►│ (saves chunk via django)   │                         │
  │                           │  ── WebSocket progress ──► │                         │
  │                           │                            │                         │
  ├─ POST assemble_chunks ───►│ ── .delay() ──────────────►│ assemble_chunks_task    │
  │                           │                            │  ├─ stream chunks ◄─────┤
  │                           │                            │  ├─ merge to local MP4  │
  │                           │                            │  ├─ delete chunks ─────►│
  │                           │                            │  └─ .delay() ──────────►│
  │                           │                            │                         │
  │                           │                            │ convert_video_to_hls    │
  │                           │                            │  ├─ download (or reuse) │
  │                           │                            │  ├─ FFmpeg → HLS local  │
  │                           │                            │  ├─ upload HLS ────────►│
  │                           │                            │  ├─ delete local + MP4  │
  │                           │                            │  ├─ update Video model  │
  │                           │                            │  └─ push notification   │
  │                           │                            │                         │
  ├─ GET stream_hls ─────────►│ (proxy from R2, inject ads)│                    ◄────┤

## 📁 Project Structure

```
farajayangu_be/
├── .env                    # Environment variables
├── .knowledge/             # AI documentation for project understanding
├── manage.py              # Django management script
├── requirements.txt       # Python dependencies
├── docker-compose.yml     # Local development environment
├── farajayangu_be/        # Django project configuration
│   ├── settings/          # Split settings (dev/prod)
│   ├── urls.py           # Main URL routing
│   └── management/       # Custom management commands
├── apps/                 # Django applications
│   ├── common/           # Shared utilities and base models
│   └── [your_apps]/      # Feature-specific apps
└── core/                 # Framework utilities and extensions
    ├── response_wrapper.py  # Standardized API responses
    ├── pagination.py       # DRF pagination classes
    └── services/           # External service integrations
```

## 🚀 Quick Start

### Prerequisites
- Python 3.12
- Redis 6/7 running locally or reachable over network
- FFmpeg (ffmpeg, ffprobe) installed and available on PATH

### 1. Environment Setup
```bash
# Clone and navigate to project
cd farajayangu_be

# Create virtual environment
python -m venv env
source env/bin/activate  # On Windows: env\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Database Setup
```bash
# Run migrations
python manage.py migrate

# Create superuser (optional)
python manage.py createsuperuser
```

### 3. Run Development Server
```bash
python manage.py runserver
```

The API will be available at:
- **API Base**: http://127.0.0.1:8000/
- **Admin Panel**: http://127.0.0.1:8000/admin/

### 4. Start Redis and Workers
Redis is required for WebSockets (Channels) and Celery.

```bash
# Start Redis (example using Docker)
docker run -d --name redis -p 6379:6379 redis:7

# Start Celery worker and beat in separate shells
celery -A farajayangu_be.celery worker -l info --pool=threads -E
celery -A farajayangu_be beat -l INFO --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

## 🛠️ Development Commands

### App Management
```bash
# Create new app with NTC structure
python manage.py create_app app_name

# Alternative: Use NTC CLI (if installed globally)
ntc create app app_name
```

### Database Operations
```bash
# Create migrations
python manage.py makemigrations [app_name]

# Apply migrations
python manage.py migrate

# Reset database (development only)
python manage.py flush
```

### Development Tools
```bash
# Run tests
python manage.py test

# Collect static files (production)
python manage.py collectstatic

# Django shell
python manage.py shell
```

## 🏛️ Development Patterns

### API Response Format
All endpoints return standardized responses:

```json
{
  "status": "success|error",
  "message": "Human-readable message",
  "data": { /* Response data */ }
}
```

### Service/Selector Pattern
```python
# Business logic in services/
from apps.myapp.services.user_service import create_user

# Data queries in selectors/
from apps.myapp.selectors.user_selector import get_active_users

# Views handle HTTP only
@api_view(['POST'])
def create_user_view(request):
    user = create_user(request.data)
    return success_response(data=user, message="User created")
```

### Model Inheritance
```python
# Use TimeStampedModel for automatic timestamps
from apps.common.models import TimeStampedModel

class MyModel(TimeStampedModel):
    name = models.CharField(max_length=100)
    # created_at and updated_at added automatically
```

## 🔧 Configuration

### Environment Variables
Create a `.env` file in the project root with at least:

```env
# Core
DEBUG=True
SECRET_KEY=your-secret-key
BASE_URL=http://127.0.0.1:8000
BACKEND_URL=http://127.0.0.1:8000

# Database (SQLite dev)
DATABASE_ENGINE=django.db.backends.sqlite3
DATABASE_NAME=db.sqlite3

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
# If you use auth on Redis
# REDIS_USER=
# REDIS_PASSWORD=

# Storage (Cloudflare R2 or S3-compatible)
R2_ACCESS_KEY_ID=your-access-key
R2_SECRET_ACCESS_KEY=your-secret
AWS_STORAGE_BUCKET_NAME=your-bucket
AWS_S3_ENDPOINT_URL=https://<your-account-id>.r2.cloudflarestorage.com
AWS_S3_REGION_NAME=auto

# Azure Email (OTP, notifications)
AZURE_EMAIL_ENDPOINT=your-acs-endpoint
AZURE_EMAIL_KEY=your-acs-key
NO_REPLY_SENDER_EMAIL=no-reply@your-domain

# Firebase Admin (push notifications)
FIREBASE_PROJECT_ID=...
FIREBASE_PRIVATE_KEY_ID=...
FIREBASE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
FIREBASE_CLIENT_EMAIL=...
FIREBASE_CLIENT_ID=...

# Sentry (optional)
SENTRY_DSN=
```

### Settings Structure
- `settings/base.py` - Shared settings
- `settings/dev.py` - Development settings
- `settings/prod.py` - Production settings

## 🐳 Docker Development

### Local Development
```bash
# Start all services
docker-compose up

# Run in background
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

Note: The provided `docker-compose.yml` starts the Django web service. You still need a Redis instance for Channels/Celery (run one separately, e.g., with `docker run redis:7`).

### Production Build
```bash
# Build production image
docker build -t farajayangu_be .

# Run production container
docker run -p 8000:8000 farajayangu_be
```

## 📚 API Documentation

Routes for schema and Swagger UI exist in `farajayangu_be/schema.py`:

- **OpenAPI Schema**: `/schema/`
- **Swagger UI**: `/docs/`

To enable them:
- Install `drf-spectacular` and include the schema URLs in your project `urls.py`.

### Authentication
```bash
# Get JWT tokens
POST /auth/login/
{
  "email": "user@example.com",
  "password": "password"
}

# Use access token in headers
Authorization: Bearer <access_token>

# Refresh token
POST /auth/refresh/
{
  "refresh": "<refresh_token>"
}
```

## 🧪 Testing

### Run Tests
```bash
# All tests
python manage.py test

# Specific app
python manage.py test apps.myapp

# With coverage
coverage run --source='.' manage.py test
coverage report
```

### Test Structure
```
apps/myapp/tests/
├── __init__.py
├── test_models.py
├── test_services.py
├── test_selectors.py
└── test_views.py
```

## 📦 Deployment

### Environment Setup
1. Set `DEBUG=False` and provide all required secrets in environment variables.
2. Use PostgreSQL (recommended) or other supported DB; set `DATABASE_ENGINE`, `DATABASE_*` vars.
3. Provide Redis for Channels and Celery (broker and result backend).
4. Configure Cloudflare R2/S3 storage, Azure Email, Firebase, and Sentry.

### Production (Docker)
- The image runs Nginx + Gunicorn (Uvicorn worker) for the ASGI app.
- Two entry scripts are provided:
  - `/app/start_core_backend.sh` – web server (Nginx + Gunicorn)
  - `/app/start_tasks_backend.sh` – Celery worker and Celery Beat
- Set env `ENTRY_SCRIPT` to select which process the container should run.

Example run (web):
```bash
docker build -t farajayangu_be .
docker run -p 80:80 -e ENTRY_SCRIPT=/app/start_core_backend.sh --env-file .env farajayangu_be
```

Example run (workers):
```bash
docker run --env-file .env -e ENTRY_SCRIPT=/app/start_tasks_backend.sh farajayangu_be
```

### CapRover Deployment
- `captain-definition` is present. Create two CapRover apps from this repo image:
  - App 1 (Web): set `ENTRY_SCRIPT=/app/start_core_backend.sh`, expose HTTP.
  - App 2 (Workers): set `ENTRY_SCRIPT=/app/start_tasks_backend.sh`.
- Configure the same environment variables on both apps.

## ☁️ Cloudflare R2 CORS Configuration

Chunked video uploads go **directly from the browser to R2** using presigned URLs. R2 must have CORS rules configured to allow these cross-origin `PUT` requests. Without this, uploads will silently fail.

### Required R2 CORS Rules (Cloudflare Dashboard → R2 → Bucket → Settings → CORS Policy)

```json
[
  {
    "AllowedOrigins": [
      "https://cms.farajayangutv.co.tz",
      "https://farajayangutv.co.tz"
    ],
    "AllowedMethods": ["GET", "PUT", "HEAD"],
    "AllowedHeaders": ["Content-Type", "Content-Length", "x-amz-*"],
    "ExposeHeaders": ["ETag", "Content-Length"],
    "MaxAgeSeconds": 3600
  }
]
```

**Key points:**
- `AllowedOrigins` must include the exact CMS domain (no trailing slash, no wildcard in production)
- `PUT` must be allowed (used for presigned chunk uploads)
- `Content-Type` must be in `AllowedHeaders` — the presigned URL is signed with `ContentType: application/octet-stream` and the browser must send this header
- `ETag` in `ExposeHeaders` allows the frontend to verify chunk integrity
- Add `http://localhost:*` origins for local development if needed

### Troubleshooting Upload Failures
- **Uploads fail at ~40% with no HTTP response**: Check presigned URL expiry (`CHUNK_UPLOAD_URL_EXPIRY` setting, default 1 hour) and R2 CORS config
- **`Failed` network error with no status code**: Usually a CORS mismatch or expired presigned URL — R2 drops the connection silently
- **Frontend must send `Content-Type: application/octet-stream`** header on every chunk PUT — the presigned URL signature requires it

## 🔍 Troubleshooting

### Common Issues

**Migration Errors**:
```bash
# Reset migrations (development only)
python manage.py migrate --fake-initial
```

**Import Errors**:
- Ensure virtual environment is activated
- Check `PYTHONPATH` includes project root
- Verify app is in `INSTALLED_APPS`

**Permission Errors**:
- Check JWT token is valid
- Verify user has required permissions
- Ensure proper authentication headers

**FFmpeg Not Found**:
- Ensure ffmpeg/ffprobe are installed and on PATH. On Windows, Chocolatey install: `choco install ffmpeg`.

## 📖 Additional Resources

- **NTC Documentation**: [Link to NTC docs]
- **Django REST Framework**: https://www.django-rest-framework.org/
- **Django Documentation**: https://docs.djangoproject.com/
- **Project Knowledge Base**: See `.knowledge/` directory for AI-friendly documentation

## 🤝 Contributing

<!-- Add your contribution guidelines here -->
*This section is for your team's contribution guidelines, coding standards, and development workflow.*

---

## 📄 License

<!-- Add your license information here -->
*Add your project's license information.*

---

**Generated by NTC (Nexent Toolkit Console)** - A tool for creating production-ready Django REST Framework projects with best practices built-in.

