from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from core.response_wrapper import success_response, error_response

from apps.management.serializers import WebsitePostSerializer, WebsitePostCreateSerializer
from apps.management.models import WebsitePost


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_website_posts(request):
    posts = WebsitePost.objects.all().order_by('-date', '-created_at')
    serializer = WebsitePostSerializer(posts, many=True, context={'request': request})
    return success_response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_website_post(request):
    serializer = WebsitePostCreateSerializer(data=request.data)
    if serializer.is_valid():
        post = serializer.save()
        response_serializer = WebsitePostSerializer(post, context={'request': request})
        return success_response(response_serializer.data, message='Website post created successfully')

    return error_response(serializer.errors, code=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_website_post(request, pk):
    try:
        post = WebsitePost.objects.get(pk=pk)
    except WebsitePost.DoesNotExist:
        return error_response('Website post not found', code=404)

    serializer = WebsitePostSerializer(post, context={'request': request})
    return success_response(serializer.data)


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def update_website_post(request, pk):
    try:
        post = WebsitePost.objects.get(pk=pk)
    except WebsitePost.DoesNotExist:
        return error_response('Website post not found', code=404)

    serializer = WebsitePostCreateSerializer(post, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        response_serializer = WebsitePostSerializer(post, context={'request': request})
        return success_response(response_serializer.data, message='Website post updated successfully')

    return error_response(serializer.errors, code=400)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_website_post(request, pk):
    try:
        post = WebsitePost.objects.get(pk=pk)
    except WebsitePost.DoesNotExist:
        return error_response('Website post not found', code=404)

    post.delete()
    return success_response(message='Website post deleted successfully')
