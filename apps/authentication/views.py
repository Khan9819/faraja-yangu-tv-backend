import random
from django.utils import timezone
from django.utils.timezone import timedelta
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.authentication.serializers.profile import ProfileSerializer
from apps.authentication.services.credit import UserCreditService
from apps.authentication.tasks.main import send_password_reset_email, send_verification_email
from core.response_wrapper import success_response, error_response
from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from apps.authentication.models import OTP, Role, User, Profile
from apps.authentication.serializers.user import UserSerializer
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
# Create your views here.

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    
    username = request.data.get('username', None)
    password = request.data.get('password', None)
    
    if not username or not password:
        return error_response(message='Username and password are required')
    
    user = authenticate(username=username, password=password)
    
    if not user:
        return error_response(message='Invalid credentials')
    
    if not user.is_active:
        return error_response(message='User is not active')
    
    # Auto-verify users who registered before is_verified=True fix
    # If they provide correct credentials, verify them and proceed
    if not user.is_verified:
        user.is_verified = True
        user.save()
    
    # Generate JWT token pair
    refresh = RefreshToken.for_user(user)
    access_token = refresh.access_token

    # Sync device info (FCM token, device_id, etc.) in the background
    device_id = request.data.get('device_id')
    if device_id:
        from apps.authentication.tasks.main import sync_user_device
        if settings.DEBUG:
            sync_user_device(
                user_id=user.id,
                device_id=device_id,
                device_type=request.data.get('device_type', ''),
                app_version=request.data.get('app_version', ''),
                fcm_token=request.data.get('fcm_token', ''),
            )
        else:
            sync_user_device.delay(
                user_id=user.id,
                device_id=device_id,
                device_type=request.data.get('device_type', ''),
                app_version=request.data.get('app_version', ''),
                fcm_token=request.data.get('fcm_token', ''),
            )

    response = success_response(
        data={
            'access_token': str(access_token),
            'refresh_token': str(refresh),
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'roles': user.roles.all().values(),
            }
        },
        message='Login successful'
    )

    # Set refresh token as HTTP-only cookie
    response.set_cookie(
        'refresh_token',
        str(refresh),
        max_age=60 * 60 * 24 * 14,  # 14 days (same as REFRESH_TOKEN_LIFETIME)
        httponly=True,
        secure=not settings.DEBUG,
        samesite='Lax'
    )

    return response

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def complete_profile(request):
    
    user = User.objects.filter(id=request.user.id).first()
    
    if not user:
        return error_response(message='User not found')
    
    if user.profile:
        return error_response(message='Profile already completed')
    
    serializer = ProfileSerializer(data=request.data)
    
    if not serializer.is_valid():
        return error_response(message=serializer.errors)
    
    user.profile = serializer.save()
    user.save()
    
    return success_response(data={}, message='Profile completed successfully')

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def profile(request):
    
    user = User.objects.filter(id=request.user.id).first()
    
    if not user:
        return error_response(message='User not found')
    
    return success_response(data={
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'setup_completed': user.profile.setup_completed,
        'initial_credit_claimed': UserCreditService(user).GAIN_FROM_INITIAL_REGISTRATION if not user.profile.initial_credit_claimed else None,
        'roles': user.roles.all().values(),
        'profile': ProfileSerializer(user.profile).data,
        'notification_count': User.notifications.filter(is_read=False).count()
    })

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_otp(request):
    
    user = User.objects.filter(id=request.user.id).first()
    
    if not user:
        return error_response(message='User not found')
    
    if not user.profile:
        return error_response(message='Profile not found')
    
    otp = OTP.objects.filter(user=user).first()
    
    if otp:
        if (timezone.now() - otp.created_at).total_seconds() < 60:
            return error_response(message='Please wait 60 seconds before resending OTP')
    
    if not otp:
        otp = OTP.objects.create(user=user)
    
    otp.otp = random.randint(100000, 999999)
    otp.expires_at = timezone.now() + timedelta(minutes=30)
    otp.save()
    
    print(otp.otp)
    
    return success_response(data={}, message='OTP sent successfully')

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_phone(request):
    
    otp = request.data.get('otp', None)
    
    if not otp:
        return error_response(message='OTP is required')
    
    user = User.objects.filter(id=request.user.id).first()
    
    if not user:
        return error_response(message='User not found')
    
    if not user.profile:
        return error_response(message='Profile not found')
    
    user.profile.is_phone_verified = True
    user.profile.save()
    
    return success_response(data={})
# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_email(request):
    
    otp = request.data.get('otp', None)
    email = request.data.get('email', None)
    
    if not email:
        return error_response(message='Email is required')
    
    if not otp:
        return error_response(message='OTP is required')
    
    user: (User, None) = User.objects.filter(email=email).first()
    
    if not user:
        return error_response(message='User not found')
    
    otp: OTP = OTP.objects.filter(user=user, otp=otp).first()
    
    if not otp:
        return error_response(message='Invalid OTP')
    
    if otp.expires_at > timezone.now():
        otp.delete()
        return error_response(message='OTP expired')
    
    user.is_verified = True
    user.save()
    otp.delete()
    
    return success_response(data={})

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def login_with_google(request):
    return success_response(data={})

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def login_google(request):
    """
    Google OAuth login endpoint.
    Accepts a Google ID token and returns JWT tokens.
    Query params: device (android/ios/web), portal (client/cms)
    """
    token = request.data.get('id_token') or request.data.get('token')
    device = request.query_params.get('device', 'web')
    portal = request.query_params.get('portal', 'client')
    
    if not token:
        return error_response(message='Google ID token is required', code=400)
    
    if not settings.GOOGLE_CLIENT_ID:
        return error_response(message='Google authentication is not configured', code=500)
    
    try:
        # Verify the Google ID token
        idinfo = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID
        )
        
        # Extract user info from the token
        google_id = idinfo.get('sub')
        email = idinfo.get('email')
        email_verified = idinfo.get('email_verified', False)
        first_name = idinfo.get('given_name', '')
        last_name = idinfo.get('family_name', '')
        
        if not email:
            return error_response(message='Email not provided by Google', code=400)
        
        # Check if user exists
        user = User.objects.filter(email=email, auth_provider='google').first()
        
        if user:
            # Update auth provider if needed
            if user.auth_provider != 'google':
                user.auth_provider = 'google'
                user.save()
        else:
            # Create new user
            user = User.objects.create(
                username=email,
                email=email,
                first_name=first_name,
                last_name=last_name,
                auth_provider='google',
                is_verified=email_verified,
                is_active=True,
            )
            # Assign USER role (consistent with email registration)
            role_obj, _ = Role.objects.get_or_create(
                name=Role.ROLES.USER,
                defaults={'description': 'Standard user role'},
            )
            user.roles.add(role_obj)
            # Create profile for new user
            profile = Profile.objects.create()
            user.profile = profile
            user.save()
            
            # Reward user for initial registration
            UserCreditService(user).gain_from_initial_registration()
        
        if not user.is_active:
            return error_response(message='User account is deactivated', code=403)
        
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        access_token = refresh.access_token

        # Sync device info (FCM token, device_id, etc.) in the background
        device_id = request.data.get('device_id')
        if device_id:
            from apps.authentication.tasks.main import sync_user_device
            if settings.DEBUG:
                sync_user_device(
                    user_id=user.id,
                    device_id=device_id,
                    device_type=request.data.get('device_type', ''),
                    app_version=request.data.get('app_version', ''),
                    fcm_token=request.data.get('fcm_token', ''),
                )
            else:
                sync_user_device.delay(
                    user_id=user.id,
                    device_id=device_id,
                    device_type=request.data.get('device_type', ''),
                    app_version=request.data.get('app_version', ''),
                    fcm_token=request.data.get('fcm_token', ''),
                )

        response = success_response(
            data={
                'access_token': str(access_token),
                'refresh_token': str(refresh),
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'roles': list(user.roles.all().values()),
                    'is_new_user': not user.profile or not user.profile.id,
                },
                'device': device,
                'portal': portal,
            },
            message='Login successful'
        )
        
        # Set refresh token as HTTP-only cookie
        response.set_cookie(
            'refresh_token',
            str(refresh),
            max_age=60 * 60 * 24 * 14,  # 14 days
            httponly=True,
            secure=not settings.DEBUG,
            samesite='Lax'
        )
        
        return response
        
    except ValueError as e:
        return error_response(message='Invalid Google token', code=401)
    except Exception as e:
        return error_response(message=f'Authentication failed: {str(e)}', code=500)

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def request_verification(request):
    email = request.data.get('email')
    
    if not email:
        return error_response(message="Email is required", code=400)
    
    user = User.objects.filter(email=email).first()
    
    if not user:
        return error_response(message="There's an issue with your email make sure it's correct", code=400)
    
    if settings.DEBUG:
        send_verification_email(user.id)
    else:
        send_verification_email.delay(user.id)
    
    return success_response(data={}, message="An OTP has been sent to your email")

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    
    first_name = request.data.get('first_name', None)
    last_name = request.data.get('last_name', None)
    email = request.data.get('email', None)
    password = request.data.get('password', None)
    password_confirmation = request.data.get('password_confirmation', None)
    
    if not first_name or not last_name or not email or not password or not password_confirmation:
        return error_response(message='First name, last name, email, password and password confirmation are required')
    
    if password != password_confirmation:
        return error_response(message='Passwords do not match')
    
    if User.objects.filter(email=email).exists():
        return error_response(message='Email already exists')
    
    payload = {key: value for key, value in request.data.items() if value}
    payload['username'] = email
    payload['auth_provider'] = 'email'
    
    serializer = UserSerializer(data=payload)
    
    if not serializer.is_valid():
        return error_response(message=serializer.errors)
    
    user: User = serializer.save()

    # Set password securely
    user.set_password(password)
    role_obj, _ = Role.objects.get_or_create(
        name=Role.ROLES.USER,
        defaults={'description': 'Standard user role'},
    )
    user.roles.add(role_obj)
    user.is_verified = True
    user.save()
    

    # Ensure a profile is created and linked to this user
    if not user.profile:
        profile = Profile.objects.create()
        user.profile = profile
        user.save()
    
    UserCreditService(user).gain_from_initial_registration()
    
    return success_response(data={})

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_user(request, id):
    
    user = User.objects.get(id=id)
    user.is_verified = True
    user.save()
    
    return success_response(data={}, message='User verified successfully')

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp(request):
    
    otp_code = request.data.get('otp', None)
    
    otp = OTP.objects.filter(otp=otp_code).first()
    
    if not otp:
        return error_response(message='Invalid OTP')
    
    if otp.expires_at < timezone.now():
        return error_response(message='OTP expired')
    
    otp.delete()
    
    return success_response(data={}, message='OTP verified successfully')

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def refresh(request):
    
    refresh_token = request.COOKIES.get('refresh_token')
    
    if not refresh_token:
        return error_response(message='Refresh token is required')
    
    try:
        refresh = RefreshToken(refresh_token)
    except Exception as e:
        return error_response(message='Invalid refresh token')
    
    access_token = refresh.access_token
    user_id = refresh['user_id']
    
    # Offload device sync to background task (non-blocking)
    device_id = request.data.get('device_id')
    if device_id:
        from apps.authentication.tasks.main import sync_user_device
        if settings.DEBUG:
            sync_user_device(
                user_id=user_id,
                device_id=device_id,
                device_type=request.data.get('device_type', ''),
                app_version=request.data.get('app_version', ''),
                fcm_token=request.data.get('fcm_token', ''),
            )
        else:
            sync_user_device.delay(
                user_id=user_id,
                device_id=device_id,
                device_type=request.data.get('device_type', ''),
                app_version=request.data.get('app_version', ''),
                fcm_token=request.data.get('fcm_token', ''),
            )
    
    response = success_response(data={
        'access_token': str(access_token),
        'refresh_token': str(refresh),
    })
    
    response.set_cookie(
        'refresh_token',
        str(refresh),
        max_age=60 * 60 * 24 * 14,  # 14 days (same as REFRESH_TOKEN_LIFETIME)
        httponly=True,
        secure=not settings.DEBUG,
        samesite='Lax'
    )
    
    return response

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def logout(request):
    
    # Blacklist Access and Refresh Token
    refresh_token = request.COOKIES.get('refresh_token')
    
    if not refresh_token:
        return error_response(message='Refresh token is required')
    
    try:
        refresh = RefreshToken(refresh_token)
    except Exception as e:
        return error_response(message='Invalid refresh token')
    
    refresh.blacklist()
    
    response = success_response(data={}, message='Logout successful')
    
    response.delete_cookie('refresh_token')
    
    return response

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def request_password_reset_with_email(request):
    
    email = request.data.get('email')
    
    if not email:
        return error_response(code=400, message="Email is required")
    
    user: (User, None) = User.objects.filter(email=email).first()
    
    if not user:
        return error_response(code=400, message="There's an issue with your email")
    
    if settings.DEBUG:
        send_password_reset_email(user.id)
    else:
        send_password_reset_email.delay(user.id)
    
    return success_response(data={})

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def request_password_reset_with_phone(request):
    return success_response(data={})

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_password_reset_otp(request):
    
    otp_code = request.data.get('otp', None)
    email = request.data.get('email', None)
    
    user: (User, None) = User.objects.filter(email=email).first()
    
    otp = OTP.objects.filter(otp=otp_code, user=user).first()
        
    if not otp:
        return error_response(message='Invalid OTP')
    
    if otp.expires_at > timezone.now():
        otp.delete()
        return error_response(message='OTP expired')
    
    return success_response(data={}, message='OTP verified successfully')

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password(request):
    
    otp_code = request.data.get('otp', None)
    email = request.data.get('email', None)
    password = request.data.get('password', None)
    password_confirmation = request.data.get('password_confirmation', None)
    
    # Validate required fields
    if not email:
        return error_response(message='Email is required')
    
    if not otp_code:
        return error_response(message='OTP is required')
    
    if not password:
        return error_response(message='Password is required')
    
    if not password_confirmation:
        return error_response(message='Password confirmation is required')
    
    # Check if passwords match
    if password != password_confirmation:
        return error_response(message='Passwords do not match')
    
    # Validate password strength (optional but recommended)
    if len(password) < 8:
        return error_response(message='Password must be at least 8 characters long')
    
    # Find user
    user: (User, None) = User.objects.filter(email=email).first()
    
    if not user:
        return error_response(message='User not found')
    
    # Verify OTP
    otp = OTP.objects.filter(otp=otp_code, user=user).first()
        
    if not otp:
        return error_response(message='Invalid OTP')
    
    if otp.expires_at > timezone.now():
        otp.delete()
        return error_response(message='OTP expired')
    
    # Reset password
    user.set_password(password)
    user.save()
    
    # Delete OTP after successful password reset
    otp.delete()
    
    return success_response(data={}, message='Password reset successfully')


# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# CMS Profile Endpoints
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def cms_profile(request):
    """Get the authenticated CMS user's profile."""
    user = request.user
    data = {
        'id': user.id,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'username': user.username,
        'email': user.email,
        'phone_number': user.profile.phone_number if user.profile else None,
        'avatar': user.profile.avatar.url if user.profile and user.profile.avatar else None,
        'permission': _get_user_permission(user),
        'last_seen': user.last_login,
    }
    return success_response(data=data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def cms_profile_update(request):
    """Update the authenticated CMS user's profile."""
    user = request.user
    allowed_fields = ['first_name', 'last_name', 'email', 'username']
    updated = False

    for field in allowed_fields:
        if field in request.data:
            # Uniqueness checks for email and username
            if field == 'email':
                if User.objects.filter(email=request.data[field]).exclude(pk=user.pk).exists():
                    return error_response('A user with this email already exists.', code=400)
            if field == 'username':
                if User.objects.filter(username=request.data[field]).exclude(pk=user.pk).exists():
                    return error_response('A user with this username already exists.', code=400)
            setattr(user, field, request.data[field])
            updated = True

    if updated:
        user.save()

    data = {
        'id': user.id,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'username': user.username,
        'email': user.email,
        'phone_number': user.profile.phone_number if user.profile else None,
        'avatar': user.profile.avatar.url if user.profile and user.profile.avatar else None,
        'permission': _get_user_permission(user),
        'last_seen': user.last_login,
    }
    return success_response(data=data, message='Profile updated.')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cms_change_password(request):
    """Change the authenticated CMS user's password."""
    user = request.user
    current_password = request.data.get('current_password')
    new_password = request.data.get('new_password')
    confirm_password = request.data.get('confirm_password')

    if not current_password or not new_password or not confirm_password:
        return error_response('All password fields are required.', code=400)

    if not user.check_password(current_password):
        return error_response('Current password is incorrect.', code=400)

    if new_password != confirm_password:
        return error_response('New passwords do not match.', code=400)

    if len(new_password) < 8:
        return error_response('Password must be at least 8 characters long.', code=400)

    user.set_password(new_password)
    user.save()
    return success_response(message='Password changed successfully.')


def _get_user_permission(user):
    """Helper to derive permission string from user roles."""
    role = user.roles.exclude(name='USER').first()
    if role:
        return role.name.lower()
    return 'admin'