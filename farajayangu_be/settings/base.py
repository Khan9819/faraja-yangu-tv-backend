from pathlib import Path
import environ
from datetime import timedelta
import pytz
import os
import sentry_sdk
from sentry_sdk import metrics
from sentry_sdk.integrations.django import DjangoIntegration

# Configure boto3 connection pool for R2 batch operations
from botocore.config import Config as BotoConfig
AWS_S3_CLIENT_CONFIG = BotoConfig(max_pool_connections=50)

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Environment Variables
env = environ.Env()
environ.Env.read_env(env_file=BASE_DIR / '.env')

DEBUG = env.bool('DEBUG', default=True)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY', default='your-secret-key')
REFRESH_TOKEN_SECRET = env('SECRET_KEY', default='your-secret-key')
BASE_URL = env('BASE_URL', default='http://127.0.0.1:8000')
BACKEND_URL = env('BACKEND_URL', default=BASE_URL)

DATABASE_ENGINE = env('DATABASE_ENGINE', default='django.db.backends.sqlite3')
DATABASE_NAME = env('DATABASE_NAME', default='db.sqlite3')
DATABASE_USER = env('DATABASE_USER', default='your-database-user')
DATABASE_PASSWORD = env('DATABASE_PASSWORD', default='your-database-password')
DATABASE_HOST = env('DATABASE_HOST', default='localhost')
DATABASE_PORT = env('DATABASE_PORT', default='5432')

EMAIL_HOST = env('EMAIL_HOST', default='localhost')
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='your-email-user')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='your-email-password')
EMAIL_PORT = env('EMAIL_PORT', default='5432')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='your-email@example.com')

JWT_ACCESS_TTL_MINUTES = env.int('JWT_ACCESS_TTL_MINUTES', default=60)

REDIS_HOST = env('REDIS_HOST', default='localhost')
REDIS_USER = env('REDIS_USER', default='your-redis-user')
REDIS_PASSWORD = env('REDIS_PASSWORD', default='your-redis-password')
REDIS_PORT = env('REDIS_PORT', default='6379')

BEEM_API_KEY = env('BEEM_API_KEY', default='your-beem-api-key')
SELCOM_MERCHANT_ID = env('SELCOM_MERCHANT_ID', default='your-selcom-merchant-id')
CLICKPESA_CLIENT_ID = env('CLICKPESA_CLIENT_ID', default='your-clickpesa-client-id')
POLAR_API_KEY = env('POLAR_API_KEY', default='your-polar-api-key')

# Google OAuth
GOOGLE_CLIENT_ID = env('GOOGLE_CLIENT_ID', default='')

# Firebase
FIREBASE_PROJECT_ID = env('FIREBASE_PROJECT_ID', default='')
FIREBASE_PRIVATE_KEY_ID = env('FIREBASE_PRIVATE_KEY_ID', default='')
FIREBASE_PRIVATE_KEY = env('FIREBASE_PRIVATE_KEY', default='').replace('\\n', '\n')
FIREBASE_CLIENT_EMAIL = env('FIREBASE_CLIENT_EMAIL', default='')
FIREBASE_CLIENT_ID = env('FIREBASE_CLIENT_ID', default='')

AWS_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME")
AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL")
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="auto")
AWS_DEFAULT_ACL = None  # Cloudflare ignores this, but keeps it clean

AZURE_EMAIL_ENDPOINT = env("AZURE_EMAIL_ENDPOINT")
AZURE_EMAIL_KEY = env("AZURE_EMAIL_KEY")
NO_REPLY_SENDER_EMAIL = env("NO_REPLY_SENDER_EMAIL")

SENTRY_DSN = env("SENTRY_DSN")

ALLOWED_HOSTS = ['*'] if DEBUG else [
    "cms.farajayangutv.co.tz",
    "farajayangutv.co.tz",
    "backend.farajayangutv.co.tz",
]

CORS_ORIGIN_ALLOW_ALL = DEBUG
CORS_ALLOW_CREDENTIALS = True
CORS_ORIGIN_WHITELIST = (
    'http://127.0.0.1:5713',
    'http://127.0.0.1:8000',
) if DEBUG else (
    "https://backend.farajayangutv.co.tz",
    "https://cms.farajayangutv.co.tz",
    "https://farajayangutv.co.tz",
)

CSRF_TRUSTED_ORIGINS = [
    'http://127.0.0.1:5713',
    'http://127.0.0.1:8000',
] if DEBUG else [
    "https://backend.farajayangutv.co.tz",
    "https://cms.farajayangutv.co.tz",
    "https://farajayangutv.co.tz",
]

AUTH_USER_MODEL = 'authentication.User'

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=JWT_ACCESS_TTL_MINUTES),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=14),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,

    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    'JWK_URL': None,
    'LEEWAY': 0,

    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'USER_AUTHENTICATION_RULE': 'rest_framework_simplejwt.authentication.default_user_authentication_rule',

    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    'TOKEN_USER_CLASS': 'rest_framework_simplejwt.models.TokenUser',

    'JTI_CLAIM': 'jti',

    'SLIDING_TOKEN_REFRESH_EXP_CLAIM': 'refresh_exp',
    'SLIDING_TOKEN_LIFETIME': timedelta(minutes=5),
    'SLIDING_TOKEN_REFRESH_LIFETIME': timedelta(days=1),

    'AUTH_COOKIE': 'access_token',  # Cookie name. Enables cookies if value is set.
    'AUTH_COOKIE_DOMAIN': None,     # A string like "example.com", or None for standard domain cookie.
    'AUTH_COOKIE_SECURE': not DEBUG,  # Secure in production (https:// only).
    'AUTH_COOKIE_HTTP_ONLY' : True, # Http only cookie flag.It's not fetch by javascript.
    'AUTH_COOKIE_PATH': '/',        # The path of the auth cookie.
    'AUTH_COOKIE_SAMESITE': 'Lax',  # Whether to set the flag restricting cookie leaks on cross-site requests. This can be 'Lax', 'Strict', or None to disable the flag.
}

INSTALLED_APPS = [
    'channels',
    "django.contrib.admin",
    "django.contrib.auth",
    'storages',
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    'rest_framework',
    'rest_framework.authtoken',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'django_celery_beat',
    'corsheaders',
    # Project apps
    'apps.common',
    'apps.authentication',
    'apps.streaming',
    'apps.advertising',
    'apps.analytics',
    'apps.profile',
    'apps.management',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]

ROOT_URLCONF = 'farajayangu_be.urls'
# WSGI_APPLICATION = 'farajayangu_be.wsgi.application'
ASGI_APPLICATION = 'farajayangu_be.asgi.application'


TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

_is_sqlite = DATABASE_ENGINE == 'django.db.backends.sqlite3'

DATABASES = {
    'default': {
        'ENGINE': DATABASE_ENGINE,
        'NAME': DATABASE_NAME,
        'USER': '' if _is_sqlite else DATABASE_USER,
        'PASSWORD': '' if _is_sqlite else DATABASE_PASSWORD,
        'HOST': '' if _is_sqlite else DATABASE_HOST,
        'PORT': '' if _is_sqlite else DATABASE_PORT,
        'CONN_MAX_AGE': 0 if _is_sqlite else 60,
        # PostgreSQL-specific options — only applied when not using SQLite
        **({} if _is_sqlite else {
            'OPTIONS': {
                'connect_timeout': 30,
                'keepalives': 1,
                'keepalives_idle': 30,
                'keepalives_interval': 10,
                'keepalives_count': 5,
                'application_name': 'farajayangutv_backend',
            },
        }),
        # Set a reasonable test timeout
        'TEST': {
            'MIGRATE': True,
        },
    }
}

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/1"],

            "channel_capacity": {
                'http.request': 200,
                'http.response!*': 200,
                'websocket.receive': 200,
                'websocket.send': 200,
            },
        }
    }
}

# Django Cache Configuration (Redis)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/2",
        'OPTIONS': {
            'socket_connect_timeout': 5,
            'socket_timeout': 5,
            'retry_on_timeout': True,
            'max_connections': 50,
        },
        'KEY_PREFIX': 'farajatv',
        'TIMEOUT': 60,  # Default timeout: 60 seconds
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '10000/hour',
        'user': '10000/hour',
        'login': '20/minute',
    },
}

# DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

STORAGES = {
    "staticfiles": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        "OPTIONS": {
            "access_key": AWS_ACCESS_KEY_ID,
            "secret_key": AWS_SECRET_ACCESS_KEY,
            "bucket_name": AWS_STORAGE_BUCKET_NAME,
            "region_name": AWS_S3_REGION_NAME,
            "endpoint_url": AWS_S3_ENDPOINT_URL,
        },
    },
    "default": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        "OPTIONS": {
            "access_key": AWS_ACCESS_KEY_ID,
            "secret_key": AWS_SECRET_ACCESS_KEY,
            "bucket_name": AWS_STORAGE_BUCKET_NAME,
            "region_name": AWS_S3_REGION_NAME,
            "endpoint_url": AWS_S3_ENDPOINT_URL,
        },
    },
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {
            'format': '[%(asctime)s] %(levelname)s %(name)s: %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'apps.streaming': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_L10N = True

USE_TZ = True

STATIC_URL = '/static/'

# File Upload Settings
DATA_UPLOAD_MAX_MEMORY_SIZE = 5368709120  # 5GB in bytes
FILE_UPLOAD_MAX_MEMORY_SIZE = 5368709120  # 5GB in bytes

# HLS Video Streaming Configuration
HLS_SEGMENT_DURATION = 6  # seconds per segment
HLS_OUTPUT_DIR = 'videos/hls'  # Base directory for HLS files
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')  # Local media root for temp processing

# HLS Encoding Performance Settings
# Encoder preset: ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow
HLS_ENCODER_PRESET = env('HLS_ENCODER_PRESET', default='superfast')
# Number of FFmpeg threads (0 = auto uses all CPU cores for maximum performance)
HLS_FFMPEG_THREADS = env.int('HLS_FFMPEG_THREADS', default=4)  # 4 threads = leave 2 cores for system (6-core server)
# Skip encoding variants higher than source resolution (saves CPU time)
HLS_SKIP_UPSCALING = env.bool('HLS_SKIP_UPSCALING', default=True)
FFMPEG_VARIANT_TIMEOUT = 5400  # 90 min per variant — enough for 46+ min videos at high quality
# Quality variants to generate (comma-separated): 1080p,720p,480p,360p
HLS_VARIANTS = env.list('HLS_VARIANTS', default=['1080p', '720p', '480p', '360p'])
# Use single-pass encoding - DISABLED by default as FFmpeg doesn't support multiple HLS outputs cleanly
# Sequential processing is more reliable and uses less memory
HLS_SINGLE_PASS = env.bool('HLS_SINGLE_PASS', default=False)
# Chunk Upload Settings
# Presigned URL expiry for chunk uploads (seconds). Default 1 hour.
# Must be long enough for slow/unstable connections to complete a single chunk upload + retries.
CHUNK_UPLOAD_URL_EXPIRY = env.int('CHUNK_UPLOAD_URL_EXPIRY', default=300)

# C++ Conversion Microservice Settings
USE_CPP_CONVERSION_SERVICE = env.bool('USE_CPP_CONVERSION_SERVICE', default=False)
CONVERSION_QUEUE_BACKEND = env('CONVERSION_QUEUE_BACKEND', default='redis')
CONVERSION_EVENTS_CHANNEL = env('CONVERSION_EVENTS_CHANNEL', default='conversion_events')
CONVERSION_HEARTBEAT_TIMEOUT_SECONDS = env.int('CONVERSION_HEARTBEAT_TIMEOUT_SECONDS', default=300)
CONVERSION_MAX_RETRIES = env.int('CONVERSION_MAX_RETRIES', default=2)

# Celery Configuration for video processing
# Build Redis URL with proper authentication
if REDIS_PASSWORD and REDIS_PASSWORD not in ['', 'your-redis-password']:
    # Format: redis://[username]:password@host:port/db
    if REDIS_USER and REDIS_USER not in ['', 'your-redis-user']:
        CELERY_BROKER_URL = f'redis://{REDIS_USER}:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0'
        CELERY_RESULT_BACKEND = f'redis://{REDIS_USER}:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0'
    else:
        # No username, only password
        CELERY_BROKER_URL = f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0'
        CELERY_RESULT_BACKEND = f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0'
else:
    # No authentication
    CELERY_BROKER_URL = f'redis://{REDIS_HOST}:{REDIS_PORT}/0'
    CELERY_RESULT_BACKEND = f'redis://{REDIS_HOST}:{REDIS_PORT}/0'

CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 180 * 60  # 3 hours hard limit (tasks set their own, this is the global default)
CELERY_TASK_SOFT_TIME_LIMIT = 150 * 60  # 2.5 hours soft limit

# Prevent broker connection issues from killing tasks
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_TRANSPORT_OPTIONS = {
    'visibility_timeout': 14400,  # 4 hours - must be > longest task time (large videos: assembly ~90min + conversion ~90min)
    'socket_timeout': 30,
    'socket_connect_timeout': 30,
    'max_connections': 50,  # Increased from default ~10 to handle concurrent large video processing
    'retry_on_timeout': True,
}

# Task acknowledgment settings for reliability
CELERY_TASK_ACKS_LATE = True  # Acknowledge after task completes, not when received
CELERY_TASK_REJECT_ON_WORKER_LOST = True  # Re-queue task if worker dies
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # Only fetch 1 task at a time for long tasks

# Result backend settings
CELERY_RESULT_EXPIRES = 86400  # Results expire after 24 hours

sentry_sdk.init(
    dsn=SENTRY_DSN,
    send_default_pii=False,
    # Set environment based on DEBUG flag
    enable_logs=True,
    traces_sample_rate=1.0,
    environment='development' if DEBUG else 'production',
)

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    # Trust X-Forwarded-Proto set by Nginx so Django knows the original scheme
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")