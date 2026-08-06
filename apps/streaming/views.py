import json
import re
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.authentication.services.credit import UserCreditService
from apps.streaming.serializers.video import (
    VideoFeedSerializer,
    VideoSerializer,
    VideoHistorySerializer,
    FavoriteVideoSerializer,
)
from apps.streaming.serializers.playlist import (
    PlaylistListSerializer,
    PlaylistDetailSerializer,
)
from apps.advertising.models import Ad
from core.response_wrapper import success_response, error_response
from rest_framework.decorators import api_view
from .models import Category, Video, Playlist, PlaylistVideo, Comment, VideoAdSlot
from apps.streaming.models import Like, Dislike, View
from django.db.models import Count, Q, F, Exists, OuterRef
from core.pagination import StandardResultsSetPagination
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.decorators import permission_classes
from .serializers.category import CategorySerializer
from .serializers.comment import CommentSerializer, ReplySerializer
from apps.streaming.tasks.tasks import assemble_chunks_task, delete_video_files_task
from apps.authentication.models import Profile, User
from rest_framework_simplejwt.tokens import RefreshToken
from django.http import HttpResponse, Http404, FileResponse, StreamingHttpResponse
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Exists, OuterRef, F, Value, Case, When, BooleanField, CharField, Q
from django.db.models.functions import Concat, Cast
from django.core.cache import cache
from django.db import close_old_connections
import logging
import mimetypes
import os
import hashlib
import io
import random
from django.shortcuts import get_object_or_404
import boto3
from botocore.config import Config
from django.conf import settings
from apps.streaming.socket.utils import send_upload_progress

logger = logging.getLogger(__name__)


def get_random_active_ad():
    """Get a random active interceptor ad from the database."""
    active_ads = VideoAdSlot.objects.filter(is_active=True).exclude(media_file='')
    if not active_ads.exists():
        return None
    return random.choice(list(active_ads))


def inject_ad_markers(playlist_content: str, video_slug: str, min_interval: int = 300) -> str:
    """
    Inject ad markers into HLS playlist for client-side ad insertion.
    
    Uses VideoAdSlot model to get active ads and injects them at random intervals,
    ensuring at least 5 minutes (300 seconds) between ads.
    
    Args:
        playlist_content: Original playlist content
        video_slug: Video slug for tracking
        min_interval: Minimum seconds between ad breaks (default: 300 = 5 minutes)
    
    Returns:
        Modified playlist with ad markers
    """
    # Get active ads from database
    active_ads = list(VideoAdSlot.objects.filter(is_active=True).exclude(media_file=''))
    if not active_ads:
        print(f"No active interceptor ads found for {video_slug}")
        return playlist_content
    
    lines = playlist_content.split('\n')
    new_lines = []
    current_duration = 0.0
    last_ad_time = 0.0
    ad_count = 0
    
    # Calculate total video duration first
    total_duration = 0.0
    for line in lines:
        if line.startswith('#EXTINF:'):
            try:
                duration_str = line.split(':')[1].split(',')[0]
                total_duration += float(duration_str)
            except (IndexError, ValueError):
                pass
    
    # Generate random ad insertion points with random intervals (5, 10, 20, 30 min)
    # Minimum interval is 5 minutes (300 seconds) after the initial ad
    interval_options = [300, 600, 1200, 1800]  # 5, 10, 20, 30 minutes in seconds
    
    ad_insertion_points = []
    if total_duration > 10:  # Only insert ads if video is longer than 10 seconds
        # Pre-roll ad at the very start (0 seconds)
        ad_insertion_points.append(0)
        
        # Subsequent ads after random intervals (5, 10, 20, or 30 min)
        current_point = random.choice(interval_options)
        while current_point < total_duration - 30:  # Don't insert ad in last 30 seconds
            ad_insertion_points.append(current_point)
            current_point += random.choice(interval_options)
    
    print(f"Planned ad insertion points for {video_slug}: {ad_insertion_points}")
    
    current_duration = 0.0
    next_ad_index = 0
    
    for line in lines:
        # Track segment duration
        if line.startswith('#EXTINF:'):
            try:
                duration_str = line.split(':')[1].split(',')[0]
                segment_duration = float(duration_str)
                current_duration += segment_duration
                
                # Check if we should insert an ad at this point
                if (next_ad_index < len(ad_insertion_points) and 
                    current_duration >= ad_insertion_points[next_ad_index]):
                    
                    # Pick a random ad from active ads
                    ad = random.choice(active_ads)
                    ad_count += 1
                    
                    # Get ad duration
                    ad_duration = ad.display_duration or 5
                    
                    # Inject HLS ad markers with ad metadata
                    new_lines.append(f'#EXT-X-CUE-OUT:DURATION={ad_duration}')
                    new_lines.append(f'#EXT-X-ASSET:CAID=interceptor-{ad.id}')
                    
                    # Add custom metadata for the player
                    if ad.media_file:
                        new_lines.append(f'#EXT-X-AD-URL:{ad.media_file.url}')
                    if ad.redirect_link:
                        new_lines.append(f'#EXT-X-AD-CLICK:{ad.redirect_link}')
                    new_lines.append(f'#EXT-X-AD-TYPE:{ad.media_type}')
                    
                    logger.info(f"Injected ad {ad.id} at {current_duration:.1f}s for {video_slug}")
                    
                    next_ad_index += 1
                    last_ad_time = current_duration
                    
            except (IndexError, ValueError):
                pass
        
        new_lines.append(line)
    
    logger.info(f"Injected {ad_count} ads into playlist for {video_slug}")
    return '\n'.join(new_lines)

# Create your views here.

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_category(request):
    
    serializer = CategorySerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return success_response(serializer.data)
    return error_response(serializer.errors)

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_category(request, pk):
    category = Category.objects.get(pk=pk)
    serializer = CategorySerializer(category, data=request.data)
    if serializer.is_valid():
        result = serializer.save()
        return success_response(serializer.data)
    return error_response(serializer.errors)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_categories(request):
    types: ('all', 'parent', 'child') = request.GET.get('type', 'all')
    
    if types == 'parent':
        categories = Category.objects.filter(parent_id=None)
    elif types == 'child':
        categories = Category.objects.filter(parent_id__isnull=False)
    else:
        categories = Category.objects.all()
    
    serializer = CategorySerializer(categories, many=True)
    
    return success_response(serializer.data)

@api_view(['GET', 'DELETE'])
@permission_classes([IsAuthenticated])
def get_category(request, pk):
    
    if request.method == 'GET':
        include_videos = request.GET.get('include_videos', 'false').lower() == 'true'
        video_count = int(request.GET.get('video_count', 10))
        parents = request.GET.get('parents_only', 'false').lower() == 'true'
        
        category = Category.objects.get(pk=pk)
        serializer = CategorySerializer(
            category, 
            include_videos=include_videos, 
            video_count=video_count,
            parents=parents
        )
        return success_response(serializer.data)
    
    elif request.method == 'DELETE':
        try:
            category = Category.objects.get(pk=pk)
            
            # Delete associated media files from storage
            if category.thumbnail:
                if default_storage.exists(category.thumbnail.name):
                    default_storage.delete(category.thumbnail.name)
            
            if category.cover:
                if default_storage.exists(category.cover.name):
                    default_storage.delete(category.cover.name)
            
            category.delete()
            return success_response(
                {'message': 'Category deleted successfully'},
            )
        except Category.DoesNotExist:
            return error_response(
                'Category not found',
                code=status.HTTP_404_NOT_FOUND
            )
    
    return error_response(
        'Method not allowed',
        code=status.HTTP_405_METHOD_NOT_ALLOWED
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_category_videos(request, pk):
    category = Category.objects.get(pk=pk)
    videos = Video.objects.filter(category=category, is_published=True, processing_status='completed', is_ad_media=False)
    serializer = VideoSerializer(videos, many=True)
    return success_response(serializer.data)

@api_view(['GET'])
def get_subcategories(request, category_id):
    subcategories = Category.objects.filter(~Q(parent=None), parent=category_id)
    serializer = CategorySerializer(subcategories, many=True)
    return success_response(serializer.data)

@api_view(['GET'])
def get_subcategory(request, pk):
    subcategory = Category.objects.get(parent=pk)
    serializer = CategorySerializer(subcategory)
    return success_response(serializer.data)

@api_view(['GET'])
def get_feed(request):
    """Return a paginated list of videos with category and parent category info."""
    close_old_connections()
    
    # Pagination params
    try:
        page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = int(request.GET.get('page_size', 20))
        page_size = min(page_size, 50)  # Cap at 50 to prevent excessive queries
    except (TypeError, ValueError):
        page_size = 20
    
    # Try cache first
    cache_key = f"feed:page:{page}:size:{page_size}"
    if not settings.DEBUG:
        cached_response = cache.get(cache_key)
        if cached_response:
            return success_response(cached_response)
    
    # Prefetch category and its parent to avoid N+1 queries
    queryset = Video.objects.filter(is_published=True, processing_status='completed', is_ad_media=False).select_related('category', 'category__parent').all().order_by('-created_at')

    paginator = Paginator(queryset, page_size)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
        page = 1
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
        page = paginator.num_pages

    # Disable starter_segments in feed for performance (uses cache after first load)
    serializer = VideoFeedSerializer(
        page_obj.object_list, 
        many=True,
        context={'include_starter_segments': False}
    )

    # Base results are videos
    results = list(serializer.data)
    
    # Inject at most one ad segment per page so feed is not full of ads
    if results:
        ad_segment = None

        # Try to use a custom ad if available
        custom_ad = Ad.objects.filter(is_published=True).first()
        if custom_ad:
            is_video = custom_ad.type == Ad.AD_TYPES.VIDEO and bool(custom_ad.video)
            ad_segment = {
                'segment_type': 'AD',
                'ad_render_type': 'CUSTOM',  # frontend: render custom ad
                'ad': {
                    'id': custom_ad.id,
                    'name': custom_ad.name,
                    'slug': custom_ad.slug,
                    'type': custom_ad.type,
                    # Fields the Flutter in-feed ad box renders directly:
                    # VIDEO ads play a muted looping box, IMAGE ads show a
                    # clickable cover — both fall back to network banners.
                    'media_type': 'VIDEO' if is_video else 'IMAGE',
                    'video_url': custom_ad.video.url if is_video else None,
                    'image_url': custom_ad.thumbnail.url if custom_ad.thumbnail else None,
                    'thumbnail': custom_ad.thumbnail.url if custom_ad.thumbnail else None,
                    'click_url': custom_ad.redirect_link,
                    'redirect_link': custom_ad.redirect_link,
                    'duration': custom_ad.duration.total_seconds() if custom_ad.duration else None,
                },
            }
        else:
            # Fallback to google ad placeholder only
            ad_segment = {
                'segment_type': 'AD',
                'ad_render_type': 'GOOGLE',  # frontend: render Google ad slot
            }

        # Place ad roughly in the middle of the page
        if ad_segment:
            insert_index = max(1, len(results) // 2)
            results.insert(insert_index, ad_segment)

    response_data = {
        'results': results,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total_items': paginator.count,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
        },
    }
    
    # Cache for 60 seconds
    cache.set(cache_key, response_data, timeout=60)
    
    return success_response(response_data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def history_list(request):
    """List videos in the authenticated user's watch history.

    This simplified version uses Profile.videos_watched without per-item
    timestamps, so `last_watched_at` is always null.
    """

    profile = getattr(request.user, "profile", None)
    if not profile:
        return success_response({
            'results': [],
            'pagination': {
                'page': 1,
                'page_size': 20,
                'has_next': False,
                'total': 0,
            },
        })

    queryset = (
        profile.videos_watched
        .select_related('category', 'category__parent')
        .all()
        .order_by('-created_at')
    )

    try:
        page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = int(request.GET.get('page_size', 20))
    except (TypeError, ValueError):
        page_size = 20

    paginator = Paginator(queryset, page_size)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
        page = 1
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
        page = paginator.num_pages

    serializer = VideoHistorySerializer(page_obj.object_list, many=True)

    return success_response({
        'results': serializer.data,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'has_next': page_obj.has_next(),
            'total': paginator.count,
        },
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def favorites_list(request):
    """List videos in the authenticated user's favorites.

    Uses Profile.favorite_videos without per-item timestamps.
    """

    profile = getattr(request.user, "profile", None)
    if not profile:
        return success_response({
            'results': [],
            'pagination': {
                'page': 1,
                'page_size': 20,
                'has_next': False,
                'total': 0,
            },
        })

    queryset = profile.favorite_videos.select_related('category', 'category__parent').all()

    try:
        page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = int(request.GET.get('page_size', 20))
    except (TypeError, ValueError):
        page_size = 20

    paginator = Paginator(queryset, page_size)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
        page = 1
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
        page = paginator.num_pages

    serializer = FavoriteVideoSerializer(page_obj.object_list, many=True)

    return success_response({
        'results': serializer.data,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'has_next': page_obj.has_next(),
            'total': paginator.count,
        },
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def downloads_list(request):
    """List videos the authenticated user marked as downloaded.

    Uses Profile.downloaded_videos; timestamp is not tracked in this version.
    """

    profile = getattr(request.user, "profile", None)
    if not profile:
        return success_response({
            'results': [],
            'pagination': {
                'page': 1,
                'page_size': 20,
                'has_next': False,
                'total': 0,
            },
        })

    queryset = profile.downloaded_videos.select_related('category', 'category__parent').all()

    try:
        page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = int(request.GET.get('page_size', 20))
    except (TypeError, ValueError):
        page_size = 20

    paginator = Paginator(queryset, page_size)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
        page = 1
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
        page = paginator.page(paginator.num_pages)

    serializer = VideoHistorySerializer(page_obj.object_list, many=True)

    return success_response({
        'results': serializer.data,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'has_next': page_obj.has_next(),
            'total': paginator.count,
        },
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def favorite_video(request, video_uid):
    """Mark a video as favorite for the current user."""

    profile = getattr(request.user, "profile", None)
    if not profile:
        return error_response({'message': 'Profile not found'})

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    profile.favorite_videos.add(video)
    return success_response(data={}, message='Favorited')

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def clear_history_list(request):
    profile = getattr(request.user, "profile", None)
    if not profile:
        return error_response(message='Profile not found', code=404)
    profile.videos_watched.clear()
    return success_response(data={}, message='History cleared')

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def clear_favorites_list(request):
    profile = getattr(request.user, "profile", None)
    if not profile:
        return error_response(message='Profile not found', code=404)
    profile.favorite_videos.clear()
    return success_response(data={}, message='Favorites cleared')

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def playlist_clear_video(request, playlist_id):
    try:
        playlist = Playlist.objects.get(id=playlist_id, owner=request.user)
    except Playlist.DoesNotExist:
        return error_response(message='Playlist not found', code=404)
    playlist.playlist_videos.all().delete()
    return success_response(data={}, message='Playlist cleared')

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def unfavorite_video(request, video_uid):
    """Remove a video from the current user's favorites."""

    profile = getattr(request.user, "profile", None)
    if not profile:
        return error_response({'message': 'Profile not found'})

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    profile.favorite_videos.remove(video)
    return success_response(data={}, message='Unfavorited')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_video_downloaded(request, video_uid):
    """Mark a video as downloaded for the current user.
    
    Idempotent: if the user already downloaded this video, returns success
    without deducting credits again.
    
    Supports optional ``Idempotency-Key`` header for additional dedup.
    
    Returns:
        - credits_used: credits deducted (0 if already downloaded)
        - updated_credits: user's new credit balance
        - already_downloaded: whether the video was already marked
    """
    from django.core.cache import cache
    from django.db import transaction

    profile = getattr(request.user, "profile", None)
    if not profile:
        return error_response({'message': 'Profile not found'})

    # Idempotency-Key header dedup
    idempotency_key = request.headers.get('Idempotency-Key')
    if idempotency_key:
        cache_key = f"idem:download:{request.user.pk}:{idempotency_key}"
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return success_response(data=cached_response, message='Already processed')

    # Validate video exists before any credit operation
    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    # Idempotency: check if already downloaded
    if profile.downloaded_videos.filter(pk=video.pk).exists():
        credit_service = UserCreditService(request.user)
        data = {
            'credits_used': 0,
            'updated_credits': credit_service.get_balance(),
            'already_downloaded': True,
        }
        if idempotency_key:
            cache.set(cache_key, data, timeout=300)
        return success_response(data=data, message='Already downloaded')

    # Credit sufficiency check — higher download qualities cost extra.
    quality = (request.data.get('quality') or '480p').lower()
    quality_premium = {'720p': 20, '1080p': 40}.get(quality, 0)
    credit_service = UserCreditService(request.user)
    cost = UserCreditService.DEDUCT_FROM_DOWNLOAD + quality_premium
    if not credit_service.is_credit_sufficient(cost):
        current = credit_service.get_balance()
        return error_response(
            f'Insufficient credits. Required: {cost}, Available: {current}',
            code=400,
        )

    # Atomic deduction + download record
    with transaction.atomic():
        credit_service.deduct_from_download()
        profile.downloaded_videos.add(video)

    data = {
        'credits_used': cost,
        'updated_credits': credit_service.get_balance(),
        'already_downloaded': False,
    }
    if idempotency_key:
        cache.set(cache_key, data, timeout=300)
    return success_response(data=data, message='Marked as downloaded')


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def unmark_video_downloaded(request, video_uid):
    """Remove a video from the current user's downloads list."""

    profile = getattr(request.user, "profile", None)
    if not profile:
        return error_response({'message': 'Profile not found'})

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    profile.downloaded_videos.remove(video)
    return success_response(data={}, message='Removed from downloads')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_download_status(request, video_uid):
    """Check if a video is already downloaded (server-side) for the current user."""

    profile = getattr(request.user, "profile", None)
    if not profile:
        return error_response({'message': 'Profile not found'})

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    is_downloaded = profile.downloaded_videos.filter(pk=video.pk).exists()
    return success_response(data={'is_downloaded': is_downloaded})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_downloads(request):
    """Return all video UIDs the current user has downloaded.

    Useful for syncing local download records after app reinstall.
    """

    profile = getattr(request.user, "profile", None)
    if not profile:
        return error_response({'message': 'Profile not found'})

    downloaded_uids = list(
        profile.downloaded_videos.values_list('uid', flat=True)
    )
    return success_response(data={'downloaded_video_uids': [str(uid) for uid in downloaded_uids]})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_videos(request):
    query = request.GET.get('search')
    page_param = request.GET.get('page')
    count_param = request.GET.get('count')

    if not query or not page_param or not count_param:
        return error_response('Invalid query parameters', code=400)

    try:
        page = int(page_param)
        count = int(count_param)
        if page < 1 or count < 1:
            raise ValueError
    except (TypeError, ValueError):
        return error_response('Invalid query parameters', code=400)

    queryset = (
        Video.objects
        .filter(is_published=True, processing_status='completed', is_ad_media=False)
        .select_related('category', 'category__parent')
        .filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(slug__icontains=query)
        )
        .order_by('-created_at')
    )

    paginator = Paginator(queryset, count)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page = 1
        page_obj = paginator.page(page)
    except EmptyPage:
        page_obj = []

    if page_obj:
        objects = getattr(page_obj, 'object_list', page_obj)
        serializer = VideoFeedSerializer(objects, many=True)
        results = serializer.data
        has_next = getattr(page_obj, 'has_next', lambda: False)()
    else:
        results = []
        has_next = False

    return success_response({
        'results': results,
        'pagination': {
            'page': page,
            'count': count,
            'has_next': has_next,
            'total': paginator.count,
        },
    }, message='Search results loaded successfully.')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def get_chunk_upload_url(request):
    """
    Get a presigned URL for direct chunk upload to R2/S3.
    Client uploads directly to cloud storage, bypassing the server.
    
    Expected request data (camelCase):
    - videoId: ID of the video being uploaded
    - chunkIndex: Current chunk number (0-based)
    - totalChunks: Total number of chunks
    """
    close_old_connections()
    
    try:
        video_id = request.data.get('videoId')
        chunk_index = request.data.get('chunkIndex')
        total_chunks = request.data.get('totalChunks')
        
        if not all([video_id, chunk_index is not None, total_chunks]):
            return error_response({
                'error': 'Missing required fields',
                'required': ['videoId', 'chunkIndex', 'totalChunks']
            })
        
        try:
            chunk_index = int(chunk_index)
            total_chunks = int(total_chunks)
        except ValueError:
            return error_response({'error': 'chunkIndex and totalChunks must be integers'})
        
        # Verify video exists and initialize upload tracking (only on first chunk)
        if chunk_index == 0:
            try:
                video = Video.objects.get(id=video_id)
                video.upload_total_chunks = total_chunks
                video.upload_completed_chunks = 0
                video.upload_progress = 0
                video.save(update_fields=['upload_total_chunks', 'upload_completed_chunks', 'upload_progress'])
                # Initialize upload progress tracking and send WebSocket update
                send_upload_progress(video_id, 0, total_chunks, "Upload started")
            except Video.DoesNotExist:
                return error_response({'error': f'Video with id {video_id} not found'})
        else:
            # Send upload progress via WebSocket (chunk_index is 0-based, report current index as completed so far)
            send_upload_progress(video_id, chunk_index, total_chunks)
        
        # Generate presigned URL for direct upload
        chunk_path = f"videos/chunks/{video_id}/chunk_{chunk_index:04d}"
        
        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            region_name=settings.AWS_S3_REGION_NAME,
            config=Config(signature_version='s3v4')
        )
        
        presigned_expiry = getattr(settings, 'CHUNK_UPLOAD_URL_EXPIRY', 300)  # 5 minutes default
        
        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                'Key': chunk_path,
                'ContentType': 'application/octet-stream',
            },
            ExpiresIn=presigned_expiry
        )
        
        return success_response({
            'upload_url': presigned_url,
            'chunk_index': chunk_index,
            'total_chunks': total_chunks,
            'expires_in': presigned_expiry,
            'required_headers': {
                'Content-Type': 'application/octet-stream',
            }
        })
        
    except Exception as e:
        try:
            video = Video.objects.get(id=video_id)
            video.upload_progress = 0
            video.save(update_fields=['upload_progress'])
        except Video.DoesNotExist:
            pass
        try:
            send_upload_progress(video_id, 0, total_chunks, "Upload failed")
        except Exception:
            pass
        logger.error(f"Error generating presigned URL: {str(e)}", exc_info=True)
        return error_response({'error': str(e)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_upload_status(request):
    """
    Get the upload status for a video, including which chunks exist in storage.
    Allows the client to resume uploads after a failure.
    
    Query params:
    - videoId: ID of the video
    - totalChunks: Total number of expected chunks
    """
    close_old_connections()
    
    try:
        video_id = request.query_params.get('videoId')
        total_chunks = request.query_params.get('totalChunks')
        
        if not video_id or not total_chunks:
            return error_response({
                'error': 'Missing required fields',
                'required': ['videoId', 'totalChunks']
            })
        
        try:
            total_chunks = int(total_chunks)
        except ValueError:
            return error_response({'error': 'totalChunks must be an integer'})
        
        # Verify video exists
        try:
            video = Video.objects.get(id=video_id)
        except Video.DoesNotExist:
            return error_response({'error': f'Video with id {video_id} not found'})
        
        # Check which chunks exist in R2 storage
        uploaded_chunks = []
        missing_chunks = []
        
        for i in range(total_chunks):
            chunk_path = f"videos/chunks/{video_id}/chunk_{i:04d}"
            if default_storage.exists(chunk_path):
                uploaded_chunks.append(i)
            else:
                missing_chunks.append(i)
        
        progress = (len(uploaded_chunks) / total_chunks * 100) if total_chunks > 0 else 0
        
        return success_response({
            'video_id': video_id,
            'total_chunks': total_chunks,
            'uploaded_chunks': uploaded_chunks,
            'missing_chunks': missing_chunks,
            'uploaded_count': len(uploaded_chunks),
            'missing_count': len(missing_chunks),
            'progress': round(progress, 1),
            'is_complete': len(missing_chunks) == 0,
        })
        
    except Exception as e:
        logger.error(f"Error checking upload status: {str(e)}", exc_info=True)
        return error_response({'error': str(e)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_chunk(request):
    """
    Upload a chunk of video data for resumable/chunked uploads.
    
    Expected request data (camelCase):
    - chunk: The file chunk (from request.FILES)
    - videoId: ID of the video being uploaded
    - chunkIndex: Current chunk number (0-based)
    - totalChunks: Total number of chunks
    - fileName: Original filename
    
    Optimized for S3/R2 cloud storage - avoids expensive listdir() calls.
    """
    close_old_connections()
    
    try:
        # Validate required fields (camelCase from frontend)
        chunk_file = request.FILES.get('chunk')
        video_id = request.data.get('videoId')
        chunk_index = request.data.get('chunkIndex')
        total_chunks = request.data.get('totalChunks')
        filename = request.data.get('fileName')
        
        if not all([chunk_file, video_id, chunk_index is not None, total_chunks, filename]):
            return error_response({
                'error': 'Missing required fields',
                'required': ['chunk', 'videoId', 'chunkIndex', 'totalChunks', 'fileName']
            })
        
        # Convert to integers
        try:
            chunk_index = int(chunk_index)
            total_chunks = int(total_chunks)
        except ValueError:
            return error_response({'error': 'chunkIndex and totalChunks must be integers'})
        
        # Verify video exists and initialize upload tracking (only on first chunk)
        if chunk_index == 0:
            try:
                video = Video.objects.get(id=video_id)
                video.upload_total_chunks = total_chunks
                video.upload_completed_chunks = 0
                video.upload_progress = 0
                video.save(update_fields=['upload_total_chunks', 'upload_completed_chunks', 'upload_progress'])
                # Initialize upload progress tracking and send WebSocket update
                from apps.streaming.socket.utils import send_upload_progress
                send_upload_progress(video_id, 0, total_chunks, "Upload started")
            except Video.DoesNotExist:
                return error_response({'error': f'Video with id {video_id} not found'})
        
        # Save chunk directly to cloud storage
        chunk_dir = f"videos/chunks/{video_id}"
        chunk_filename = f"chunk_{chunk_index:04d}"
        chunk_path = f"{chunk_dir}/{chunk_filename}"
        
        # Save the chunk - use save() with max_length to allow overwrite if retry
        saved_path = default_storage.save(chunk_path, chunk_file)
        
        # Send upload progress via WebSocket
        from apps.streaming.socket.utils import send_upload_progress
        completed_chunks = chunk_index + 1
        send_upload_progress(video_id, completed_chunks, total_chunks)
        
        # Trust client-side tracking instead of expensive listdir() on cloud storage
        # The assembly endpoint will verify all chunks exist before combining
        is_last_chunk = (chunk_index == total_chunks - 1)
        
        response_data = {
            'message': f'Chunk {chunk_index + 1}/{total_chunks} uploaded',
            'chunk_index': chunk_index,
            'total_chunks': total_chunks,
            'is_last_chunk': is_last_chunk
        }
        
        if is_last_chunk:
            response_data['message'] = 'Last chunk uploaded. Ready for assembly.'
            response_data['next_step'] = 'Call /api/streaming/assemble-chunks/ to combine chunks'
        
        return success_response(response_data)
        
    except Exception as e:
        logger.error(f"Error uploading chunk: {str(e)}", exc_info=True)
        return error_response({'error': str(e)})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def assemble_chunks(request):
    """
    Queue chunk assembly as a background task.
    
    Expected request data (camelCase):
    - videoId: ID of the video
    - fileName: Original filename for the assembled video
    """
    try:
        video_id = request.data.get('videoId')
        filename = request.data.get('fileName')
        
        if not video_id or not filename:
            return error_response({'error': 'Missing videoId or fileName'})
        
        # Verify video exists
        try:
            video = Video.objects.get(id=video_id)
        except Video.DoesNotExist:
            return error_response({'error': f'Video with id {video_id} not found'})
        
        # Queue the assembly task
        try:
            task = assemble_chunks_task.delay(video_id, filename)
            logger.info(f"Queued chunk assembly task {task.id} for video {video_id}")
            message = 'Video assembly queued. Processing will begin shortly.'
        except Exception as e:
            logger.error(f"Could not queue chunk assembly task: {str(e)}", exc_info=True)
            return error_response({'error': 'Could not queue video assembly. Please try again later.'})
        
        return success_response({
            'message': message,
            'video_id': video.id,
            'task_id': task.id
        })
        
    except Exception as e:
        logger.error(f"Error queuing chunk assembly: {str(e)}", exc_info=True)
        return error_response({'error': str(e)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_from_google_drive(request):
    """
    Trigger a background task to download a video from Google Drive and
    attach it to an existing video record.

    Expected request body (JSON):
        - videoId (int): ID of the video record (already created via create-video).
        - google_drive_url (str): A valid Google Drive share link.
    """
    close_old_connections()

    video_id = request.data.get('videoId')
    google_drive_url = request.data.get('google_drive_url')

    if not video_id or not google_drive_url:
        return error_response('videoId and google_drive_url are required.', status.HTTP_400_BAD_REQUEST)

    # Validate the URL and extract file ID
    from apps.streaming.services.google_drive import extract_google_drive_file_id
    file_id = extract_google_drive_file_id(google_drive_url)
    if not file_id:
        return error_response('Invalid Google Drive URL.', status.HTTP_400_BAD_REQUEST)

    try:
        video = Video.objects.get(id=video_id)
    except Video.DoesNotExist:
        return error_response('Video record not found.', status.HTTP_404_NOT_FOUND)

    # Create or update import record
    from apps.streaming.models import GoogleDriveImport
    gdrive_import, _ = GoogleDriveImport.objects.update_or_create(
        video=video,
        defaults={
            'google_drive_url': google_drive_url,
            'google_drive_file_id': file_id,
            'status': 'pending',
            'progress': 0,
            'message': 'Import queued...',
            'error': None,
        },
    )

    # Dispatch Celery task
    from apps.streaming.tasks.tasks import import_video_from_google_drive
    task = import_video_from_google_drive.delay(video_id, google_drive_url)
    gdrive_import.task_id = task.id
    gdrive_import.save(update_fields=['task_id'])

    return success_response({
        'video_id': video_id,
        'task_id': task.id,
        'status': 'pending',
    }, message='Google Drive import started.')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def google_drive_import_status(request):
    """
    Poll the current status of a Google Drive import task.

    Query params:
        - videoId (int): ID of the video record.
    """
    close_old_connections()

    video_id = request.query_params.get('videoId')
    if not video_id:
        return error_response('videoId is required.', status.HTTP_400_BAD_REQUEST)

    from apps.streaming.models import GoogleDriveImport
    try:
        gdrive_import = GoogleDriveImport.objects.get(video_id=video_id)
    except GoogleDriveImport.DoesNotExist:
        return error_response('No import task found for this video.', status.HTTP_404_NOT_FOUND)

    return success_response({
        'video_id': int(video_id),
        'status': gdrive_import.status,
        'progress': gdrive_import.progress,
        'message': gdrive_import.message,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_video(request):
    """
    Create a new video record and return its ID.
    The client uses this ID to upload chunks via get_chunk_upload_url/upload_chunk.
    HLS conversion is triggered later by assemble_chunks.
    """
    data = {key: value for key, value in request.data.items()}
    data['is_published'] = request.data.get('status', 'draft') == 'published'
    data['uploaded_by'] = request.user.id

    serializer = VideoSerializer(data=data)
    if serializer.is_valid():
        video = serializer.save()
        response_data = serializer.data
        response_data['message'] = 'Video created successfully. Ready for chunk upload.'
        return success_response(response_data)
    return error_response(message='Validation failed', code=400, errors=serializer.errors)

@api_view(['GET'])
@permission_classes([AllowAny])
def stream_hls(request, video_slug, file_path):
    """
    Stream HLS files with ad injection support.
    
    This endpoint proxies HLS files from R2 storage and modifies playlists
    to inject ad markers for client-side ad insertion.
    
    Args:
        video_slug: The video slug
        file_path: Path to the HLS file (e.g., 'master.m3u8', '1080p/1080p.m3u8', '1080p/1080p_001.ts')
    
    Returns:
        HLS file with appropriate content type and ad markers
    """
    try:
        # Construct the full path in R2 storage
        storage_path = f"videos/hls/{video_slug}/{file_path}"
        
        # Check if file exists in storage
        if not default_storage.exists(storage_path):
            logger.warning(f"HLS file not found: {storage_path}")
            raise Http404("Video file not found")
        
        # Determine content type based on file extension
        content_type, _ = mimetypes.guess_type(file_path)
        if file_path.endswith('.m3u8'):
            content_type = 'application/vnd.apple.mpegurl'
        elif file_path.endswith('.ts'):
            content_type = 'video/mp2t'
        else:
            content_type = content_type or 'application/octet-stream'
        
        # For playlist files, modify content to inject ad markers
        if file_path.endswith('.m3u8'):
            # Read playlist content
            file_obj = default_storage.open(storage_path, 'rb')
            content = file_obj.read().decode('utf-8')
            file_obj.close()
            
            # Use HLS service to rewrite URLs
            from apps.streaming.services.hls_service import HLSService
            hls_service = HLSService(video_slug)
            modified_content = hls_service.rewrite_playlist_urls(content, file_path)
            
            # Strip PROGRAM-DATE-TIME lines to avoid player duration issues
            modified_content = '\n'.join(
                line for line in modified_content.split('\n')
                if not line.strip().startswith('#EXT-X-PROGRAM-DATE-TIME:')
            )
            
            # Inject ad markers for variant playlists (not master playlist)
            if '/' in file_path:  # This is a variant playlist like "1080p/1080p.m3u8"
                modified_content = inject_ad_markers(modified_content, video_slug)
            
            # Return modified playlist
            response = HttpResponse(modified_content, content_type=content_type)
        elif file_path.endswith('.ts'):
            # Stream .ts segment directly from R2 via Django
            file_obj = default_storage.open(storage_path, 'rb')
            response = FileResponse(file_obj, content_type=content_type)
        else:
            # For other files, stream directly
            file_obj = default_storage.open(storage_path, 'rb')
            response = FileResponse(file_obj, content_type=content_type)
        
        # Add CORS headers for cross-origin streaming
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Range'
        
        # Cache playlists for shorter time (to allow ad updates)
        # (.ts segments are now redirected to R2 and never reach here)
        response['Cache-Control'] = 'public, max-age=10'
        
        logger.info(f"Streaming HLS file: {storage_path}")
        return response
        
    except Exception as e:
        logger.error(f"Error streaming HLS file {video_slug}/{file_path}: {str(e)}")
        raise Http404("Error loading video file")


@api_view(['GET'])
@permission_classes([AllowAny])
def download_video_chunks(request, uid):
    """
    Stream video chunks from R2 as a single downloadable MP4 file.
    Uses StreamingHttpResponse with HTTP Range request support for resume.
    
    Chunks must exist in R2 at: videos/chunks/{video_id}/chunk_0000, chunk_0001, ...
    They are assembled on-the-fly without storing a duplicate MP4.
    """
    try:
        video = Video.objects.get(uid=uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'}, code=404)

    if not video.is_ready_for_streaming:
        return error_response({'message': 'Video is still processing'})

    if video.upload_total_chunks == 0:
        return error_response({'message': 'chunks not available for this video'})

    from django.core.files.storage import default_storage

    # Discover chunks from R2
    chunk_dir = f'videos/chunks/{video.id}'
    chunk_keys = []

    try:
        if hasattr(default_storage, 'connection') and hasattr(default_storage.connection, 'meta'):
            s3_client = default_storage.connection.meta.client
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(
                Bucket=default_storage.bucket_name,
                Prefix=f'{chunk_dir}/',
            )
            for page in pages:
                for obj in page.get('Contents', []):
                    chunk_keys.append(obj['Key'])
            chunk_keys.sort()
        else:
            # Fallback: enumerate by naming convention
            i = 0
            while True:
                chunk_path = f'{chunk_dir}/chunk_{i:04d}'
                if not default_storage.exists(chunk_path):
                    break
                chunk_keys.append(chunk_path)
                i += 1
    except Exception:
        chunk_keys = []

    if not chunk_keys:
        return error_response(
            {'message': 'Download not available — chunks missing from storage'},
            code=404,
        )

    # Calculate total size from chunk objects
    chunk_sizes = []
    total_size = 0
    try:
        for key in chunk_keys:
            head = s3_client.head_object(Bucket=default_storage.bucket_name, Key=key)
            size = head.get('ContentLength', 0)
            chunk_sizes.append(size)
            total_size += size
    except Exception:
        return error_response({'message': 'Failed to read chunk metadata'}, code=500)

    if total_size == 0:
        return error_response({'message': 'Chunk files appear to be empty'}, code=500)

    range_header = request.META.get('HTTP_RANGE', '')

    if range_header:
        range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
        if not range_match:
            return error_response({'message': 'Invalid Range header'}, code=416)

        start_byte = int(range_match.group(1))
        end_byte = (
            int(range_match.group(2))
            if range_match.group(2)
            else total_size - 1
        )

        if start_byte >= total_size:
            return error_response(
                {'message': f'Range not satisfiable: start {start_byte} >= total {total_size}'},
                code=416,
            )

        end_byte = min(end_byte, total_size - 1)

        def ranged_chunk_generator():
            r2 = default_storage.connection.meta.client
            bucket = default_storage.bucket_name
            byte_offset = 0
            for idx in range(len(chunk_keys)):
                chunk_size = chunk_sizes[idx]
                chunk_start = byte_offset
                chunk_end = byte_offset + chunk_size

                if chunk_end <= start_byte:
                    byte_offset = chunk_end
                    continue

                if chunk_start > end_byte:
                    break

                local_start = max(0, start_byte - chunk_start)
                local_end = min(chunk_size, end_byte - chunk_start + 1)

                if local_start < local_end:
                    resp = r2.get_object(
                        Bucket=bucket,
                        Key=chunk_keys[idx],
                        Range=f'bytes={local_start}-{local_end - 1}',
                    )
                    data = resp['Body'].read()
                    if data:
                        yield data
                        byte_offset = chunk_end
                        continue

                # Fallback: download full chunk and slice
                resp = r2.get_object(Bucket=bucket, Key=chunk_keys[idx])
                data = resp['Body'].read()
                if local_start < local_end:
                    yield data[local_start:local_end]

                byte_offset = chunk_end
                if byte_offset > end_byte:
                    break

        response = StreamingHttpResponse(
            ranging_chunk_generator(),
            status=206,
            content_type='video/mp4',
        )
        response['Content-Range'] = f'bytes {start_byte}-{end_byte}/{total_size}'
        response['Content-Length'] = str(end_byte - start_byte + 1)
    else:
        def full_chunk_generator():
            r2 = default_storage.connection.meta.client
            bucket = default_storage.bucket_name
            for key in chunk_keys:
                resp = r2.get_object(Bucket=bucket, Key=key)
                data = resp['Body'].read()
                if data:
                    yield data

        response = StreamingHttpResponse(
            full_chunk_generator(),
            content_type='video/mp4',
        )
        response['Content-Length'] = str(total_size)

    response['Accept-Ranges'] = 'bytes'
    response['Content-Disposition'] = f'attachment; filename="{video.title}.mp4"'
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_video_stream_url(request, uid):
    """
    Get the streaming URL for a video.
    
    Returns:
        Video details with HLS streaming URL from R2 storage
    """
    try:
        video = Video.objects.get(uid=uid)
        
        if not video.is_ready_for_streaming:
            return error_response({
                'message': 'Video is still processing',
                'processing_status': video.processing_status
            })

        # If the user is authenticated, record a view and update watch history
        user = getattr(request, 'user', None)
        if user is not None and getattr(user, 'is_authenticated', False):
            from apps.streaming.models import View

            _, created = View.objects.get_or_create(video=video, user=user)
            if created:
                Video.objects.filter(id=video.id).update(views_count=F('views_count') + 1)

            # Optionally add to watch history like record_view_stream
            profile = getattr(user, 'profile', None)
            if profile:
                profile.videos_watched.add(video)

        # Construct backend streaming URL for ad injection
        from django.conf import settings
        backend_url = getattr(settings, 'BACKEND_URL', 'https://backend.farajayangutv.co.tz')

        # Use backend proxy URL to enable ad injection
        stream_url = f"{backend_url}/streaming/hls/{video.uid}/master.m3u8"
        
        # Direct chunk-streaming download URL (assembles on-the-fly from R2 chunks)
        download_url = f"{backend_url}/streaming/stream/{video.uid}/download-file/"
        
        parent_category_name = None
        category_name = None
        if video.category is not None:
            category_name = video.category.name
            if video.category.parent is not None:
                parent_category_name = video.category.parent.name

        has_liked = False
        has_disliked = False
        user = getattr(request, 'user', None)
        if user is not None and getattr(user, 'is_authenticated', False):
            has_liked = Like.objects.filter(video=video, user=user).exists()
            has_disliked = Dislike.objects.filter(video=video, user=user).exists()

        return success_response({
            'id': video.id,
            'uid': str(video.uid),
            'title': video.title,
            'description': video.description,
            # Thumbnail URL comes directly from object storage backend
            'thumbnail': video.thumbnail.url if video.thumbnail else None,
            'duration': str(video.duration) if video.duration else None,
            'views_count': video.views_count,
            'likes_count': video.likes_count,
            'dislikes_count': video.dislikes_count,
            'slug': video.slug,
            'created_at': video.created_at,
            'parent_category_name': parent_category_name,
            'category_name': category_name,
            'has_liked': has_liked,
            'has_disliked': has_disliked,
            'stream_url': stream_url,
            'download_url': download_url,
            'is_ready': video.is_ready_for_streaming,
        })
        
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_video(request, pk):
    video = Video.objects.get(pk=pk)
    uploaded_by = video.uploaded_by.id
    data = { key: value for key, value in request.data.items() }
    data['uploaded_by'] = uploaded_by
    data['is_published'] = request.data.get('status', 'draft') == 'published'
    serializer = VideoSerializer(video, data=data)
    if serializer.is_valid():
        serializer.save()
        return success_response(serializer.data)
    return error_response(serializer.errors)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_video(request, pk):
    video = Video.objects.get(pk=pk)
    
    # Queue background task to delete HLS files before deleting the video record
    if video.hls_path:
        delete_video_files_task.delay(video.hls_path, str(video.uid))
    
    video.delete()
    return success_response()

@api_view(['GET'])
def get_all_videos(request):
    feed = Video.objects.exclude(is_ad_media=True)
    category_id = request.query_params.get('category')
    if category_id:
        feed = feed.filter(category_id=category_id)
    serializer = VideoSerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['GET'])
def get_video(request, pk):
    feed = Video.objects.get(pk=pk)
    serializer = VideoSerializer(feed)
    return success_response(serializer.data)

@api_view(['GET'])
def get_video_comments(request, pk):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['GET'])
def get_video_related(request, video_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['POST'])
def like_video(request, video_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['POST'])
def dislike_video(request, video_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['POST'])
def like_comment(request, comment_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['POST'])
def dislike_comment(request, comment_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['POST'])
def comment(request, video_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['POST'])
def reply(request, comment_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['POST'])
def view(request, video_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)


# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# /////////////////////////// VIDEO PLAYER: RELATED & INTERACTION ENDPOINTS ///////////////////////// #


@api_view(['GET'])
@permission_classes([AllowAny])
def interceptor_ads(request, video_uid):
    """Return all interceptor ads for the given video uid.

    Supports two types of ad slots:
    1. Linked Ad: References an existing Ad from the advertising system
    2. Self-contained: Has its own media_file (image/video) with redirect_link

    Outer contract:
        {"data": [ ... ] | []}

    - 404 if video_uid does not exist
    - data == [] if there are no ads to show
    """

    # Ensure video exists. The uid column is a UUID field, so invalid strings
    # must be caught and turned into a 404 instead of a 500.
    from django.core.exceptions import ValidationError as DjangoValidationError
    try:
        video = Video.objects.select_related('category__parent').get(uid=video_uid)
    except (Video.DoesNotExist, DjangoValidationError, ValueError):
        raise Http404

    # Optional future-proof position hint ("pre" | "mid" | "post")
    position = request.GET.get('position')  # noqa: F841  # currently unused

    # Gather the video's own category plus its parent (so ads targeting a
    # parent category also match videos inside its subcategories).
    video_category_ids = set()
    if video.category_id:
        video_category_ids.add(video.category_id)
        if video.category.parent_id:
            video_category_ids.add(video.category.parent_id)

    # Get ad slots for this video: slots pinned to this specific video OR
    # global slots (video = null) that target "All Videos".
    slots = (
        VideoAdSlot.objects
        .select_related('ad', 'content_video')
        .prefetch_related('categories')
        .filter(Q(video=video) | Q(video__isnull=True))
        .order_by('start_time')
    )

    valid_slots = []
    for slot in slots:
        # 1. Slot pinned to this exact video — always applies.
        if slot.video_id == video.id:
            valid_slots.append(slot)
            continue

        # 2. Global slot (All Videos): apply category targeting if any.
        #    No categories set = global ad that applies to every video.
        #    Categories set = must overlap with the video's category (or its parent).
        slot_category_ids = {c.id for c in slot.categories.all()}
        if not slot_category_ids or (slot_category_ids & video_category_ids):
            valid_slots.append(slot)

    # Filter: include slots with published ad, self-contained media, or HLS content video
    valid_slots = [
        slot for slot in valid_slots
        if (slot.ad and slot.ad.is_published) or slot.media_file or slot.content_video
    ]

    if not valid_slots:
        return success_response([])

    ads_payload = []
    backend_url = getattr(settings, 'BACKEND_URL', 'https://backend.farajayangutv.co.tz')
    
    for slot in valid_slots:
        if slot.content_video:
            # HLS-converted video ad via content_video FK
            media_type = "VIDEO"
            if slot.content_video.hls_master_playlist and slot.content_video.processing_status == 'completed':
                video_url = f"{backend_url}/streaming/hls/{slot.content_video.uid}/master.m3u8"
            elif slot.content_video.video:
                video_url = request.build_absolute_uri(slot.content_video.video.url)
            else:
                video_url = None
            image_url = slot.content_video.thumbnail.url if slot.content_video.thumbnail else None
            total_seconds = int(slot.content_video.duration.total_seconds()) if slot.content_video.duration else 15
            click_url = slot.redirect_link
            ad_id = f"slot_{slot.id}"
        elif slot.media_file:
            # Self-contained interceptor ad
            media_type = slot.media_type.upper()  # 'IMAGE' or 'VIDEO'
            if media_type == 'VIDEO':
                video_url = request.build_absolute_uri(slot.media_file.url)
                image_url = None
            else:
                image_url = request.build_absolute_uri(slot.media_file.url)
                video_url = None
            
            total_seconds = slot.display_duration or 5
            click_url = slot.redirect_link
            ad_id = f"slot_{slot.id}"
        elif slot.ad:
            # Linked Ad from advertising system
            ad = slot.ad
            if ad.type == Ad.AD_TYPES.VIDEO and ad.video:
                media_type = "VIDEO"
                video_url = ad.video.url
                image_url = None
            else:
                media_type = "IMAGE"
                image_url = ad.thumbnail.url if ad.thumbnail else None
                video_url = None

            if ad.duration:
                total_seconds = int(ad.duration.total_seconds())
            else:
                total_seconds = 15
            click_url = None
            ad_id = ad.id
        else:
            continue

        skippable_after = min(10, total_seconds)

        # Convert TimeField to seconds for start/end time
        def time_to_seconds(t):
            return t.hour * 3600 + t.minute * 60 + t.second if t else 0

        ads_payload.append({
            "id": ad_id,
            "media_type": media_type,
            "image_url": image_url,
            "video_url": video_url,
            "click_url": click_url,
            "duration": total_seconds,
            "skippable_after": skippable_after,
            "start_time": time_to_seconds(slot.start_time),
            "end_time": time_to_seconds(slot.end_time),
            "label": "Sponsored",
            "tracking": {
                "impression_url": None,
                "click_url": None,
            },
        })

    return success_response(ads_payload)


@api_view(['GET'])
def get_related_videos(request, video_uid):
    """Return related videos for a given video.

    Uses RelatedVideoSerializer for consistent payload structure.
    """
    from apps.streaming.serializers.video import RelatedVideoSerializer

    try:
        video = Video.objects.select_related('category').get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    user = getattr(request, 'user', None)
    is_authenticated = user is not None and getattr(user, 'is_authenticated', False)

    # Build queryset with select_related and annotations
    qs = (
        Video.objects
        .select_related('category', 'category__parent')
        .filter(category=video.category, is_published=True, processing_status='completed', is_ad_media=False)
        .exclude(id=video.id)
        .order_by('-created_at')[:20]
    )

    # Annotate like/dislike flags for efficiency (avoids N+1 queries)
    if is_authenticated:
        qs = qs.annotate(
            has_liked=Exists(Like.objects.filter(video=OuterRef('pk'), user=user)),
            has_disliked=Exists(Dislike.objects.filter(video=OuterRef('pk'), user=user)),
        )

    serializer = RelatedVideoSerializer(
        qs,
        many=True,
        context={
            'user': user,
            'include_starter_segments': False,
        }
    )

    return success_response({
        'videos': serializer.data,
        'has_more': False,
    })


def _like_video_stream(request, video_uid):
    """Internal helper to like a video."""
    close_old_connections()

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    from apps.streaming.models import Like

    like, created = Like.objects.get_or_create(video=video, user=request.user)
    if created:
        Video.objects.filter(id=video.id).update(likes_count=F('likes_count') + 1)

    return success_response(data={}, message='Liked')


def _unlike_video_stream(request, video_uid):
    """Internal helper to remove like from a video."""
    close_old_connections()

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    from apps.streaming.models import Like

    deleted_count, _ = Like.objects.filter(video=video, user=request.user).delete()
    if deleted_count > 0:
        Video.objects.filter(id=video.id).update(likes_count=F('likes_count') - 1)

    return success_response(data={}, message='Like removed')


@api_view(['POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def video_like_stream(request, video_uid):
    """Combined like/unlike endpoint for `/stream/{video_uid}/like/`."""

    if request.method == 'POST':
        return _like_video_stream(request, video_uid)
    return _unlike_video_stream(request, video_uid)


def _dislike_video_stream(request, video_uid):
    """Internal helper to dislike a video."""
    close_old_connections()

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    from apps.streaming.models import Dislike

    dislike, created = Dislike.objects.get_or_create(video=video, user=request.user)
    if created:
        Video.objects.filter(id=video.id).update(dislikes_count=F('dislikes_count') + 1)

    return success_response(data={}, message='Disliked')


def _undislike_video_stream(request, video_uid):
    """Internal helper to remove dislike from a video."""
    close_old_connections()

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    from apps.streaming.models import Dislike

    deleted_count, _ = Dislike.objects.filter(video=video, user=request.user).delete()
    if deleted_count > 0:
        Video.objects.filter(id=video.id).update(dislikes_count=F('dislikes_count') - 1)

    return success_response(data={}, message='Dislike removed')


@api_view(['POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def video_dislike_stream(request, video_uid):
    """Combined dislike/undislike endpoint for `/stream/{video_uid}/dislike/`."""

    if request.method == 'POST':
        return _dislike_video_stream(request, video_uid)
    return _undislike_video_stream(request, video_uid)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def record_view_stream(request, video_uid):
    """Record a view for a video."""
    close_old_connections()

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    from apps.streaming.models import View

    _, created = View.objects.get_or_create(video=video, user=request.user)
    if created:
        Video.objects.filter(id=video.id).update(views_count=F('views_count') + 1)

    # Optionally add to watch history
    profile = getattr(request.user, 'profile', None)
    if profile:
        profile.videos_watched.add(video)

    return success_response(data={}, message='View recorded')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def record_share_stream(request, video_uid):
    """Record a share action for analytics (no extra payload)."""

    # For now, we just acknowledge; you can add analytics model later.
    try:
        Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    return success_response(data={}, message='Share recorded')


# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# /////////////////////////////////////// COMMENTS ENDPOINTS /////////////////////////////////////// #


def _get_video_comments_payload(request, video_uid):
    """Internal helper to get paginated comments payload for a video."""

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    try:
        page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page = 1

    try:
        per_page = int(request.GET.get('per_page', 4))
    except (TypeError, ValueError):
        per_page = 4

    qs = Comment.objects.filter(video=video, reply_to__isnull=True).order_by('-created_at')
    paginator = Paginator(qs, per_page)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
        page = 1
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
        page = paginator.num_pages

    serializer = CommentSerializer(page_obj.object_list, many=True)

    return success_response({
        'comments': serializer.data,
        'has_more': page_obj.has_next(),
    })


def _post_comment_payload(request, video_uid):
    """Internal helper to create a comment and return response payload."""

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    content = request.data.get('content')
    if not content:
        return error_response({'message': 'content is required'})

    comment = Comment.objects.create(
        video=video,
        user=request.user,
        comment=content,
    )

    serializer = CommentSerializer(comment)
    return success_response(serializer.data, message='Comment posted')


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def video_comments_stream(request, video_uid):
    """Combined list/create endpoint for `/stream/{video_uid}/comments/`."""

    if request.method == 'GET':
        return _get_video_comments_payload(request, video_uid)
    return _post_comment_payload(request, video_uid)


def _get_comment_replies_payload(request, comment_id):
    """Internal helper to get paginated replies payload for a comment."""

    try:
        comment = Comment.objects.get(id=comment_id)
    except Comment.DoesNotExist:
        return error_response({'message': 'Comment not found'})

    try:
        page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page = 1

    try:
        per_page = int(request.GET.get('per_page', 10))
    except (TypeError, ValueError):
        per_page = 10

    qs = Comment.objects.filter(reply_to=comment).order_by('created_at')
    paginator = Paginator(qs, per_page)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
        page = 1
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
        page = paginator.num_pages

    serializer = ReplySerializer(page_obj.object_list, many=True)

    return success_response({
        'replies': serializer.data,
        'has_more': page_obj.has_next(),
    })


def _post_comment_reply_payload(request, comment_id):
    """Internal helper to create a reply and return response payload."""

    try:
        parent = Comment.objects.select_related('video', 'user').get(id=comment_id)
    except Comment.DoesNotExist:
        return error_response({'message': 'Comment not found'})

    content = request.data.get('content')
    if not content:
        return error_response({'message': 'content is required'})

    reply = Comment.objects.create(
        video=parent.video,
        user=request.user,
        comment=content,
        reply_to=parent,
    )

    # Notify the original commenter (don't notify yourself)
    if parent.user_id != request.user.id:
        from apps.streaming.tasks.tasks import notify_user_of_reply
        replier_name = request.user.get_full_name() or request.user.username
        if settings.DEBUG:
            notify_user_of_reply(
                commenter_user_id=parent.user_id,
                replier_name=replier_name,
                comment_text=content,
                video_uid=str(parent.video.uid),
                video_title=parent.video.title,
            )
        else:
            notify_user_of_reply.delay(
                commenter_user_id=parent.user_id,
                replier_name=replier_name,
                comment_text=content,
                video_uid=str(parent.video.uid),
                video_title=parent.video.title,
            )

    serializer = ReplySerializer(reply)
    return success_response(serializer.data, message='Reply posted')


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def comment_replies_stream(request, comment_id):
    """Combined list/create endpoint for `/comments/{comment_id}/replies/`."""

    if request.method == 'GET':
        return _get_comment_replies_payload(request, comment_id)
    return _post_comment_reply_payload(request, comment_id)


def _like_comment_stream(request, comment_id):
    """Internal helper to like a comment (placeholder, no persistence)."""

    try:
        Comment.objects.get(id=comment_id)
    except Comment.DoesNotExist:
        return error_response({'message': 'Comment not found'})

    return success_response(data={}, message='Comment liked')


def _unlike_comment_stream(request, comment_id):
    """Internal helper to unlike a comment (placeholder)."""

    try:
        Comment.objects.get(id=comment_id)
    except Comment.DoesNotExist:
        return error_response({'message': 'Comment not found'})

    return success_response(data={}, message='Comment like removed')


@api_view(['POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def comment_like_stream(request, comment_id):
    """Combined like/unlike endpoint for `/comments/{comment_id}/like/`."""

    if request.method == 'POST':
        return _like_comment_stream(request, comment_id)
    return _unlike_comment_stream(request, comment_id)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_comment_stream(request, comment_id):
    """Delete a comment (or reply) by ID for the current user."""

    try:
        comment = Comment.objects.get(id=comment_id, user=request.user)
    except Comment.DoesNotExist:
        return error_response({'message': 'Comment not found'})

    comment.delete()
    return success_response(data={}, message='Comment deleted')


# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# /////////////////////////////////////// PLAYLIST ENDPOINTS /////////////////////////////////////// #

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def playlist_list(request):
    """List playlists for the authenticated user (paginated)."""

    qs = Playlist.objects.filter(owner=request.user).order_by('-created_at')

    try:
        page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = int(request.GET.get('page_size', 20))
    except (TypeError, ValueError):
        page_size = 20

    paginator = Paginator(qs, page_size)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
        page = 1
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
        page = paginator.num_pages

    serializer = PlaylistListSerializer(page_obj.object_list, many=True)

    return success_response({
        'results': serializer.data,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'has_next': page_obj.has_next(),
            'total': paginator.count,
        },
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def playlist_create(request):
    """Create a new playlist for the authenticated user."""

    data = {
        'name': request.data.get('name'),
        'description': request.data.get('description', ''),
        'thumbnail': request.data.get('thumbnail'),
    }

    playlist = Playlist(owner=request.user, **{k: v for k, v in data.items() if k != 'thumbnail'})

    # Handle optional thumbnail separately (supports multipart or URL-like value)
    if 'thumbnail' in request.FILES:
        playlist.thumbnail = request.FILES['thumbnail']

    playlist.save()

    serializer = PlaylistListSerializer(playlist)
    return success_response(serializer.data, message='Playlist created')

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def playlist_detail(request, playlist_uid):
    """Get playlist details with videos for the authenticated user."""

    try:
        playlist = Playlist.objects.get(uid=playlist_uid, owner=request.user)
    except Playlist.DoesNotExist:
        return error_response({'message': 'Playlist not found'})

    serializer = PlaylistDetailSerializer(playlist)
    return success_response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def playlist_add_video(request, playlist_id):
    """Add a video to a playlist.

    Expects JSON body: { "video_uid": "..." }
    """

    try:
        playlist = Playlist.objects.get(id=playlist_id, owner=request.user)
    except Playlist.DoesNotExist:
        return error_response({'message': 'Playlist not found'})

    video_uid = request.data.get('video_uid')
    if not video_uid:
        return error_response({'message': 'video_uid is required'})

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    PlaylistVideo.objects.get_or_create(playlist=playlist, video=video)
    return success_response(data={}, message='Video added to playlist')

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def playlist_remove_video(request, playlist_uid, video_uid):
    """Remove a video from a playlist."""

    try:
        playlist = Playlist.objects.get(uid=playlist_uid, owner=request.user)
    except Playlist.DoesNotExist:
        return error_response({'message': 'Playlist not found'})

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    PlaylistVideo.objects.filter(playlist=playlist, video=video).delete()
    return success_response(data={}, message='Video removed from playlist')

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def playlist_delete(request, playlist_uid):
    """Delete a playlist belonging to the authenticated user."""

    try:
        playlist = Playlist.objects.get(uid=playlist_uid, owner=request.user)
    except Playlist.DoesNotExist:
        return error_response({'message': 'Playlist not found'})

    playlist.delete()
    return success_response(data={}, message='Playlist deleted')


# ============================================================================
# 13. Comments (CMS)
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recent_comments(request):
    """Get the most recent top-level comments across all videos (Dashboard)."""
    limit = int(request.query_params.get('limit', 5))

    comments = (
        Comment.objects
        .filter(reply_to__isnull=True)
        .select_related('user', 'user__profile', 'video')
        .prefetch_related('replies')
        .order_by('-created_at')[:limit]
    )

    data = []
    for c in comments:
        avatar = None
        if c.user.profile and c.user.profile.avatar:
            avatar = c.user.profile.avatar.url
        data.append({
            'id': c.id,
            'user_name': c.user.get_full_name() or c.user.username,
            'username': c.user.username,
            'user_avatar': avatar,
            'text': c.comment,
            'video_id': c.video_id,
            'video_title': c.video.title if c.video else None,
            'created_at': c.created_at,
            'replies_count': c.replies.count(),
        })

    return success_response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cms_comment_reply(request, comment_id):
    """Reply to a comment from the CMS."""
    try:
        parent = Comment.objects.select_related('video', 'user').get(id=comment_id)
    except Comment.DoesNotExist:
        return error_response('Comment not found', code=404)

    text = request.data.get('text') or request.data.get('content')
    if not text:
        return error_response('text is required', code=400)

    reply = Comment.objects.create(
        video=parent.video,
        user=request.user,
        comment=text,
        reply_to=parent,
    )

    # Notify the original commenter (don't notify yourself)
    if parent.user_id != request.user.id:
        from apps.streaming.tasks.tasks import notify_user_of_reply
        replier_name = request.user.get_full_name() or request.user.username
        if settings.DEBUG:
            notify_user_of_reply(
                commenter_user_id=parent.user_id,
                replier_name=replier_name,
                comment_text=text,
                video_uid=str(parent.video.uid),
                video_title=parent.video.title,
            )
        else:
            notify_user_of_reply.delay(
                commenter_user_id=parent.user_id,
                replier_name=replier_name,
                comment_text=text,
                video_uid=str(parent.video.uid),
                video_title=parent.video.title,
            )

    return success_response({
        'id': reply.id,
        'uid': str(reply.uid),
        'text': reply.comment,
        'user_name': request.user.get_full_name() or request.user.username,
        'created_at': reply.created_at,
    }, message='Reply posted')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def cms_comment_replies(request, comment_id):
    """Get replies for a specific comment (CMS Dashboard)."""
    try:
        comment = Comment.objects.select_related('video').get(id=comment_id)
    except Comment.DoesNotExist:
        return error_response('Comment not found', code=404)

    replies = (
        Comment.objects
        .filter(reply_to=comment)
        .select_related('user', 'user__profile')
        .order_by('created_at')
    )

    data = []
    for r in replies:
        avatar = None
        if r.user.profile and r.user.profile.avatar:
            avatar = r.user.profile.avatar.url
        data.append({
            'id': r.id,
            'user_name': r.user.get_full_name() or r.user.username,
            'username': r.user.username,
            'user_avatar': avatar,
            'text': r.comment,
            'created_at': r.created_at,
        })

    return success_response(data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def cms_comment_delete(request, comment_id):
    """Delete any comment from the CMS (moderation)."""
    try:
        comment = Comment.objects.get(id=comment_id)
    except Comment.DoesNotExist:
        return error_response('Comment not found', code=404)

    comment.delete()
    return success_response(data={}, message='Comment deleted')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def video_comments_list(request, video_id):
    """Get top-level comments for a specific video with nested replies (CMS)."""
    qs = (
        Comment.objects
        .filter(video_id=video_id, reply_to__isnull=True)
        .select_related('user', 'user__profile')
        .prefetch_related('replies__user', 'replies__user__profile')
        .order_by('-created_at')
    )

    paginator = StandardResultsSetPagination()
    paginator.page_size = int(request.query_params.get('page_size', 50))
    page = paginator.paginate_queryset(qs, request)

    def _serialize(c):
        avatar = None
        if c.user.profile and c.user.profile.avatar:
            avatar = c.user.profile.avatar.url
        return {
            'id': c.id,
            'uid': str(c.uid),
            'user_id': c.user_id,
            'user_name': c.user.get_full_name() or c.user.username,
            'username': c.user.username,
            'user_avatar': avatar,
            'text': c.comment,
            'created_at': c.created_at,
        }

    items = page if page is not None else qs
    data = []
    for c in items:
        entry = _serialize(c)
        entry['replies_count'] = c.replies.count()
        entry['replies'] = [_serialize(r) for r in c.replies.all().order_by('created_at')[:5]]
        data.append(entry)
    return success_response(data)


# ============================================================================
# 14. Video Viewers & Interactions (CMS)
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def video_viewers(request, video_id):
    """Get all users who have watched a specific video with per-user interaction flags."""
    views_qs = (
        View.objects
        .filter(video_id=video_id)
        .select_related('user', 'user__profile')
        .order_by('-created_at')
    )

    paginator = StandardResultsSetPagination()
    paginator.page_size = int(request.query_params.get('page_size', 50))
    page = paginator.paginate_queryset(views_qs, request)

    items = page if page is not None else views_qs

    # Collect unique user ids from this page to batch-lookup interactions
    user_ids = list({v.user_id for v in items})

    liked_set = set(
        Like.objects.filter(video_id=video_id, user_id__in=user_ids)
        .values_list('user_id', flat=True)
    )
    disliked_set = set(
        Dislike.objects.filter(video_id=video_id, user_id__in=user_ids)
        .values_list('user_id', flat=True)
    )
    # Saved = video in profile.favorite_videos
    saved_set = set(
        Profile.objects.filter(
            user__in=user_ids,
            favorite_videos__id=video_id,
        ).values_list('user', flat=True)
    )
    # Downloaded = video in profile.downloaded_videos
    downloaded_set = set(
        Profile.objects.filter(
            user__in=user_ids,
            downloaded_videos__id=video_id,
        ).values_list('user', flat=True)
    )

    data = []
    seen_users = set()
    for v in items:
        if v.user_id in seen_users:
            continue
        seen_users.add(v.user_id)

        avatar = None
        if v.user.profile and v.user.profile.avatar:
            avatar = v.user.profile.avatar.url

        # Find the latest view for this user on this video
        last_watched = (
            View.objects.filter(video_id=video_id, user_id=v.user_id)
            .order_by('-created_at')
            .values_list('created_at', flat=True)
            .first()
        )

        data.append({
            'id': v.id,
            'user_id': v.user_id,
            'full_name': v.user.get_full_name() or v.user.username,
            'username': v.user.username,
            'avatar': avatar,
            'watched_at': v.created_at,
            'last_watched': last_watched,
            'liked': v.user_id in liked_set,
            'disliked': v.user_id in disliked_set,
            'saved': v.user_id in saved_set,
            'downloaded': v.user_id in downloaded_set,
            'shared': False,
        })

    return success_response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def video_interactions(request, video_id):
    """Get aggregated interaction counts for a specific video."""
    try:
        video = Video.objects.get(pk=video_id)
    except Video.DoesNotExist:
        return error_response('Video not found', code=404)

    views_count = View.objects.filter(video=video).count()
    likes_count = Like.objects.filter(video=video).count()
    dislikes_count = Dislike.objects.filter(video=video).count()
    comments_count = Comment.objects.filter(video=video).count()
    saves_count = Profile.objects.filter(favorite_videos=video).count()
    downloads_count = Profile.objects.filter(downloaded_videos=video).count()

    payload = {
        'views_count': views_count,
        'likes_count': likes_count,
        'dislikes_count': dislikes_count,
        'comments_count': comments_count,
        'saves_count': saves_count,
        'downloads_count': downloads_count,
        'shares_count': 0,
    }
    return success_response(payload)


@api_view(['POST'])
@permission_classes([AllowAny])
def tv_device_auth(request):
    """
    Authenticate a TV device and return a JWT access token.
    Creates a guest user account tied to the device ID if not exists.
    No user credentials required — the device is identified by its unique ID.
    Content access is unrestricted for TV devices (no premium checks).
    """
    device_id = request.data.get('device_id') or request.data.get('deviceId')
    device_name = request.data.get('device_name', 'Android TV')

    if not device_id:
        return error_response({'message': 'device_id is required'})

    # Use a predictable username for the guest account
    username = f'tv_guest_{device_id[:30]}'

    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            'email': f'{username}@tv.farajayangutv.local',
            'first_name': device_name,
            'is_active': True,
            'is_verified': True,
            'auth_provider': 'tv_device',
        }
    )

    refresh = RefreshToken.for_user(user)
    return success_response({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user_id': user.id,
        'is_new_device': created,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def retry_conversion(request, video_id):
    """
    Manually retry a failed/stuck video conversion.
    Clears stale locks, reads checkpoint, and re-queues convert_video_to_hls.
    Supports resume from last completed variant.
    """
    from django.core.cache import cache
    from apps.streaming.tasks.tasks import convert_video_to_hls

    try:
        video = Video.objects.get(id=video_id)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'}, code=404)

    if video.processing_status not in ('failed', 'killed', 'pending'):
        return error_response({
            'message': f'Video is {video.processing_status}, not failed/killed/pending'
        }, code=400)

    checkpoint = video.processing_checkpoint or {}
    completed_variants = checkpoint.get('completed_variants', [])
    local_path = checkpoint.get('local_video_path')
    stage = checkpoint.get('stage', 'start')

    resume_from = completed_variants[-1] if completed_variants else None

    lock_key = f'video_conversion_lock_{video_id}'
    cache.delete(lock_key)

    video.processing_status = 'processing'
    video.processing_error = None
    video.processing_message = f'Retry queued' + (f' - resuming from {resume_from}' if resume_from else '')
    video.save(update_fields=['processing_status', 'processing_error', 'processing_message'])

    task = convert_video_to_hls.delay(video_id, local_video_path=local_path)

    return success_response({
        'status': 'retry_queued',
        'task_id': task.id,
        'video_id': video_id,
        'stage': stage,
        'completed_variants': completed_variants,
        'resuming_from_variant': resume_from,
    })
