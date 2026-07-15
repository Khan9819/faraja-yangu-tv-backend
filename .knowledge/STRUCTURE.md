# Project Structure - farajayangu_be

This document describes the complete project structure and organization for AI assistants to understand how to work with this codebase.

## 📁 Root Directory Structure

```
farajayangu_be/
├── .env                    # Environment variables
├── .gitignore             # Git ignore patterns
├── .knowledge/            # AI documentation (this directory)
├── manage.py              # Django management script
├── requirements.txt       # Python dependencies
├── docker-compose.yml     # Docker composition
├── Dockerfile            # Docker build instructions
├── captain-definition    # CapRover deployment config
├── README.md             # Project documentation
├── farajayangu_be/       # Django project configuration
├── apps/                 # Django applications
└── core/                 # Core utilities and frameworks
```

## 🏗️ Django Project Configuration (`farajayangu_be/`)

```
farajayangu_be/
├── __init__.py
├── asgi.py               # ASGI application entry point
├── wsgi.py               # WSGI application entry point
├── schema.py             # API schema configuration (OpenAPI/Swagger)
├── urls.py               # Main URL routing
├── celery.py             # Celery task configuration
├── settings/             # Split settings configuration
│   ├── __init__.py
│   ├── base.py          # Base settings (shared)
│   ├── dev.py           # Development settings
│   └── prod.py          # Production settings
└── management/           # Custom Django management commands
    └── commands/
        ├── __init__.py
        └── create_app.py # NTC app creation command
```

## 📱 Applications Directory (`apps/`)

```
apps/
├── __init__.py
├── common/               # Shared utilities and base models
│   ├── __init__.py
│   ├── apps.py          # App configuration
│   ├── models.py        # Abstract base models (TimeStampedModel)
│   ├── serializers/     # Shared serializers
│   ├── services/        # Shared business logic
│   └── tests/           # Common tests
└── [app_name]/          # Individual Django apps (created via `ntc create app`)
    ├── __init__.py
    ├── admin.py         # Django admin configuration
    ├── apps.py          # App configuration
    ├── models.py        # Data models
    ├── urls.py          # App-specific URL patterns
    ├── views.py         # API views and endpoints
    ├── permissions/     # Custom permissions
    ├── serializers/     # DRF serializers
    ├── selectors/       # Data selection logic
    ├── services/        # Business logic
    ├── socket/          # WebSocket handlers
    ├── tasks/           # Celery tasks
    └── tests/           # App-specific tests
```

## 🔧 Core Framework (`core/`)

```
core/
├── __init__.py
├── pagination.py         # DRF pagination classes
├── base_model.py        # Abstract base model with common fields
├── response_wrapper.py  # Standardized API response utilities
├── permissions/         # Custom permission classes
├── exceptions/          # Custom exception handlers
├── signals/             # Django signals
├── utils/               # General utilities
├── middlewares/         # Custom middleware
├── services/            # External service integrations
│   ├── azure/          # Azure cloud services
│   └── aws/            # AWS cloud services
└── logging/            # Logging configuration
    ├── formatter.py    # Custom log formatters
    └── logger.py       # Logger setup
```

## 🎯 Key Conventions

### File Naming
- **Models**: `PascalCase` classes in `models.py`
- **Views**: `snake_case` functions/classes in `views.py`
- **URLs**: `kebab-case` patterns in `urls.py`
- **Apps**: `snake_case` directory names

### Import Patterns
- **Models**: `from apps.common.models import TimeStampedModel`
- **Response**: `from core.response_wrapper import success_response, error_response`
- **Pagination**: `from core.pagination import StandardResultsSetPagination`

### URL Structure
- **App URLs**: `/{app_name}/endpoint/`
- **API Versioning**: Not implemented (single version)
- **Admin**: `/admin/`
- **API Docs**: `/docs/` (Swagger UI)

## 🔄 Development Workflow

1. **Create new app**: `ntc create app app_name`
2. **Add models**: Edit `apps/app_name/models.py`
3. **Create migrations**: `python manage.py makemigrations app_name`
4. **Apply migrations**: `python manage.py migrate`
5. **Add views**: Edit `apps/app_name/views.py`
6. **Configure URLs**: Edit `apps/app_name/urls.py`
7. **Test endpoint**: `GET /app_name/hello/` (auto-created test endpoint)

## 📋 Important Notes for AI

- **Always use the NTC structure** when creating new apps
- **Follow the Service/Selector pattern** for business logic
- **Use `success_response()` and `error_response()`** for consistent API responses
- **Inherit from `TimeStampedModel`** for automatic timestamp fields
- **Place business logic in `services/`**, not in views
- **Use `selectors/` for complex data queries**
- **All new apps are automatically added to `INSTALLED_APPS` and main `urls.py`**
