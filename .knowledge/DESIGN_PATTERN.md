# Design Patterns - farajayangu_be

This document outlines the design patterns, architectural decisions, and coding conventions used in this NTC-generated Django REST Framework project.

## 🏗️ Architectural Patterns

### **1. Service/Selector Pattern**

**Purpose**: Separate business logic from views and data access logic.

**Structure**:
```
apps/myapp/
├── views.py          # HTTP request/response handling only
├── services/         # Business logic and operations
├── selectors/        # Data querying and filtering
└── serializers/      # Data validation and transformation
```

**Example Implementation**:

```python
# selectors/user_selector.py
from django.db.models import QuerySet
from apps.users.models import User

def get_active_users() -> QuerySet[User]:
    """Get all active users."""
    return User.objects.filter(is_active=True)

def get_user_by_email(email: str) -> User:
    """Get user by email address."""
    return User.objects.get(email=email)

# services/user_service.py
from django.contrib.auth import authenticate
from apps.users.models import User
from apps.users.selectors.user_selector import get_user_by_email

def create_user(email: str, password: str, **kwargs) -> User:
    """Create a new user with validation."""
    if User.objects.filter(email=email).exists():
        raise ValueError("User with this email already exists")
    
    user = User.objects.create_user(
        email=email,
        password=password,
        **kwargs
    )
    return user

def authenticate_user(email: str, password: str) -> User:
    """Authenticate user credentials."""
    user = authenticate(email=email, password=password)
    if not user:
        raise ValueError("Invalid credentials")
    return user

# views.py
from rest_framework.decorators import api_view
from core.response_wrapper import success_response, error_response
from .services.user_service import create_user, authenticate_user
from .selectors.user_selector import get_active_users

@api_view(['POST'])
def create_user_view(request):
    """Create a new user."""
    try:
        user = create_user(
            email=request.data['email'],
            password=request.data['password']
        )
        return success_response(
            data={"user_id": user.id},
            message="User created successfully"
        )
    except ValueError as e:
        return error_response(message=str(e), code=400)
```

### **2. Repository Pattern (via Selectors)**

**Purpose**: Abstract data access logic and provide a consistent interface for querying data.

```python
# selectors/base_selector.py
from typing import Optional, List
from django.db.models import Model, QuerySet

class BaseSelector:
    model = None
    
    @classmethod
    def get_by_id(cls, id: int) -> Optional[Model]:
        """Get object by ID."""
        try:
            return cls.model.objects.get(id=id)
        except cls.model.DoesNotExist:
            return None
    
    @classmethod
    def get_all(cls) -> QuerySet:
        """Get all objects."""
        return cls.model.objects.all()
    
    @classmethod
    def filter_by(cls, **kwargs) -> QuerySet:
        """Filter objects by given criteria."""
        return cls.model.objects.filter(**kwargs)

# selectors/user_selector.py
from .base_selector import BaseSelector
from apps.users.models import User

class UserSelector(BaseSelector):
    model = User
    
    @classmethod
    def get_active_users(cls) -> QuerySet:
        """Get all active users."""
        return cls.filter_by(is_active=True)
```

### **3. Factory Pattern (for Model Creation)**

**Purpose**: Centralize object creation logic with proper validation.

```python
# services/factories/user_factory.py
from apps.users.models import User
from apps.common.models import TimeStampedModel

class UserFactory:
    @staticmethod
    def create_user(email: str, password: str, **kwargs) -> User:
        """Create user with proper validation."""
        # Validation logic
        if not email:
            raise ValueError("Email is required")
        
        # Creation logic
        user = User.objects.create_user(
            email=email,
            password=password,
            **kwargs
        )
        
        # Post-creation logic (send welcome email, etc.)
        # ...
        
        return user
```

## 🎯 Response Pattern

### **Standardized API Responses**

**Purpose**: Consistent response format across all endpoints.

```python
# core/response_wrapper.py
from rest_framework.response import Response

def success_response(data=None, message='Success', status=200):
    """Standard success response format."""
    return Response({
        'status': 'success',
        'message': message,
        'data': data
    }, status=status)

def error_response(message='Error', code=400, errors=None):
    """Standard error response format."""
    response_data = {
        'status': 'error',
        'message': message
    }
    if errors:
        response_data['errors'] = errors
    
    return Response(response_data, status=code)

# Usage in views
@api_view(['GET'])
def get_users(request):
    users = get_active_users()
    serializer = UserSerializer(users, many=True)
    return success_response(
        data=serializer.data,
        message="Users retrieved successfully"
    )
```

## 🗄️ Model Patterns

### **1. Abstract Base Models**

**Purpose**: Provide common fields and functionality across models.

```python
# apps/common/models.py
from django.db import models

class TimeStampedModel(models.Model):
    """Abstract model with timestamp fields."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True

# core/base_model.py
from django.db import models

class BaseModel(models.Model):
    """Enhanced base model with common fields."""
    id = models.BigAutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True
        
    def __str__(self):
        return f"{self.__class__.__name__}({self.id})"

# Usage in app models
from apps.common.models import TimeStampedModel

class User(TimeStampedModel):
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=100)
    # ... other fields
```

### **2. Manager Pattern**

**Purpose**: Custom query methods at the model level.

```python
# apps/users/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models

class ActiveUserManager(models.Manager):
    """Manager for active users only."""
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)

class User(AbstractUser):
    email = models.EmailField(unique=True)
    
    # Managers
    objects = models.Manager()  # Default manager
    active = ActiveUserManager()  # Custom manager
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

# Usage
active_users = User.active.all()  # Only active users
all_users = User.objects.all()    # All users
```

## 🔐 Authentication Patterns

### **JWT Token Pattern**

**Purpose**: Stateless authentication with refresh token support.

```python
# services/auth_service.py
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate

class AuthService:
    @staticmethod
    def login_user(email: str, password: str) -> dict:
        """Authenticate user and return tokens."""
        user = authenticate(email=email, password=password)
        if not user:
            raise ValueError("Invalid credentials")
        
        refresh = RefreshToken.for_user(user)
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': {
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
            }
        }
    
    @staticmethod
    def refresh_token(refresh_token: str) -> dict:
        """Refresh access token."""
        try:
            refresh = RefreshToken(refresh_token)
            return {
                'access': str(refresh.access_token)
            }
        except Exception:
            raise ValueError("Invalid refresh token")
```

## 📊 Serializer Patterns

### **Nested Serializer Pattern**

**Purpose**: Handle complex data relationships efficiently.

```python
# serializers/user_serializer.py
from rest_framework import serializers
from apps.users.models import User, Profile

class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ['bio', 'avatar', 'phone']

class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)
    full_name = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'full_name', 'profile']
        
    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'password']
        
    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User.objects.create_user(password=password, **validated_data)
        return user
```

## 🔄 Task Patterns (Celery)

### **Background Task Pattern**

**Purpose**: Handle long-running operations asynchronously.

```python
# tasks/email_tasks.py
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings

@shared_task
def send_welcome_email(user_id: int):
    """Send welcome email to new user."""
    from apps.users.models import User
    
    try:
        user = User.objects.get(id=user_id)
        send_mail(
            subject='Welcome to farajayangu_be',
            message=f'Welcome {user.first_name}!',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )
        return f"Welcome email sent to {user.email}"
    except User.DoesNotExist:
        return f"User with ID {user_id} not found"

# Usage in services
from .tasks.email_tasks import send_welcome_email

def create_user(email: str, password: str) -> User:
    user = User.objects.create_user(email=email, password=password)
    
    # Send welcome email asynchronously
    send_welcome_email.delay(user.id)
    
    return user
```

## 🧪 Testing Patterns

### **Test Organization Pattern**

**Purpose**: Structured testing approach with proper fixtures.

```python
# tests/test_user_service.py
from django.test import TestCase
from apps.users.services.user_service import create_user, authenticate_user
from apps.users.models import User

class UserServiceTest(TestCase):
    def setUp(self):
        """Set up test data."""
        self.user_data = {
            'email': 'test@example.com',
            'password': 'testpass123',
            'first_name': 'Test'
        }
    
    def test_create_user_success(self):
        """Test successful user creation."""
        user = create_user(**self.user_data)
        
        self.assertIsInstance(user, User)
        self.assertEqual(user.email, self.user_data['email'])
        self.assertTrue(user.check_password(self.user_data['password']))
    
    def test_create_user_duplicate_email(self):
        """Test user creation with duplicate email."""
        create_user(**self.user_data)
        
        with self.assertRaises(ValueError):
            create_user(**self.user_data)
```

## 📋 Naming Conventions

### **File and Directory Naming**
- **Apps**: `snake_case` (e.g., `user_management`)
- **Models**: `PascalCase` (e.g., `UserProfile`)
- **Views**: `snake_case` functions (e.g., `create_user_view`)
- **Services**: `snake_case` functions (e.g., `create_user`)
- **URLs**: `kebab-case` (e.g., `/api/user-profile/`)

### **Variable Naming**
- **Python**: `snake_case`
- **Constants**: `UPPER_SNAKE_CASE`
- **Private methods**: `_leading_underscore`
- **Class methods**: `snake_case`

## 🎯 Error Handling Patterns

### **Centralized Error Handling**

```python
# core/exceptions.py
class BusinessLogicError(Exception):
    """Custom exception for business logic errors."""
    def __init__(self, message, code=400):
        self.message = message
        self.code = code
        super().__init__(self.message)

# services/base_service.py
from core.exceptions import BusinessLogicError

class BaseService:
    @staticmethod
    def validate_required_fields(data: dict, required_fields: list):
        """Validate required fields in data."""
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            raise BusinessLogicError(
                f"Missing required fields: {', '.join(missing_fields)}"
            )
```

This design pattern documentation ensures consistent, maintainable, and scalable code across the entire project. AI assistants should follow these patterns when working with the codebase.
