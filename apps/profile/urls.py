from django.urls import path
from . import views

app_name = 'profile'

urlpatterns = [
    # Add your URL patterns here
    path('', views.profile, name='profile'),
    path('acknowledge-initial-credit/', views.acknowledge_initial_credit, name='acknowledge-initial-credit'),
    path('update/', views.profile_update, name='profile-update'),
    path('upload/', views.upload_profile, name='profile-upload'),
    path('reset-password/', views.profile_reset_password, name='profile-reset-password'),
    path('request-data-delete/', views.profile_request_data_delete, name='profile-request-data-delete'),
    path('request-account-delete/', views.profile_request_account_delete, name='profile-request-account-delete'),
]