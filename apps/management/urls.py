from django.urls import path
from . import views

app_name = 'management'

urlpatterns = [
    # Dashboard
    path('summary/', views.get_dashboard_summary, name='get-dashboard-summary'),
    path('clients-stats/', views.get_dashboard_client_stats, name='get-dashboard-client-stats'),
    path('dashboard-analytics-chart/', views.get_dashboard_analytics_chart, name='get-dashboard-analytics-chart'),

    # Interceptor ads
    path('interceptor/ads/', views.get_interceptor_ads, name='get-interceptor-ads'),
    path('interceptor/ads/create/', views.create_interceptor_ad, name='create-interceptor-ad'),
    path('interceptor/ad/<int:pk>/', views.get_interceptor_ad, name='get-interceptor-ad'),
    path('interceptor/ads/<int:pk>/', views.delete_interceptor_ad, name='delete-interceptor-ad'),
    path('interceptor/ads/<int:pk>/update/', views.update_interceptor_ad, name='update-interceptor-ad'),
    path('interceptor/ads/<int:pk>/toggle/', views.toggle_interceptor_ad, name='toggle-interceptor-ad'),

    # App Users Management
    path('app-users/', views.list_app_users, name='list-app-users'),
    path('app-users/<int:pk>/', views.get_app_user, name='get-app-user'),
    path('app-users/<int:pk>/comments/', views.get_app_user_comments, name='get-app-user-comments'),
    path('app-users/<int:pk>/suspend/', views.suspend_app_user, name='suspend-app-user'),
    path('app-users/<int:pk>/unsuspend/', views.unsuspend_app_user, name='unsuspend-app-user'),

    # Admin Users Management
    path('admin-users/', views.list_admin_users, name='list-admin-users'),
    path('admin-users/create/', views.create_admin_user, name='create-admin-user'),
    path('admin-users/<int:pk>/update/', views.update_admin_user, name='update-admin-user'),
    path('admin-users/<int:pk>/', views.delete_admin_user, name='delete-admin-user'),

    # Notifications
    path('notifications/', views.list_notifications, name='list-notifications'),
    path('notifications/<int:pk>/read/', views.mark_notification_read, name='mark-notification-read'),
    path('notifications/read-all/', views.mark_all_notifications_read, name='mark-all-notifications-read'),

    # Reports / Analytics
    path('reports/summary/', views.reports_summary, name='reports-summary'),
    path('reports/top-videos/', views.top_videos, name='top-videos'),
    path('reports/category-performance/', views.category_performance, name='category-performance'),

    # Settings (GET + PATCH on same path)
    path('settings/', views.settings_view, name='settings'),

    # Active Users Today
    path('active-users-today/', views.active_users_today, name='active-users-today'),

    # Comment Conversations (CMS Inbox)
    path('comment-conversations/', views.comment_conversations, name='comment-conversations'),
    path('comment-conversations/<int:user_id>/<int:video_id>/', views.comment_conversation_detail, name='comment-conversation-detail'),

    # Website Posts
    path('website-posts/', views.list_website_posts, name='list-website-posts'),
    path('website-posts/create/', views.create_website_post, name='create-website-post'),
    path('website-posts/<int:pk>/', views.get_website_post, name='get-website-post'),
    path('website-posts/<int:pk>/update/', views.update_website_post, name='update-website-post'),
    path('website-posts/<int:pk>/delete/', views.delete_website_post, name='delete-website-post'),
]
