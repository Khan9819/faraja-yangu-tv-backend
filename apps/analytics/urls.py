from django.urls import path
from . import views

app_name = 'analytics'

urlpatterns = [
    path('notifications/', views.list_notifications, name='notifications-list'),
    path('notifications/mark-all-read/', views.mark_all_notifications_read, name='notifications-mark-all-read'),
    path('notifications/<int:pk>/read/', views.mark_notification_read, name='notification-mark-read'),
    path('notifications/<int:pk>/', views.delete_notification, name='notification-delete'),
    path('notifications/clear-all/', views.clear_all_notification, name='notification-delete'),
]
