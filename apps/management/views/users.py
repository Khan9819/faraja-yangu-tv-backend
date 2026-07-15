from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from django.db.models import Q
from core.response_wrapper import success_response, error_response

from apps.authentication.models import User, Role
from apps.streaming.models import Comment
from apps.management.serializers import (
    AppUserSerializer, AdminUserSerializer, AdminUserCreateSerializer, AdminUserUpdateSerializer,
)
from core.pagination import StandardResultsSetPagination

ROLE_MAP = {
    'super_admin': 'ADMIN',
    'admin': 'ADMIN',
    'moderator': 'EDITOR',
}


# ---------------------------------------------------------------------------
# App Users
# ---------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_app_users(request):
    """List all app users with pagination and filtering."""
    qs = User.objects.filter(roles__name=Role.ROLES.USER).distinct()

    search = request.query_params.get('search', '').strip()
    if search:
        qs = qs.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search) |
            Q(profile__phone_number__icontains=search)
        )

    status_filter = request.query_params.get('status', '').strip().lower()
    if status_filter == 'active':
        qs = qs.filter(is_active=True, is_suspended=False)
    elif status_filter == 'suspended':
        qs = qs.filter(is_suspended=True)
    elif status_filter == 'inactive':
        qs = qs.filter(is_active=False)

    qs = qs.select_related('profile').order_by('-date_joined')

    paginator = StandardResultsSetPagination()
    paginator.page_size = int(request.query_params.get('page_size', 25))
    page = paginator.paginate_queryset(qs, request)

    if page is not None:
        serializer = AppUserSerializer(page, many=True)
        return success_response(serializer.data)

    serializer = AppUserSerializer(qs, many=True)
    return success_response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_app_user(request, pk):
    """Get details for a single app user."""
    try:
        user = User.objects.select_related('profile').get(pk=pk)
    except User.DoesNotExist:
        return error_response('User not found', code=404)
    serializer = AppUserSerializer(user)
    return success_response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_app_user_comments(request, pk):
    """Get all comments made by a specific app user."""
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return error_response('User not found', code=404)

    qs = (
        Comment.objects
        .filter(user=user)
        .select_related('video')
        .order_by('-created_at')
    )

    paginator = StandardResultsSetPagination()
    paginator.page_size = int(request.query_params.get('page_size', 20))
    page = paginator.paginate_queryset(qs, request)
    items = page if page is not None else qs

    data = [{
        'id': c.id,
        'text': c.comment,
        'video_id': c.video_id,
        'video_title': c.video.title if c.video else None,
        'is_reply': c.reply_to_id is not None,
        'created_at': c.created_at,
    } for c in items]

    return success_response(data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def suspend_app_user(request, pk):
    """Suspend an app user."""
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return error_response('User not found', code=404)
    user.is_suspended = True
    user.save(update_fields=['is_suspended'])
    return success_response(message='User suspended.')


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def unsuspend_app_user(request, pk):
    """Unsuspend an app user."""
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return error_response('User not found', code=404)
    user.is_suspended = False
    user.save(update_fields=['is_suspended'])
    return success_response(message='User unsuspended.')


# ---------------------------------------------------------------------------
# Admin Users
# ---------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_admin_users(request):
    """List all admin/staff users (non-USER role)."""
    qs = User.objects.filter(
        roles__name__in=[Role.ROLES.ADMIN, Role.ROLES.EDITOR]
    ).distinct().order_by('-date_joined')
    serializer = AdminUserSerializer(qs, many=True)
    return success_response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_admin_user(request):
    """Create a new admin/staff user."""
    serializer = AdminUserCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return error_response(serializer.errors, code=400)

    data = serializer.validated_data
    user = User.objects.create(
        first_name=data['first_name'],
        last_name=data['last_name'],
        email=data['email'],
        username=data['username'],
        auth_provider='email',
        is_verified=True,
        is_active=True,
    )
    user.set_password(data['password'])
    user.save()

    role_name = ROLE_MAP.get(data['role'], 'ADMIN')
    role_obj, _ = Role.objects.get_or_create(
        name=role_name,
        defaults={'description': f'{role_name} role'},
    )
    user.roles.add(role_obj)

    response_serializer = AdminUserSerializer(user)
    return success_response(response_serializer.data, message='Admin user created.')


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_admin_user(request, pk):
    """Update an existing admin/staff user."""
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return error_response('Admin user not found', code=404)

    serializer = AdminUserUpdateSerializer(data=request.data, context={'user': user})
    if not serializer.is_valid():
        return error_response(serializer.errors, code=400)

    data = serializer.validated_data
    for field in ['first_name', 'last_name', 'email', 'username']:
        if field in data:
            setattr(user, field, data[field])

    if 'password' in data:
        user.set_password(data['password'])

    user.save()

    if 'role' in data:
        role_name = ROLE_MAP.get(data['role'], 'ADMIN')
        role_obj, _ = Role.objects.get_or_create(
            name=role_name,
            defaults={'description': f'{role_name} role'},
        )
        user.roles.clear()
        user.roles.add(role_obj)

    response_serializer = AdminUserSerializer(user)
    return success_response(response_serializer.data, message='Admin user updated.')


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_admin_user(request, pk):
    """Delete an admin/staff user."""
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return error_response('Admin user not found', code=404)

    if user.pk == request.user.pk:
        return error_response('You cannot delete your own account.', code=400)

    user.delete()
    return success_response(message='Admin user deleted.')
