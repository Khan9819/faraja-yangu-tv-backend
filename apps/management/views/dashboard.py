from datetime import date, timedelta
import calendar

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from core.response_wrapper import success_response, error_response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from django.utils import timezone
from django.db.models import Q, Count, Sum
from django.core.cache import cache
from django.db import close_old_connections

from apps.authentication.models import User, Role, Devices
from apps.management.serializers import ClientSerializer
from apps.streaming.models import View, Like, Comment
from apps.advertising.models import Ad
from apps.analytics.models import Analytics, Report, Notification


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard_summary(request):
    """Return high-level dashboard summary stats."""
    close_old_connections()

    today = timezone.localdate()

    cache_key = f"dashboard_summary:{today.isoformat()}"
    cached_data = cache.get(cache_key)
    if cached_data:
        return success_response(cached_data)

    today = timezone.localdate()
    year_start = date(today.year, 1, 1)
    month_start = date(today.year, today.month, 1)

    clients_qs = User.objects.filter(roles__name=Role.ROLES.USER, is_active=True, is_suspended=False).distinct()
    total_clients = clients_qs.count()

    def period_counts_for_created(model_qs):
        base = model_qs
        return {
            "total": base.count(),
            "year": base.filter(created_at__date__gte=year_start).count(),
            "month": base.filter(created_at__date__gte=month_start).count(),
            "today": base.filter(created_at__date=today).count(),
        }

    registrations = {
        "total": total_clients,
        "year": clients_qs.filter(date_joined__date__gte=year_start).count(),
        "month": clients_qs.filter(date_joined__date__gte=month_start).count(),
        "today": clients_qs.filter(date_joined__date=today).count(),
    }

    views_qs = View.objects.filter(user__in=clients_qs)
    likes_qs = Like.objects.filter(user__in=clients_qs)
    comments_qs = Comment.objects.filter(user__in=clients_qs)

    views = period_counts_for_created(views_qs)
    likes = period_counts_for_created(likes_qs)
    comments = period_counts_for_created(comments_qs)

    def active_users_counts(qs):
        return {
            "total": qs.values("user").distinct().count(),
            "year": qs.filter(created_at__date__gte=year_start).values("user").distinct().count(),
            "month": qs.filter(created_at__date__gte=month_start).values("user").distinct().count(),
            "today": qs.filter(created_at__date=today).values("user").distinct().count(),
        }

    active_users = active_users_counts(views_qs)

    def watch_time_hours(qs):
        agg = qs.aggregate(total=Sum("watch_time"))
        total = agg["total"]
        return round(total.total_seconds() / 3600, 2) if total else 0

    watch_time = {
        "total": watch_time_hours(views_qs),
        "year": watch_time_hours(views_qs.filter(created_at__date__gte=year_start)),
        "month": watch_time_hours(views_qs.filter(created_at__date__gte=month_start)),
        "today": watch_time_hours(views_qs.filter(created_at__date=today)),
    }

    def safe_div(num, denom):
        return num / denom if denom else 0

    avg_watch_time_per_user = {
        "total": safe_div(watch_time["total"], active_users["total"]),
        "year": safe_div(watch_time["year"], active_users["year"]),
        "month": safe_div(watch_time["month"], active_users["month"]),
        "today": safe_div(watch_time["today"], active_users["today"]),
    }

    def engagement_for_period(v, l, c):
        return safe_div(l + c, v) if v else 0

    engagement_rate = {
        "total": engagement_for_period(views["total"], likes["total"], comments["total"]),
        "year": engagement_for_period(views["year"], likes["year"], comments["year"]),
        "month": engagement_for_period(views["month"], likes["month"], comments["month"]),
        "today": engagement_for_period(views["today"], likes["today"], comments["today"]),
    }

    last_7_start = today - timedelta(days=7)
    last_30_start = today - timedelta(days=30)

    active_last_7_days = (
        views_qs.filter(created_at__date__gte=last_7_start)
        .values("user")
        .distinct()
        .count()
    )
    active_last_30_days = (
        views_qs.filter(created_at__date__gte=last_30_start)
        .values("user")
        .distinct()
        .count()
    )

    retention = {
        "active_last_7_days": active_last_7_days,
        "active_last_30_days": active_last_30_days,
        "active_last_7_days_pct": safe_div(active_last_7_days * 100, total_clients) if total_clients else 0,
        "active_last_30_days_pct": safe_div(active_last_30_days * 100, total_clients) if total_clients else 0,
    }

    total_ads = Ad.objects.count()
    published_ads = Ad.objects.filter(is_published=True).count()
    ads_views_agg = Ad.objects.aggregate(total_views=Sum("views_count"), total_likes=Sum("likes_count"), total_dislikes=Sum("dislikes_count"))

    ads_metrics = {
        "total_ads": total_ads,
        "published_ads": published_ads,
        "types": {
            "banner": Ad.objects.filter(type=Ad.AD_TYPES.BANNER).count(),
            "video": Ad.objects.filter(type=Ad.AD_TYPES.VIDEO).count(),
            "carousel": Ad.objects.filter(type=Ad.AD_TYPES.CAROUSEL).count(),
        },
        "aggregates": {
            "views": ads_views_agg["total_views"] or 0,
            "likes": ads_views_agg["total_likes"] or 0,
            "dislikes": ads_views_agg["total_dislikes"] or 0,
        },
    }

    reports_metrics = {
        "total": Report.objects.count(),
        "pending": Report.objects.filter(status=Report.REPORT_STATUS.PENDING).count(),
        "approved": Report.objects.filter(status=Report.REPORT_STATUS.APPROVED).count(),
        "rejected": Report.objects.filter(status=Report.REPORT_STATUS.REJECTED).count(),
    }

    analytics_metrics = {
        "types": {
            "video": Analytics.objects.filter(type=Analytics.ANALYTICS_TYPES.VIDEO).count(),
            "ad": Analytics.objects.filter(type=Analytics.ANALYTICS_TYPES.AD).count(),
        }
    }

    notifications_metrics = {
        "total": Notification.objects.count(),
        "unread": Notification.objects.filter(is_read=False).count(),
    }

    total_devices = Devices.objects.filter(is_active=True).count()
    android_count = Devices.objects.filter(is_active=True, device_os__icontains='android').count()
    ios_count = Devices.objects.filter(is_active=True, device_os__icontains='ios').count()

    latest_version = Devices.objects.filter(is_active=True).order_by('-app_version').values_list('app_version', flat=True).first()

    if latest_version and total_devices > 0:
        uptodate_count = Devices.objects.filter(is_active=True, app_version=latest_version).count()
        uptodate_ratio = round((uptodate_count / total_devices) * 100, 2)
        outdated_ratio = round(100 - uptodate_ratio, 2)
    else:
        uptodate_ratio = 0
        outdated_ratio = 0

    devices = {
        "total": total_devices,
        "androids": android_count,
        "iOS": ios_count,
        "uptodate_ratio": uptodate_ratio,
        "outdated_ratio": outdated_ratio,
        "latest_version": latest_version or "N/A",
    }

    payload = {
        "clients": registrations,
        "registrations": registrations,
        "views": views,
        "likes": likes,
        "comments": comments,
        "watch_time": watch_time,
        "active_users": active_users,
        "avg_watch_time_per_user": avg_watch_time_per_user,
        "engagement_rate": engagement_rate,
        "retention": retention,
        "ads": ads_metrics,
        "analytics": {
            "reports": reports_metrics,
            "analytics": analytics_metrics,
            "notifications": notifications_metrics,
        },
        "devices": devices,
        "current_date": today.isoformat(),
    }

    cache.set(cache_key, payload, timeout=60)

    return success_response(payload)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard_client_stats(request):
    users = User.objects.filter(roles__name=Role.ROLES.USER, is_active=True, is_suspended=False).distinct()
    serializer = ClientSerializer(users, many=True)
    return success_response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard_analytics_chart(request):
    today = timezone.localdate()
    year = int(request.query_params.get("year", today.year))
    month = int(request.query_params.get("month", today.month))

    first_day = date(year, month, 1)
    days_in_month = calendar.monthrange(year, month)[1]
    last_day = date(year, month, days_in_month)

    date_range = {"created_at__date__gte": first_day, "created_at__date__lte": last_day}

    views_qs = (
        View.objects.filter(**date_range)
        .values("created_at__date")
        .annotate(count=Count("id"), watch_time_sum=Sum("watch_time"))
    )
    views_by_day = {row["created_at__date"]: row["count"] for row in views_qs}
    watch_time_by_day = {
        row["created_at__date"]: round(row["watch_time_sum"].total_seconds() / 3600, 2) if row["watch_time_sum"] else 0
        for row in views_qs
    }

    likes_qs = (
        Like.objects.filter(**date_range)
        .values("created_at__date")
        .annotate(count=Count("id"))
    )
    likes_by_day = {row["created_at__date"]: row["count"] for row in likes_qs}

    comments_qs = (
        Comment.objects.filter(**date_range)
        .values("created_at__date")
        .annotate(count=Count("id"))
    )
    comments_by_day = {row["created_at__date"]: row["count"] for row in comments_qs}

    active_qs = (
        View.objects.filter(**date_range)
        .values("created_at__date")
        .annotate(count=Count("user", distinct=True))
    )
    active_by_day = {row["created_at__date"]: row["count"] for row in active_qs}

    labels = []
    views_series = []
    likes_series = []
    comments_series = []
    watch_time_series = []
    active_users_series = []

    for day in range(1, days_in_month + 1):
        current = date(year, month, day)
        labels.append(day)
        views_series.append(views_by_day.get(current, 0))
        likes_series.append(likes_by_day.get(current, 0))
        comments_series.append(comments_by_day.get(current, 0))
        watch_time_series.append(watch_time_by_day.get(current, 0))
        active_users_series.append(active_by_day.get(current, 0))

    months = [
        {"id": idx, "name": name}
        for idx, name in enumerate(
            ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
            start=1,
        )
    ]

    payload = {
        "current_date": today.isoformat(),
        "months": months,
        "labels": labels,
        "data": {
            "views": views_series,
            "likes": likes_series,
            "comments": comments_series,
            "watch_time": watch_time_series,
            "active_users": active_users_series,
        },
        "year": year,
        "month": month,
    }

    return success_response(payload)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def active_users_today(request):
    """List app users who were active today (logged in or had activity)."""
    today = timezone.localdate()

    active_viewer_ids = (
        View.objects.filter(created_at__date=today)
        .values_list('user_id', flat=True)
        .distinct()
    )
    active_liker_ids = (
        Like.objects.filter(created_at__date=today)
        .values_list('user_id', flat=True)
        .distinct()
    )
    active_commenter_ids = (
        Comment.objects.filter(created_at__date=today)
        .values_list('user_id', flat=True)
        .distinct()
    )
    logged_in_ids = (
        User.objects.filter(last_login__date=today)
        .values_list('id', flat=True)
    )

    all_active_ids = set(active_viewer_ids) | set(active_liker_ids) | set(active_commenter_ids) | set(logged_in_ids)

    users = User.objects.filter(
        id__in=all_active_ids,
        roles__name=Role.ROLES.USER,
    ).distinct().select_related('profile')

    data = []
    for user in users:
        watched_count = View.objects.filter(user=user, created_at__date=today).count()
        last_view = View.objects.filter(user=user, created_at__date=today).order_by('-created_at').values_list('created_at', flat=True).first()
        last_like = Like.objects.filter(user=user, created_at__date=today).order_by('-created_at').values_list('created_at', flat=True).first()
        last_comment = Comment.objects.filter(user=user, created_at__date=today).order_by('-created_at').values_list('created_at', flat=True).first()
        timestamps = [t for t in [last_view, last_like, last_comment, user.last_login] if t is not None]
        last_active = max(timestamps) if timestamps else user.last_login

        data.append({
            'id': user.id,
            'full_name': user.get_full_name() or user.username,
            'email': user.email,
            'provider': user.auth_provider,
            'watched_video_count_today': watched_count,
            'last_active': last_active,
            'last_login': user.last_login,
        })

    return success_response(data)
