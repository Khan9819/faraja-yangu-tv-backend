from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from core.response_wrapper import success_response, error_response

from apps.analytics.models import Notification
from apps.management.serializers import NotificationSerializer
from core.pagination import StandardResultsSetPagination


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_notifications(request):
    """List notifications for the authenticated admin user."""
    qs = Notification.objects.filter(user=request.user).order_by('-created_at')

    paginator = StandardResultsSetPagination()
    paginator.page_size = int(request.query_params.get('page_size', 10))
    page = paginator.paginate_queryset(qs, request)

    if page is not None:
        serializer = NotificationSerializer(page, many=True)
        return success_response(serializer.data)

    serializer = NotificationSerializer(qs, many=True)
    return success_response(serializer.data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def mark_notification_read(request, pk):
    """Mark a single notification as read."""
    try:
        notification = Notification.objects.get(pk=pk, user=request.user)
    except Notification.DoesNotExist:
        return error_response('Notification not found', code=404)

    notification.is_read = True
    notification.save(update_fields=['is_read', 'updated_at'])
    return success_response(message='Notification marked as read.')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_all_notifications_read(request):
    """Mark all notifications as read for the authenticated user."""
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return success_response(message='All notifications marked as read.')
