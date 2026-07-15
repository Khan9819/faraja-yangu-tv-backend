from datetime import date, timedelta

from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from django.utils import timezone
from django.db.models import Count, Sum
from core.response_wrapper import success_response

from apps.streaming.models import Video, View, Like, Category


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def reports_summary(request):
    """High-level counts for the reports page."""
    total_videos = Video.objects.count()
    published_videos = Video.objects.filter(is_published=True).count()
    draft_videos = total_videos - published_videos
    total_views = View.objects.count()
    total_likes = Like.objects.count()
    active_users = View.objects.values('user').distinct().count()

    payload = {
        'total_videos': total_videos,
        'published_videos': published_videos,
        'draft_videos': draft_videos,
        'total_views': total_views,
        'total_likes': total_likes,
        'active_users': active_users,
    }
    return success_response(payload)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def top_videos(request):
    """Top performing videos sorted by views descending."""
    limit = int(request.query_params.get('limit', 10))
    period = request.query_params.get('period', 'all')

    qs = Video.objects.filter(is_published=True)

    if period != 'all':
        today = timezone.localdate()
        if period == 'week':
            start = today - timedelta(days=7)
        elif period == 'month':
            start = date(today.year, today.month, 1)
        elif period == 'year':
            start = date(today.year, 1, 1)
        else:
            start = None

        if start:
            video_ids = (
                View.objects.filter(created_at__date__gte=start)
                .values('video')
                .annotate(cnt=Count('id'))
                .order_by('-cnt')
                .values_list('video', flat=True)[:limit]
            )
            qs = qs.filter(id__in=video_ids)

    videos = qs.order_by('-views_count')[:limit]
    data = [
        {
            'id': v.id,
            'title': v.title,
            'views_count': v.views_count,
            'likes_count': v.likes_count,
            'thumbnail': v.thumbnail.url if v.thumbnail else None,
        }
        for v in videos
    ]
    return success_response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def category_performance(request):
    """Category performance data sorted by total views descending."""
    categories = (
        Category.objects.annotate(
            video_count=Count('videos'),
            total_views=Sum('videos__views_count'),
        )
        .order_by('-total_views')
    )
    data = [
        {
            'id': c.id,
            'name': c.name,
            'video_count': c.video_count,
            'total_views': c.total_views or 0,
        }
        for c in categories
    ]
    return success_response(data)
