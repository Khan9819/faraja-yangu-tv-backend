from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import close_old_connections

from core.response_wrapper import success_response, error_response
from apps.analytics.models import Notification
from apps.analytics.serializers.notification import NotificationSerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def unread_notification_count(request):
    """Return count of unread notifications for badge display."""
    close_old_connections()
    count = Notification.objects.filter(user=request.user, is_read=False).count()
    return success_response({'unread_count': count}, message='OK')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_notifications(request):
    close_old_connections()
    
    user = request.user

    page_param = request.GET.get('page')
    page_size_param = request.GET.get('page_size')

    if not page_param or not page_size_param:
        return error_response('Invalid query parameters', code=400)

    try:
        page = int(page_param)
        page_size = int(page_size_param)
        page_size = min(page_size, 50)  # Cap at 50
        if page < 1 or page_size < 1:
            raise ValueError
    except (TypeError, ValueError):
        return error_response('Invalid query parameters', code=400)

    queryset = Notification.objects.filter(user=user).order_by('-created_at')

    paginator = Paginator(queryset, page_size)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page = 1
        page_obj = paginator.page(page)
    except EmptyPage:
        page_obj = []

    if page_obj:
        objects = getattr(page_obj, 'object_list', page_obj)
        serializer = NotificationSerializer(objects, many=True)
        results = serializer.data
        has_next = getattr(page_obj, 'has_next', lambda: False)()
    else:
        results = []
        has_next = False

    return success_response({
        'results': results,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'has_next': has_next,
            'total': paginator.count,
        },
    }, message='Notifications loaded successfully.')


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def mark_notification_read(request, pk):
    close_old_connections()
    
    try:
        notification = Notification.objects.get(pk=pk, user=request.user)
    except Notification.DoesNotExist:
        return error_response('Notification not found', code=404)

    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=['is_read'])

    return success_response({
        'id': notification.id,
        'is_read': notification.is_read,
    }, message='Notification marked as read.')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_all_notifications_read(request):
    close_old_connections()
    
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return success_response(None, message='All notifications marked as read.')


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_notification(request, pk):
    close_old_connections()
    
    try:
        notification = Notification.objects.get(pk=pk, user=request.user)
    except Notification.DoesNotExist:
        return error_response('Notification not found', code=404)

    notification.delete()
    return success_response(None, message='Notification deleted.')


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def clear_all_notification(request):
    close_old_connections()
    
    try:
        notification = Notification.objects.filter(user=request.user)
    except Notification.DoesNotExist:
        return error_response('Notification not found', code=404)

    notification.delete()
    return success_response(None, message='Notifications deleted.')