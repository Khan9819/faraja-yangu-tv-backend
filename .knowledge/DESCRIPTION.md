# Project Description - farajayangu_be

This document provides a comprehensive overview of the project architecture, purpose, and technical stack for AI assistants.

## 🎯 Project Purpose

**farajayangu_be** is a Django REST Framework (DRF) project built using the **NTC (Nexent Toolkit Console)** structure. This project follows enterprise-grade patterns and best practices for building scalable, maintainable API-driven applications.

## 🏛️ Architecture Overview

### **API-First Design**
- **Backend**: Django REST Framework providing JSON APIs
- **Frontend**: Separate frontend applications (React, Angular, Vue, etc.)
- **Communication**: RESTful APIs with standardized JSON responses
- **Authentication**: JWT-based authentication with refresh tokens

### **Modular Structure**
- **Apps**: Feature-based Django applications in `apps/` directory
- **Core**: Shared utilities, base classes, and framework extensions
- **Services**: External integrations (AWS, Azure, payment gateways)
- **Common**: Shared models, serializers, and utilities

## 🛠️ Technical Stack

### **Backend Framework**
- **Django 4.2+**: Web framework
- **Django REST Framework**: API framework
- **PostgreSQL/SQLite**: Database (configurable)
- **Redis**: Caching and session storage
- **Celery**: Background task processing
- **JWT**: Authentication tokens

### **Development Tools**
- **Docker**: Containerization
- **Docker Compose**: Local development environment
- **CapRover**: Deployment platform
- **Environment Variables**: Configuration management

### **API Features**
- **OpenAPI/Swagger**: Auto-generated API documentation at `/docs/`
- **CORS**: Cross-origin resource sharing configured
- **Pagination**: Standardized pagination for list endpoints
- **Error Handling**: Consistent error response format
- **Logging**: Structured logging with custom formatters

## 🔧 Key Components

### **Authentication System**
- **JWT Access Tokens**: Short-lived (15 minutes default)
- **Refresh Tokens**: Long-lived (14 days default)
- **Token Blacklisting**: Secure logout functionality
- **Cookie Support**: Optional cookie-based authentication

### **Response Format**
All API responses follow a standardized format:

```json
{
  "status": "success|error",
  "message": "Human-readable message",
  "data": { /* Response data */ }
}
```

### **Database Models**
- **TimeStampedModel**: Base model with `created_at` and `updated_at`
- **BaseModel**: Enhanced base model with BigAutoField primary key
- **Abstract Models**: Reusable model patterns in `apps.common`

### **Business Logic Pattern**
- **Views**: Handle HTTP requests/responses only
- **Services**: Contain business logic and complex operations
- **Selectors**: Handle data querying and filtering
- **Serializers**: Data validation and transformation

## 🌐 External Integrations

### **Cloud Services**
- **AWS Services**: S3, SES, SNS (configured but not implemented)
- **Azure Services**: Storage, Email, SMS (configured but not implemented)

### **Payment Gateways** (Tanzania-focused)
- **SELCOM**: Mobile payments
- **ClickPesa**: Payment processing
- **Beem**: SMS and payment services
- **Polar**: Payment gateway

### **Communication**
- **Email**: SMTP configuration with environment variables
- **SMS**: Integration ready for Beem and other providers
- **WebSocket**: Socket handlers in app structure

## 🔄 Development Patterns

### **Service/Selector Pattern**
```python
# services/user_service.py
def create_user(email, password):
    # Business logic here
    pass

# selectors/user_selector.py  
def get_active_users():
    # Data querying here
    pass

# views.py
def create_user_view(request):
    # Use service for business logic
    user = create_user(email, password)
    return success_response(data=user)
```

### **Response Wrapper Usage**
```python
from core.response_wrapper import success_response, error_response

# Success response
return success_response(
    data={"user_id": 123},
    message="User created successfully"
)

# Error response
return error_response(
    message="Invalid credentials",
    code=400
)
```

## 📊 Environment Configuration

### **Development Settings** (`settings/dev.py`)
- **DEBUG**: True
- **Database**: SQLite (default)
- **CORS**: Localhost allowed
- **Logging**: Console output

### **Production Settings** (`settings/prod.py`)
- **DEBUG**: False
- **Database**: PostgreSQL (via environment variables)
- **Security**: HTTPS redirects, secure cookies
- **Logging**: File-based logging

## 🚀 Deployment

### **Docker Support**
- **Multi-stage builds**: Optimized for production
- **Environment variables**: Configurable via `.env`
- **Health checks**: Built-in health monitoring

### **CapRover Deployment**
- **One-click deployment**: Using `captain-definition`
- **Auto-scaling**: Configurable scaling rules
- **SSL**: Automatic SSL certificate management

## 📝 API Documentation

### **Auto-generated Docs**
- **Swagger UI**: Available at `/docs/`
- **OpenAPI Schema**: Available at `/schema/`
- **Interactive Testing**: Built-in API testing interface

### **Response Examples**
The API provides consistent, well-documented responses with examples for all endpoints.

## 🎯 Best Practices Implemented

1. **Separation of Concerns**: Clear separation between views, services, and data access
2. **DRY Principle**: Reusable components and base classes
3. **Security First**: JWT authentication, CORS, secure headers
4. **Scalability**: Modular app structure, background tasks with Celery
5. **Maintainability**: Clear naming conventions, comprehensive documentation
6. **Testing Ready**: Test directories in every app, test utilities available

## 🤖 AI Assistant Guidelines

When working with this project:
- **Follow NTC patterns** and conventions
- **Use the service/selector pattern** for business logic
- **Leverage existing utilities** in `core/` and `apps.common/`
- **Maintain consistent API responses** using response wrappers
- **Add proper error handling** and validation
- **Update documentation** when adding new features
- **Use environment variables** for configuration
- **Follow Django and DRF best practices**
