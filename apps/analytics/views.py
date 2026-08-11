from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import close_old_connections
from django.utils import timezone
from django.db.models import Count, Sum, Q
from django.db.models.functions import TruncHour
from datetime import timedelta

from core.response_wrapper import success_response, error_response
from apps.analytics.models import Notification, WebsiteEvent
from apps.analytics.serializers.notification import NotificationSerializer


# Dakika 5: session inachukuliwa kuwa "online" ikiwa imetuma event ndani ya muda huu.
ONLINE_WINDOW_MINUTES = 5


def _client_ip(request):
    """IP ya mtumiaji — inaheshimu reverse proxy (X-Forwarded-For)."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def _online_sessions_qs():
    """Sessions zilizotuma event ndani ya dakika 5 zilizopita."""
    cutoff = timezone.now() - timedelta(minutes=ONLINE_WINDOW_MINUTES)
    return (
        WebsiteEvent.objects.filter(created_at__gte=cutoff)
        .exclude(session_id='')
        .values('session_id')
        .distinct()
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def website_events(request):
    """Collector ya events za website (public — inatumiwa na JS ya website).

    Body: object moja AU list ya objects:
      {"event_type": "pageview|video_play|watch_seconds|scroll|heartbeat|...",
       "session_id": "...", "page": "/", "video_uid": "...",
       "video_title": "...", "value": 0}
    """
    close_old_connections()
    data = request.data
    events = data if isinstance(data, list) else [data]
    if not isinstance(events, list):
        return error_response('Invalid payload', code=400)

    valid_types = {choice.value for choice in WebsiteEvent.EVENT_TYPES}
    created = 0
    ua = str(request.META.get('HTTP_USER_AGENT', ''))[:500]
    ip = _client_ip(request)[:64]

    for ev in events[:50]:
        if not isinstance(ev, dict):
            continue
        etype = str(ev.get('event_type', '')).lower()
        if etype not in valid_types:
            continue
        session = str(ev.get('session_id', ''))[:64]
        if not session:
            continue
        try:
            value = int(ev.get('value', 0) or 0)
        except (TypeError, ValueError):
            value = 0
        WebsiteEvent.objects.create(
            session_id=session,
            event_type=etype,
            page=str(ev.get('page', ''))[:255],
            video_uid=str(ev.get('video_uid', ''))[:64],
            video_title=str(ev.get('video_title', ''))[:255],
            value=max(value, 0),
            referrer=str(ev.get('referrer', ''))[:500],
            user_agent=ua,
            ip=ip,
        )
        created += 1

    return success_response({'created': created}, message='OK')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def website_summary(request):
    """High-level counts za website engagement."""
    close_old_connections()
    qs = WebsiteEvent.objects.all()
    today = timezone.localdate()

    active_now = _online_sessions_qs().count()
    total_pageviews = qs.filter(event_type='pageview').count()
    total_video_plays = qs.filter(event_type='video_play').count()
    unique_sessions = qs.values('session_id').distinct().count()
    watch_seconds = qs.filter(event_type='watch_seconds').aggregate(t=Sum('value'))['t'] or 0

    today_pageviews = qs.filter(event_type='pageview', created_at__date=today).count()
    today_video_plays = qs.filter(event_type='video_play', created_at__date=today).count()
    today_sessions = (
        qs.filter(created_at__date=today).values('session_id').distinct().count()
    )

    return success_response({
        'active_now': active_now,
        'total_pageviews': total_pageviews,
        'total_video_plays': total_video_plays,
        'unique_sessions': unique_sessions,
        'watch_seconds_total': watch_seconds,
        'watch_minutes_total': round(watch_seconds / 60, 1),
        'today_pageviews': today_pageviews,
        'today_video_plays': today_video_plays,
        'today_sessions': today_sessions,
    }, message='OK')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def website_realtime(request):
    """Real-time: waliopo mtandaoni sasa + events za hivi punde."""
    close_old_connections()
    active_now = _online_sessions_qs().count()
    cutoff = timezone.now() - timedelta(hours=1)
    recent = list(
        WebsiteEvent.objects.filter(created_at__gte=cutoff)
        .order_by('-created_at')[:30]
        .values('event_type', 'page', 'video_uid', 'video_title', 'value', 'session_id', 'created_at')
    )

    def fmt(ev):
        delta = timezone.now() - ev['created_at']
        secs = int(delta.total_seconds())
        if secs < 60:
            ago = f'{max(secs, 1)}s ago'
        elif secs < 3600:
            ago = f'{secs // 60}m ago'
        else:
            ago = f'{secs // 3600}h ago'
        return {
            'event_type': ev['event_type'],
            'page': ev['page'],
            'video_uid': ev['video_uid'],
            'video_title': ev['video_title'],
            'value': ev['value'],
            'session_short': str(ev['session_id'])[:8],
            'time_ago': ago,
            'created_at': ev['created_at'].isoformat(),
        }

    return success_response({
        'active_now': active_now,
        'recent_events': [fmt(ev) for ev in recent],
    }, message='OK')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def website_top_videos(request):
    """Videos zilizotazamwa zaidi kwenye website (kwa plays na watch time)."""
    close_old_connections()
    limit = min(int(request.query_params.get('limit', 10) or 10), 50)
    qs = (
        WebsiteEvent.objects.filter(event_type='video_play')
        .exclude(video_uid='')
        .values('video_uid', 'video_title')
        .annotate(plays=Count('id'))
        .order_by('-plays')
    )

    # Watch time kwa kila video (from watch_seconds events)
    watch = dict(
        WebsiteEvent.objects.filter(event_type='watch_seconds')
        .exclude(video_uid='')
        .values('video_uid')
        .annotate(total=Sum('value'))
        .values_list('video_uid', 'total')
    )

    rows = []
    for entry in qs[:limit]:
        rows.append({
            'video_uid': entry['video_uid'],
            'video_title': entry['video_title'] or entry['video_uid'][:12],
            'plays': entry['plays'],
            'watch_seconds': watch.get(entry['video_uid'], 0),
        })
    return success_response(rows, message='OK')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def website_timeline(request):
    """Data ya chart: saa 24 zilizopita (pageviews, plays, active sessions)."""
    close_old_connections()
    hours = 24
    now = timezone.now()
    start = now - timedelta(hours=hours)

    def hourly_counts(event_filter, values=('id',)):
        """Group by hour (portable: SQLite + PostgreSQL)."""
        qs = (
            WebsiteEvent.objects.filter(created_at__gte=start)
            .annotate(hour=TruncHour('created_at'))
        )
        if event_filter is not None:
            qs = qs.filter(event_filter)
        qs = qs.values('hour').annotate(c=Count('id'))
        if 'session' in values:
            qs = (
                WebsiteEvent.objects.filter(created_at__gte=start)
                .annotate(hour=TruncHour('created_at'))
                .values('hour', 'session_id').distinct()
                .values('hour').annotate(c=Count('session_id'))
            )
        # Keys ziwe strings (TruncHour inarudisha datetime objects)
        return {
            (dt.strftime('%Y-%m-%d %H') if hasattr(dt, 'strftime') else str(dt)): c
            for dt, c in qs.values_list('hour', 'c')
        }

    pageviews = hourly_counts(Q(event_type='pageview'))
    plays = hourly_counts(Q(event_type='video_play'))
    sessions = hourly_counts(None, values=('session',))

    labels, pv_series, play_series, sess_series = [], [], [], []
    for i in range(hours - 1, -1, -1):
        ts = start + timedelta(hours=i)
        key = ts.strftime('%Y-%m-%d %H')
        labels.append(ts.strftime('%H:%M'))
        pv_series.append(pageviews.get(key, 0))
        play_series.append(plays.get(key, 0))
        sess_series.append(sessions.get(key, 0))

    return success_response({
        'labels': labels,
        'pageviews': pv_series,
        'video_plays': play_series,
        'active_sessions': sess_series,
    }, message='OK')



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