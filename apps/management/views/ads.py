from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from core.response_wrapper import success_response, error_response

from apps.management.serializers import VideoAdSlotSerializer, VideoAdSlotCreateSerializer
from apps.streaming.models import VideoAdSlot


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_interceptor_ads(request):
    """Get all video ad slots (interceptor ads)."""
    ad_slots = VideoAdSlot.objects.select_related('video', 'ad', 'content_video').order_by('-created_at')
    serializer = VideoAdSlotSerializer(ad_slots, many=True, context={'request': request})
    return success_response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_interceptor_ad(request):
    """Create a new video ad slot (interceptor ad)."""
    serializer = VideoAdSlotCreateSerializer(data=request.data)
    if serializer.is_valid():
        ad_slot = serializer.save()
        response_serializer = VideoAdSlotSerializer(ad_slot, context={'request': request})
        return success_response(response_serializer.data, message='Interceptor ad created successfully')

    return error_response(serializer.errors, code=400)


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def update_interceptor_ad(request, pk):
    """Update an existing interceptor ad."""
    try:
        ad_slot = VideoAdSlot.objects.get(pk=pk)
    except VideoAdSlot.DoesNotExist:
        return error_response('Interceptor ad not found', code=404)

    serializer = VideoAdSlotCreateSerializer(ad_slot, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        response_serializer = VideoAdSlotSerializer(ad_slot, context={'request': request})
        return success_response(response_serializer.data, message='Interceptor ad updated successfully')

    return error_response(serializer.errors, code=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_interceptor_ad(request, pk):
    """Get a single interceptor ad by ID."""
    try:
        ad_slot = VideoAdSlot.objects.select_related('video', 'ad', 'content_video').get(pk=pk)
    except VideoAdSlot.DoesNotExist:
        return error_response('Interceptor ad not found', code=404)

    serializer = VideoAdSlotSerializer(ad_slot, context={'request': request})
    return success_response(serializer.data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_interceptor_ad(request, pk):
    """Delete an interceptor ad."""
    try:
        ad_slot = VideoAdSlot.objects.get(pk=pk)
    except VideoAdSlot.DoesNotExist:
        return error_response('Interceptor ad not found', code=404)

    ad_slot.delete()
    return success_response(message='Interceptor ad deleted successfully')


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def toggle_interceptor_ad(request, pk):
    """Toggle the is_active status of an interceptor ad."""
    try:
        ad_slot = VideoAdSlot.objects.get(pk=pk)
    except VideoAdSlot.DoesNotExist:
        return error_response('Interceptor ad not found', code=404)

    is_active = request.data.get('is_active', not ad_slot.is_active)
    ad_slot.is_active = is_active
    ad_slot.save(update_fields=['is_active', 'updated_at'])

    serializer = VideoAdSlotSerializer(ad_slot, context={'request': request})
    status_msg = 'activated' if ad_slot.is_active else 'deactivated'
    return success_response(serializer.data, message=f'Interceptor ad {status_msg} successfully')
