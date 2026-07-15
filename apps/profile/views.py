from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from core.response_wrapper import success_response, error_response
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from apps.authentication.serializers.profile import ProfileSerializer
from apps.authentication.models import User
from apps.profile.serializers.profile import UserProfileSerializer, ProfileDetailSerializer
from apps.authentication.services.credit import UserCreditService
# Create your views here.

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def profile(request):
    user = request.user

    # Ensure the user has a profile initialized
    if not user.profile:
        from apps.authentication.models import Profile

        profile = Profile.objects.create()
        user.profile = profile
        user.save()

    serializer = UserProfileSerializer(user)
    return success_response(data={
        'initial_credit_claimed': UserCreditService(user).GAIN_FROM_INITIAL_REGISTRATION if not user.profile.initial_credit_claimed else None,
        **serializer.data
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def acknowledge_initial_credit(request):
    user = request.user
    profile = user.profile
    profile.initial_credit_claimed = True
    profile.save()
    return success_response()
    
@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def profile_update(request):
    user = request.user
    serializer = ProfileSerializer(User.objects.get(id=user.id), data=request.data)
    if serializer.is_valid():
        serializer.save()
        return success_response(serializer.data)
    return error_response(serializer.errors)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_profile(request):
    """Create or update the authenticated user's profile."""

    user = request.user

    # Ensure the user has a profile instance
    if not user.profile:
        from apps.authentication.models import Profile

        profile = Profile.objects.create()
        user.profile = profile
        user.save()
    else:
        profile = user.profile

    serializer = ProfileDetailSerializer(profile, data=request.data, partial=True)

    if serializer.is_valid():
        serializer.save()
        # Return the full combined user+profile representation
        user.refresh_from_db()
        return success_response(UserProfileSerializer(user).data)

    return error_response(serializer.errors)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def profile_reset_password(request):
    user = request.user
    serializer = ProfileSerializer(User.objects.get(id=user.id), data=request.data)
    if serializer.is_valid():
        serializer.save()
        return success_response(serializer.data)
    return error_response(serializer.errors)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def profile_request_data_delete(request):
    user = request.user
    serializer = ProfileSerializer(User.objects.get(id=user.id), data=request.data)
    if serializer.is_valid():
        serializer.save()
        return success_response(serializer.data)
    return error_response(serializer.errors)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def profile_request_account_delete(request):
    user = request.user
    serializer = ProfileSerializer(User.objects.get(id=user.id), data=request.data)
    if serializer.is_valid():
        serializer.save()
        return success_response(serializer.data)
    return error_response(serializer.errors)
