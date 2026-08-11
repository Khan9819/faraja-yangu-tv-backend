from django.urls import path
from . import views

app_name = 'analytics'

urlpatterns = [
    # Website engagement (public collector + admin real-time dashboard)
    path('website/events/', views.website_events, name='website-events'),
    path('website/summary/', views.website_summary, name='website-summary'),
    path('website/realtime/', views.website_realtime, name='website-realtime'),
    path('website/top-videos/', views.website_top_videos, name='website-top-videos'),
    path('website/timeline/', views.website_timeline, name='website-timeline'),

    path('notifications/', views.list_notifications, name='notifications-list'),
    path('notifications/unread-count/', views.unread_notification_count, name='notifications-unread-count'),
    path('notifications/mark-all-read/', views.mark_all_notifications_read, name='notifications-mark-all-read'),
    path('notifications/<int:pk>/read/', views.mark_notification_read, name='notification-mark-read'),
    path('notifications/<int:pk>/', views.delete_notification, name='notification-delete'),
    path('notifications/clear-all/', views.clear_all_notification, name='notification-delete'),
]
